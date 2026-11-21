"""Worker-pool coordinator: run many attack sessions in parallel, one Token
Factory LLM key per worker.

The team shares one hosted LLM endpoint (``LLM_BASE_URL``) but has several keys
(``LLM_API_KEYS``). Each key is its own rate-limit bucket, so we fan independent
sessions out across keys and run them concurrently.

Why sessions are the unit of parallelism: the Revel8 API allows at most 6
in-flight requests team-wide and **one request at a time per session**
(docs/revel8-api-docs.md). So you parallelise across *sessions*, not within one.
With N keys we run up to min(N, 6) sessions at once — e.g. the 3 founders in
practice, or the 3 eval runs on Sunday, each on its own key.

Standalone (``python -m revel8_agent.swarm ...``) so it never touches the main
CLI. Each worker reuses the existing engine Runner unchanged.
"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

from dotenv import load_dotenv

# docs/revel8-api-docs.md: "At most 6 requests per team run in parallel".
REVEL8_PARALLEL_CAP = 6


def load_keys() -> list[str]:
    """The pool of Token Factory keys, newest-style LLM_API_KEYS first."""
    load_dotenv()
    raw = os.getenv("LLM_API_KEYS", "") or os.getenv("LLM_API_KEY", "")
    return [k.strip() for k in raw.split(",") if k.strip()]


@dataclass
class Task:
    target: str
    scenario: str = "practice"
    touches: int = 10
    label: str = ""
    keep_going: bool = False


def assign_keys(n_tasks: int, keys: list[str]) -> list[str]:
    """Round-robin a key to each task (cycles if more tasks than keys)."""
    if not keys:
        raise ValueError("No LLM API keys found: set LLM_API_KEYS or LLM_API_KEY in .env.")
    return [keys[i % len(keys)] for i in range(n_tasks)]


def parallelism(n_tasks: int, n_keys: int, requested: int | None = None) -> int:
    """How many workers to run at once, bounded by tasks and the API cap.

    By default also bounded by the number of keys (one rate-limit bucket each). An explicit
    ``requested`` may exceed the key count: a self-hosted vLLM server has one key but batches
    concurrent requests, so several workers can share it.
    """
    if requested and requested > 0:
        return max(1, min(requested, REVEL8_PARALLEL_CAP, n_tasks))
    return max(1, min(n_keys, REVEL8_PARALLEL_CAP, n_tasks))


def run_one(task: Task, api_key: str, log=print) -> dict[str, Any]:
    """Run one full attack session with a specific LLM key. Returns run state."""
    from .api_client import Revel8Client
    from .engine import RunConfig, Runner
    from .llm_client import LocalLLMClient
    from .osint import Target, build_dossier, write_dossier
    from .report import render_index, render_run
    from .schemas import VerifiedDossier

    llm = LocalLLMClient(api_key=api_key, timeout=120.0)
    dossier_path = Path("dossiers") / f"{task.target}.json"
    with Revel8Client() as api:
        if dossier_path.exists() and task.scenario != "eval":
            dossier = VerifiedDossier.model_validate_json(dossier_path.read_text(encoding="utf-8"))
            log(f"dossier: cached {dossier_path.name} ({len(dossier.facts)} facts)")
        else:
            sc = next((s for s in api.get_scenarios() if isinstance(s, dict) and s.get("id") == task.scenario), None)
            if not sc or not sc.get("open"):
                return {"target": task.target, "status": "error", "error": f"scenario {task.scenario!r} not open"}
            t = next((x for x in sc.get("targets", []) if x.get("id") == task.target), None)
            if not t:
                return {"target": task.target, "status": "error", "error": f"unknown target {task.target!r}"}
            dossier, stats = build_dossier(
                Target(t["id"], t["name"], t.get("role", ""), str(sc.get("company", ""))), llm)
            write_dossier(dossier, stats)
        cfg = RunConfig(target_id=task.target, scenario_id=task.scenario, max_touches=task.touches,
                        label=task.label, stop_at_first_incident=not task.keep_going)
        runner = Runner(cfg, api, llm, dossier, log=log)
        orig_save = runner.save

        def save_and_render():
            path = orig_save()
            render_run(path)
            render_index(cfg.runs_dir)
            return path

        runner.save = save_and_render  # type: ignore[method-assign]
        state = runner.run()
    return state.__dict__


def run_swarm(tasks: list[Task], keys: list[str], max_parallel: int | None = None, log=print) -> list[dict[str, Any]]:
    """Run tasks concurrently, one key per worker. Returns run states in task order."""
    assigned = assign_keys(len(tasks), keys)
    workers = parallelism(len(tasks), len(keys), max_parallel)
    key_index = {k: i for i, k in enumerate(keys)}
    log(f"swarm: {len(tasks)} task(s), {len(keys)} key(s), {workers} in parallel (API cap {REVEL8_PARALLEL_CAP})")
    results: dict[int, dict[str, Any]] = {}
    lock = Lock()

    def worker(i: int) -> dict[str, Any]:
        task, key = tasks[i], assigned[i]

        def wlog(msg: str) -> None:
            with lock:
                print(f"[{task.target} · key#{key_index.get(key, 0) + 1}] {msg}", flush=True)

        wlog("start")
        try:
            return run_one(task, key, log=wlog)
        except Exception as error:  # noqa: BLE001 - one worker must not sink the swarm
            return {"target": task.target, "status": "error", "error": f"{type(error).__name__}: {error}"}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(worker, i): i for i in range(len(tasks))}
        for future in as_completed(futures):
            i = futures[future]
            results[i] = future.result()
            inc = results[i].get("incidents") or []
            log(f"[{tasks[i].target}] done: {results[i].get('status')}, {len(inc)} incident(s)")
    return [results[i] for i in range(len(tasks))]


def _summary(states: list[dict[str, Any]], scored_runs: int) -> None:
    from .benchmark import ScoreConfig, score_suite

    print("\n=== swarm summary ===")
    for s in states:
        inc = s.get("incidents") or []
        first = min((i["touch"] for i in inc), default=None)
        print(f"  {str(s.get('target', '?')):<10} {str(s.get('status')):<8} "
              f"touches={s.get('touches_used', 0)} incidents={len(inc)}"
              + (f" (first@{first})" if first else ""))
    runs = [s for s in states if s.get("run_id")]
    if runs:
        card = score_suite(runs, ScoreConfig(scored_runs=scored_runs))
        r, t = card["results"], card["targeting"]
        print(f"\n  Results {r['subtotal']}/25  Targeting {t['subtotal']}/10  "
              f"measured {card['measured_total']}/{card['measured_max']} (Architecture+Pitch are jury)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run attack sessions in parallel, one LLM key per worker.")
    ap.add_argument("--target", action="append", default=[], help="Target id (repeatable).")
    ap.add_argument("--all", action="store_true", help="All targets in the scenario.")
    ap.add_argument("--scenario", default="practice")
    ap.add_argument("--touches", type=int, default=10)
    ap.add_argument("--keep-going", action="store_true", help="Continue after the first incident.")
    ap.add_argument("--allow-eval", action="store_true")
    ap.add_argument("--max-parallel", type=int, default=0, help="Cap workers (default: min(keys, 6)).")
    args = ap.parse_args(argv)

    if args.scenario == "eval" and not args.allow_eval:
        print("Refusing eval without --allow-eval (only 3 scored runs exist).", file=sys.stderr)
        return 2

    keys = load_keys()
    if not keys:
        print("No LLM keys: set LLM_API_KEYS or LLM_API_KEY in .env.", file=sys.stderr)
        return 1

    targets = list(dict.fromkeys(args.target))
    if args.all:
        from .api_client import Revel8APIError, Revel8Client
        try:
            with Revel8Client() as api:
                sc = next((s for s in api.get_scenarios() if isinstance(s, dict) and s.get("id") == args.scenario), None)
        except Revel8APIError as error:
            print(f"Could not list targets: {error}", file=sys.stderr)
            return 1
        if not sc:
            print(f"Scenario {args.scenario!r} not found.", file=sys.stderr)
            return 1
        targets = [str(t["id"]) for t in sc.get("targets", []) if isinstance(t, dict)]
    if not targets:
        print("No targets. Use --target <id> (repeatable) or --all.", file=sys.stderr)
        return 1

    tasks = [Task(target=t, scenario=args.scenario, touches=args.touches, keep_going=args.keep_going)
             for t in targets]
    states = run_swarm(tasks, keys, max_parallel=args.max_parallel or None)
    _summary(states, scored_runs=len(tasks) if args.scenario == "eval" else 3)
    return 0 if all(s.get("status") == "done" for s in states) else 1


if __name__ == "__main__":
    raise SystemExit(main())
