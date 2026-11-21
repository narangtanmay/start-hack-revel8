from datetime import datetime

from revel8_agent.osint import Target
from revel8_agent.research import Identity
from revel8_agent.schemas import VerifiedFact
from revel8_agent.snowball import find_gaps, parse_leads, plan_round, run_snowball

T = Target("robert", "Robert Seilbeck", "Co-Founder & CTO", "revel8")
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


def test_parse_leads_keeps_only_literal_entities_and_ranks_upcoming_events_first() -> None:
    raw = [
        {"kind": "organisation", "name": "Merantix Capital", "fact_ids": ["r3"]},
        {"kind": "event", "name": "Cyber Night Berlin", "fact_ids": ["r2"]},
        {"kind": "event", "name": "it-sa 2026", "fact_ids": ["r1"]},
        {"kind": "person", "name": "Jane Invented", "fact_ids": ["r3"]},   # not in the facts
        {"kind": "event", "name": "revel8"},                                 # the company alone
        {"kind": "gadget", "name": "Peak"},                                  # unknown kind
        {"kind": "event", "name": "IT-SA 2026"},                             # duplicate after folding
    ]
    leads = parse_leads(raw, FACTS, T, TODAY)
    assert {lead.name for lead in leads} == {"it-sa 2026", "Merantix Capital", "Cyber Night Berlin"}
    assert leads[0].name == "it-sa 2026" and leads[0].timing == "upcoming"
    assert all(lead.timing == "past" for lead in leads[1:])


def test_find_gaps_counts_only_upcoming_events() -> None:
    gaps = find_gaps(FACTS, TODAY)
    assert "upcoming_event" not in gaps                         # it-sa on 2026-12-08 is upcoming
    assert {"network", "hiring", "interest", "tooling"} <= set(gaps)
    assert "upcoming_event" in find_gaps(FACTS[1:], TODAY)     # only past talks left


def test_plan_round_orders_leads_then_gaps_and_skips_done_queries() -> None:
    leads = parse_leads([{"kind": "event", "name": "it-sa 2026", "fact_ids": ["r1"]}], FACTS, T, TODAY)
    done = {'"robert seilbeck" "it-sa 2026"'}
    qs = plan_round(T, leads, ["network"], ["triathlon"], done, max_queries=10, today=TODAY)
    assert qs[0].startswith('"Robert Seilbeck" Mitgründer')    # the lead's first query was already run
    assert '"Robert Seilbeck" triathlon' in qs                  # free query gets the full name added
    assert any(q.startswith('"it-sa 2026" Seilbeck agenda') for q in qs)
    assert len(qs) == len(set(qs))
    again = plan_round(T, leads, ["network"], ["triathlon"], done, max_queries=10, today=TODAY)
    assert again == []                                          # everything is now in `done`


class _FakeLLM:
    def __init__(self, replies: list[dict]) -> None:
        self.replies = replies

    def chat(self, *_args, **_kwargs):
        return self.replies.pop(0) if self.replies else {}


def test_run_snowball_adds_facts_and_stops_when_a_round_adds_too_few() -> None:
    facts = list(FACTS)
    searched: list[list[str]] = []

    def run_queries(plan):
        searched.append([q for _, _, q, _ in plan])
        return ["hit"]

    def extract_all(docs):
        if len(searched) == 1:                                  # round 1 finds 3 new facts, round 2 finds none
            facts.extend(_f(f"new {i}", f"Robert Seilbeck new fact number {i}") for i in range(3))

    llm = _FakeLLM([
        {"anchors": ["Nuremberg", "Invented GmbH"], "leads": [{"kind": "event", "name": "it-sa 2026"}], "queries": []},
        {"anchors": [], "leads": [], "queries": ["sailing"]},
    ])
    st: dict = {"search": [{"query": '"Robert Seilbeck" revel8'}]}
    new_docs = run_snowball(T, llm, Identity(T), facts, st, run_queries=run_queries, to_docs=lambda hits: ["doc"],
                            extract_all=extract_all, left=lambda: 200.0, log=lambda _m: None)
    assert len(searched) == 2 and new_docs == ["doc", "doc"]
    assert st["snowball"][0]["new_facts"] == 3 and st["snowball"][1]["new_facts"] == 0
    assert '"Robert Seilbeck" "it-sa 2026"' in searched[0]
    assert st["anchors_added"] == []                            # "Nuremberg" is in a fact, not a quote


def test_run_snowball_respects_budget() -> None:
    st: dict = {}
    out = run_snowball(T, _FakeLLM([]), Identity(T), list(FACTS), st, run_queries=lambda p: [], to_docs=lambda h: [],
                       extract_all=lambda d: None, left=lambda: 30.0, log=lambda _m: None)
    assert out == [] and st["snowball"] == []
