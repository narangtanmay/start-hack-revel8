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
    """Keep tests from writing into the real memory/ dir (engine runs update target memory and the playbook)."""
    monkeypatch.setenv("REVEL8_MEMORY_DIR", str(tmp_path / "memory"))


@pytest.fixture(autouse=True)
def _neutral_llm_env(monkeypatch):
    """The LLM client calls load_dotenv(), which never overrides a set variable: pin the tuning knobs to their
    defaults so a developer's .env (e.g. Qwen's LLM_EXTRA_BODY, LLM_REASONING=0) cannot change request payloads."""
    for name, value in (("LLM_EXTRA_BODY", ""), ("LLM_REASONING", "1"), ("LLM_REASONING_EFFORT", ""),
                        ("LLM_REASONING_DEFAULT", ""), ("LLM_MAX_TOKENS", ""), ("LLM_TIMEOUT", "")):
        monkeypatch.setenv(name, value)
