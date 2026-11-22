import json
from pathlib import Path

from revel8_agent.memory import TargetMemory, extract_thread, memory_dir



def _state(win=True):
    steps = [
        {"touch": 1, "action": {"channel": "email", "subject": "Deepfake question"},
         "payload": {"channel": "email", "body": "<p>Hi Julius, near-miss in finance...</p>"},
         "events": [{"type": "reply", "body": "Yes, please send the requirements profile. How many people are in finance?"}]},
        {"touch": 2, "action": {"channel": "email", "attachment_filename": "Invite_0930.ics"},
         "payload": {"channel": "email", "body": "Invite attached.", "attachments": [{"filename": "Invite_0930.ics"}]},
         "events": ([{"type": "attachment.opened", "filename": "Invite_0930.ics"}] if win else [])},
        {"touch": 3, "action": {"channel": "email"}, "attempts": [], "events": []},  # unsent error step
    ]
    return {"run_id": "r1", "started_at": "x", "config": {"scenario_id": "practice"},
            "plan": {"hook_id": "h1", "pretext": "prospect", "persona": {"role": "Head of IT Security", "organisation": "Broker"}},
            "steps": steps,
            "incidents": ([{"touch": 2, "type": "credentials", "source": "api event"}] if win else [])}


def test_tests_never_write_real_memory():
    assert "memory" != str(memory_dir())  # conftest isolates REVEL8_MEMORY_DIR


def test_extract_thread_skips_unsent_and_captures_questions_asks_artifact():
    th = extract_thread(_state())
    assert [t["touch"] for t in th] == [1, 2]
    assert th[0]["we"].startswith("Hi Julius")
    assert any("finance" in q for q in th[0]["their_questions"])
    assert any("requirements profile" in a for a in th[0]["their_asks"])
    assert th[1]["artifact"] == "Invite_0930.ics" and th[1]["api_event"] == "attachment.opened"


def test_deja_vu_replays_win_compressed():
    m = TargetMemory("Julius Muth")
    m.learn_from_run(_state(win=True))
    m.save()
    again = TargetMemory("Julius Muth")
    txt = again.prompt()
    assert "YOU ALREADY WON THIS PERSON" in txt and "touch 2" in txt
    assert "Invite_0930.ics" in again.deja_vu_hint(2)


def test_deja_vu_without_win_uses_closest_thread():
    m = TargetMemory("Robert Seilbeck")
    m.learn_from_run(_state(win=False))
    assert "CLOSEST EARLIER THREAD" in m.deja_vu()
    assert "requirements profile" in m.deja_vu_hint(1)


def test_empty_memory_is_silent():
    assert TargetMemory("Nobody").deja_vu() == ""


def test_scoring_update_open_is_not_a_win():
    from revel8_agent.memory import is_confirmed_win, is_win
    opened = {"touch": 3, "type": "opened", "source": "api event (engagement)"}
    assert not is_win(opened) and not is_confirmed_win(opened)
    assert is_win({"type": "disclosure", "source": "llm-judge (estimate)"})
    assert is_confirmed_win({"type": "credentials", "source": "api event"})
    assert not is_confirmed_win({"type": "action", "source": "llm-judge (estimate)"})
