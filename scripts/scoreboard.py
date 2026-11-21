"""Per-run scoreboard for benchmark runs (mock and real practice).

Reads every run state under runs/bench/models*/<model>/ and prints one row per run with the rubric-shaped
Results estimate from engine.estimate_score (20 pts for an incident + up to 5 for speed vs. a best team at 2
contacts), plus Targeting share on the mock target (it records topic hits; the real API does not expose them).
Flags runs that are still going and how long since their last update.

Usage: uv run python scripts/scoreboard.py [--stall 240] [--md out.md]
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from revel8_agent.engine import estimate_score


def rows(stall_s: float) -> list[dict]:
    out = []
    for p in sorted(Path("runs/bench").glob("models*/*/*.json")):
        try:
            d = json.loads(p.read_text())
        except ValueError:
            continue
        if "steps" not in d:
            continue
        mode = "real" if "models-real" in str(p) else "mock"
        sc = estimate_score(d)
        truth = d.get("truth") or []
        idle = time.time() - p.stat().st_mtime
        live = d.get("status") in ("starting", "running")
        out.append({
            "mode": mode, "model": p.parent.name, "target": (d.get("target") or {}).get("id", "?"),
            "status": ("STALLED?" if live and idle > stall_s else d.get("status")),
            "touches": d.get("touches_used", 0), "llm_calls": d.get("llm_calls", 0),
            "first_incident": sc["first_incident_touch"], "types": ",".join(sc["incident_types"]),
            "api_confirmed": sc["confirmed_by_api_event"], "results_pts": sc["results_points"],
            "topic_share": round(sum(t.get("topic_hit", False) for t in truth) / len(truth), 2) if truth else None,
            "idle_s": int(idle), "error": (d.get("error") or "")[:60], "file": p.name,
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stall", type=float, default=240)
    ap.add_argument("--md", default="")
    args = ap.parse_args()
    rs = rows(args.stall)
    hdr = ("mode", "model", "target", "status", "touches", "first_incident", "types", "api_confirmed",
           "results_pts", "topic_share", "llm_calls", "idle_s", "error")
    lines = ["| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)]
    for r in rs:
        lines.append("| " + " | ".join("" if r[h] is None else str(r[h]) for h in hdr) + " |")
    # per model (done runs): mean Results over its runs = expected Results for a 3-run eval with these odds
    lines.append("")
    lines.append("| mode | model | runs done | incidents | median first incident | mean results pts (of 25) |")
    lines.append("|---|---|---|---|---|---|")
    for mode in ("real", "mock"):
        for m in sorted({r["model"] for r in rs if r["mode"] == mode}):
            done = [r for r in rs if r["mode"] == mode and r["model"] == m and r["status"] == "done"]
            if not done:
                continue
            firsts = [r["first_incident"] for r in done if r["first_incident"]]
            lines.append(f"| {mode} | {m} | {len(done)} | {len(firsts)} | "
                         f"{statistics.median(firsts) if firsts else '-'} | "
                         f"{round(statistics.mean(r['results_pts'] for r in done), 1)} |")
    text = "\n".join(lines)
    print(text)
    if args.md:
        Path(args.md).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
