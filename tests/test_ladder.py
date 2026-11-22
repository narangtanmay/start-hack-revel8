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


def test_public_info_is_vetoed_as_disclosure():
    from revel8_agent.engine import _PUBLIC_INFO

    assert _PUBLIC_INFO.search("Hosting is public: Germany, on STACKIT. Our ISO 27001 certification is public too.")
    assert _PUBLIC_INFO.search("please write to hello@revel8.ai")
    assert not _PUBLIC_INFO.search("Claudia Lannes from Solution Engineering owns the works council template.")


def test_live_reply_triggers():
    from revel8_agent.ladder import prompt

    def st(body):
        return [{"touch": 1, "payload": {"body": "x"}, "events": [{"type": "reply", "body": body}]}]

    p = prompt(st("Tuesday 24 November, 09:30 works for me. Please send an invite to this address."), [])
    assert "CONVERSION POINT" in p and "calendar_invite" in p
    p = prompt(st("I won't send you our template wording by mail. It goes to customers and serious prospects."), [])
    assert "FORMAL STEP" in p
    assert "CONVERSION" not in prompt(st("Thanks, interesting."), [])


def test_gate_trigger_generalises_beyond_vendor_founders():
    from revel8_agent.ladder import prompt

    def st(body):
        return [{"touch": 1, "payload": {"body": "x"}, "events": [{"type": "reply", "body": body}]}]

    assert "FORMAL STEP" in prompt(st("Any bank detail change has to go through finance with a signed form."), [])
    assert "FORMAL STEP" in prompt(st("That needs approval from my manager first."), [])
