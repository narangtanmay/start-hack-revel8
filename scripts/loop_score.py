#!/usr/bin/env python3
"""Score archived runs on the two dimensions that actually matter in the loop.

    python scripts/loop_score.py runs/*loop*.json

Per run: first incident touch (lower is better, `-` when none), incident count,
reply touches, calls offered / accepted / placed / completed, and the first touch
where a concrete slot was proposed. Eyeballing "did it feel better" hid that
loop2/loop3/loop4 all converted at touch 2 while only loop4 moved the call leg.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

FIELDS = ("first_incident", "incidents", "replied", "proposed", "accepted", "dialled", "completed")


def score(path: Path) -> dict[str, Any]:
    run = json.loads(path.read_text())
    steps = run.get("steps") or []
    first_incident = next((int(i["touch"]) for i in run.get("incidents") or [] if i.get("touch")), None)
    if first_incident is None:
        first_incident = next(
            (int(s.get("touch") or n) for n, s in enumerate(steps, 1) if s.get("incidents")), None
        )

    def first(pred) -> int | None:
        return next((int(s.get("touch") or n) for n, s in enumerate(steps, 1) if pred(s)), None)

    def state(s: dict[str, Any]) -> dict[str, Any]:
        return s.get("target_state") or {}

    return {
        "run": path.name,
        "status": run.get("status"),
        "touches": len(steps),
        "first_incident": first_incident,
        "incidents": len(run.get("incidents") or []),
        "replied": sum(1 for s in steps if any(e.get("type") == "reply" for e in s.get("events") or [])),
        "proposed": first(lambda s: state(s).get("call_proposed")),
        "accepted": first(lambda s: state(s).get("call_accepted")),
        "dialled": first(lambda s: s.get("policy", {}).get("move_type") == "ESCALATE_CALL"),
        "completed": first(lambda s: state(s).get("call_completed")),
    }


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv[1:]] or sorted(Path("runs").glob("*.json"))
    if not paths:
        print("no run files")
        return 1
    width = max(len(p.name) for p in paths)
    print(f"{'run':<{width}}  " + "  ".join(f"{f:>14}" for f in FIELDS))
    for path in paths:
        row = score(path)
        cells = "  ".join(f"{row[f] if row[f] is not None else '-':>14}" for f in FIELDS)
        print(f"{path.name:<{width}}  {cells}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
