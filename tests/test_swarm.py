"""Tests for the swarm coordinator's key assignment and parallelism bounds."""

import pytest

from revel8_agent.swarm import REVEL8_PARALLEL_CAP, Task, assign_keys, load_keys, parallelism


def test_assign_keys_round_robin():
    assert assign_keys(3, ["k0", "k1"]) == ["k0", "k1", "k0"]
    assert assign_keys(4, ["a", "b", "c", "d"]) == ["a", "b", "c", "d"]
    assert assign_keys(0, ["k0"]) == []


def test_assign_keys_requires_keys():
    with pytest.raises(ValueError):
        assign_keys(2, [])


def test_parallelism_bounded_by_tasks_keys_and_cap():
    assert parallelism(3, 4) == 3            # fewer tasks than keys
    assert parallelism(10, 4) == 4           # bounded by keys
    assert parallelism(10, 8) == REVEL8_PARALLEL_CAP   # bounded by API cap (6)
    assert parallelism(3, 4, requested=2) == 2         # explicit cap honoured
    assert parallelism(5, 1) == 1            # single key
    assert parallelism(10, 8, requested=99) == REVEL8_PARALLEL_CAP  # never exceeds 6


def test_load_keys_parses_comma_list(monkeypatch):
    monkeypatch.setattr("revel8_agent.swarm.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("LLM_API_KEYS", " a, b ,c ,")
    assert load_keys() == ["a", "b", "c"]


def test_load_keys_falls_back_to_single(monkeypatch):
    monkeypatch.setattr("revel8_agent.swarm.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("LLM_API_KEYS", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "solo")
    assert load_keys() == ["solo"]


def test_task_defaults():
    t = Task(target="julius")
    assert t.scenario == "practice" and t.touches == 10 and not t.keep_going
