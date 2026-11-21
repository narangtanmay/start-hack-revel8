"""Rubric-shaped scoring and A/B proof for Revel8 attack runs.

Reads ``runs/<id>.json`` files (the ``RunState`` the engine writes) and scores
them against the challenge rubric so we can measure the agent and *prove* one
decision policy beats another.

What this computes, per the published rubric (100 pts):

- **Results (25)** — API-measured, computed here.
    - Incidents (20): ``20 * runs_with_incident / scored_runs``.
    - Speed (5):      ``5 * best_contacts / your_contacts`` (your_contacts =
      median contacts-to-first-incident).
- **Targeting (10)** — API-measured, computed here (topic share is an estimate,
  see below).
    - Their topic (6): ``6 * your_share / best_share``.
    - Your own angle (4): full if any run lands an incident via a hook the
      dossier flagged ``is_own_angle``.
- **Craft (10)** — only computed when per-item ratings are supplied (or an LLM
  rater is wired in); otherwise reported as "needs rating". The real score is a
  jury render after the window.
- **Architecture (40)** and **Pitch (15)** — jury-scored; reported as N/A.

Two categories are *relative to the best team* (Speed, Their-topic), whose
numbers we cannot know. They are computed against configurable baselines
(``best_contacts``, ``best_topic_share``) and labelled estimates. The absolute,
non-relative truth we own is: *did a run get an incident, and on which contact*.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

JsonObj = dict[str, Any]

# Rubric maxima.
MAX_INCIDENTS = 20.0
MAX_SPEED = 5.0
MAX_THEIR_TOPIC = 6.0
MAX_OWN_ANGLE = 4.0
MAX_CRAFT = 10.0
MAX_ARCHITECTURE = 40.0  # jury
MAX_PITCH = 15.0         # jury

_RENDERED_CHANNELS = {"email", "calendar_invite", "shared_document"}


@dataclass
class ScoreConfig:
    scored_runs: int = 3            # the rubric divides incidents by 3 eval runs
    best_contacts: float = 2.0      # assumed best team's contacts-to-first-incident
    best_topic_share: float = 1.0   # assumed best team's on-topic share
    susceptible_topic: list[str] = field(default_factory=list)  # keywords; empty => use each run's planned hook


# --------------------------------------------------------------------------- loading


def load_runs(paths: Iterable[str | Path]) -> list[JsonObj]:
    """Load run JSON from files and/or directories (``*.json`` within them)."""
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files.extend(sorted(q for q in p.glob("*.json") if q.name != "index.json"))
        elif p.is_file():
            files.append(p)
    runs: list[JsonObj] = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("run_id"):
            runs.append(data)
    return runs


# --------------------------------------------------------------------------- per-run extraction


def _steps(run: JsonObj) -> list[JsonObj]:
    return [s for s in run.get("steps", []) if isinstance(s, dict)]


def _sent_contacts(run: JsonObj) -> int:
    """Contacts actually spent (a STOP step sends nothing)."""
    sent = [s for s in _steps(run) if s.get("message_id") or s.get("conversation_id")]
    if sent:
        return len(sent)
    return int(run.get("touches_used") or 0)


def _incidents(run: JsonObj) -> list[JsonObj]:
    return [i for i in run.get("incidents", []) if isinstance(i, dict)]


def first_incident_contact(run: JsonObj) -> int | None:
    """The contact number (1-based touch) of the first incident, or None."""
    touches = [int(i["touch"]) for i in _incidents(run) if isinstance(i.get("touch"), (int, float))]
    return min(touches) if touches else None


def has_incident(run: JsonObj) -> bool:
    return first_incident_contact(run) is not None


def _planned_hook_keywords(run: JsonObj) -> list[str]:
    """Keywords describing the hook the campaign planned to ride."""
    plan = run.get("plan") or {}
    hook_id = str(plan.get("hook_id") or "")
    hooks = ((run.get("brief") or {}).get("hooks")) or []
    for h in hooks:
        if isinstance(h, dict) and str(h.get("id")) == hook_id:
            text = " ".join(str(h.get(k, "")) for k in ("topic", "rationale"))
            return [w.lower() for w in re.findall(r"[a-zA-Z][a-zA-Z0-9+/-]{3,}", text)][:12]
    return [w.lower() for w in re.findall(r"[a-zA-Z]{4,}", hook_id)]


def _step_text(step: JsonObj) -> str:
    a = step.get("action") or {}
    parts = [str(a.get("subject") or ""), str(a.get("call_goal") or "")]
    paras = a.get("paragraphs") or []
    if isinstance(paras, list):
        parts.extend(str(p) for p in paras)
    elif isinstance(paras, str):
        parts.append(paras)
    return " ".join(parts).lower()


def on_topic_share(run: JsonObj, topic_keywords: list[str]) -> float | None:
    """Share of sent contacts whose text mentions the susceptible topic.

    Estimate: topic match by keyword. If no keywords are given we fall back to
    the run's own planned hook, which measures focus, not correctness.
    """
    kws = [k.lower() for k in topic_keywords] or _planned_hook_keywords(run)
    sent = [s for s in _steps(run) if s.get("message_id") or s.get("conversation_id")]
    if not sent or not kws:
        return None
    hits = sum(1 for s in sent if any(k in _step_text(s) for k in kws))
    return hits / len(sent)


def used_own_angle(run: JsonObj) -> bool:
    """True if the run landed an incident while riding an ``is_own_angle`` hook."""
    if not has_incident(run):
        return False
    plan = run.get("plan") or {}
    hook_id = str(plan.get("hook_id") or "")
    for h in ((run.get("brief") or {}).get("hooks")) or []:
        if isinstance(h, dict) and str(h.get("id")) == hook_id:
            return bool(h.get("is_own_angle"))
    return False


def rendered_items(run: JsonObj) -> list[JsonObj]:
    """Emails and landing pages — the only things the craft jury renders."""
    items: list[JsonObj] = []
    for s in _steps(run):
        a = s.get("action") or {}
        if a.get("channel") in _RENDERED_CHANNELS and (s.get("message_id") or a.get("paragraphs")):
            items.append({"kind": f"mail:{a.get('channel')}", "touch": s.get("touch")})
        if isinstance(s.get("page"), dict) and s["page"].get("url"):
            items.append({"kind": "landing_page", "touch": s.get("touch"), "url": s["page"].get("url")})
    return items


# --------------------------------------------------------------------------- scoring


def _median(xs: list[float]) -> float | None:
    return statistics.median(xs) if xs else None


def score_run(run: JsonObj, cfg: ScoreConfig) -> JsonObj:
    first = first_incident_contact(run)
    share = on_topic_share(run, cfg.susceptible_topic)
    return {
        "run_id": run.get("run_id"),
        "target": (run.get("target") or {}).get("name") or (run.get("target") or {}).get("id"),
        "status": run.get("status"),
        "contacts_sent": _sent_contacts(run),
        "incident": has_incident(run),
        "first_incident_contact": first,
        "incident_types": sorted({str(i.get("type")) for i in _incidents(run)}),
        "incident_api_confirmed": any(i.get("source") == "api event" for i in _incidents(run)),
        "on_topic_share": share,
        "used_own_angle": used_own_angle(run),
        "rendered_items": len(rendered_items(run)),
    }


def score_suite(
    runs: list[JsonObj],
    cfg: ScoreConfig,
    craft_ratings: list[float] | None = None,
) -> JsonObj:
    """Aggregate a set of runs (e.g. the 3 eval runs) into a rubric scorecard."""
    per_run = [score_run(r, cfg) for r in runs]
    n = len(runs)
    denom = cfg.scored_runs if cfg.scored_runs > 0 else max(1, n)

    # Results -------------------------------------------------------------
    runs_with_incident = sum(1 for r in per_run if r["incident"])
    incidents_pts = min(MAX_INCIDENTS, MAX_INCIDENTS * runs_with_incident / denom)

    first_contacts = [r["first_incident_contact"] for r in per_run if r["first_incident_contact"]]
    your_contacts = _median([float(c) for c in first_contacts])
    speed_pts = min(MAX_SPEED, MAX_SPEED * cfg.best_contacts / your_contacts) if your_contacts else 0.0

    # Targeting -----------------------------------------------------------
    shares = [r["on_topic_share"] for r in per_run if r["on_topic_share"] is not None]
    your_share = _median([float(s) for s in shares])
    their_topic_pts = (
        min(MAX_THEIR_TOPIC, MAX_THEIR_TOPIC * your_share / cfg.best_topic_share)
        if your_share and cfg.best_topic_share > 0 else 0.0
    )
    own_angle_pts = MAX_OWN_ANGLE if any(r["used_own_angle"] for r in per_run) else 0.0

    # Craft ---------------------------------------------------------------
    total_rendered = sum(r["rendered_items"] for r in per_run)
    if craft_ratings:
        craft_median = _median([float(x) for x in craft_ratings]) or 0.0  # ratings on a 0..8 scale
        craft_pts: float | None = round(MAX_CRAFT * craft_median / 8.0, 2)
        craft_note = f"median of {len(craft_ratings)} supplied ratings (0-8 scaled to 10)"
    else:
        craft_pts = None
        craft_note = (
            f"{total_rendered} rendered item(s) across runs; not auto-scored "
            "(jury renders these, or supply --craft-ratings)"
        )

    measured = round(incidents_pts + speed_pts + their_topic_pts + own_angle_pts + (craft_pts or 0.0), 2)
    measured_max = 35 + (MAX_CRAFT if craft_pts is not None else 0)

    return {
        "n_runs": n,
        "scored_runs_assumed": denom,
        "results": {
            "incidents_points": round(incidents_pts, 2),
            "runs_with_incident": runs_with_incident,
            "speed_points": round(speed_pts, 2),
            "your_contacts_median": your_contacts,
            "subtotal": round(incidents_pts + speed_pts, 2),
            "max": 25,
        },
        "targeting": {
            "their_topic_points": round(their_topic_pts, 2),
            "your_topic_share_median": your_share,
            "own_angle_points": own_angle_pts,
            "subtotal": round(their_topic_pts + own_angle_pts, 2),
            "max": 10,
        },
        "craft": {"points": craft_pts, "rendered_items": total_rendered, "note": craft_note, "max": 10},
        "jury": {
            "architecture_points": None,
            "pitch_points": None,
            "max": int(MAX_ARCHITECTURE + MAX_PITCH),
            "note": "jury-scored; not measurable from run files",
        },
        "measured_total": measured,
        "measured_max": measured_max,
        "assumptions": {
            "best_contacts": cfg.best_contacts,
            "best_topic_share": cfg.best_topic_share,
            "topic_match": "keywords" if cfg.susceptible_topic else "each run's planned hook (focus, not correctness)",
            "note": "Speed and Their-topic are relative to the best team; points are estimates under these baselines.",
        },
        "per_run": per_run,
    }


def compare(label_a: str, runs_a: list[JsonObj], label_b: str, runs_b: list[JsonObj], cfg: ScoreConfig) -> JsonObj:
    """A/B proof: two policies scored on the same rubric, side by side."""
    a = score_suite(runs_a, cfg)
    b = score_suite(runs_b, cfg)
    return {
        "a": {"label": label_a, "score": a},
        "b": {"label": label_b, "score": b},
        "delta_measured_total": round(a["measured_total"] - b["measured_total"], 2),
        "winner": label_a if a["measured_total"] >= b["measured_total"] else label_b,
    }


# --------------------------------------------------------------------------- CLI


def _print_scorecard(card: JsonObj) -> None:
    r, t, c = card["results"], card["targeting"], card["craft"]
    print(f"  runs: {card['n_runs']}  (scored-runs assumed: {card['scored_runs_assumed']})")
    print(f"  Results   {r['subtotal']:>5}/25   incidents {r['incidents_points']} "
          f"({r['runs_with_incident']} w/ incident) + speed {r['speed_points']} "
          f"(median contacts: {r['your_contacts_median']})")
    print(f"  Targeting {t['subtotal']:>5}/10   their-topic {t['their_topic_points']} "
          f"(share {t['your_topic_share_median']}) + own-angle {t['own_angle_points']}")
    print(f"  Craft     {str(c['points']) + '/10' if c['points'] is not None else '  n/a':>8}   {c['note']}")
    print(f"  Jury      40+15 not measurable (architecture + pitch)")
    print(f"  ---> MEASURED TOTAL {card['measured_total']}/{card['measured_max']} "
          f"(of 45 API/craft pts; 55 are jury)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Score Revel8 runs against the rubric, or A/B compare two run sets.")
    ap.add_argument("runs", nargs="+", help="Run JSON files or directories.")
    ap.add_argument("--vs", nargs="+", metavar="RUN", help="A second run set to A/B compare against.")
    ap.add_argument("--scored-runs", type=int, default=3, help="Denominator for the incident rate (default 3).")
    ap.add_argument("--best-contacts", type=float, default=2.0, help="Assumed best team's contacts-to-first-incident.")
    ap.add_argument("--best-topic-share", type=float, default=1.0, help="Assumed best team's on-topic share.")
    ap.add_argument("--topic", nargs="*", default=[], help="Susceptible-topic keywords (default: each run's hook).")
    ap.add_argument("--craft-ratings", nargs="*", type=float, help="Per-item craft ratings on a 0-8 scale.")
    ap.add_argument("--labels", nargs=2, metavar=("A", "B"), default=["policy A", "policy B"])
    ap.add_argument("--json", action="store_true", help="Emit the scorecard as JSON.")
    args = ap.parse_args(argv)

    cfg = ScoreConfig(
        scored_runs=args.scored_runs, best_contacts=args.best_contacts,
        best_topic_share=args.best_topic_share, susceptible_topic=list(args.topic),
    )
    runs_a = load_runs(args.runs)
    if not runs_a:
        print("No run files found.", file=sys.stderr)
        return 1

    if args.vs:
        runs_b = load_runs(args.vs)
        result = compare(args.labels[0], runs_a, args.labels[1], runs_b, cfg)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
            return 0
        print(f"\n=== {result['a']['label']} ===")
        _print_scorecard(result["a"]["score"])
        print(f"\n=== {result['b']['label']} ===")
        _print_scorecard(result["b"]["score"])
        print(f"\n>>> winner (measured): {result['winner']}  (delta {result['delta_measured_total']:+})\n")
        return 0

    card = score_suite(runs_a, cfg, craft_ratings=args.craft_ratings)
    if args.json:
        print(json.dumps(card, indent=2, default=str))
        return 0
    print("\n=== Revel8 rubric scorecard ===")
    _print_scorecard(card)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
