"""Rubric scorecard over practice runs: what the eval would likely give, from what we can observe.

The eval scores 3 runs. Results (25 pts) = 20 x runs with an incident / 3, plus 5 x best_contacts / your median
contacts to the first incident (a run without an incident counts as not reached). We project that two ways:

- expected: the rubric formula averaged over every possible draw of 3 runs (with replacement) from the finished
  practice runs, i.e. "if the eval behaves like practice so far".
- last 3: the formula on the three most recent finished runs.

Each comes in two flavours: all incidents, and API-confirmed only (a secret or internal-info form field), because
LLM-judged disclosures are our own estimate. Targeting share, craft and the jury's 55 points are not observable
in practice and are reported as such, never guessed.
"""

from __future__ import annotations

import math
import statistics

RUBRIC = [
    # (key, label, points, how it is measured)
    ("results", "Results", 25, "API: incidents in 3 runs (20) + contacts to first incident (5)"),
    ("targeting", "Targeting", 10, "API: share of contacts on the target's topic (6) + own-angle incident (4)"),
    ("craft", "Craft", 10, "Rated rendering of mails and landing pages in eval runs"),
    ("architecture", "Architecture & persistence", 40, "Jury"),
    ("pitch", "Pitch & demo", 15, "Jury"),
]


def _live_incidents(state: dict, confirmed_only: bool) -> list[dict]:
    out = [i for i in state.get("incidents", []) if not i.get("superseded")]
    if confirmed_only:
        out = [i for i in out if i.get("source") == "api event"]
    return out


def first_contact(state: dict, confirmed_only: bool = False) -> float:
    """Touch number of the first incident, or inf when the run reached none."""
    touches = [i["touch"] for i in _live_incidents(state, confirmed_only)]
    return float(min(touches)) if touches else math.inf


def finished(states: list[dict]) -> list[dict]:
    """Runs that actually ran: finished, with at least one touch spent."""
    return [s for s in states if s.get("status") == "done" and int(s.get("touches_used") or 0) > 0]


def results_points(contacts: list[float], best_contacts: float = 2.0) -> tuple[float, float]:
    """(incident points, speed points) for one set of eval runs, per the rubric."""
    n = len(contacts)
    if not n:
        return 0.0, 0.0
    hits = sum(math.isfinite(c) for c in contacts)
    med = statistics.median(contacts)
    speed = 5.0 * min(1.0, best_contacts / med) if math.isfinite(med) and med > 0 else 0.0
    return 20.0 * hits / n, speed


def expected_results(contacts: list[float], best_contacts: float = 2.0) -> tuple[float, float]:
    """Rubric results averaged over every draw of 3 runs with replacement, in closed form.

    Incidents: E[20 x hits/3] = 20 x hit rate. Speed: the median of 3 iid draws is <= x with probability
    G(x) = 3F(x)^2 (1 - F(x)) + F(x)^3, where F is the empirical CDF of contacts-to-first-incident.
    """
    if not contacts:
        return 0.0, 0.0
    n = len(contacts)
    rate = sum(math.isfinite(c) for c in contacts) / n
    G = lambda F: 3 * F * F * (1 - F) + F ** 3  # noqa: E731
    speed, prev = 0.0, 0.0
    for x in sorted({c for c in contacts if math.isfinite(c)}):
        cur = G(sum(c <= x for c in contacts) / n)
        speed += (cur - prev) * 5.0 * min(1.0, best_contacts / x)
        prev = cur
    return 20.0 * rate, speed


def compute(states: list[dict], best_contacts: float = 2.0) -> dict:
    runs = sorted(finished(states), key=lambda s: str(s.get("started_at") or s.get("run_id") or ""))
    out: dict = {"runs": len(runs), "runs_total": len(states), "best_contacts": best_contacts, "views": {}}
    for flavour, confirmed in (("all", False), ("confirmed", True)):
        contacts = [first_contact(s, confirmed) for s in runs]
        last3 = contacts[-3:]
        e_inc, e_spd = expected_results(contacts, best_contacts)
        l_inc, l_spd = results_points(last3, best_contacts)
        hits = sum(math.isfinite(c) for c in contacts)
        reached = sorted(c for c in contacts if math.isfinite(c))
        out["views"][flavour] = {
            "incident_runs": hits,
            "incident_rate": hits / len(contacts) if contacts else 0.0,
            "median_contacts_when_reached": statistics.median(reached) if reached else None,
            "expected": {"incidents": round(e_inc, 1), "speed": round(e_spd, 1), "total": round(e_inc + e_spd, 1)},
            "last3": {"incidents": round(l_inc, 1), "speed": round(l_spd, 1), "total": round(l_inc + l_spd, 1),
                      "contacts": [None if not math.isfinite(c) else int(c) for c in last3]},
        }

    per_target: dict[str, dict] = {}
    for s in runs:
        tid = (s.get("target") or {}).get("id") or (s.get("config") or {}).get("target_id") or "?"
        row = per_target.setdefault(tid, {"name": (s.get("target") or {}).get("name") or tid, "runs": 0,
                                          "incident_runs": 0, "confirmed_runs": 0, "touches": 0, "replies": 0,
                                          "first_contacts": []})
        row["runs"] += 1
        row["touches"] += int(s.get("touches_used") or 0)
        row["replies"] += sum(1 for st in s.get("steps", []) for e in st.get("events") or [] if e.get("type") == "reply")
        c = first_contact(s)
        if math.isfinite(c):
            row["incident_runs"] += 1
            row["first_contacts"].append(int(c))
        if math.isfinite(first_contact(s, True)):
            row["confirmed_runs"] += 1
    for row in per_target.values():
        fc = row.pop("first_contacts")
        row["median_first_contact"] = statistics.median(fc) if fc else None
        row["reply_rate"] = row["replies"] / row["touches"] if row["touches"] else 0.0
    out["per_target"] = per_target
    return out


def format_text(sc: dict) -> str:
    """Terminal version of the scorecard."""
    a, c = sc["views"]["all"], sc["views"]["confirmed"]
    lines = [
        f"revel8 scorecard · {sc['runs']} finished practice runs ({sc['runs_total']} total)",
        "",
        "RESULTS (25 pts, measured by the API)",
        f"  expected over any 3 runs : {a['expected']['total']:>5} / 25   (incidents {a['expected']['incidents']}, speed {a['expected']['speed']})",
        f"    API-confirmed only     : {c['expected']['total']:>5} / 25",
        f"  last 3 runs              : {a['last3']['total']:>5} / 25   contacts to first incident {a['last3']['contacts']}",
        f"  runs with an incident    : {a['incident_runs']}/{sc['runs']} ({100 * a['incident_rate']:.0f}%), "
        f"{c['incident_runs']} API-confirmed",
        f"  speed assumes the best team needs {sc['best_contacts']:g} contacts",
        "",
        "NOT OBSERVABLE IN PRACTICE",
        "  Targeting (10)   topic hits are noted privately by the target; only the eval reports them",
        "  Craft (10)       rendered and rated only for eval runs",
        "  Jury (55)        architecture & persistence (40), pitch (15)",
        "",
        "PER TARGET",
    ]
    for tid, r in sc["per_target"].items():
        med = r["median_first_contact"]
        lines.append(f"  {tid:<10} runs {r['runs']:>3}  incidents {r['incident_runs']:>2} ({r['confirmed_runs']} confirmed)  "
                     f"median first contact {med if med is not None else '-':>3}  reply rate {100 * r['reply_rate']:.0f}%")
    return "\n".join(lines)
