"""Snowball expansion for research v2: follow what the last round found, then fill what is missing.

Each round:
1. leads    the LLM names specific things in the verified facts worth following: events they speak at,
            people around them (co-founders, investors' partners, co-speakers, advisors), organisations
            they work with, projects they lead. A lead is kept only if its name occurs literally in the
            facts (no invented entities) and was not followed in an earlier round. The newest facts are
            shown first, so each round builds on what the previous one found. Event timing comes from the
            dates of the supporting facts; people and organisations count as current relationships.
2. gaps     deterministic check for what a social engineer needs but the facts lack: upcoming talks,
            the people around them, hiring, what they are looking for, tools they use.
3. queries  short templated queries per lead and per gap (English and German, LinkedIn posts for
            hiring and "looking for"), spread over rounds; never a query already run. The LLM's own
            follow-up queries are kept only if they add something specific beyond name, company and role.
4. search -> identity check -> extraction -> verbatim verification, using research.py's own steps.

Rounds repeat while they still add facts and the time budget allows.
"""

from __future__ import annotations

import re
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

# Words that say nothing specific about a person: too common to anchor identity or to make a query worth running.
GENERIC = {
    # roles
    "ceo", "cto", "coo", "cfo", "cpo", "cmo", "ciso", "founder", "co-founder", "cofounder", "mitgruender",
    "gruender", "managing director", "geschaeftsfuehrer", "head", "engineer", "manager", "partner", "director",
    # places
    "berlin", "munich", "muenchen", "hamburg", "frankfurt", "cologne", "koeln", "stuttgart", "london", "paris",
    "vienna", "wien", "zurich", "zuerich", "germany", "deutschland", "europe", "europa", "dach", "usa",
    # topics and fillers
    "ai", "cybersecurity", "cyber security", "security", "startup", "start-up", "tech", "technology",
    "talk", "interview", "news", "linkedin", "profile", "career", "company", "team",
}

_PROMPT = """You extend research on {name} ({role} at {company}). TODAY: {today}.
Below are verified facts, newest first, each with an id and a date. Return ONLY JSON:
{{"anchors": [str], "leads": [{{"kind": "event"|"person"|"organisation"|"project", "name": str, "fact_ids": [str]}}],
  "queries": [str]}}
- anchors: up to 6 identity anchors that tell THIS person apart from namesakes and appear literally in the facts:
  earlier employers, universities, co-founders, personal handles, distinctive project names. Never a job title,
  a city or a country on its own.
- leads: up to 8 specific named things to follow up NOW, copied exactly as written in the facts:
  events they speak at or attend (upcoming first), people around them (co-founders, investors' partners,
  co-speakers, moderators, advisors, customers' contacts), organisations they partner with, invest with or buy from
  (kind "organisation" for companies and funds), projects they lead.
  Never {name} themself, never "{company}" alone, never generic words ("conference", "investors").
  ALREADY FOLLOWED (do not repeat): {followed}
- queries: up to 4 web queries about the PERSON (not the company) for specific things the facts hint at but do not
  cover: earlier career, studies, talks at other events, side projects, sports or hobbies, charities, co-authored
  work, podcasts. Each must contain "{name}" in quotes and at least one specific term (a name, title or place)."""


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


def _event_timing(facts: Sequence[VerifiedFact], today: datetime) -> str:
    labels = [timing(f.recency, today) for f in facts]
    if "upcoming" in labels:
        return "upcoming"
    if labels and all(label == "past" for label in labels):
        return "past"
    return "current"


def is_generic(term: str, t: Target) -> bool:
    """True if a term is only a role, place, topic, or the target's own name or company."""
    own = {fold_text(t.name), fold_text(t.company), *map(fold_text, t.name.split()),
           *(fold_text(w) for w in re.split(r"[\s,&()/]+", t.role) if w)}
    words = [w for w in re.split(r"[\s,;:/()\"'“”„]+", fold_text(term)) if w and w not in {"or", "and", "the", "of"}]
    return not words or fold_text(term).strip() in GENERIC or all(w in GENERIC or w in own for w in words)


def good_anchor(anchor: str, t: Target) -> bool:
    a = anchor.strip()
    return len(a) >= 4 and not is_generic(a, t)


def parse_leads(raw: object, facts: Sequence[VerifiedFact], t: Target, today: datetime | None = None,
                exclude: set[str] | None = None) -> list[Lead]:
    """Keep only new leads whose name occurs in the facts, with a valid kind; dedupe; sort by priority.

    `facts` must be in the order shown to the LLM: its fact ids are r1, r2, ... in that order.
    """
    today = today or datetime.now()
    exclude = exclude or set()
    by_id = {f"r{i}": f for i, f in enumerate(facts, 1)}
    corpus = fold_text(" ".join(f"{f.fact} {f.verbatim_quote}" for f in facts))
    leads: list[Lead] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower()
        name = str(item.get("name") or "").strip().strip("\"'“”„").strip()
        key = fold_text(name)
        if (kind not in KINDS or not 3 <= len(name) <= 60 or key in seen or key in exclude
                or key not in corpus or is_generic(name, t)):
            continue
        ids = [i for i in item.get("fact_ids") or [] if isinstance(i, str) and i in by_id]
        support = [by_id[i] for i in ids] or [f for f in facts if key in fold_text(f"{f.fact} {f.verbatim_quote}")]
        seen.add(key)
        when = _event_timing(support, today) if kind == "event" else "current"
        leads.append(Lead(kind, name, when, ids))
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


def gap_queries(t: Target, gap: str, today: datetime) -> list[str]:
    """Short queries, strongest first; later ones are used in later rounds while the gap stays open."""
    n = f'"{t.name}"'
    y, y1 = today.year, today.year + 1
    # Late in the year, upcoming talks are mostly next year's.
    years = f"{y1}" if today.month >= 10 else f"{y} OR {y1}"
    return {
        "upcoming_event": [f"{n} speaker {years}", f"{n} Referent OR Vortrag {years}", f"{n} agenda {years}",
                           f"{n} webinar OR fireside OR roundtable"],
        "network": [f"{n} advisor OR mentor OR Beirat", f"{n} co-founder OR Mitgründer"],
        "hiring": [f"site:linkedin.com/posts {n} hiring", f'{n} "we\'re hiring" OR "join our team"'],
        "interest": [f'site:linkedin.com/posts {n} "looking for"', f'{n} "looking for" OR "suchen"'],
        "tooling": [f'{n} "we use" OR "built on"', f"{n} architecture OR engineering OR stack"],
    }.get(gap, [])


def _lead_queries(t: Target, lead: Lead) -> list[str]:
    n, last = f'"{t.name}"', t.name.split()[-1]
    if lead.kind == "event":
        return [f'{n} "{lead.name}"', f'"{lead.name}" {last} agenda OR Programm OR speakers']
    return [f'{n} "{lead.name}"']


def clean_free_queries(t: Target, queries: Sequence[object]) -> list[str]:
    """Keep the LLM's own queries only if they add something specific beyond name, company, role and place."""
    out: list[str] = []
    for q in queries:
        if not isinstance(q, str) or not q.strip():
            continue
        q = q.strip()
        rest = re.sub(re.escape(fold_text(t.name)), " ", fold_text(q))
        if is_generic(rest, t):
            continue
        out.append(q if fold_text(t.name) in fold_text(q) else f'"{t.name}" {q}')
    return out


def plan_round(t: Target, leads: Sequence[Lead], gaps: Sequence[str], free_queries: Sequence[object],
               done: set[str], max_queries: int = 10, today: datetime | None = None, max_leads: int = 5) -> list[str]:
    """Order: best query of the top leads, first open query of each gap, specific LLM queries,
    then the rest (more lead queries, further gap queries, past events). Already-run queries are skipped,
    so a gap that stays open gets its next query in the next round."""
    today = today or datetime.now()
    live = [lead for lead in leads if lead.timing != "past"]
    past = [lead for lead in leads if lead.timing == "past"]
    per_lead = [_lead_queries(t, lead) for lead in live]
    per_gap = [[q for q in gap_queries(t, g, today) if fold_text(q) not in done] for g in gaps]
    ordered = ([qs[0] for qs in per_lead[:max_leads]]
               + [qs[0] for qs in per_gap if qs]
               + clean_free_queries(t, free_queries)[:3]
               + [q for qs in per_lead[:max_leads] for q in qs[1:]]
               + [qs[0] for qs in per_lead[max_leads:]]
               + [q for qs in per_gap for q in qs[1:2]]
               + [_lead_queries(t, lead)[0] for lead in past])
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
    reserve_s: float = 20.0,
    min_round_s: float = 30.0,
    plan_timeout_s: float = 15.0,
    min_new_facts: int = 3,
    max_docs: int = 20,
    max_queries: int = 10,
) -> list:
    """Run expansion rounds in place: new facts are appended to `facts` by `extract_all`. Returns new docs.

    Deadline-aware: `reserve_s` stays free for consolidation after the snowball, a round starts only if at
    least `min_round_s` more are available, and the planning call is abandoned after `plan_timeout_s`.
    """
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FutureTimeout

    from .research import _json, fold

    st.setdefault("snowball", [])
    st.setdefault("expansion_queries", [])
    st.setdefault("anchors_added", [])
    st.setdefault("anchors_rejected", [])
    done = {fold(q["query"]) for q in st.get("search", []) if isinstance(q, dict) and q.get("query")}
    followed: set[str] = set()
    followed_names: list[str] = []
    new_docs: list = []
    last_start = 0  # facts[last_start:] were added by the previous round (round 1: everything so far)
    for round_no in range(1, max_rounds + 1):
        if left() - reserve_s < min_round_s or not facts:
            if facts:
                log(f"[{t.id}] snowball {round_no}: skipped, {left():.0f}s left")
            break
        started, before, today = time.monotonic(), len(facts), datetime.now()
        shown = facts[last_start:] + facts[:last_start]  # newest first, so truncation drops the oldest
        listing = "\n".join(f"[r{i}] ({f.category}, {f.recency}) {f.fact} | quote: {f.verbatim_quote}"
                            for i, f in enumerate(shown, 1))[:8000]
        prompt = _PROMPT.format(name=t.name, role=t.role, company=t.company, today=f"{today:%Y-%m-%d}",
                                followed=", ".join(followed_names) or "(none yet)")
        ex = ThreadPoolExecutor(1)
        try:
            out = ex.submit(_json, llm, prompt, listing, 0.3).result(timeout=plan_timeout_s)
        except FutureTimeout:
            log(f"[{t.id}] snowball {round_no}: planning call over {plan_timeout_s:.0f}s, stopping")
            st["snowball"].append({"round": round_no, "timeout": True})
            break
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
        quotes = fold(" ".join(f.verbatim_quote for f in facts))
        for a in (out.get("anchors") or [])[:6]:
            if not isinstance(a, str) or fold(a) not in quotes:
                continue
            if not good_anchor(a, t):
                st["anchors_rejected"].append(a)
            elif ident.add_anchor(a):
                st["anchors_added"].append(a)
        leads = parse_leads(out.get("leads"), shown, t, today, exclude=followed)
        gaps = find_gaps(facts, today)
        queries = plan_round(t, leads, gaps, out.get("queries") or [], done, max_queries, today)
        for lead in leads:
            if any(f'"{lead.name}"' in q for q in queries):
                followed.add(fold(lead.name))
                followed_names.append(lead.name)
        record = {"round": round_no, "leads": [vars(lead) for lead in leads], "gaps": gaps, "queries": queries}
        st["snowball"].append(record)
        if not queries:
            log(f"[{t.id}] snowball {round_no}: nothing new to search")
            break
        log(f"[{t.id}] snowball {round_no}: {len(leads)} new leads, gaps {gaps}, {len(queries)} queries")
        st["expansion_queries"] += queries
        docs = to_docs(run_queries([("expansion", "web", q, 10) for q in queries]))[:max_docs]
        extract_all(docs)
        new_docs += docs
        last_start = before
        record.update(new_docs=len(docs), new_facts=len(facts) - before,
                      seconds=round(time.monotonic() - started, 1))
        log(f"[{t.id}] snowball {round_no}: +{len(docs)} sources, +{len(facts) - before} facts")
        if len(facts) - before < min_new_facts:
            break
    return new_docs
