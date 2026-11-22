from revel8_agent.model_strategy import choose_model, situation

_UPCOMING = {"hooks": [{"id": "theme", "timing": "undated", "confidence": 0.9},
                       {"id": "talk", "timing": "upcoming", "confidence": 0.5}]}
_THEMES = {"hooks": [{"id": "theme", "timing": "undated", "confidence": 0.9}]}


def test_situation_follows_the_upcoming_hook_like_the_policy() -> None:
    assert situation(_UPCOMING, {"hook_id": "theme", "objective": "disclosure"})[0] == "portal"
    assert situation(_THEMES, {"hook_id": "theme", "objective": "disclosure"})[0] == "conversation"
    assert situation(_THEMES, {"hook_id": "theme", "objective": "credentials"})[0] == "portal"


def test_choose_model_is_off_by_default_and_configurable(monkeypatch) -> None:
    monkeypatch.delenv("MODEL_STRATEGY", raising=False)
    assert choose_model(_UPCOMING, {"hook_id": "talk"}) is None
    monkeypatch.setenv("MODEL_STRATEGY", "1")
    portal = choose_model(_UPCOMING, {"hook_id": "talk"})
    assert portal["model"] == "DeepSeek-V4.1-Flash" and portal["extra_body"] == {}
    convo = choose_model(_THEMES, {"hook_id": "theme", "objective": "disclosure"})
    assert convo["model"] == "Qwen3.8-27B" and convo["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
    monkeypatch.setenv("MODEL_CONVERSATION", "other-model")
    assert choose_model(_THEMES, {"hook_id": "theme"})["model"] == "other-model"


def test_pool_set_model_switches_every_key(monkeypatch) -> None:
    from revel8_agent.llm_client import LLMPool

    monkeypatch.setenv("LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("LLM_MODEL", "first")
    pool = LLMPool(keys=["a", "b"])
    lane = pool.lane(0)
    lane.set_model("second", {"x": 1})
    assert {c.model for c in pool.clients} == {"second"} and all(c.extra_body == {"x": 1} for c in pool.clients)
