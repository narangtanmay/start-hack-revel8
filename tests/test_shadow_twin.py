from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from revel8_agent import engine, swarm
from revel8_agent.engine import RunConfig, Runner
from revel8_agent.report import _shadow_twin_html
from revel8_agent.schemas import HookHypothesis, VerifiedFact
from revel8_agent.shadow_twin import ShadowForecast, score_forecast, select_shadow_twin_move

WEEKDAY = datetime(2026, 11, 23)   # Monday
WEEKEND = datetime(2026, 11, 22)   # Sunday

BRIEF = {
    "facts": [{"id": "f1", "fact": "x", "timing": "upcoming"}],
    "hooks": [{"id": "h1", "timing": "upcoming", "confidence": 0.9, "supporting_fact_ids": ["f1"]}],
}
PLAN = {"objective": "disclosure", "hook_id": "h1", "sequence": []}


def _step(touch: int, channel: str, *, reply: str | None = None, sentiment: str | None = None) -> dict[str, Any]:
    events = [{"type": "reply", "body": reply}] if reply else []
    step: dict[str, Any] = {"touch": touch, "action": {"channel": channel, "hook_id": "h1"}, "events": events}
    if sentiment:
        step["judge"] = {"sentiment": sentiment}
    return step


def _select(steps, today, plan=PLAN, touch=None, brief=BRIEF):
    return select_shadow_twin_move(brief, steps, touch or len(steps) + 1, 10, plan, today=today)


def _by_tier(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["risk_tier"]: c for c in payload["candidates"]}


def test_score_forecast_math() -> None:
    f = ShadowForecast(risk_tier="safe", predicted_reaction="engage", progress_prob=0.9, suspicion_risk=0.5,
                       social_norm_violation=0.2, verifiability_risk=0.1, rationale="r")
    assert score_forecast(f) == round(0.9 - 0.4 - 0.2 - 0.07, 3) == 0.23


def test_forecast_rejects_out_of_range_probability() -> None:
    with pytest.raises(ValueError):
        ShadowForecast(risk_tier="safe", predicted_reaction="engage", progress_prob=1.2, suspicion_risk=0,
                       social_norm_violation=0, verifiability_risk=0, rationale="r")


def test_three_distinct_tiers_exactly_one_selected() -> None:
    move, payload = _select([], WEEKDAY)
    assert [c["risk_tier"] for c in payload["candidates"]] == ["safe", "balanced", "bold"]
    assert [c["selected"] for c in payload["candidates"]].count(True) == 1
    assert _by_tier(payload)[payload["selected_tier"]]["selected"] is True
    assert {"move_type", "hook_id", "channel", "objective", "ask", "cited_fact_ids", "promises", "rationale",
            "alternatives_considered"} <= set(move)
    assert move["cited_fact_ids"] == ["f1"]


def test_deterministic() -> None:
    steps = [_step(1, "email", sentiment="silent")]
    assert _select(steps, WEEKDAY) == _select(steps, WEEKDAY)


def test_weekend_phone_call_flagged_and_loses() -> None:
    steps = [_step(i, ch, sentiment="silent") for i, ch in enumerate(["email", "linkedin_message", "slack"], 1)]
    move, payload = _select(steps, WEEKEND)
    bold = _by_tier(payload)["bold"]
    assert bold["channel"] == "phone_call" and bold["kind"] == "call"
    assert bold["forecast"]["social_norm_violation"] >= 0.65
    assert payload["selected_tier"] in ("safe", "balanced")
    assert move["channel"] != "phone_call"


def test_email_reply_penalizes_jumping_to_sms() -> None:
    steps = [_step(1, "email", reply="Thanks, who is this?", sentiment="questioning")]
    plan = {**PLAN, "sequence": [{"channel": "email"}, {"channel": "sms"}]}
    move, payload = _select(steps, WEEKDAY, plan=plan)
    bold = _by_tier(payload)["bold"]
    assert bold["channel"] == "sms"
    assert bold["forecast"]["social_norm_violation"] >= 0.65
    assert payload["selected_tier"] != "bold" and move["channel"] == "email"


def test_weekday_multichannel_silence_boosts_phone_call() -> None:
    steps = [_step(i, ch, sentiment="silent") for i, ch in enumerate(["email", "linkedin_message", "slack"], 1)]
    move, payload = _select(steps, WEEKDAY)
    assert payload["selected_tier"] == "bold" and move["channel"] == "phone_call"
    assert move["move_type"] == "ESCALATE_CALL"
    assert _by_tier(payload)["bold"]["forecast"]["social_norm_violation"] == 0.0


def test_past_hook_raises_verifiability_risk() -> None:
    brief = {**BRIEF, "hooks": [{"id": "h1", "timing": "PAST (2025)", "confidence": 0.9}]}
    _, payload = _select([], WEEKDAY, brief=brief)
    assert all(c["forecast"]["verifiability_risk"] >= 0.55 for c in payload["candidates"])


def test_declined_attachments_never_pick_action_and_prefer_credentials_or_disclosure() -> None:
    steps = [_step(1, "email", reply="Ich öffne keine Anhänge.", sentiment="refusing")]
    move, payload = _select(steps, WEEKDAY, plan={**PLAN, "objective": "action"})
    balanced = _by_tier(payload)["balanced"]
    assert move["objective"] != "action"
    assert "credentials" in balanced["summary"] or "disclosure" in balanced["summary"]
    assert _by_tier(payload)["safe"]["forecast"]["suspicion_risk"] < 0.45


def test_negative_verdict_makes_aggressive_branch_suspicious_and_never_repeats_sms() -> None:
    steps = [_step(1, "sms", sentiment="suspicious")]
    _, payload = _select(steps, WEEKDAY)
    assert _by_tier(payload)["bold"]["forecast"]["suspicion_risk"] >= 0.45
    assert _by_tier(payload)["balanced"]["channel"] != "sms"


def test_report_renders_all_three_cards() -> None:
    _, payload = _select([], WEEKDAY)
    html = _shadow_twin_html(payload)
    for tier in ("SAFE", "BALANCED", "BOLD"):
        assert tier in html
    assert html.count("SELECTED") == 1
    for c in payload["candidates"]:
        assert f"EV {c['ev_score']:.2f}" in html


# ---- Runner wiring (offline) -------------------------------------------------------------------
class _LLM:
    def __init__(self, responses: list[dict]) -> None:
        self.responses, self.calls = list(responses), []

    def chat(self, messages, *, json_mode=False, temperature=None):
        self.calls.append(list(messages))
        return self.responses.pop(0)


def test_swarm_task_and_cli_carry_shadow_twin_flag() -> None:
    assert swarm.Task(target="t").use_shadow_twin is False
    assert swarm.Task(target="t", use_shadow_twin=True).use_shadow_twin is True


def test_runner_populates_shadow_twin_and_binds_winner(dossier, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(engine, "domain_is_registered", lambda _d: False)
    dossier.facts.append(VerifiedFact(id="f2", fact="Ships a product", category="role", source_url="https://x.test",
                                      verbatim_quote="Ships a product", recency="2026-12-10"))
    dossier.hypotheses = [HookHypothesis(id="h_top", topic="b", rationale="r", confidence=0.9,
                                         supporting_fact_ids=["f2"])]
    persona = {"name": "Event Desk", "organisation": "Workshop Crew", "role": "Coordinator",
               "email": "desk@workshop-crew.test", "phone": "+49 89 1234", "website_domain": "workshop-crew.test"}
    plan = {"hook_id": "h_top", "objective": "disclosure", "persona": persona, "language": "en"}
    # the LLM tries to wander off to slack with another hook; the winning branch must still drive the send
    decide = {"decision": "PIVOT_CHANNEL", "rationale": "r", "discarded": [], "hook_id": "h_low", "kind": "message",
              "channel": "slack", "sender": {"name": "Event Desk", "address": "desk@workshop-crew.test"},
              "subject": "s", "format": "plain", "paragraphs": ["Check-in opens at 9 a.m."],
              "link": None, "attachment_filename": None, "cited_fact_ids": ["check-in"]}
    api = MagicMock()
    api.create_session.return_value = {"session_id": "s1"}
    api.send_message.return_value = {"message_id": "m1", "events": [], "touches_used": 1}
    llm = _LLM([plan, decide])
    cfg = RunConfig(target_id=dossier.target_id, runs_dir=tmp_path, max_touches=1, use_shadow_twin=True)
    runner = Runner(cfg, api, llm, dossier, log=lambda *_a, **_k: None)
    runner.judge = lambda step: None  # type: ignore[method-assign]
    state = runner.run()

    assert state.status == "done", state.error
    step = state.steps[0]
    twin = step["shadow_twin"]
    assert [c["risk_tier"] for c in twin["candidates"]] == ["safe", "balanced", "bold"]
    chosen = next(c for c in twin["candidates"] if c["selected"])
    assert chosen["risk_tier"] == twin["selected_tier"]
    assert step["policy"]["channel"] == step["action"]["channel"] == chosen["channel"]
    assert step["action"]["hook_id"] == step["policy"]["hook_id"] == "h_top"
    assert api.send_message.call_args.args[1]["channel"] == chosen["channel"]
    assert "POLICY MOVE" in llm.calls[1][1]["content"]
