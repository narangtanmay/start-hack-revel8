from revel8_agent.demands import check_draft, ledger, prompt


def _steps():
    return [
        {"touch": 1, "payload": {"channel": "email", "body": "Hi Julius, near miss in finance..."},
         "events": [{"type": "reply", "body": "Yes, please send the requirements profile. "
                                             "Roughly how many people are in finance and claims? Please copy Claudia."}]},
    ]


def test_extracts_artifact_question_and_include():
    kinds = {d["kind"] for d in ledger(_steps())}
    assert {"artifact", "question", "include"} <= kinds
    assert all(d["status"] == "open" for d in ledger(_steps()))
    assert "OPEN DEMANDS" in prompt(_steps())


def test_draft_missing_artifact_and_person_is_blocked():
    errs = check_draft(_steps(), {"channel": "email", "paragraphs": ["Finance and claims are about 36 people."]}, "")
    assert errs and "[artifact]" in errs[0] and "[include]" in errs[0] and "[question]" not in errs[0]


def test_complete_draft_passes_and_later_touch_marks_met():
    a = {"channel": "email", "attachment_filename": "Profile.pdf",
         "paragraphs": ["Attached is the profile. Finance and claims together are about 36 people. I have copied Claudia."]}
    assert check_draft(_steps(), a, "") == []
    steps = _steps() + [{"touch": 2, "payload": {"channel": "email", "attachments": [{"filename": "Profile.pdf"}],
                                                  "body": " ".join(a["paragraphs"])}, "events": []}]
    assert all(d["status"] == "met" for d in ledger(steps))


def test_refused_attachments_not_forced_and_calls_skip():
    st = _steps()
    assert not any("[artifact]" in e for e in check_draft(st, {"channel": "email", "paragraphs": ["Claudia"]}, "", {"attachments"}))
    assert check_draft(st, {"kind": "conversation"}, "") == []
