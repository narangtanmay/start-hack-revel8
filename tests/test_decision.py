"""Tests for the human-like decision controller and belief updates.

Every rule in ``choose_move`` is deterministic, so the agent's escalate/hold
judgement is pinned down here — that is the point of making it explicit.
"""

from revel8_agent.decision import (
    DE_ESCALATE,
    ESCALATE_CALL,
    ESCALATE_PRESSURE,
    HOLD,
    PIVOT_CHANNEL,
    PIVOT_HOOK,
    STOP,
    AdvancedDecider,
    BeliefState,
    choose_move,
    read_signal,
    update_belief,
)


# --- perception ------------------------------------------------------------

def test_read_signal_classifies_events():
    sig = read_signal("email", [{"type": "link.opened"}, {"type": "page.submitted", "fields": ["email"]}])
    assert sig.opened_link and sig.submitted and not sig.silent
    silent = read_signal("email", [])
    assert silent.silent and not silent.replied


def test_read_signal_from_call_transcript():
    sig = read_signal("phone_call", [], transcript=[{"who": "target", "text": "sure, go on"}])
    assert sig.replied and "sure" in sig.reply_text


# --- belief updates --------------------------------------------------------

def test_submission_raises_commitment():
    b = BeliefState()
    update_belief(b, read_signal("email", [{"type": "page.submitted"}]), "h1")
    assert b.commitment >= 0.5 and b.channel_status["email"] == "replied"


def test_suspicious_reply_raises_suspicion_and_can_burn():
    b = BeliefState()
    update_belief(b, read_signal("email", [{"type": "reply", "body": "who is this? this looks like a scam"}]), "h1")
    assert b.suspicion >= 0.5


def test_question_reply_adds_open_loop():
    b = BeliefState()
    update_belief(b, read_signal("email", [{"type": "reply", "body": "which invoice do you mean?"}]), "h1")
    assert b.open_loops and b.channel_status["email"] == "replied"


def test_silence_accumulates_streak():
    b = BeliefState()
    for _ in range(2):
        update_belief(b, read_signal("email", []), "h1")
    assert b.silent_streak["email"] == 2


# --- the escalation controller (one assertion per rule) --------------------

def test_rule_stop_when_alarmed_and_cold():
    b = BeliefState(suspicion=0.85, warmth=0.1)
    b.channel_status["email"] = "burned"
    assert choose_move(b, last_channel="email", touches_left=5).move == STOP


def test_rule_deescalate_on_rising_suspicion():
    b = BeliefState(suspicion=0.6, warmth=0.5)
    assert choose_move(b, last_channel="email", touches_left=5).move == DE_ESCALATE


def test_rule_hold_to_answer_open_loop():
    b = BeliefState(warmth=0.4, suspicion=0.1, commitment=0.1)
    b.channel_status["email"] = "replied"
    b.open_loops = ["which invoice?"]
    assert choose_move(b, last_channel="email", touches_left=5).move == HOLD


def test_rule_escalate_pressure_when_warm_and_committed():
    b = BeliefState(warmth=0.6, suspicion=0.1, commitment=0.5)
    b.channel_status["email"] = "opened"
    assert choose_move(b, last_channel="email", touches_left=5).move == ESCALATE_PRESSURE


def test_rule_escalate_call_on_opened_but_silent():
    b = BeliefState(warmth=0.3, suspicion=0.1, commitment=0.2)
    b.channel_status["email"] = "opened"
    d = choose_move(b, last_channel="email", touches_left=5)
    assert d.move == ESCALATE_CALL and d.channel_hint == "phone_call"


def test_rule_pivot_channel_on_silence_streak():
    b = BeliefState(warmth=0.2, suspicion=0.1)
    b.channel_status["email"] = "silent"
    b.silent_streak["email"] = 2
    d = choose_move(b, last_channel="email", touches_left=5)
    assert d.move == PIVOT_CHANNEL and d.channel_hint != "email"


def test_rule_pivot_hook_on_poor_resonance():
    b = BeliefState(warmth=0.3, suspicion=0.1, current_hook="h1")
    b.channel_status["email"] = "replied"
    b.hook_resonance["h1"] = -0.4
    assert choose_move(b, last_channel="email", touches_left=5).move == PIVOT_HOOK


def test_rule_hold_on_first_contact():
    assert choose_move(BeliefState(), last_channel="email", touches_left=10).move == HOLD


def test_call_not_chosen_when_live_disallowed():
    b = BeliefState(warmth=0.3, suspicion=0.1)
    b.channel_status["email"] = "opened"
    d = choose_move(b, last_channel="email", touches_left=5, allow_live=False)
    assert d.move != ESCALATE_CALL


# --- end-to-end through the decider ---------------------------------------

def test_decider_opened_then_recommends_call():
    dec = AdvancedDecider()
    dec.observe("email", "h1", [{"type": "link.opened"}])
    move = dec.decide(touches_left=8).move
    assert move == ESCALATE_CALL


def test_decider_two_silences_then_pivots_channel():
    dec = AdvancedDecider()
    dec.observe("email", "h1", [])
    dec.observe("email", "h1", [])
    assert dec.decide(touches_left=8).move == PIVOT_CHANNEL
