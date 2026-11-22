"""Does the hook score predict how targets actually respond? Ground truth = outcomes of real practice runs.

For every message touch in every real (non-mock) practice run, take the hook that touch used, re-score it with
the CURRENT score_hook() against the facts in that run's own brief, and label what the target did:

  outcome 0  no reply
          1  replied, but routed us elsewhere (sales, a colleague, info@, the website)
          2  replied and engaged personally
          3  API engagement event (link.opened / attachment.opened)
          4  API-confirmed incident (page.submitted / credentials / attachment incident)

Reports Spearman rank correlation (score vs outcome) with a bootstrap 90% interval, per-component correlations,
routing rate by needs_him bucket, and mean outcome by score tercile. Touches are not independent (same run,
same target), so runs are resampled as units in the bootstrap.

Usage: uv run python scripts/eval_hook_ranking.py [--runs runs] [--json out.json]
"""

import argparse
import glob
import json
import random
import re
import statistics
from pathlib import Path

from revel8_agent.research import normalize, score_hook
from revel8_agent.schemas import HookHypothesis, VerifiedFact

ROUTED = re.compile(
    r"sales|hello@|info@|press@|contact form|via (?:our|the) website|book a (?:slot|demo|call)|pass (?:it|this) (?:on )?to|"
    r"forward(?:ed)? (?:it|this) to|colleague|solution engineering|our team (?:will|handles)|handled by|go(?:es)? through|"
    r"will get in touch with you|reach out to (?:our|my)|please (?:send|write) (?:it |this )?to|careers page|"
    r"vertrieb|kollegin|kollege|weiterleiten", re.I)
API_ENGAGE = {"link.opened", "attachment.opened"}
API_INCIDENT = {"page.submitted"}
COMPONENTS = ["needs_him", "openness", "recency", "personal", "specificity", "breadth", "llm_confidence"]


def spearman(xs: list[float], ys: list[float]) -> float:
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    if len(xs) < 3:
        return float("nan")
    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx) ** 0.5
    vy = sum((b - my) ** 2 for b in ry) ** 0.5
    return cov / (vx * vy) if vx and vy else float("nan")


def bootstrap(rows: list[dict], key: str, n: int = 2000, seed: int = 0) -> tuple[float, float]:
    by_run: dict[str, list[dict]] = {}
    for r in rows:
        by_run.setdefault(r["run"], []).append(r)
    runs = list(by_run)
    rng = random.Random(seed)
    vals = []
    for _ in range(n):
        sample = [t for _ in runs for t in by_run[rng.choice(runs)]]
        v = spearman([t[key] for t in sample], [t["outcome"] for t in sample])
        if v == v:
            vals.append(v)
    vals.sort()
    return (vals[int(0.05 * len(vals))], vals[int(0.95 * len(vals)) - 1]) if vals else (float("nan"), float("nan"))


def load_rows(runs_dir: str) -> list[dict]:
    rows = []
    for fn in sorted(glob.glob(f"{runs_dir}/**/*.json", recursive=True)):
        try:
            r = json.loads(Path(fn).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(r, dict) or "steps" not in r or not isinstance(r.get("brief"), dict):
            continue
        if str(r.get("session_id", "")).startswith("s_mock") or (r.get("config") or {}).get("scenario_id") != "practice":
            continue
        brief = r["brief"]
        name = (brief.get("target") or {}).get("name") or ""
        if not name:
            continue
        surname, first = normalize(name.split()[-1]), normalize(name.split()[0])
        by_id = {}
        for f in brief.get("facts") or []:
            if isinstance(f, dict) and f.get("id"):
                by_id[f["id"]] = VerifiedFact(id=f["id"], fact=f.get("fact", ""), category=f.get("category", "other"),
                                              source_url="", verbatim_quote=f.get("fact", ""), recency=f.get("recency", ""))
        hooks = {h["id"]: h for h in brief.get("hooks") or [] if isinstance(h, dict) and h.get("id")}
        scored: dict[str, tuple[float, dict]] = {}
        for hid, h in hooks.items():
            try:
                hh = HookHypothesis(id=hid, topic=h.get("topic", ""), rationale=h.get("rationale", ""),
                                    confidence=float(h.get("confidence") or 0.5),
                                    supporting_fact_ids=[i for i in h.get("supporting_fact_ids") or [] if i in by_id],
                                    open_signal=h.get("open_signal") or "", sender_archetype=h.get("sender_archetype") or "",
                                    natural_ask=h.get("natural_ask") or "")
            except (TypeError, ValueError):
                continue
            scored[hid] = score_hook(hh, by_id, [], surname, first)
        for s in r["steps"]:
            a = s.get("action") or {}
            if a.get("kind") == "call" or a.get("hook_id") not in scored:
                continue
            events = s.get("events") or []
            types = {e.get("type") for e in events}
            replies = [e.get("body", "") for e in events if e.get("type") == "reply"]
            api_inc = any(i.get("source") == "api event" and i.get("touch") == s.get("touch") for i in r.get("incidents") or [])
            if api_inc or types & API_INCIDENT:
                outcome = 4
            elif types & API_ENGAGE:
                outcome = 3
            elif replies and not any(ROUTED.search(b) for b in replies):
                outcome = 2
            elif replies:
                outcome = 1
            else:
                outcome = 0
            score, parts = scored[a["hook_id"]]
            rows.append({"run": fn, "target": (r.get("config") or {}).get("target_id"), "touch": s.get("touch"),
                         "hook": a["hook_id"], "topic": hooks[a["hook_id"]].get("topic", "")[:70],
                         "sender": hooks[a["hook_id"]].get("sender_archetype", "")[:70],
                         "score": score, **{c: parts.get(c, 0.0) for c in COMPONENTS}, "outcome": outcome,
                         "routed": outcome == 1, "replied": outcome >= 1})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    rows = load_rows(args.runs)
    runs = {r["run"] for r in rows}
    print(f"{len(rows)} message touches from {len(runs)} real practice runs")
    dist = {k: sum(1 for r in rows if r["outcome"] == k) for k in range(5)}
    print("outcomes: 0 no reply={0}  1 routed={1}  2 engaged={2}  3 api engage={3}  4 api incident={4}".format(*dist.values()))
    print("\nSpearman vs outcome (90% CI, runs resampled):")
    for key in ["score"] + COMPONENTS:
        rho = spearman([r[key] for r in rows], [r["outcome"] for r in rows])
        lo, hi = bootstrap(rows, key, n=1000)
        print(f"  {key:15} rho={rho:+.3f}  [{lo:+.3f}, {hi:+.3f}]")
    print("\nneeds_him bucket   touches  replied  routed-of-replies  engaged(2+)")
    for lo, hi, label in [(0, 0.3, "low (<0.3)"), (0.3, 0.7, "mid"), (0.7, 1.01, "high (>=0.7)")]:
        b = [r for r in rows if lo <= r["needs_him"] < hi]
        if b:
            rep = [r for r in b if r["replied"]]
            print(f"  {label:16} {len(b):7}  {len(rep)/len(b):6.0%}  {sum(r['routed'] for r in rep)/max(1,len(rep)):17.0%}"
                  f"  {sum(r['outcome']>=2 for r in b)/len(b):10.0%}")
    srt = sorted(rows, key=lambda r: r["score"])
    k = len(srt) // 3
    print("\nscore tercile      touches  mean score  mean outcome  engaged(2+)")
    for label, part in [("low", srt[:k]), ("mid", srt[k:2 * k]), ("high", srt[2 * k:])]:
        if part:
            print(f"  {label:16} {len(part):7}  {statistics.fmean(r['score'] for r in part):10.3f}"
                  f"  {statistics.fmean(r['outcome'] for r in part):12.2f}  {sum(r['outcome']>=2 for r in part)/len(part):10.0%}")
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"\nper-touch rows written to {args.json}")


if __name__ == "__main__":
    main()
