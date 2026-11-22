from revel8_agent.memory import _rates, archetype, merge_playbook, playbook_prompt, role_family


def test_sender_role_beats_story_words():
    assert archetype("Head of IT Security at Broker", "met you at the conference") == "customer/prospect"
    assert archetype("", "I organise the summit speakers") == "event organiser"


def test_role_family_is_name_free():
    assert role_family("Co-Founder & Co-CEO (business and go-to-market)") == "sales/bd"
    assert role_family("Head of Accounts Payable") == "finance"
    assert role_family("Office Assistant") == "operations/assistant"


def test_win_rate_ranks_wins_over_replies_and_shrinks_small_samples():
    chatty = _rates({"runs": 20, "touches": 120, "replies": 110, "brushoffs": 0, "incidents_api": 0, "runs_won": 0})
    winner = _rates({"runs": 8, "touches": 42, "replies": 30, "brushoffs": 2, "incidents_api": 1, "runs_won": 1})
    once = _rates({"runs": 1, "touches": 6, "replies": 2, "brushoffs": 0, "incidents_api": 0, "runs_won": 0})
    assert winner["win_rate"] > once["win_rate"] > chatty["win_rate"]


def test_merge_never_loses_evidence():
    old = {"archetypes": {"x": {"runs": 8, "touches": 42, "replies": 30, "brushoffs": 1, "incidents_api": 1}},
           "mechanisms": [{"run": "a", "target": "t"}]}
    new = {"archetypes": {"x": {"runs": 1, "touches": 5, "replies": 3, "brushoffs": 0, "incidents_api": 0, "runs_won": 0}},
           "mechanisms": [{"run": "b", "target": "u"}]}
    m = merge_playbook(new, old)
    assert m["archetypes"]["x"]["touches"] == 42 and {x["run"] for x in m["mechanisms"]} == {"a", "b"}


def test_prompt_puts_same_role_family_first():
    pb = {"archetypes": {"customer/prospect": {"runs": 8, "touches": 42, "replies": 30, "brushoffs": 2, "incidents_api": 1, "runs_won": 1}},
          "mechanisms": [
              {"run": "1", "sender": "researcher/student", "target_family": "product/marketing", "artifact": "link to registered page", "touch": 3, "objective": "credentials", "they_asked_first": False},
              {"run": "2", "sender": "customer/prospect", "target_family": "finance", "artifact": "pdf", "touch": 4, "objective": "action", "they_asked_first": True}]}
    txt = playbook_prompt(pb, target_role="Head of Finance")
    assert txt.index("-> finance target") < txt.index("-> product/marketing target")
    assert "never the facts" in txt
