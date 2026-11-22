from revel8_agent import council
from revel8_agent.council import CRITIC_SYS


def test_council_runs_lenses_in_parallel_and_critic_picks():
    seen = []

    def ask(system, user, temperature):
        if system == CRITIC_SYS:
            return {"best": 1, "why": "own angle is routine", "scores": []}
        seen.append(user.rsplit("LENS: ", 1)[1].split(".")[0])
        return {"hook_id": "h1", "objective": "disclosure", "pretext": user[-40:], "persona": {"name": "X"}}

    plan, log = council.convene(ask, "SYS", "USER", "profile", n=3)
    assert len(seen) == 3 and len(log["candidates"]) == 3
    assert log["picked"] == log["lenses"][1] and plan["hook_id"] == "h1"


def test_council_survives_failures_and_disable(monkeypatch):
    def ask(system, user, temperature):
        raise RuntimeError("endpoint down")

    assert council.convene(ask, "SYS", "USER", "p", n=3)[0] is None
    monkeypatch.setenv("REVEL8_COUNCIL", "0")
    assert council.size() == 0 and council.convene(ask, "S", "U", "p") == (None, {})
