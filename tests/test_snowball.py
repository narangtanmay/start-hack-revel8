from datetime import datetime

from revel8_agent.osint import Target
from revel8_agent.research import Identity
from revel8_agent.schemas import VerifiedFact
from revel8_agent.snowball import (
    clean_free_queries,
    find_gaps,
    gap_queries,
    good_anchor,
    parse_leads,
    plan_round,
    run_snowball,
)

T = Target("robert", "Robert Seilbeck", "Co-Founder & CTO, revel8", "revel8")
TODAY = datetime(2026, 11, 21)


def _f(fact: str, quote: str, category: str = "other", recency: str = "unknown") -> VerifiedFact:
    return VerifiedFact(id="", fact=fact, category=category, source_url="https://x.test", verbatim_quote=quote,
                        recency=recency)


FACTS = [
    _f("Speaks at it-sa 2026 in Nuremberg", "Robert will speak at it-sa 2026 on deepfakes", "talk_or_event", "2026-12-08"),
    _f("Spoke at Cyber Night Berlin", "Robert spoke at Cyber Night Berlin last year", "talk_or_event", "2025-05"),
    _f("Seed round led by Peak with Merantix Capital", "seed round led by Peak with participation from Merantix Capital",
       "company_news", "2025-09"),
]


def test_parse_leads_keeps_literal_new_entities_with_event_only_timing() -> None:
    raw = [
        {"kind": "organisation", "name": "Merantix Capital", "fact_ids": ["r3"]},
        {"kind": "event", "name": "Cyber Night Berlin", "fact_ids": ["r2"]},
        {"kind": "event", "name": "it-sa 2026", "fact_ids": ["r1"]},
        {"kind": "person", "name": "Jane Invented"},          # not in the facts
        {"kind": "event", "name": "revel8"},                  # the company alone
        {"kind": "event", "name": "Berlin"},                  # generic place
        {"kind": "gadget", "name": "Peak"},                   # unknown kind
        {"kind": "event", "name": "IT-SA 2026"},              # duplicate after folding
    ]
    leads = parse_leads(raw, FACTS, T, TODAY)
    assert [(lead.name, lead.timing) for lead in leads] == [
        ("it-sa 2026", "upcoming"),           # upcoming event first
        ("Merantix Capital", "current"),      # an investor relationship is ongoing, not "past"
        ("Cyber Night Berlin", "past"),       # past event last
    ]
    again = parse_leads(raw, FACTS, T, TODAY, exclude={"merantix capital", "it-sa 2026"})
    assert [lead.name for lead in again] == ["Cyber Night Berlin"]


def test_generic_anchors_and_queries_are_rejected() -> None:
    assert not good_anchor("CTO", T) and not good_anchor("Berlin", T) and not good_anchor("revel8", T)
    assert good_anchor("Celonis", T) and good_anchor("TU München", T) and good_anchor("Julius Muth", T)
    kept = clean_free_queries(T, ['"Robert Seilbeck" cybersecurity', '"Robert Seilbeck" Berlin talk',
                                  "Celonis", '"Robert Seilbeck" DaMoN 2014', ""])
    assert kept == ['"Robert Seilbeck" Celonis', '"Robert Seilbeck" DaMoN 2014']


def test_find_gaps_counts_only_upcoming_events() -> None:
    gaps = find_gaps(FACTS, TODAY)
    assert "upcoming_event" not in gaps                        # it-sa on 2026-12-08 is upcoming
    assert {"network", "hiring", "interest", "tooling"} <= set(gaps)
    assert "upcoming_event" in find_gaps(FACTS[1:], TODAY)    # only past talks left


def test_gap_queries_look_at_next_year_late_in_the_year() -> None:
    assert gap_queries(T, "upcoming_event", TODAY)[0] == '"Robert Seilbeck" speaker 2027'
    assert gap_queries(T, "upcoming_event", datetime(2026, 3, 1))[0] == '"Robert Seilbeck" speaker 2026 OR 2027'
    assert gap_queries(T, "hiring", TODAY)[0].startswith("site:linkedin.com/posts")


def test_plan_round_spreads_gap_queries_over_rounds_and_never_repeats() -> None:
    leads = parse_leads([{"kind": "event", "name": "it-sa 2026", "fact_ids": ["r1"]}], FACTS, T, TODAY)
    done: set[str] = set()
    r1 = plan_round(T, leads, ["network", "hiring"], ['"Robert Seilbeck" Celonis'], done, max_queries=4, today=TODAY)
    assert r1 == ['"Robert Seilbeck" "it-sa 2026"', '"Robert Seilbeck" advisor OR mentor OR Beirat',
                  'site:linkedin.com/posts "Robert Seilbeck" hiring', '"Robert Seilbeck" Celonis']
    r2 = plan_round(T, [], ["network", "hiring"], [], done, max_queries=4, today=TODAY)
    assert r2 == ['"Robert Seilbeck" co-founder OR Mitgründer', '"Robert Seilbeck" "we\'re hiring" OR "join our team"']
    assert plan_round(T, [], ["network", "hiring"], [], done, today=TODAY) == []


class _FakeLLM:
    def __init__(self, replies: list[dict]) -> None:
        self.replies = replies
        self.prompts: list[str] = []
        self.listings: list[str] = []

    def chat(self, messages, **_kwargs):
        self.prompts.append(messages[0]["content"])
        self.listings.append(messages[1]["content"])
        return self.replies.pop(0) if self.replies else {}


def test_run_snowball_builds_on_the_last_round() -> None:
    facts = list(FACTS)
    searched: list[list[str]] = []

    def run_queries(plan):
        searched.append([q for _, _, q, _ in plan])
        return ["hit"]

    def extract_all(docs):
        if len(searched) == 1:   # round 1 finds a moderator; round 2 finds nothing
            facts.extend(_f(f"Panel moderated by Steven Perlberg {i}", f"moderated by Steven Perlberg number {i}",
                            "network", "2026-10-28") for i in range(3))

    llm = _FakeLLM([
        {"anchors": ["Nuremberg", "Berlin"], "leads": [{"kind": "event", "name": "it-sa 2026"}], "queries": []},
        {"anchors": [], "leads": [{"kind": "event", "name": "it-sa 2026"},
                                  {"kind": "person", "name": "Steven Perlberg"}], "queries": []},
    ])
    st: dict = {"search": [{"query": '"Robert Seilbeck" revel8'}]}
    ident = Identity(T)
    new_docs = run_snowball(T, llm, ident, facts, st, run_queries=run_queries, to_docs=lambda hits: ["doc"],
                            extract_all=extract_all, left=lambda: 200.0, log=lambda _m: None)

    assert len(searched) == 2 and new_docs == ["doc", "doc"]
    assert '"Robert Seilbeck" "it-sa 2026"' in searched[0]
    assert "ALREADY FOLLOWED (do not repeat): it-sa 2026" in llm.prompts[1]
    assert llm.listings[1].startswith("[r1] (network, 2026-10-28) Panel moderated by Steven Perlberg")
    assert [lead["name"] for lead in st["snowball"][1]["leads"]] == ["Steven Perlberg"]
    assert '"Robert Seilbeck" "Steven Perlberg"' in searched[1]
    assert st["anchors_rejected"] == ["Berlin"] and "Berlin" not in ident.anchors   # "Nuremberg": not in a quote
    assert st["snowball"][0]["new_facts"] == 3 and st["snowball"][1]["new_facts"] == 0


def test_run_snowball_respects_budget() -> None:
    st: dict = {}
    out = run_snowball(T, _FakeLLM([]), Identity(T), list(FACTS), st, run_queries=lambda p: [], to_docs=lambda h: [],
                       extract_all=lambda d: None, left=lambda: 30.0, log=lambda _m: None)
    assert out == [] and st["snowball"] == []
