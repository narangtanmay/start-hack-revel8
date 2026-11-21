"""Command-line entry points for the Revel8 agent."""

import argparse
import sys
from collections.abc import Sequence

from .api_client import Revel8APIError, Revel8Client


def _status() -> int:
    try:
        with Revel8Client() as client:
            scenarios = client.get_scenarios()
            channels = client.get_channels()
    except Revel8APIError as error:
        print(f"Revel8 API status check failed. {error}", file=sys.stderr)
        return 1

    open_scenarios = sum(
        isinstance(scenario, dict) and scenario.get("open") is True for scenario in scenarios
    )
    entries = channels.get("channels") if isinstance(channels, dict) else channels
    if not isinstance(entries, (list, dict)):
        entries = channels
    print("Revel8 API reachable")
    print(f"Scenarios: {len(scenarios)} ({open_scenarios} open)")
    print(f"Channel entries: {len(entries)}")
    return 0


def _osint(scenario_id: str, target_ids: list[str], budget: float, out_dir: str) -> int:
    from concurrent.futures import ThreadPoolExecutor

    from .llm_client import LocalLLMClient, LocalLLMError
    from .osint import Target, build_dossier, write_dossier

    try:
        with Revel8Client() as client:
            scenarios = client.get_scenarios()
    except Revel8APIError as error:
        print(f"Could not load scenarios. {error}", file=sys.stderr)
        return 1
    scenario = next((s for s in scenarios if isinstance(s, dict) and s.get("id") == scenario_id), None)
    if not scenario or not scenario.get("open"):
        print(f"Scenario {scenario_id!r} not found or not open.", file=sys.stderr)
        return 1

    company = str(scenario.get("company", ""))
    targets = [
        Target(str(t["id"]), str(t["name"]), str(t.get("role", "")), company)
        for t in scenario.get("targets", [])
        if isinstance(t, dict) and (not target_ids or t.get("id") in target_ids)
    ]
    if not targets:
        print("No matching targets.", file=sys.stderr)
        return 1

    try:
        llm = LocalLLMClient(timeout=60.0)
    except LocalLLMError as error:
        print(error, file=sys.stderr)
        return 1

    def run(t: Target) -> str:
        dossier, stats = build_dossier(t, llm, budget_s=budget)
        path = write_dossier(dossier, stats, out_dir)
        return f"{t.id}: {len(dossier.facts)} facts, {len(dossier.hypotheses)} hooks, {stats['elapsed_s']}s -> {path}"

    with ThreadPoolExecutor(len(targets)) as pool:
        for line in pool.map(run, targets):
            print(line)
    return 0


def _run(target: str, scenario: str, touches: int, label: str, allow_eval: bool, keep_going: bool) -> int:
    import json
    from pathlib import Path

    from .engine import RunConfig, Runner, estimate_score
    from .llm_client import LocalLLMClient
    from .osint import Target, build_dossier, write_dossier
    from .report import render_index, render_run
    from .schemas import VerifiedDossier

    if scenario == "eval" and not allow_eval:
        print("Refusing to use an EVAL session without --allow-eval (only 3 scored runs exist).", file=sys.stderr)
        return 2
    from .llm_client import LLMPool

    pool = LLMPool(timeout=120.0)
    llm = pool.lane(0)  # same interface as LocalLLMClient; uses any key with room in its 20 req/min window
    dossier_path = Path("dossiers") / f"{target}.json"
    with Revel8Client() as api:
        if dossier_path.exists() and scenario != "eval":
            dossier = VerifiedDossier.model_validate_json(dossier_path.read_text(encoding="utf-8"))
            print(f"dossier: loaded {dossier_path} ({len(dossier.facts)} facts)")
        else:
            sc = next((s for s in api.get_scenarios() if isinstance(s, dict) and s.get("id") == scenario), None)
            if not sc or not sc.get("open"):
                print(f"Scenario {scenario!r} is not open.", file=sys.stderr)
                return 1
            t = next((x for x in sc.get("targets", []) if x.get("id") == target), None)
            if not t:
                print(f"Unknown target {target!r}.", file=sys.stderr)
                return 1
            from .research import research

            dossier, stats = research(Target(t["id"], t["name"], t.get("role", ""), str(sc.get("company", ""))), pool)
            write_dossier(dossier, stats)
        cfg = RunConfig(target_id=target, scenario_id=scenario, max_touches=touches, label=label,
                        stop_at_first_incident=not keep_going)
        runner = Runner(cfg, api, llm, dossier)
        print(f"report: {(cfg.runs_dir / (runner.state.run_id + '.html')).resolve()}")

        orig_save = runner.save

        def save_and_render():
            path = orig_save()
            render_run(path)
            render_index(cfg.runs_dir)
            return path

        runner.save = save_and_render  # type: ignore[method-assign]
        state = runner.run()
    print(json.dumps(estimate_score(state.__dict__), indent=1))
    print(f"report: {render_index(cfg.runs_dir).resolve()}")
    return 0 if state.status == "done" else 1


def _research(scenario_id: str, target_ids: list[str], budget: float, anchors: list[str]) -> int:
    from .llm_client import LLMPool
    from .osint import Target, write_dossier
    from .research import research

    try:
        with Revel8Client() as client:
            scenarios = client.get_scenarios()
    except Revel8APIError as error:
        print(f"Could not load scenarios. {error}", file=sys.stderr)
        return 1
    sc = next((s for s in scenarios if isinstance(s, dict) and s.get("id") == scenario_id), None)
    if not sc or not sc.get("open"):
        print(f"Scenario {scenario_id!r} not found or not open.", file=sys.stderr)
        return 1
    targets = [Target(str(t["id"]), str(t["name"]), str(t.get("role", "")), str(sc.get("company", "")))
               for t in sc.get("targets", []) if isinstance(t, dict) and (not target_ids or t.get("id") in target_ids)]
    pool = LLMPool(timeout=90.0)
    print(f"research v2: {len(targets)} target(s), {len(pool)} Token Factory key(s)")
    for t in targets:  # one target at a time; inside, every lane runs in parallel on its own key
        dossier, stats = research(t, pool, budget_s=budget, anchors=anchors)
        path = write_dossier(dossier, stats)
        print(f"{t.id}: {len(dossier.facts)} facts, {len(dossier.themes)} themes, {len(dossier.hypotheses)} hooks, "
              f"{stats['elapsed_s']}s -> {path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Revel8 agent tools.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Check API connectivity and list scenario and channel counts.")
    osint = sub.add_parser("osint", help="Build verified dossiers for scenario targets.")
    osint.add_argument("--scenario", default="practice")
    osint.add_argument("--target", action="append", default=[], help="Target id (repeatable). Default: all.")
    osint.add_argument("--budget", type=float, default=150.0, help="Seconds per target.")
    osint.add_argument("--out", default="dossiers")
    run = sub.add_parser("run", help="Run one full attack session against a target.")
    run.add_argument("--target", required=True)
    run.add_argument("--scenario", default="practice")
    run.add_argument("--touches", type=int, default=10, help="Touch cap (eval allows 10).")
    run.add_argument("--label", default="")
    run.add_argument("--allow-eval", action="store_true")
    run.add_argument("--keep-going", action="store_true", help="Continue after the first incident.")
    rep = sub.add_parser("report", help="Rebuild the dashboard (runs/index.html).")
    rep.add_argument("--open", action="store_true", help="Open the dashboard in the browser.")
    rep.add_argument("--public-out", default="", help="Also write a public snapshot (landing pages not rendered) here.")
    score = sub.add_parser("score", help="Rubric scorecard over the practice runs in runs/ (projection of the eval).")
    score.add_argument("--best", type=float, default=2.0, help="Contacts the fastest team needs (speed points).")
    score.add_argument("--json", action="store_true")
    sub.add_parser("rejudge", help="Re-check LLM-judged incidents in runs/ with the current judge (withdraws, never deletes).")
    res = sub.add_parser("research", help="Research v2: person-first multi-lane OSINT using every Token Factory key.")
    res.add_argument("--scenario", default="practice")
    res.add_argument("--target", action="append", default=[], help="Target id (repeatable). Default: all.")
    res.add_argument("--budget", type=float, default=300.0, help="Seconds per target.")
    res.add_argument("--anchor", action="append", default=[], help="Extra identity anchor (repeatable).")
    args = parser.parse_args(argv)

    if args.command == "score":
        import json
        from pathlib import Path

        from .scorecard import compute, format_text

        states = []
        for f in sorted(Path("runs").glob("*.json")):
            try:
                states.append(json.loads(f.read_text(encoding="utf-8")))
            except ValueError:
                continue
        sc = compute(states, best_contacts=args.best)
        print(json.dumps(sc, indent=1) if args.json else format_text(sc))
        return 0

    if args.command == "research":
        return _research(args.scenario, args.target, args.budget, args.anchor)

    if args.command == "rejudge":
        from pathlib import Path

        from .engine import rejudge_run
        from .llm_client import LocalLLMClient

        llm = LocalLLMClient(timeout=120.0)
        total = sum(rejudge_run(f, llm) for f in sorted(Path("runs").glob("*.json")))
        print(f"withdrawn: {total}")
        return 0

    if args.command == "run":
        return _run(args.target, args.scenario, args.touches, args.label, args.allow_eval, args.keep_going)
    if args.command == "report":
        from .report import render_index

        path = render_index().resolve()
        print(path)
        if args.public_out:
            from pathlib import Path

            print(render_index(Path("runs"), Path(args.public_out), public=True).resolve())
        if args.open:
            import webbrowser

            webbrowser.open(path.as_uri())
        return 0

    if args.command == "osint":
        return _osint(args.scenario, args.target, args.budget, args.out)
    return _status()


if __name__ == "__main__":
    raise SystemExit(main())
