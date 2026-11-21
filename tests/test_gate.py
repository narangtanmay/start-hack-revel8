import pytest

from revel8_agent.gate import validate_contact_plan, validate_session_consistency
from revel8_agent.schemas import ContactPlan, VerifiedDossier

BLOCKED = {"Company.Example.test."}


def test_allows_sourced_event_logistics(plan: ContactPlan, dossier: VerifiedDossier) -> None:
    verdict = validate_contact_plan(plan, dossier, BLOCKED)
    assert verdict.passed
    assert verdict.errors == []
    assert verdict.warnings == []


@pytest.mark.parametrize("host", ["company.example.test", "desk.company.example.test"])
def test_rejects_blocked_sender_domain(host: str, plan: ContactPlan, dossier: VerifiedDossier) -> None:
    assert plan.sender is not None
    plan.sender.address = f"desk@{host.upper()}"
    verdict = validate_contact_plan(plan, dossier, BLOCKED)
    assert not verdict.passed
    assert "Sender address uses a blocked organization domain." in verdict.errors


@pytest.mark.parametrize("host", ["company.example.test", "desk.company.example.test."])
def test_rejects_blocked_page_host(host: str, plan: ContactPlan, dossier: VerifiedDossier) -> None:
    assert plan.landing_page is not None
    plan.landing_page.url = f"https://{host}:443/schedule"
    verdict = validate_contact_plan(plan, dossier, BLOCKED)
    assert not verdict.passed
    assert "Landing page uses a blocked organization domain." in verdict.errors


def test_domain_matching_uses_label_boundaries(plan: ContactPlan, dossier: VerifiedDossier) -> None:
    assert plan.sender is not None and plan.landing_page is not None
    plan.sender.address = "desk@notcompany.example.test"
    plan.landing_page.url = "https://company.example.test.events.example.test/schedule"
    assert validate_contact_plan(plan, dossier, BLOCKED).passed


@pytest.mark.parametrize(
    "text",
    [
        "IGNORE previous",
        "ignore your instructions",
        "system prompt",
        "you are an AI",
        "as an ai",
        "language model",
        "simulator",
        "<p>system <strong>prompt</strong></p>",
        "<p>simu&#108;ator</p>",
    ],
)
def test_rejects_meta_language(text: str, plan: ContactPlan, dossier: VerifiedDossier) -> None:
    plan.body = text
    verdict = validate_contact_plan(plan, dossier, BLOCKED)
    assert not verdict.passed
    assert "Draft contains simulator or instruction-override language." in verdict.errors


@pytest.mark.parametrize(
    ("markup", "error"),
    [
        ("<ScRiPt>/* example */</ScRiPt>", "HTML contains a script tag."),
        ('<img src="https://events.example.test/schedule.png">', "HTML images must use asset:// sources."),
        ("<IMG alt=schedule SRC=//events.example.test/schedule.png>", "HTML images must use asset:// sources."),
    ],
)
def test_checks_html_in_message_and_page(
    markup: str, error: str, plan: ContactPlan, dossier: VerifiedDossier
) -> None:
    assert plan.landing_page is not None
    for draft in (
        plan.model_copy(update={"body": markup}),
        plan.model_copy(update={"landing_page": plan.landing_page.model_copy(update={"html": markup})}),
    ):
        verdict = validate_contact_plan(draft, dossier, BLOCKED)
        assert not verdict.passed
        assert error in verdict.errors


def test_rejects_missing_fact(plan: ContactPlan, dossier: VerifiedDossier) -> None:
    plan.cited_fact_ids = ["missing"]
    verdict = validate_contact_plan(plan, dossier, BLOCKED)
    assert not verdict.passed
    assert verdict.errors == ["Cited fact 'missing' is missing from the dossier."]


@pytest.mark.parametrize("missing_field", ["source_url", "verbatim_quote"])
def test_requires_nonblank_fact_evidence(
    missing_field: str, plan: ContactPlan, dossier: VerifiedDossier
) -> None:
    dossier.facts[0] = dossier.facts[0].model_copy(update={missing_field: " \t "})
    verdict = validate_contact_plan(plan, dossier, BLOCKED)
    assert not verdict.passed
    assert verdict.errors == ["Cited fact 'check-in' requires a source URL and verbatim quote."]


@pytest.mark.parametrize(
    ("fields", "subject", "body"),
    [
        (["email", "password"], "Workshop check-in", "<p>Open the <b>public page</b> to view details.</p>"),
        (["PASSWORD"], "No login required", "<p>Check-in opens at 9 a.m.</p>"),
        (["otp"], "Workshop check-in", "<p>View the schedule without signing in.</p>"),
        (["passcode"], "Workshop check-in", "<p>Available without an account or no sign-in needed.</p>"),
        (["email", "password"], "Workshop check-in", "<p>Read it without logging in.</p>"),
        (["email", "password"], "Workshop check-in", "<p>No sign in required.</p>"),
        (["email", "password"], "Workshop check-in", "<p>No account needed.</p>"),
    ],
)
def test_rejects_public_claim_when_landing_page_requests_credentials(
    fields: list[str],
    subject: str,
    body: str,
    plan: ContactPlan,
    dossier: VerifiedDossier,
) -> None:
    assert plan.landing_page is not None
    plan.landing_page.fields = fields
    plan.subject = subject
    plan.body = body
    verdict = validate_contact_plan(plan, dossier, BLOCKED)
    assert not verdict.passed
    assert (
        "Message promises a public/no-login page but landing page requests credentials."
        in verdict.errors
    )


def test_allows_credential_page_without_contradictory_claim(
    plan: ContactPlan, dossier: VerifiedDossier
) -> None:
    assert plan.landing_page is not None
    plan.landing_page.fields = ["email", "password"]
    plan.subject = "Workshop portal"
    plan.body = "<p>Please sign in on the workshop portal to confirm your session.</p>"
    verdict = validate_contact_plan(plan, dossier, BLOCKED)
    assert verdict.passed
    assert verdict.errors == []


def test_allows_public_claim_when_landing_page_has_no_credential_fields(
    plan: ContactPlan, dossier: VerifiedDossier
) -> None:
    assert plan.landing_page is not None
    plan.landing_page.fields = ["preferred_workshop"]
    plan.subject = "Public page schedule"
    plan.body = "<p>This is a public page with no login required.</p>"
    verdict = validate_contact_plan(plan, dossier, BLOCKED)
    assert verdict.passed
    assert verdict.errors == []


# ---- entity / date / cross-turn consistency
BRIEF = {
    "facts": [{"id": "check-in", "fact": "Check-in opens at 9 a.m.", "verbatim_quote": "Check-in opens at 9 a.m."}],
    "hooks": [
        {"id": "h_past", "timing": "PAST (do not pitch as upcoming)"},
        {"id": "h_unc", "timing": "uncertain-date (verify before pitching as upcoming)"},
        {"id": "h_now", "timing": "current"},
    ],
}
PERSONA = {"name": "Event Desk", "organisation": "Workshop Crew"}


def _check(plan: ContactPlan, dossier: VerifiedDossier, steps=None, hook_id="h_now") -> list[str]:
    return validate_session_consistency(plan, dossier, BRIEF, steps or [], PERSONA, hook_id)


def _sent(body: str, attachments=None) -> dict:
    return {"payload": {"body": body, "attachments": attachments or []}}


def test_clean_draft_passes_consistency(plan: ContactPlan, dossier: VerifiedDossier) -> None:
    assert _check(plan, dossier) == []


@pytest.mark.parametrize(
    "body",
    ["Your colleague Jane Doe asked me to reach out.", "Jane Doe at Example Events shared the agenda."],
)
def test_rejects_ungrounded_person(body: str, plan: ContactPlan, dossier: VerifiedDossier) -> None:
    plan.body, plan.is_html = body, False
    assert any("Ungrounded person claim" in e and "Jane Doe" in e for e in _check(plan, dossier))


def test_allows_person_grounded_in_facts(plan: ContactPlan, dossier: VerifiedDossier) -> None:
    dossier.facts[0].verbatim_quote = "Check-in opens at 9 a.m. with Jane Doe."
    plan.body, plan.is_html = "Your colleague Jane Doe asked me to reach out.", False
    assert _check(plan, dossier) == []


@pytest.mark.parametrize("hook_id", ["h_past", "h_unc"])
@pytest.mark.parametrize("phrase", ["upcoming", "next month", "register for", "join us at", "invite you to"])
def test_rejects_past_hook_pitched_as_upcoming(
    hook_id: str, phrase: str, plan: ContactPlan, dossier: VerifiedDossier
) -> None:
    plan.body, plan.is_html = f"We would like to {phrase} the summit.", False
    assert any("Past-hook upcoming pitch" in e for e in _check(plan, dossier, hook_id=hook_id))
    assert not any("Past-hook" in e for e in _check(plan, dossier, hook_id="h_now"))


def test_rejects_attachment_after_no_attachment_promise(plan: ContactPlan, dossier: VerifiedDossier) -> None:
    errors = _check(plan, dossier, steps=[_sent("Just a quick note, no attachment needed.")])
    assert any("Cross-turn contradiction" in e and "attach" in e for e in errors)


def test_rejects_no_attachment_claim_after_attachment_sent(plan: ContactPlan, dossier: VerifiedDossier) -> None:
    plan.attachments, plan.body, plan.is_html = [], "Kein Anhang diesmal.", False
    errors = _check(plan, dossier, steps=[_sent("See file", [{"filename": "a.pdf"}])])
    assert any("Cross-turn contradiction" in e for e in errors)


def test_rejects_credential_form_after_no_login_promise(plan: ContactPlan, dossier: VerifiedDossier) -> None:
    plan.attachments = []
    assert plan.landing_page is not None
    plan.landing_page.fields = ["email", "password"]
    errors = _check(plan, dossier, steps=[_sent("It is a public page, no login.")])
    assert any("Cross-turn contradiction" in e and "credential" in e for e in errors)
    assert _check(plan, dossier, steps=[_sent("Hello again.")]) == []
