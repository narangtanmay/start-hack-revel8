"""Snowball expansion for research v2: follow what the last round found, then fill what is missing.

Each round:
1. leads    the LLM names specific things in the verified facts worth following: events they speak at,
            people around them (co-founders, investors' partners, co-speakers, advisors), organisations
            they work with, projects they lead. A lead is kept only if its name occurs literally in the
            facts (no invented entities). Its timing comes from the dates of its supporting facts.
2. gaps     deterministic check for what a social engineer needs but the facts lack: upcoming talks,
            the people around them, hiring, what they are looking for, tools they use.
3. queries  templated queries per lead and per gap, English and German, never a query already run.
4. search -> identity check -> extraction -> verbatim verification, using research.py's own steps.

Rounds repeat while they still add facts and the time budget allows.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from .engine import timing
from .osint import Target
from .schemas import VerifiedFact

KINDS = ("event", "person", "organisation", "project")

# Minimum counts before a category stops being a gap. "upcoming_event" is computed from dates.
GAP_MIN = {"upcoming_event": 1, "network": 3, "hiring": 1, "interest": 2, "tooling": 1}

_PROMPT = """You extend research on {name} ({role} at {company}). TODAY: {today}.
Below are verified facts, each with an id and a date. Return ONLY JSON:
{{"anchors": [str], "leads": [{{"kind": "event"|"person"|"organisation"|"project", "name": str, "fact_ids": [str]}}],
  "queries": [str]}}
- anchors: up to 6 identity anchors that tell THIS person apart from namesakes and appear literally in the facts:
  earlier employers, universities, cities, co-founders, personal handles, distinctive project names.
- leads: up to 8 specific named things to follow up NOW, copied exactly as written in the facts:
  events they speak at or attend (upcoming first), people around them (co-founders, investors' partners,
  co-speakers, advisors, customers' contacts), organisations they partner with or buy from, projects they lead.
  Never {name} themself, never "{company}" alone, never generic words ("conference", "investors").
- queries: up to 4 web queries about the PERSON (not the company) for things the facts hint at but do not cover:
  earlier career, studies, talks at other events, side projects, sports or hobbies, charities, co-authored work,
  podcasts. Each must contain "{name}" in quotes."""


@dataclass
class Lead:
    kind: str
    name: str
    timing: str  # "upcoming" | "current" | "past"
    fact_ids: list[str] = field(default_factory=list)

    @property
    def priority(self) -> int:
        if self.timing == "past":
            return 4
        if self.kind == "event":
            return 0 if self.timing == "upcoming" else 2
        return 1 if self.kind == "person" else 2


def fold_text(text: str) -> str:
    from .research import fold

    return fold(text)


def _lead_timing(facts: Sequence[VerifiedFact], today: datetime) -> str:
    labels = [timing(f.recency, today) for f in facts]
    if "upcoming" in labels:
        return "upcoming"
    if labels and all(label == "past" for label in labels):
        return "past"
    return "current"


def parse_leads(raw: object, facts: Sequence[VerifiedFact], t: Target, today: datetime | None = None) -> list[Lead]:
    """Keep only leads whose name occurs in the facts, with a valid kind; dedupe; sort by priority."""
    today = today or datetime.now()
    by_id = {f"r{i}": f for i, f in enumerate(facts, 1)}
    corpus = fold_text(" ".join(f"{f.fact} {f.verbatim_quote}" for f in facts))
    banned = {fold_text(t.name), fold_text(t.company), *map(fold_text, t.name.split())}
    leads: list[Lead] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower()
        name = str(item.get("name") or "").strip().strip("\"'“”„").strip()
        key = fold_text(name)
        if kind not in KINDS or not 3 <= len(name) <= 60 or key in banned or key in seen or key not in corpus:
            continue
        ids = [i for i in item.get("fact_ids") or [] if isinstance(i, str) and i in by_id]
        support = [by_id[i] for i in ids] or [f for f in facts if key in fold_text(f"{f.fact} {f.verbatim_quote}")]
        seen.add(key)
        leads.append(Lead(kind, name, _lead_timing(support, today), ids))
    return sorted(leads, key=lambda lead: lead.priority)


def find_gaps(facts: Sequence[VerifiedFact], today: datetime | None = None) -> list[str]:
    today = today or datetime.now()
    counts = {k: 0 for k in GAP_MIN}
    for f in facts:
        if f.category == "talk_or_event" and timing(f.recency, today) == "upcoming":
            counts["upcoming_event"] += 1
        if f.category in counts:
            counts[f.category] += 1
    return [k for k, minimum in GAP_MIN.items() if counts[k] < minimum]


def _gap_queries(t: Target, gap: str, today: datetime) -> list[str]:
    n = f'"{t.name}"'
    years = f"{today.year} OR {today.year + 1}"
    return {
        "upcoming_event": [f"{n} Vortrag OR Keynote OR Speaker OR Panel {years}",
                           f'{n} "will speak" OR "join me" OR "see you at" OR "speaking at"'],
        "network": [f"{n} Mitgründer OR co-founder OR advisor OR Beirat OR mentor OR investor"],
        "hiring": [f'{n} hiring OR "we are hiring" OR "join our team" OR Stellenangebot OR "wir suchen"'],
        "interest": [f'{n} "looking for" OR "reach out" OR "excited to" OR "freue mich" OR "suchen"'],
        "tooling": [f'{n} "we use" OR "built on" OR stack OR tools OR "wir nutzen" OR "setzen auf"'],
    }.get(gap, [])


def _lead_queries(t: Target, lead: Lead) -> list[str]:
    n, last = f'"{t.name}"', t.name.split()[-1]
    if lead.kind == "event":
        return [f'{n} "{lead.name}"', f'"{lead.name}" {last} agenda OR Programm OR speakers OR Referenten']
    return [f'{n} "{lead.name}"']


def plan_round(t: Target, leads: Sequence[Lead], gaps: Sequence[str], free_queries: Sequence[object],
               done: set[str], max_queries: int = 10, today: datetime | None = None) -> list[str]:
    """Order: each live lead's best query, then gaps, then the LLM's own queries, then remaining lead queries."""
    today = today or datetime.now()
    live = [lead for lead in leads if lead.timing != "past"]
    per_lead = [_lead_queries(t, lead) for lead in live]
    free: list[str] = []
    for q in free_queries:
        if isinstance(q, str) and q.strip():
            q = q.strip()
            free.append(q if fold_text(t.name) in fold_text(q) else f'"{t.name}" {q}')
    ordered = ([qs[0] for qs in per_lead]
               + [q for g in gaps for q in _gap_queries(t, g, today)]
               + free[:4]
               + [q for qs in per_lead for q in qs[1:]]
               + [q for lead in leads if lead.timing == "past" for q in _lead_queries(t, lead)[:1]])
    out: list[str] = []
    for q in ordered:
        key = fold_text(q)
        if key not in done and len(q) <= 300:
            done.add(key)
            out.append(q)
        if len(out) >= max_queries:
            break
    return out


def run_snowball(
    t: Target,
    llm: object,
    ident: object,
    facts: list[VerifiedFact],
    st: dict,
    *,
    run_queries: Callable[[list[tuple[str, str, str, int]]], list],
    to_docs: Callable[[list], list],
    extract_all: Callable[[list], None],
    left: Callable[[], float],
    log: Callable[[str], None] = print,
    max_rounds: int = 2,
    min_left_s: float = 90.0,
    min_new_facts: int = 3,
    max_docs: int = 20,
    max_queries: int = 10,
) -> list:
    """Run expansion rounds in place: new facts are appended to `facts` by `extract_all`. Returns new docs."""
    from .research import _json, fold

    st.setdefault("snowball", [])
    st.setdefault("expansion_queries", [])
    st.setdefault("anchors_added", [])
    done = {fold(q["query"]) for q in st.get("search", []) if isinstance(q, dict) and q.get("query")}
    new_docs: list = []
    for round_no in range(1, max_rounds + 1):
        if left() < min_left_s or not facts:
            break
        started, before, today = time.monotonic(), len(facts), datetime.now()
        listing = "\n".join(f"[r{i}] ({f.category}, {f.recency}) {f.fact} | quote: {f.verbatim_quote}"
                            for i, f in enumerate(facts, 1))[:14000]
        out = _json(llm, _PROMPT.format(name=t.name, role=t.role, company=t.company, today=f"{today:%Y-%m-%d}"),
                    listing, temperature=0.3)
        quotes = fold(" ".join(f.verbatim_quote for f in facts))
        for a in (out.get("anchors") or [])[:6]:
            if isinstance(a, str) and fold(a) in quotes and ident.add_anchor(a):
                st["anchors_added"].append(a)
        leads = parse_leads(out.get("leads"), facts, t, today)
        gaps = find_gaps(facts, today)
        queries = plan_round(t, leads, gaps, out.get("queries") or [], done, max_queries, today)
        record = {"round": round_no, "leads": [vars(lead) for lead in leads], "gaps": gaps, "queries": queries}
        st["snowball"].append(record)
        if not queries:
            log(f"[{t.id}] snowball {round_no}: nothing new to search")
            break
        log(f"[{t.id}] snowball {round_no}: {len(leads)} leads, gaps {gaps}, {len(queries)} queries")
        st["expansion_queries"] += queries
        docs = to_docs(run_queries([("expansion", "web", q, 10) for q in queries]))[:max_docs]
        extract_all(docs)
        new_docs += docs
        record.update(new_docs=len(docs), new_facts=len(facts) - before,
                      seconds=round(time.monotonic() - started, 1))
        log(f"[{t.id}] snowball {round_no}: +{len(docs)} sources, +{len(facts) - before} facts")
        if len(facts) - before < min_new_facts:
            break
    return new_docs
