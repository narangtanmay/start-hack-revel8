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
