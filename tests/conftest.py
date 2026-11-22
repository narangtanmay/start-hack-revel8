import pytest

from revel8_agent.schemas import ContactPlan, LandingPageSpec, SenderInfo, VerifiedDossier, VerifiedFact


@pytest.fixture
def dossier() -> VerifiedDossier:
    return VerifiedDossier(
        target_id="event-coordinator",
        target_name="Event Coordinator",
        role="Coordinator",
        company="Example Events",
        facts=[
            VerifiedFact(
                id="check-in",
                fact="Check-in opens at 9 a.m.",
                category="logistics",
                source_url="https://events.example.test/schedule",
                verbatim_quote="Check-in opens at 9 a.m.",
                recency="Current event schedule",
            )
        ],
    )


@pytest.fixture
def plan() -> ContactPlan:
    return ContactPlan(
        to="event-coordinator",
        channel="email",
        sender=SenderInfo(name="Event Desk", address="desk@events.example.test"),
        subject="Workshop check-in",
        body="<p>Check-in opens at 9 a.m.</p><img src='asset://a_schedule'>",
        is_html=True,
        attachments=["a_schedule", {"filename": "schedule.pdf"}],
        landing_page=LandingPageSpec(
            url="https://events.example.test/schedule",
            title="Workshop schedule",
            html="<p>Check-in opens at 9 a.m.</p>",
            fields=["preferred_workshop"],
        ),
        cited_fact_ids=["check-in"],
    )


@pytest.fixture(autouse=True)
def _isolated_memory(tmp_path, monkeypatch):
    """Tests must never write into the real memory/ (fake 'event-coordinator' wins polluted it)."""
    monkeypatch.setenv("REVEL8_MEMORY_DIR", str(tmp_path / "memory"))


@pytest.fixture(autouse=True)
def _ladder_off_for_scripted_llm(monkeypatch):
    # scripted fake-LLM engine tests count calls exactly; the ladder gate's redraft is tested in test_ladder.py
    import revel8_agent.engine as eng

    monkeypatch.setattr(eng, "LADDER_ON", False)


@pytest.fixture(autouse=True)
def _council_off_for_scripted_llm(monkeypatch):
    # the strategy council fans out several planner calls; scripted engine tests count calls exactly
    monkeypatch.setenv("REVEL8_COUNCIL", "0")


@pytest.fixture(autouse=True)
def _offline_dns(monkeypatch):
    # tests never hit public DNS: no real-domain discovery, and nothing counts as registered unless a test says so
    monkeypatch.setenv("REVEL8_DNS", "0")
    import revel8_agent.domains as dom

    monkeypatch.setattr(dom, "_doh", lambda name, rtype: 3)
    dom.registered.cache_clear()
