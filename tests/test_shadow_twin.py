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


# Robert v3 (runs/20261122-060729-robert-adaptive-ds-robert-v3.json): every reply deflected to
# info@revel8.ai / sales in wording _ROUTED_RE never matched, and the twin stayed on h4 for 6 touches.
ROBERT_REPLIES = [
    "Hi Herr Ostermeier, thanks for the feedback. The works-council side of deployments is handled by our "
    "solution engineering and customer team, not by me.",
    "Hi Herr Ostermeier, please use info@revel8.ai or the demo form on the website. Solution engineering "
    "picks it up from there and assigns the right person.",
    "Hi Herr Ostermeier, send the one-pager and your question to info@revel8.ai. Solution engineering will "
    "answer the anonymization question binding and in writing.",
    "Hi Herr Ostermeier, I can't answer how solution engineering runs works-council rounds. Please put that "
    "question in your message to info@revel8.ai.",
]
TWO_HOOKS = {**BRIEF, "hooks": BRIEF["hooks"] + [
    {"id": "h2", "timing": "upcoming", "confidence": 0.8, "supporting_fact_ids": ["f1"]}]}


def test_stalled_hook_pivots_regardless_of_reply_wording() -> None:
    # Every one of these replies routes to info@ — the dead hook is dropped (h2) and, since 22 Nov,
    # the stall is closed by mailing the desk instead of pivoting onto the same dead thread.
    steps = [_step(i + 1, "email", reply=r) for i, r in enumerate(ROBERT_REPLIES)]
    move, _ = _select(steps, WEEKDAY, brief=TWO_HOOKS)
    assert move["hook_id"] == "h2"
    assert move["move_type"] == "STAY"
    assert "info@revel8.ai" in move["ask"]


def test_one_unproductive_reply_does_not_pivot() -> None:
    steps = [_step(i + 1, "email", reply=r) for i, r in enumerate(ROBERT_REPLIES[:2])]
    move, _ = _select(steps, WEEKDAY, brief=TWO_HOOKS)
    assert move["hook_id"] == "h1"


# Tom task-1805 (runs/20261122-051859-tom-adaptive-kimi-tom.json): engaged, kept asking for the call
# and the PDF-after-call. Repeating an undelivered ask is not a stall; 1e4f43e keeps his hook.
TOM_REPLIES = [
    "Hi Sebastian, Thanks for reaching out. Voice-based payment-change scenarios are in scope. Before a call, "
    "a few numbers would help me scope this.",
    "Hi Sebastian, Thanks, this is what I needed. 100 participants across Leipzig (60) and Chemnitz (40), a "
    "works-council review on 10 December and pilot calls 11-22 January fit our planning.",
    "Hi Sebastian, Yes, send the one-page PDF after the call and I'll forward it to the colleague drafting the "
    "note. Our draft will reach you early next week. Then send me your slot suggestions.",
    "Hi Sebastian, Thanks. I'm keeping to what we agreed: I'll look at the PDF after our call, so I won't "
    "forward it before then. Please send me your slot suggestions for early next week.",
    "Hi Sebastian, Tuesday 8 December, 14:00-14:20 CET works for me. Please send the invite to tom@revel8.ai. "
    "The PDF follows after the call, as agreed.",
]


def test_engaged_target_with_undelivered_ask_keeps_hook() -> None:
    steps = [_step(i + 1, "email", reply=r) for i, r in enumerate(TOM_REPLIES)]
    move, _ = _select(steps, WEEKDAY, brief=TWO_HOOKS)
    assert move["hook_id"] == "h1"


THREE_HOOKS = {**BRIEF, "hooks": TWO_HOOKS["hooks"] + [
    {"id": "h3", "timing": "upcoming", "confidence": 0.7, "supporting_fact_ids": ["f1"]}]}


def test_routed_pivots_once_not_on_every_silent_touch() -> None:
    # Robert smoke T5/T6: ROUTED stuck after he went silent and the twin rotated h4 -> h2 -> h3.
    routed = _step(1, "email", reply="Please send it to info@revel8.ai, not the right person for this.")
    pivot, _ = _select([routed], WEEKDAY, brief=THREE_HOOKS)
    assert pivot["hook_id"] == "h2"
    silent = {"touch": 2, "action": {"channel": "email", "hook_id": "h2"}, "events": []}
    move, _ = _select([routed, silent], WEEKDAY, brief=THREE_HOOKS)
    assert move["hook_id"] == "h2"


def test_silence_after_a_deflection_counts_toward_the_stall() -> None:
    # Robert final (5ade40d): deflected at T2, then 4 silent touches all on h4 with the same portal link.
    steps = [
        _step(1, "email", reply="Hi Andreas, thanks for writing. Both topics are relevant to us."),
        _step(2, "email", reply="Please send the one-pager and the portal request to Claudia Lannes and the sales desk."),
        {"touch": 3, "action": {"channel": "email", "hook_id": "h1"}, "events": []},
    ]
    move, _ = _select(steps, WEEKDAY, brief=TWO_HOOKS)
    assert move["hook_id"] == "h2"


def test_a_chatty_target_gets_slot_asks_instead_of_endless_mail() -> None:
    # live 2026-11-22: robert answered ten emails, was engaged from T2 and got no next step.
    steps = [
        _step(1, "email", reply="Thanks, useful context.", sentiment="engaged"),
        _step(2, "email", reply="Please use the contact form.", sentiment="engaged"),
    ]
    move, meta = _select(steps, WEEKDAY)
    assert move["move_type"] == "STAY"
    assert "slot" in move["ask"].casefold()


def test_an_unconfirmed_offer_keeps_the_thread_in_mail() -> None:
    proposed = _step(2, "email", reply="Let me check my calendar.", sentiment="engaged")
    proposed["action"]["paragraphs"] = ["For the fifteen minutes: Tue 09:30 or Thu 16:00."]
    steps = [
        _step(1, "email", reply="Thanks, useful context.", sentiment="engaged"),
        proposed,
    ]
    move, meta = _select(steps, WEEKDAY)
    assert move["move_type"] == "STAY"
    assert "hold" in move["ask"].casefold()


def test_once_slots_are_on_the_table_the_call_wins_the_tier_ranking() -> None:
    proposed = _step(2, "email", reply="Thursday works.", sentiment="engaged")
    proposed["action"]["paragraphs"] = ["For the fifteen minutes: Tue 09:30 or Thu 16:00."]
    steps = [
        _step(1, "email", reply="Thanks, useful context.", sentiment="engaged"),
        proposed,
    ]
    move, meta = _select(steps, WEEKDAY)
    assert move["channel"] == "phone_call"
    assert move["move_type"] == "ESCALATE_CALL"
    assert meta["selected_tier"] == "bold"


def _completed_call(steps, *, reply: str = "Good talk, send it over.", transcript: str = "") -> list[dict]:
    call = _step(len(steps) + 1, "phone_call", reply=reply, sentiment="engaged")
    call["transcript"] = [{"who": "target", "text": transcript or reply}]
    return [*steps, call]


def test_after_a_call_the_thread_is_not_pivoted_or_dialled_again() -> None:
    steps = _completed_call([
        _step(1, "email", reply="Send the two-pager over.", sentiment="engaged"),
        _step(2, "email", reply="Tuesday works.", sentiment="engaged"),
    ])
    move, meta = _select(steps, WEEKDAY)
    assert move["move_type"] == "STAY"
    assert move["channel"] == "email"
    assert "promised" in move["ask"].casefold()


def test_the_advance_ask_names_an_internal_detail() -> None:
    # Organiser 09:35: only internal, non-public disclosure or a real action is an incident. A generic
    # ask earns generic answers, so every advance ask names the kind of thing that scores.
    steps = [_step(1, "email", reply="Thanks, useful context.", sentiment="engaged")]
    move, _ = _select(steps, WEEKDAY)
    assert "internal" in move["ask"].casefold()


def test_the_first_touch_offers_a_slot_as_well_as_the_internal_question() -> None:
    # loop7-robert T1 asked only for internal detail and got "not by mail with me", then silence.
    # A router needs something to accept first; the internal question rides along, and lives on the call.
    move, _ = _select([], WEEKDAY)
    ask = move["ask"].casefold()
    assert "slot" in ask and "internal" in ask


def test_a_handoff_by_mail_is_mailed_instead_of_another_hook_pivot() -> None:
    # loop6-robert T1: "I'm passing this to them" -> T2 pivoted the hook instead of writing to them.
    steps = [_step(1, "email", reply="I'm passing this to Claudia at info@revel8.ai, she owns it.",
                   sentiment="engaged")]
    move, meta = _select(steps, WEEKDAY)
    assert move["move_type"] == "STAY"
    assert move["channel"] == "email"
    assert "claudia" in move["ask"].casefold()


def test_a_handoff_on_the_call_is_mailed_instead_of_the_target() -> None:
    steps = _completed_call([
        _step(1, "email", reply="Thanks, useful context.", sentiment="engaged"),
        _step(2, "email", reply="Tuesday works.", sentiment="engaged"),
    ], reply="Write to Claudia or info@revel8.ai with a few time slots.",
       transcript="Write to Claudia or info@revel8.ai with a few time slots.")
    move, meta = _select(steps, WEEKDAY)
    assert move["move_type"] == "STAY"
    assert "claudia" in move["ask"].casefold()
    assert "info@revel8.ai" in move["ask"].casefold()
