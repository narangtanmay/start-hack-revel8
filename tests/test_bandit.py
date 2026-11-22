import random

from revel8_agent import bandit


PB = {"archetypes": {
    "event organiser": {"runs": 20, "runs_won": 0, "touches": 100, "replies": 40, "brushoffs": 5, "incidents_api": 0},
    "customer/prospect": {"runs": 10, "runs_won": 2, "touches": 50, "replies": 20, "brushoffs": 2, "incidents_api": 2,
                          "families": {"executive": {"runs": 4, "runs_won": 2}}},
    "thin": {"runs": 1, "runs_won": 1, "touches": 2, "replies": 1, "brushoffs": 0, "incidents_api": 1},
}}


def test_family_cell_borrows_from_archetype():
    arm = bandit._arms(PB)["customer/prospect"]
    a_exec, b_exec = bandit.posterior(arm, "executive")
    a_fin, b_fin = bandit.posterior(arm, "finance")
    assert a_exec / (a_exec + b_exec) > a_fin / (a_fin + b_fin) > 0


def test_thin_arms_excluded_and_winner_usually_sampled():
    rng = random.Random(0)
    picks = [bandit.sample_archetypes(PB, "Co-Founder & CEO", rng, sample=True)[0]["archetype"] for _ in range(300)]
    assert "thin" not in picks
    assert picks.count("customer/prospect") > picks.count("event organiser")
    assert "event organiser" in picks          # still explores


def test_rank_targets_and_disable(monkeypatch):
    ranked = bandit.rank_targets(PB, [{"id": "a", "role": "CEO"}, {"id": "b", "role": "Head of Finance"}],
                                 random.Random(1))
    assert {t["id"] for t in ranked} == {"a", "b"} and ranked[0]["draw"] >= ranked[1]["draw"]
    assert bandit.sample_archetypes({}, "CEO", random.Random()) == []
    monkeypatch.setenv("REVEL8_BANDIT", "0")
    assert not bandit.enabled()


def test_greedy_by_default_and_never_casts_other():
    pb = {"archetypes": {**PB["archetypes"],
                         "other": {"runs": 30, "runs_won": 9, "touches": 90, "replies": 9, "brushoffs": 0, "incidents_api": 9}}}
    picks = {bandit.sample_archetypes(pb, "CEO", random.Random(i))[0]["archetype"] for i in range(50)}
    assert picks == {"customer/prospect"}
