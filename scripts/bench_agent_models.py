"""End-to-end model comparison: full agent runs against the offline mock target, one model at a time.

Every LLM call the agent makes (plan, decide, live-call lines, judge) is wrapped and logged with its outcome:
ok / invalid JSON / HTTP error / timeout / refusal, plus latency. No Revel8 touches are spent (--mock).

Usage:
  uv run python scripts/bench_agent_models.py --model Qwen3.8-27B [--targets julius,tom,robert] [--touches 10]
Results: runs/bench/models/<model>.json (+ the mock run files under runs/bench/models/<model>/)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

REFUSAL = re.compile(r"\b(I can(?:no|')t (?:help|assist|create|write|comply)|I'm (?:sorry|unable)|"
                     r"I am (?:sorry|unable)|cannot (?:assist|help) with|against my (?:guidelines|policy))", re.I)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--targets", default="julius,tom,robert")
    ap.add_argument("--touches", type=int, default=10)
    ap.add_argument("--decider", default="controller", choices=["controller", "llm", "rules"],
                    help="rules = Tanmay's RuleBasedPolicy (cli --policy)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--real", action="store_true",
                    help="Use the real Revel8 practice API (spends practice touches) instead of the mock target.")
    ap.add_argument("--tag", default="", help="Suffix for the results folder, e.g. v2 (pipeline version).")
    args = ap.parse_args()

    os.environ["LLM_MODEL"] = args.model
    from revel8_agent import cli
    from revel8_agent.llm_client import LocalLLMClient, LocalLLMError

    calls: list[dict] = []
    orig = LocalLLMClient.chat

    def chat(self, messages, *, json_mode=False, temperature=None, **kw):  # type: ignore[no-untyped-def]
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        kind = ("plan" if "planning brain" in system else "decide" if "decision brain" in system
                else "call" if "You are on a live" in system else "judge" if "You judge" in system else "other")
        t0 = time.monotonic()
        rec = {"kind": kind, "json_mode": json_mode, "reasoning": kw.get("reasoning")}
        try:
            out = orig(self, messages, json_mode=json_mode, temperature=temperature, **kw)
        except LocalLLMError as e:
            rec.update(ok=False, error=str(e), status=e.status_code, s=round(time.monotonic() - t0, 2))
            calls.append(rec)
            raise
        text = json.dumps(out, ensure_ascii=False) if not isinstance(out, str) else out
        refused = bool(REFUSAL.search(text))
        rec.update(ok=not refused, error="refusal" if refused else "", s=round(time.monotonic() - t0, 2),
                   chars=len(text), sample=text[:160] if refused else "")
        calls.append(rec)
        return out

    LocalLLMClient.chat = chat  # type: ignore[method-assign]

    slug = re.sub(r"[^A-Za-z0-9._-]", "_", args.model)
    base = Path(("runs/bench/models-real" if args.real else "runs/bench/models") + (f"-{args.tag}" if args.tag else ""))
    out_dir = base / slug
    runs = []
    t_all = time.monotonic()
    for target in [t.strip() for t in args.targets.split(",") if t.strip()]:
        before = len(calls)
        t0 = time.monotonic()
        try:
            mode = [] if args.real else ["--mock", "--seed", str(args.seed)]
            code = cli.main(["run", "--target", target, *mode, "--touches", str(args.touches),
                             *(["--policy"] if args.decider == "rules" else ["--decider", args.decider]), "--runs-dir", str(out_dir), "--label", slug])
        except Exception as e:  # noqa: BLE001
            code = f"crash: {type(e).__name__}: {e}"
        latest = max(out_dir.glob(f"*{target}*.json"), key=lambda p: p.stat().st_mtime, default=None)
        state = json.loads(latest.read_text()) if latest else {}
        from revel8_agent.engine import estimate_score
        score = estimate_score(state) if state else {}
        runs.append({
            "target": target, "exit": code, "wall_s": round(time.monotonic() - t0, 1),
            "results_points": score.get("results_points"), "incident_types": score.get("incident_types"),
            "api_confirmed": score.get("confirmed_by_api_event"), "run_file": str(latest) if latest else "",
            "status": state.get("status"), "error": state.get("error", ""),
            "touches": state.get("touches_used"), "incidents": len(state.get("incidents") or []),
            "first_incident_touch": min((i.get("touch", 99) for i in state.get("incidents") or []), default=None),
            "llm_calls": len(calls) - before,
            "on_topic": sum(1 for t in state.get("truth") or [] if t.get("topic_hit")),
        })
        print(f"[{args.model}] {target}: {runs[-1]}", flush=True)

    ok = [c for c in calls if c["ok"]]
    errs: dict[str, int] = {}
    for c in calls:
        if not c["ok"]:
            key = c["error"].split(".")[0][:60] or "error"
            errs[key] = errs.get(key, 0) + 1
    by_kind = {}
    for k in sorted({c["kind"] for c in calls}):
        ks = [c for c in calls if c["kind"] == k]
        by_kind[k] = {"n": len(ks), "fail": sum(not c["ok"] for c in ks),
                      "median_s": round(statistics.median(c["s"] for c in ks), 2)}
    summary = {
        "model": args.model, "mode": "real-practice" if args.real else "mock",
        "finished_utc": datetime.now(UTC).isoformat(), "decider": args.decider,
        "wall_s": round(time.monotonic() - t_all, 1),
        "calls": len(calls), "failed": len(calls) - len(ok),
        "fail_rate": round((len(calls) - len(ok)) / len(calls), 3) if calls else None,
        "errors": errs,
        "median_s": round(statistics.median(c["s"] for c in ok), 2) if ok else None,
        "p90_s": round(sorted(c["s"] for c in ok)[int(0.9 * (len(ok) - 1))], 2) if ok else None,
        "by_kind": by_kind,
        "runs_done": sum(r["status"] == "done" for r in runs), "runs": runs,
        "incidents": sum(r["incidents"] for r in runs),
        "refusal_samples": [c["sample"] for c in calls if c["error"] == "refusal"][:3],
        "error_samples": [c["error"] for c in calls if not c["ok"] and c["error"] != "refusal"][:5],
    }
    base.mkdir(parents=True, exist_ok=True)
    (base / f"{slug}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("runs",)}, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
