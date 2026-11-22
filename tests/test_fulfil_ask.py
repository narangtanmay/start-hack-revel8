from types import SimpleNamespace

from revel8_agent.engine import Runner


def _fake(steps):
    return SimpleNamespace(state=SimpleNamespace(steps=steps), _ARTIFACT_ASK=Runner._ARTIFACT_ASK)


def ask(steps, cur=None):
    return Runner._open_artifact_ask(_fake(steps), cur or {})


def test_detects_invite_request():
    s = [{"payload": {"body": "x"}, "events": [{"type": "reply", "body": "Works for me. Please send the invite to my address."}]}]
    assert "invite" in ask(s)


def test_slots_or_plain_reply_are_not_artifacts():
    s = [{"payload": {"body": "x"}, "events": [{"type": "reply", "body": "Could you send two or three slots? Thanks."}]}]
    assert ask(s) == ""


def test_silence_on_last_touch_means_no_open_ask():
    s = [{"payload": {}, "events": [{"type": "reply", "body": "Please send the PDF."}]}, {"payload": {"body": "y"}, "events": []}]
    assert ask(s) == ""


def test_refused_attachments_never_forced():
    s = [{"payload": {"body": "x"}, "events": [{"type": "reply", "body": "Send me the document."}]}]
    assert ask(s, {"target_state": {"blocked_mechanisms": ["attachments"]}}) == ""
