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


def test_pre_call_move_after_booked_call_and_invite():
    from revel8_agent.ladder import check_draft, pre_call, prompt

    steps = [
        {"touch": 2, "action": {"channel": "email"}, "events": [
            {"type": "reply", "body": "Tuesday 24 November, 09:30 works for me. Please send an invite to this address."}]},
        {"touch": 3, "action": {"channel": "email"}, "events": [
            {"type": "attachment.opened", "filename": "Sanity_Check_Tue.ics"},
            {"type": "reply", "body": "got the invite, Tuesday 09:30 is in my calendar."}]},
    ]
    assert pre_call(steps) and "PRE-CALL MOVE" in prompt(steps, [])
    email = {"kind": "message", "paragraphs": ["Which tool do you use for this internally?"]}
    assert check_draft(steps, [], email, "")                       # another email is rejected
    assert check_draft(steps, [], {"kind": "call", "channel": "phone_call"}, "") == []
    called = steps + [{"touch": 4, "action": {"channel": "phone_call"}, "transcript": [{"who": "target", "text": "Hi"}]}]
    assert not pre_call(called)
    assert not pre_call(steps[:1])                                 # booked but no invite yet: send the invite first


def test_already_public_vetoes_research_terms_only():
    from revel8_agent.engine import _already_public

    public = "revel8 runs on stackit in germany and is iso 27001 certified. claudia lannes works in sales."
    assert _already_public("the platform runs in Germany on STACKIT, so it stays in the EU. We are ISO 27001 certified.",
                           public + " eu")
    assert not _already_public("Our pilot price is 38,000 EUR and Jonas Klein owns the Salesforce instance.", public)


def test_silence_forces_channel_switch():
    from revel8_agent.ladder import check_draft, prompt, silent_streak

    steps = [{"touch": 6, "action": {"channel": "email"}, "events": [{"type": "reply", "body": "ok"}]},
             {"touch": 7, "action": {"channel": "email"}, "events": []},
             {"touch": 8, "action": {"channel": "email"}, "events": []}]
    assert silent_streak(steps) == (2, "email")
    assert "WENT SILENT" in prompt(steps, [])
    same = {"kind": "message", "channel": "email", "paragraphs": ["Which tool do you use for this?"]}
    assert check_draft(steps, [], same, "")
    other = {"kind": "message", "channel": "linkedin_message", "paragraphs": ["Which tool do you use for this?"]}
    assert check_draft(steps, [], other, "") == []
    assert check_draft(steps, [], {"kind": "call", "channel": "phone_call"}, "") == []


def test_text_in_body_request_is_not_an_attachment_request():
    from revel8_agent.demands import check_draft, extract

    steps = [{"touch": 4, "payload": {"body": "x"}, "events": [{"type": "reply", "body":
              "I haven't opened the attachment, so please keep the final text in the email body."}]}]
    assert [d["kind"] for d in extract(steps) if d["kind"] in ("artifact", "inline")] == ["inline"]
    with_file = {"kind": "message", "attachment_filename": "final.pdf", "paragraphs": ["see attached"]}
    assert check_draft(steps, with_file, "")
    inline = {"kind": "message", "paragraphs": [" ".join(["word"] * 45)]}
    assert check_draft(steps, inline, "") == []
