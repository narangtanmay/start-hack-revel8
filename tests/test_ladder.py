from revel8_agent.ladder import check_draft, rung


def _st(reply=False, opened=False):
    ev = ([{"type": "reply", "body": "Sounds good."}] if reply else []) + ([{"type": "attachment.opened"}] if opened else [])
    return [{"touch": 1, "payload": {"body": "x"}, "events": ev}]


def test_rungs_follow_events():
    assert rung(_st(), []) == 0 and rung(_st(reply=True), []) == 1 and rung(_st(True, True), []) == 2
    assert rung(_st(True), [{"type": "disclosure", "source": "llm-judge (estimate)"}]) == 3


def test_gate_requires_scoring_ask_from_touch_one():
    a = {"kind": "message", "paragraphs": ["Thanks, great to hear."]}
    assert check_draft(_st(), [], a, "")          # v3: the ask is required from touch 1
    assert check_draft(_st(reply=True), [], a, "")
    a2 = {"kind": "message", "paragraphs": ["So I set it up right on your side: which tool do you use for scheduling?"]}
    assert check_draft(_st(reply=True), [], a2, "") == []
