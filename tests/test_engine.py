from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from revel8_agent import cli
from revel8_agent.engine import RunConfig, Runner, estimate_score, timing
from revel8_agent.schemas import VerifiedDossier

TODAY = datetime(2026, 11, 21)


@pytest.mark.parametrize("recency,expected", [
    ("2026-10-28", "past"), ("2026-07", "past"), ("July 16, 2026", "past"), ("16 July 2026", "past"),
    ("19-23/01/2026", "past"), ("23/01/2026", "past"), ("01/2026", "past"), ("January 19-23, 2026", "past"),
    ("2026 Q1", "past"), ("2025", "past"), ("2026-12-10", "upcoming"), ("2027-03", "upcoming"),
    ("upcoming", "upcoming"), ("2026", "this-year"), ("unknown", "undated"),
])
def test_timing_labels(recency: str, expected: str) -> None:
    assert timing(recency, TODAY) == expected


def test_estimate_score() -> None:
    assert estimate_score({"incidents": []})["results_points"] == 0
    hit = estimate_score({"incidents": [{"touch": 4, "type": "credentials", "source": "api event"}]})
    assert hit["incident"] and hit["first_incident_touch"] == 4 and hit["results_points"] == 22.5


def test_strip_salutations_and_placeholders() -> None:
    from revel8_agent.engine import _fill_placeholders, _strip_salutations

    paras = ["Hi Tom,\n\nI'm Sarah from TechEx.", "Access it here: [link to registration page].",
             "Best regards,\nSarah Bennett"]
    cleaned = _strip_salutations(paras, "Sarah Bennett")
    assert cleaned == ["I'm Sarah from TechEx.", "Access it here: [link to registration page]."]
    assert _fill_placeholders(cleaned, "https://x-events.de/s")[1] == "Access it here: https://x-events.de/s."
    assert _strip_salutations(["Hallo Julius,", "Kurze Frage.\n\nViele Grüße\nLena"], "Lena Fischer") == ["Kurze Frage."]
    assert _strip_salutations(["Hi Julius, I'm Sarah from CyberShield."], "Sarah Mitchell") == ["I'm Sarah from CyberShield."]


def test_pdf_attachment_fallback_preserves_pdf_filename(dossier: VerifiedDossier, tmp_path: Path) -> None:
    cfg = RunConfig(target_id=dossier.target_id, runs_dir=tmp_path)
    runner = Runner(cfg, MagicMock(), MagicMock(), dossier, log=lambda *_a, **_k: None)
    runner.state.plan = {
        "language": "en",
        "persona": {
            "name": "Event Desk",
            "organisation": "Events Partner",
            "role": "Coordinator",
            "email": "desk@events-partner.test",
            "website_domain": "events-partner.test",
            "phone": "+49 89 12345",
        },
    }
    runner._pdf_asset = lambda _fname: None  # type: ignore[method-assign]

    action = {
        "kind": "message",
        "channel": "email",
        "format": "plain",
        "subject": "Workshop agenda",
        "paragraphs": ["Attached is the agenda PDF for review."],
        "attachment_filename": "Workshop_Agenda.pdf",
        "cited_fact_ids": ["check-in"],
    }
    plan, payload, _page = runner.build(action)

    assert payload["attachments"] == [{"filename": "Workshop_Agenda.pdf"}]
    assert len(plan.attachments) == 1
    assert plan.attachments[0].filename == "Workshop_Agenda.pdf"
    assert not any(
        isinstance(item, dict) and str(item.get("filename", "")).endswith(".docx")
        for item in payload["attachments"]
    )


def test_run_config_ablation_defaults_and_serialization(dossier: VerifiedDossier, tmp_path: Path) -> None:
    default_cfg = RunConfig(target_id=dossier.target_id, runs_dir=tmp_path)
    assert default_cfg.use_ledger_gate is True
    assert default_cfg.use_shadow_twin is False

    custom_cfg = RunConfig(
        target_id=dossier.target_id,
        runs_dir=tmp_path,
        use_ledger_gate=False,
        use_shadow_twin=True,
    )
    runner = Runner(custom_cfg, MagicMock(), MagicMock(), dossier, log=lambda *_a, **_k: None)
    assert runner.state.config["use_ledger_gate"] == "False"
    assert runner.state.config["use_shadow_twin"] == "True"


def test_cli_run_ablation_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(
        target: str,
        scenario: str,
        touches: int,
        label: str,
        allow_eval: bool,
        keep_going: bool,
        use_ledger_gate: bool = True,
        use_shadow_twin: bool = False,
        use_policy: bool = False,
        **_kwargs: object,
    ) -> int:
        captured.update(
            target=target,
            use_ledger_gate=use_ledger_gate,
            use_shadow_twin=use_shadow_twin,
        )
        return 0

    monkeypatch.setattr(cli, "_run", fake_run)

    assert cli.main(["run", "--target", "julius"]) == 0
    assert captured == {"target": "julius", "use_ledger_gate": True, "use_shadow_twin": False}

    assert cli.main(["run", "--target", "julius", "--no-ledger-gate", "--shadow-twin"]) == 0
    assert captured == {"target": "julius", "use_ledger_gate": False, "use_shadow_twin": True}


# ---- plan() schema validation, policy binding, gate wiring (offline) ----------------------------
from revel8_agent import engine  # noqa: E402
from revel8_agent.schemas import CampaignPlan, HookHypothesis, VerifiedFact  # noqa: E402

_PERSONA = {"name": "Event Desk", "organisation": "Workshop Crew", "role": "Coordinator",
            "email": "desk@workshop-crew.test", "phone": "+49 89 1234", "website_domain": "workshop-crew.test"}


class _ScriptedLLM:
    def __init__(self, responses: list[dict]) -> None:
        self.responses, self.calls = list(responses), []

    def chat(self, messages, *, json_mode=False, temperature=None):
        self.calls.append(list(messages))
        return self.responses.pop(0)


def _hooked(dossier: VerifiedDossier) -> VerifiedDossier:
    dossier.facts.append(VerifiedFact(id="f2", fact="Ships a new product", category="role", source_url="https://x.test",
                                      verbatim_quote="Ships a new product", recency="2026-12-10"))
    dossier.hypotheses = [
        HookHypothesis(id="h_low", topic="a", rationale="r", confidence=0.2, supporting_fact_ids=["f2"]),
        HookHypothesis(id="h_top", topic="b", rationale="r", confidence=0.9, is_own_angle=True, supporting_fact_ids=["f2"]),
    ]
    return dossier


def _plan_runner(dossier, tmp_path, monkeypatch, responses):
    monkeypatch.setattr(engine, "domain_is_registered", lambda _d: False)
    llm = _ScriptedLLM(responses)
    runner = Runner(RunConfig(target_id=dossier.target_id, runs_dir=tmp_path), MagicMock(), llm, _hooked(dossier),
                    log=lambda *_a, **_k: None)
    return runner, llm


def test_plan_valid_passes_without_retry(dossier, tmp_path, monkeypatch) -> None:
    good = {"hook_id": "h_low", "objective": "credentials", "persona": dict(_PERSONA)}
    runner, llm = _plan_runner(dossier, tmp_path, monkeypatch, [good])
    runner.plan()
    assert len(llm.calls) == 1
    assert runner.state.plan["hook_id"] == "h_low" and runner.state.plan["objective"] == "credentials"


def test_plan_normalizes_hook_alias_without_retry(dossier, tmp_path, monkeypatch) -> None:
    runner, llm = _plan_runner(dossier, tmp_path, monkeypatch,
                               [{"hook": "h_top", "objective": "action", "persona": dict(_PERSONA)}])
    runner.plan()
    assert len(llm.calls) == 1
    assert runner.state.plan["hook_id"] == "h_top"


def test_plan_invalid_retries_once_with_feedback(dossier, tmp_path, monkeypatch) -> None:
    bad = {"hook_id": "", "objective": "win", "persona": dict(_PERSONA)}
    good = {"hook_id": "h_low", "objective": "action", "persona": dict(_PERSONA)}
    runner, llm = _plan_runner(dossier, tmp_path, monkeypatch, [bad, good])
    runner.plan()
    assert len(llm.calls) == 2
    assert "previous plan was invalid" in llm.calls[1][1]["content"]
    assert runner.state.plan["hook_id"] == "h_low" and runner.state.plan["objective"] == "action"


def test_plan_still_invalid_fills_hook_and_objective_deterministically(dossier, tmp_path, monkeypatch) -> None:
    bad = {"hook_id": None, "objective": None, "persona": dict(_PERSONA)}
    runner, llm = _plan_runner(dossier, tmp_path, monkeypatch, [bad, dict(bad)])
    runner.plan()
    assert len(llm.calls) == 2  # exactly one retry
    assert runner.state.plan["hook_id"] == "h_top"  # top-ranked hook
    assert runner.state.plan["objective"] == "disclosure"
    CampaignPlan.model_validate(runner.state.plan)


def test_campaign_plan_rejects_bad_fields() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CampaignPlan.model_validate({"hook_id": "h", "objective": "win", "persona": _PERSONA})
    with pytest.raises(ValidationError):
        CampaignPlan.model_validate({"hook_id": "h", "objective": "action", "persona": {**_PERSONA, "name": " "}})


def test_stop_allowed_only_on_last_touch(dossier, tmp_path) -> None:
    runner = Runner(RunConfig(target_id=dossier.target_id, runs_dir=tmp_path, max_touches=4, use_policy=True),
                    MagicMock(), MagicMock(), dossier, log=lambda *_a, **_k: None)
    for used, allowed in [(0, False), (2, False), (3, True)]:
        runner.state.touches_used = used
        assert runner._stop_allowed() is allowed


def test_bind_policy_overrides_action_channel_and_hook() -> None:
    a = {"kind": "message", "channel": "email", "hook_id": "h1"}
    move = {"channel": "slack", "hook_id": "h2"}
    Runner._bind_policy(a, move)
    assert (a["channel"], a["hook_id"]) == ("slack", "h2")
    assert move == {"channel": "slack", "hook_id": "h2"}


def test_bind_policy_incompatible_channel_syncs_policy_to_action() -> None:
    a = {"kind": "message", "channel": "email", "hook_id": "h1"}
    move = {"channel": "phone_call", "hook_id": "h1"}  # live channel for a message action
    Runner._bind_policy(a, move)
    assert a["channel"] == "email" and move["channel"] == "email"


def test_run_binds_policy_move_to_step_action(dossier, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(engine, "domain_is_registered", lambda _d: False)

    class OneMove:
        def choose_next_move(self, brief, steps, touch, max_touches, plan):
            return {"move_type": "PIVOT_CHANNEL", "hook_id": "h_top", "channel": "slack", "objective": "action",
                    "ask": "x", "cited_fact_ids": ["check-in"], "promises": [], "rationale": "r",
                    "alternatives_considered": []}

    decide = {"decision": "PIVOT_CHANNEL", "rationale": "r", "discarded": [], "hook_id": "h_low", "kind": "message",
              "channel": "email", "sender": {"name": "Event Desk", "address": "desk@workshop-crew.test"},
              "subject": "s", "format": "plain", "paragraphs": ["Check-in opens at 9 a.m."],
              "link": None, "attachment_filename": None, "cited_fact_ids": ["check-in"]}
    plan = {"hook_id": "h_top", "objective": "action", "persona": dict(_PERSONA), "language": "en"}
    api = MagicMock()
    api.create_session.return_value = {"session_id": "s1"}
    api.send_message.return_value = {"message_id": "m1", "events": [], "touches_used": 1}
    llm = _ScriptedLLM([plan, decide])
    cfg = RunConfig(target_id=dossier.target_id, runs_dir=tmp_path, max_touches=1, use_policy=True)
    runner = Runner(cfg, api, llm, _hooked(dossier), log=lambda *_a, **_k: None, policy=OneMove())
    runner.judge = lambda step: None  # type: ignore[method-assign]
    state = runner.run()

    step = state.steps[0]
    assert state.status == "done", state.error
    assert step["action"]["channel"] == step["policy"]["channel"] == "slack"
    assert step["action"]["hook_id"] == step["policy"]["hook_id"] == "h_top"
    assert api.send_message.call_args.args[1]["channel"] == "slack"


def test_check_wires_session_consistency_gate(dossier, tmp_path) -> None:
    runner = Runner(RunConfig(target_id=dossier.target_id, runs_dir=tmp_path), MagicMock(), MagicMock(), dossier,
                    log=lambda *_a, **_k: None)
    runner.state.plan = {"hook_id": "h", "persona": dict(_PERSONA), "language": "en"}
    runner.state.brief = {"facts": [], "hooks": []}
    a = {"kind": "message", "channel": "email", "format": "plain", "subject": "Hi",
         "paragraphs": ["Your colleague Jane Doe asked me to write."], "cited_fact_ids": []}
    plan, _payload, _page = runner.build(a)
    assert any("Ungrounded person claim" in e for e in runner.check(a, plan))




def test_registered_organisation_domain_falls_back_to_organisation_lookalike(dossier, tmp_path, monkeypatch):
    # Jonas eval T1: Nordwerk's real domain was correctly rejected, but Miriam then mailed from a personal domain
    # and every later link was pinned to it. Preserve the organisational identity instead.
    runner, _llm = _plan_runner(dossier, tmp_path, monkeypatch, [{
        "hook_id": "h_top", "objective": "credentials",
        "persona": {
            "name": "Miriam Kessler", "organisation": "Nordwerk Logistik GmbH", "role": "IT Security Lead",
            "email": "miriam@nordwerk-logistik.de", "phone": "+49 40 1234",
            "website_domain": "nordwerk-logistik.de",
        },
    }])
    registered = {"nordwerk-logistik.de"}
    monkeypatch.setattr(engine, "domain_is_registered", lambda d: d in registered)
    runner.plan()
    persona = runner.state.plan["persona"]
    assert persona["website_domain"] == "nordwerklogistik-group.de"
    assert persona["email"] == "miriam@nordwerklogistik-group.de"
    registered.add(persona["website_domain"])
    assert runner._organisation_domain("nordwerk-logistik.de", persona["organisation"]) == "nordwerklogistik-group.com"
    registered.add("nordwerklogistik-group.com")
    assert runner._organisation_domain("nordwerk-logistik.de", persona["organisation"]) == "nordwerklogistik-group.eu"


def test_organisation_lookalike_never_reuses_a_real_or_target_domain(monkeypatch):
    r = engine.Runner.__new__(engine.Runner)
    r.blocked = {"revel8.ai"}
    monkeypatch.setattr(engine, "domain_is_registered", lambda d: True)
    assert r._organisation_domain("revel8.ai", "revel8") == ""
    assert r._organisation_domain("nordwerk-logistik.de", "Nordwerk Logistik GmbH") == ""


def test_personal_domain_for_individual_persona(monkeypatch):
    from revel8_agent import engine

    monkeypatch.setattr(engine, "domain_is_registered", lambda d: d == "lena-hofer.de")
    r = engine.Runner.__new__(engine.Runner)
    r.blocked = {"revel8.ai"}
    assert r._personal_domain("Lena Höfer") == "lena-hofer.eu"
    assert r._personal_domain("") == ""


def test_judge_veto_scheduling_is_not_an_action():
    from revel8_agent.engine import _NOT_AN_ACTION, _REAL_ACTION

    ev = "Wednesday morning works, around 10:00. Please send the invite to this address."
    assert _NOT_AN_ACTION.search(ev) and not _REAL_ACTION.search(ev)
    real = "Done, I opened the file and forwarded it to the team."
    assert _REAL_ACTION.search(real)


def test_judge_veto_public_fact_is_not_a_disclosure():
    # Organiser 09:35: an incident needs internal, non-public information. Robert's only "incident"
    # was website material; Julius's was internal practice and must survive the veto.
    from revel8_agent.engine import _INTERNAL_DETAIL, _PUBLIC_FACT

    public = "Public information on hosting: Germany, STACKIT, ISO 27001."
    assert _PUBLIC_FACT.search(public) and not _INTERNAL_DETAIL.search(public)
    internal = ("I look at the median time to first report across the whole group, not at individuals, "
                "and I never publish names.")
    assert _INTERNAL_DETAIL.search(internal) or not _PUBLIC_FACT.search(internal)


def test_strip_salutations_inline_greeting_and_first_name_signoff():
    from revel8_agent.engine import _strip_salutations

    paras = ["Hi Julius, sorry about that, the link was a preview page.", "The piece is as you approved.",
             "Best,", "Lukas"]
    out = _strip_salutations(paras, "Lukas Weber")
    assert out == ["sorry about that, the link was a preview page.", "The piece is as you approved."]


def test_long_bracket_placeholder_is_rejected():
    import re
    text = "[Article text with the four approved quotes and the works council section, in plain text.]"
    assert re.search(r"\[[^\]]{2,300}\]", text)


def test_live_lookup_adds_notes(monkeypatch):
    from types import SimpleNamespace

    from revel8_agent import engine, research

    r = engine.Runner.__new__(engine.Runner)
    r.state = SimpleNamespace(live_notes=[], llm_calls=0)
    r.dossier = SimpleNamespace(target_name="Tom Müller", role="Co-CEO", company="revel8")
    r.llm = None
    r.log = lambda *_: None
    monkeypatch.setattr(engine, "_llm_json", lambda *a, **k: {"queries": ["Tom Müller revel8 Unicon Berlin"]})
    monkeypatch.setattr(research, "brave", lambda *a, **k: [{"title": "Unicon 2026", "snippet": "revel8 at Unicon", "url": "https://u.test"}])
    step = {"touch": 2, "events": [{"type": "reply", "body": "We were at Gartner SRM in September and last week at Unicon in Berlin."}]}
    r.live_lookup(step)
    assert r.state.live_notes and r.state.live_notes[0]["query"].startswith("Tom")
    assert "Unicon" in r.state.live_notes[0]["found"][0]


def test_judge_veto_accepting_an_invite_is_not_an_action():
    from revel8_agent.engine import _NOT_AN_ACTION, _REAL_ACTION
    ev = "I'll accept the invite on Monday and send you a line then."
    assert _NOT_AN_ACTION.search(ev) and not _REAL_ACTION.search(ev)


def test_stop_at_first_incident_ignores_llm_judge_estimates(dossier, tmp_path) -> None:
    decide = {"decision": "STAY", "rationale": "r", "discarded": [], "hook_id": "h_top", "kind": "message",
              "channel": "email", "sender": {"name": "Event Desk", "address": "desk@workshop-crew.test"},
              "subject": "s", "format": "plain", "paragraphs": ["Check-in opens at 9 a.m."],
              "link": None, "attachment_filename": None, "cited_fact_ids": ["check-in"]}
    plan = {"hook_id": "h_top", "objective": "credentials", "persona": dict(_PERSONA), "language": "en"}
    api = MagicMock()
    api.create_session.return_value = {"session_id": "s1"}
    api.send_message.side_effect = [
        {"message_id": "m1", "events": [{"type": "reply", "body": "I looked at the page."}], "touches_used": 1},
        {"message_id": "m2", "events": [{"type": "page.submitted", "fields": ["email"]}], "touches_used": 2},
    ]
    llm = _ScriptedLLM([plan, decide, decide])
    cfg = RunConfig(target_id=dossier.target_id, runs_dir=tmp_path, max_touches=3, stop_at_first_incident=True)
    runner = Runner(cfg, api, llm, _hooked(dossier), log=lambda *_a, **_k: None)

    def fake_judge(step):
        if step["touch"] == 1:
            runner._incident(1, "action", "I looked at the page.", judged=True)
        elif step["touch"] == 2:
            runner._incident(2, "credentials", "submitted ['email']", judged=False)

    runner.judge = fake_judge  # type: ignore[method-assign]
    state = runner.run()

    assert state.status == "done", state.error
    # Did NOT abort at touch 1 on llm-judge (estimate); stopped at touch 2 on API-confirmed page.submitted.
    assert state.touches_used == 2
    assert any(i["source"] == "api event" and i["touch"] == 2 for i in state.incidents)


def test_empty_drafts_do_not_crash_the_run(dossier, tmp_path) -> None:
    empty = {"decision": "STAY", "rationale": "r", "discarded": [], "hook_id": "h_top", "kind": "message",
             "channel": "email", "sender": {"name": "Event Desk", "address": "desk@workshop-crew.test"},
             "subject": "s", "format": "plain", "paragraphs": [], "link": None, "attachment_filename": None,
             "cited_fact_ids": ["check-in"]}
    plan = {"hook_id": "h_top", "objective": "credentials", "persona": dict(_PERSONA), "language": "en"}
    api = MagicMock()
    api.create_session.return_value = {"session_id": "s1"}
    llm = _ScriptedLLM([plan] + [empty] * 6)
    cfg = RunConfig(target_id=dossier.target_id, runs_dir=tmp_path, max_touches=3)
    runner = Runner(cfg, api, llm, _hooked(dossier), log=lambda *_a, **_k: None)
    state = runner.run()

    assert state.status == "done", state.error
    assert state.touches_used == 0 and not api.send_message.called
    assert [s["error"].startswith("no valid draft") for s in state.steps] == [True, True]
    assert state.steps[0]["attempts"][0]["raw"]["paragraphs"] == []


# ---- steering + writer (2026-11-22)


def test_policy_run_rejects_credentials_draft_without_link(dossier, tmp_path) -> None:
    base = {"decision": "STAY", "rationale": "r", "discarded": [], "hook_id": "h_top", "kind": "message",
            "channel": "email", "sender": {"name": "Event Desk", "address": "desk@workshop-crew.test"},
            "subject": "Your session", "format": "plain", "paragraphs": ["Please confirm your session details."],
            "attachment_filename": None, "cited_fact_ids": ["check-in"]}
    no_link = dict(base, link=None)
    with_link = dict(base, link={"url": "https://workshop-crew.test/speaker", "page_type": "signin"})
    plan = {"hook_id": "h_top", "objective": "credentials", "persona": dict(_PERSONA), "language": "en"}
    api = MagicMock()
    api.create_session.return_value = {"session_id": "s1"}
    api.send_message.return_value = {"message_id": "m1", "events": [{"type": "page.submitted", "fields": ["email"]}],
                                     "touches_used": 1}
    llm = _ScriptedLLM([plan, no_link, with_link])
    cfg = RunConfig(target_id=dossier.target_id, runs_dir=tmp_path, max_touches=2, stop_at_first_incident=True,
                    use_policy=True)
    runner = Runner(cfg, api, llm, _hooked(dossier), log=lambda *_a, **_k: None)
    runner.judge = lambda step: runner._incident(step["touch"], "credentials", "submitted", judged=False)  # type: ignore
    runner._ensure_brand = lambda: False  # type: ignore[method-assign]
    state = runner.run()

    assert state.status == "done", state.error
    step = state.steps[0]
    assert step["policy"]["require_link"] is True
    assert any("registered link" in e for e in step["attempts"][0]["errors"])
    sent = api.send_message.call_args
    assert "workshop-crew.test/speaker" in str(sent)


def test_writer_problem_rejects_softening_and_urls() -> None:
    from revel8_agent.engine import _writer_problem

    draft = ["Please confirm your corrected profile in the speaker portal before Monday."]
    assert _writer_problem(draft, ["Bitte bestätigen Sie Ihr Profil. Eine Anmeldung ist nicht erforderlich."], True)
    assert _writer_problem(draft, ["Hinweis: Dies ist eine Simulation."], True)
    assert _writer_problem(draft, ["Open https://x.test/login to confirm."], True)
    assert "added numbers" in _writer_problem(draft, ["Please confirm your corrected profile in the speaker portal before Monday, 9:00."], True)
    assert _writer_problem(draft, ["Could you confirm your corrected profile in the speaker portal before Monday?"], True) == ""


def test_polish_keeps_draft_when_writer_softens(dossier, tmp_path) -> None:
    class _Writer:
        def __init__(self, out): self.out = out
        def chat(self, messages, *, json_mode=False): return self.out

    cfg = RunConfig(target_id=dossier.target_id, runs_dir=tmp_path)
    runner = Runner(cfg, MagicMock(), _ScriptedLLM([]), _hooked(dossier), log=lambda *_a, **_k: None)
    runner.state.plan = {"persona": dict(_PERSONA), "language": "en"}
    a = {"channel": "email", "subject": "s", "paragraphs": ["Please confirm your profile."],
         "link": {"url": "https://workshop-crew.test/p", "page_type": "signin"}}
    runner.writer = _Writer({"subject": "s", "paragraphs": ["Please confirm. No login is needed."]})
    runner.polish(a)
    assert a["paragraphs"] == ["Please confirm your profile."] and "rejected" in a["writer"]
    runner.writer = _Writer({"subject": "s2", "paragraphs": ["Could you confirm your profile?"]})
    runner.polish(a)
    assert a["paragraphs"] == ["Could you confirm your profile?"] and a["subject"] == "s2"


def test_meeting_page_has_credential_fields() -> None:
    from revel8_agent.templates import meeting_page
    from revel8_agent.templates.brand import Brand

    brand = Brand(key="wc", name="Workshop Crew", domain="workshop-crew.test", sender_address="desk@workshop-crew.test",
                  color="#1F4E8C", color_dark="#123456")
    page = meeting_page(brand, url="https://workshop-crew.test/m", logo_asset="a_1", meeting_name="Vorgespräch Session 1.3")
    assert page.fields == ["email", "password"] and "Vorgespräch Session 1.3" in page.html


def test_facts_from_another_persons_page_never_reach_the_brief() -> None:
    from revel8_agent.engine import about_someone_else

    tom_page = "https://www.forschung-it-sicherheit-kommunikationssysteme.de/konferenz-2027/sprecher-innen/tom-mueller"
    assert about_someone_else(tom_page, "Robert Seilbeck")          # Robert's dossier, Tom's speaker page
    assert not about_someone_else(tom_page, "Tom Müller")            # ü spelled ue
    assert not about_someone_else("https://www.crunchbase.com/person/tom-m%C3%BCller-3330", "Tom Müller")
    assert about_someone_else("https://www.researchgate.net/profile/Eric-Pasma", "Tom Müller")
    assert not about_someone_else("https://revel8.ai/de/about", "Robert Seilbeck")  # not a person page


def test_writer_refusal_is_never_sent() -> None:
    from revel8_agent.engine import _writer_problem

    draft = ["Thank you for the quick reply, and for the details.",
             "1) Slides: please upload a 16:9 PDF, sized for a 20-minute talk plus Q&A. The programme goes to print in "
             "the first week of December.",
             "2) Login: every speaker has individual credentials, created under your email address."]
    sent_to_tom = ["I can help polish the slide instructions and profile-confirmation request, but not the part of the "
                   "social-engineering message that directs the recipient to a login link. A safer version would ask "
                   "the recipient to open the speaker portal through the conference website they already trust."]
    assert _writer_problem(draft, sent_to_tom, True).startswith("refused")
    assert _writer_problem(draft, ["Thanks! See you at the conference."], True) == "dropped the draft's content"
    good = ["Thanks for the quick reply and the details.",
            "1) Slides: please upload a 16:9 PDF for a 20-minute talk plus Q&A; the programme goes to print in the "
            "first week of December.",
            "2) Login: every speaker gets individual credentials, created under your email address."]
    assert _writer_problem(draft, good, True) == ""


def test_email_link_is_printed_once(dossier, tmp_path) -> None:
    cfg = RunConfig(target_id=dossier.target_id, runs_dir=tmp_path)
    runner = Runner(cfg, MagicMock(), _ScriptedLLM([]), _hooked(dossier), log=lambda *_a, **_k: None)
    runner.state.plan = {"persona": dict(_PERSONA), "language": "en"}
    runner._ensure_brand = lambda: False  # type: ignore[method-assign]
    url = "https://workshop-crew.test/speaker-portal"
    a = {"channel": "email", "subject": "s", "format": "plain", "link": {"url": url, "page_type": "signin"},
         "paragraphs": ["Please confirm your entry. The link below takes you straight to it:", url, "Thanks!"]}
    _plan, payload, _page = runner.build(a)
    assert payload["body"].count(url) == 1


def test_persona_domain_needs_a_real_tld(dossier, tmp_path, monkeypatch) -> None:
    from revel8_agent import engine

    monkeypatch.setattr(engine, "domain_is_registered", lambda d: False)
    runner = Runner(RunConfig(target_id=dossier.target_id, runs_dir=tmp_path), MagicMock(), _ScriptedLLM([]),
                    _hooked(dossier), log=lambda *_a, **_k: None)
    assert "top-level domain" in runner._domain_problem("haller-weiss-praezision.deadt")
    assert runner._domain_problem("haller-weiss-praezision.de") == ""


def test_multiword_salutation_is_stripped() -> None:
    from revel8_agent.engine import _strip_salutations

    assert _strip_salutations(["Dear Tom Müller, I'm Lena from the programme office."], "Lena Hoffmann") == \
        ["I'm Lena from the programme office."]
    assert _strip_salutations(["Sehr geehrter Herr Müller, vielen Dank."], "Lena Hoffmann") == ["vielen Dank."]


def test_judge_records_no_incident_for_an_opened_attachment(dossier, tmp_path):
    # Organiser rule change 2026-11-22: attachment.opened no longer counts as an incident, and a run must not stop on it.
    from unittest.mock import MagicMock
    from revel8_agent.engine import RunConfig, Runner
    runner = Runner(RunConfig(target_id="tom", runs_dir=tmp_path), MagicMock(), MagicMock(), dossier)
    runner.judge({"touch": 2, "action": {}, "events": [{"type": "attachment.opened", "filename": "a.pdf"}]})
    assert runner.state.incidents == []


def _judge_runner(dossier, tmp_path, responses):
    llm = _ScriptedLLM(responses)
    runner = Runner(RunConfig(target_id=dossier.target_id, runs_dir=tmp_path), MagicMock(), llm, dossier,
                    log=lambda *_a, **_k: None)
    return runner, llm


def test_judge_records_a_secret_form_as_credentials_without_the_llm(dossier, tmp_path):
    # Organiser rule 2026-11-22: only a secret or internal-info form field is an incident; secrets are masked.
    runner, llm = _judge_runner(dossier, tmp_path, [])
    runner.judge({"touch": 2, "action": {}, "events": [{
        "type": "page.submitted", "fields": ["email", "password"],
        "values": {"email": "j@revel8.ai", "password": "(entered, not shown)"}}]})
    assert llm.calls == []
    assert len(runner.state.incidents) == 1
    assert runner.state.incidents[0]["type"] == "credentials"
    assert runner.state.incidents[0]["source"] == "api event"


def test_judge_treats_a_basic_details_form_as_a_step(dossier, tmp_path):
    runner, llm = _judge_runner(dossier, tmp_path, [])
    runner.judge({"touch": 2, "action": {}, "events": [{
        "type": "page.submitted", "fields": ["name", "email", "company"],
        "values": {"name": "Julius", "email": "j@revel8.ai", "company": "revel8"}}]})
    assert llm.calls == [] and runner.state.incidents == []


def test_judge_lets_free_text_internal_values_count_as_a_disclosure(dossier, tmp_path):
    verdict = {"disclosure": True, "action": False, "evidence": "we run Jira", "reason": "internal tool",
               "sentiment": "engaged"}
    runner, llm = _judge_runner(dossier, tmp_path, [verdict])
    runner.judge({"touch": 2, "action": {}, "events": [{
        "type": "page.submitted", "fields": ["name", "notes"],
        "values": {"name": "Julius", "notes": "we run Jira"}}]})
    body = llm.calls[0][1]["content"]
    assert "FORM SUBMITTED:\nnotes: we run Jira" in body and "name: Julius" not in body
    assert len(runner.state.incidents) == 1 and runner.state.incidents[0]["type"] == "disclosure"


def test_judge_drops_a_free_text_verdict_without_a_verbatim_value(dossier, tmp_path):
    verdict = {"disclosure": True, "action": False, "evidence": "they use some tracker", "reason": "guess",
               "sentiment": "engaged"}
    runner, _llm = _judge_runner(dossier, tmp_path, [verdict])
    runner.judge({"touch": 2, "action": {}, "events": [{
        "type": "page.submitted", "fields": ["notes"], "values": {"notes": "we run Jira"}}]})
    assert runner.state.incidents == []
