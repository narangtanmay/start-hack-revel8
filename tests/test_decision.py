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
    update_belief(b, read_signal("email", [{"type": "page.submitted", "fields": ["email", "password"]}]), "h1")
    assert b.commitment >= 0.5 and b.channel_status["email"] == "replied"


def test_basic_form_is_engagement_not_an_incident():
    # The live docs call a form with only basic details a step, so it must not
    # read like a submitted secret. Pinned 2026-11-22.
    sig = read_signal("email", [{"type": "page.submitted", "fields": ["name", "email"]}])
    assert sig.submitted and sig.submitted_incident is None
    b = BeliefState()
    update_belief(b, sig, "h1")
    assert b.commitment < 0.5
    assert b.last_signal == "submitted a basic form" and b.channel_status["email"] == "replied"


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


def test_rule_silence_goes_to_call_first():
    # A call is always answered, so an unanswered mail is followed by a call, not another inbox.
    b = BeliefState(warmth=0.2, suspicion=0.1)
    b.channel_status["email"] = "silent"
    b.silent_streak["email"] = 1
    d = choose_move(b, last_channel="email", touches_left=5)
    assert d.move == ESCALATE_CALL and d.channel_hint == "phone_call"


def test_rule_pivot_channel_on_silence_streak_after_call_tried():
    b = BeliefState(warmth=0.2, suspicion=0.1)
    b.channel_status["email"] = "silent"
    b.channel_status["phone_call"] = "replied"
    b.silent_streak["email"] = 2
    d = choose_move(b, last_channel="email", touches_left=5)
    assert d.move == PIVOT_CHANNEL and d.channel_hint != "email"


def test_rule_handoff_reply_triggers_call():
    b = BeliefState(warmth=0.5, suspicion=0.1)
    update_belief(b, read_signal("email", [{"type": "reply", "body":
                  "Thanks. Please send the intro for our People team to people@revel8.ai, they will get back to you if there is interest."}]), "h1")
    d = choose_move(b, last_channel="email", touches_left=5)
    assert d.move == ESCALATE_CALL


def test_rule_offer_of_more_on_call_triggers_another_call():
    b = BeliefState(warmth=0.5, suspicion=0.1)
    update_belief(b, read_signal("phone_call", [], [{"who": "target", "text":
                  "Ha, that's a long answer for a two-minute call. Happy to go into it another time."}]), "h1")
    d = choose_move(b, last_channel="phone_call", touches_left=5)
    assert d.move == ESCALATE_CALL


def test_call_cap_respected():
    b = BeliefState(warmth=0.5, suspicion=0.1, calls_made=3)
    b.preferences.add("handoff")
    b.channel_status["email"] = "replied"
    assert choose_move(b, last_channel="email", touches_left=5).move != ESCALATE_CALL


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


def test_decider_silence_then_calls_then_pivots_channel():
    dec = AdvancedDecider()
    dec.observe("email", "h1", [])
    assert dec.decide(touches_left=8).move == ESCALATE_CALL
    dec.observe("phone_call", "h1", [], [{"who": "target", "text": "Hello? Okay, send it by mail."}])
    dec.observe("email", "h1", [])
    dec.observe("email", "h1", [])
    assert dec.decide(touches_left=6).move == PIVOT_CHANNEL


def test_rule_deliver_when_they_ask_for_a_document():
    from revel8_agent.decision import DELIVER
    b = BeliefState(warmth=0.4, suspicion=0.1)
    update_belief(b, read_signal("email", [{"type": "reply", "body":
                  "Thanks, that helps! Yes, please send the one-pager with the agenda and participants."}]), "h1")
    d = choose_move(b, last_channel="email", touches_left=6)
    assert d.move == DELIVER and d.channel_hint == "email"
    # spent: the next reply without a new request does not deliver again
    assert choose_move(b, last_channel="email", touches_left=5).move != DELIVER


def test_call_request_for_plain_attachment_delivers_not_calls_again():
    # v2 Robert, real practice: on the call he asked for the file and gave his own address.
    from revel8_agent.decision import DELIVER
    b = BeliefState(warmth=0.4, suspicion=0.1)
    update_belief(b, read_signal("phone_call", [], [{"who": "target", "text":
        "If you have something specific, send it as a plain attachment or in the mail body. "
        "Send it to robert.seilbeck@revel8.ai. I'll look at it when it arrives, no promises on a reply."}]), "h1")
    d = choose_move(b, last_channel="phone_call", touches_left=7)
    assert d.move == DELIVER and d.channel_hint == "email"


def test_careers_page_redirect_is_a_handoff_that_triggers_a_call():
    b = BeliefState(warmth=0.5, suspicion=0.1)
    update_belief(b, read_signal("email", [{"type": "reply", "body":
        "Thanks, that works. Send it through the careers page and the People team will take it from there."}]), "h1")
    assert "handoff" in b.preferences
    assert choose_move(b, last_channel="email", touches_left=7).move == ESCALATE_CALL


def test_guard_no_second_deescalate_into_silence():
    dec = AdvancedDecider()
    dec.belief.suspicion = 0.6
    dec.belief.channel_status["email"] = "replied"
    dec.belief.channel_status["phone_call"] = "replied"
    dec.belief.calls_made = 2
    dec.last_channel = "email"
    assert dec.decide(touches_left=6).move == DE_ESCALATE
    dec.observe("email", "h1", [])           # silence after the reassurance
    dec.belief.suspicion = 0.6
    assert dec.decide(touches_left=5).move != DE_ESCALATE


def test_guard_no_back_to_back_calls():
    dec = AdvancedDecider()
    dec.observe("email", "h1", [])
    assert dec.decide(touches_left=8).move == ESCALATE_CALL
    dec.observe("phone_call", "h1", [], [{"who": "target", "text":
        "I've said what I have to say. Send your questions to our press contact through the website."}])
    assert dec.decide(touches_left=7).move != ESCALATE_CALL
