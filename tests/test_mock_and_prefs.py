from revel8_agent.decision import (
    ELICIT,
    ESCALATE_CALL,
    BeliefState,
    Signal,
    choose_move,
    update_belief,
)
from revel8_agent.mock_target import MockRevel8Client


def _reply(belief: BeliefState, text: str, channel: str = "email") -> None:
    update_belief(belief, Signal(channel=channel, replied=True, reply_text=text), "h1", reply_sentiment=0.5)


# Verbatim from our practice logs (team sessions on 2026-11-21).
def test_preferences_from_real_replies() -> None:
    b = BeliefState()
    _reply(b, "I'd rather not create another login just to leave a comment. Happy to just send my KPI framing "
              "input here by email, or we can go over it quickly on the call.")
    assert {"no_login", "offers_input", "call_ok", "wants_plain_text"} <= b.preferences
    b2 = BeliefState()
    _reply(b2, "I won't open Word files from an organisation I can't verify yet. Please don't send further reminders.")
    assert {"no_office_files", "no_reminders"} <= b2.preferences


def test_offered_input_triggers_elicit() -> None:
    b = BeliefState(warmth=0.5)
    _reply(b, "Here's my input: I'd lead with time-to-first-report as the primary signal.")
    assert choose_move(b, last_channel="email", touches_left=6).move == ELICIT


def test_friendly_deferral_triggers_call_not_reminder() -> None:
    b = BeliefState(warmth=0.5)
    _reply(b, "Thanks, I'm travelling until Monday and will come back to you early next week.")
    assert choose_move(b, last_channel="email", touches_left=6).move == ESCALATE_CALL


def test_mock_target_rewards_on_topic_and_records_truth() -> None:
    api = MockRevel8Client(seed=1)
    sid = api.create_session()["session_id"]
    off = api.send_message(sid, {"to": "robert", "channel": "email", "from": {"name": "A B", "address": "a@x.de"},
                                 "subject": "Quick question", "body": "Do you like football?"})
    on = api.send_message(sid, {"to": "robert", "channel": "email", "from": {"name": "A B", "address": "a@x.de"},
                                "subject": "Senior engineer candidates", "body": "Following up: here are the profiles "
                                "of two engineers for your hiring.", "attachments": [{"filename": "Profiles.pdf"}]})
    truth = api.truth(sid)
    assert [t["topic_hit"] for t in truth] == [False, True]
    assert on["touches_used"] == 2 and isinstance(off["events"], list)


def test_mock_sender_switch_raises_suspicion() -> None:
    api = MockRevel8Client()
    sid = api.create_session()["session_id"]
    for name in ("Lena Hofer", "Max Weber"):
        api.send_message(sid, {"to": "tom", "channel": "email", "from": {"name": name, "address": "x@y.de"},
                               "body": "deepfake demo for your product"})
    assert "different sender than before" in api.truth(sid)[1]["notes"]


def test_invitation_or_two_holds_makes_the_ask() -> None:
    from revel8_agent.decision import ESCALATE_PRESSURE, HOLD, AdvancedDecider

    b = BeliefState(warmth=0.5)
    _reply(b, "Sounds good. What would you need from me exactly?")
    assert choose_move(b, last_channel="email", touches_left=6).move == ESCALATE_PRESSURE
    d = AdvancedDecider()
    d.belief.warmth = 0.5
    moves = []
    for _ in range(3):
        d.observe("email", "h1", [{"type": "reply", "body": "Interesting. Which organisation are you with?"}], reply_sentiment=0.3)
        moves.append(d.decide(6).move)
    assert moves[:2] == [HOLD, HOLD] and moves[2] == ESCALATE_PRESSURE
