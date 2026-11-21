"""research() must return within its budget even when searches, pages or the model hang."""

import threading
import time

import pytest

from revel8_agent import research as R
from revel8_agent.osint import Target

T = Target("robert", "Robert Seilbeck", "Co-Founder & CTO, revel8", "revel8")
BUDGET = 9.0  # every phase window scales with the budget (90 s -> 9 s here)
SLACK = 1.0   # thread hand-off and bookkeeping


@pytest.fixture
def release():
    """Hung calls wait on this event; set it at the end so no thread outlives the test."""
    ev = threading.Event()
    yield ev
    ev.set()


def _row(i: int) -> dict:
    return {"url": f"https://news.test/{i}", "title": f"Robert Seilbeck of revel8 story {i}",
            "snippet": f"Robert Seilbeck of revel8 will speak at Demo Day number {i} in March 2027.", "published": ""}


class _Pool:
    def __init__(self, chat) -> None:
        self.chat = chat

    def __len__(self) -> int:
        return 2

    def lane(self, _i: int):
        return self


def _patch_sources(monkeypatch, release, *, hang_some_searches: bool) -> None:
    def brave(_http, _vertical, q, _count=10, _deadline=None):
        if hang_some_searches and "linkedin" in q:
            release.wait(60)          # a search that never answers in time
            return []
        return [_row(abs(hash(q)) % 1000)]

    def hang(*_a, **_k):
        release.wait(60)
        return None

    monkeypatch.setattr(R, "brave", brave)
    monkeypatch.setattr(R, "fetch_text", hang)    # every page hangs: snippets are the fallback
    monkeypatch.setattr(R, "openalex", hang)
    monkeypatch.setattr(R, "gh_users", hang)


def test_everything_hangs_still_returns_on_time(monkeypatch, release) -> None:
    _patch_sources(monkeypatch, release, hang_some_searches=True)

    def chat(*_a, **_k):
        release.wait(60)              # the model never answers
        return {}

    t0 = time.monotonic()
    dossier, st = R.research(T, _Pool(chat), budget_s=BUDGET, log=lambda _m: None)
    elapsed = time.monotonic() - t0
    assert elapsed <= BUDGET + SLACK, elapsed
    assert st["within_budget"] and dossier.facts == [] and dossier.hypotheses == []


def test_fast_model_with_hung_pages_keeps_snippet_facts_and_returns_on_time(monkeypatch, release) -> None:
    _patch_sources(monkeypatch, release, hang_some_searches=True)

    def chat(messages, **_k):
        user = messages[-1]["content"]
        if "SOURCE:\n" in user:       # extraction: quote the snippet verbatim
            text = user.split("SOURCE:\n", 1)[1]
            quote = text.split("\n")[1].split(" in March")[0]
            return {"facts": [{"fact": "Speaks at Demo Day", "category": "talk_or_event",
                               "verbatim_quote": quote, "recency": "2027-03"}]}
        return {}

    t0 = time.monotonic()
    dossier, st = R.research(T, _Pool(chat), budget_s=BUDGET, log=lambda _m: None)
    elapsed = time.monotonic() - t0
    assert elapsed <= BUDGET + SLACK, elapsed
    assert st["within_budget"]
    assert dossier.facts, "snippets of pages that were too slow must still yield verified facts"
    assert any("too slow" in s.get("status", "") for s in st["sources"].values())
