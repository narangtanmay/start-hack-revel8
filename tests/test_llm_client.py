import json

import pytest
import respx

from revel8_agent.llm_client import ChatMessage, LocalLLMClient, LocalLLMError

BASE = "http://llm.example.test"
MESSAGES: list[ChatMessage] = [{"role": "user", "content": "Summarize workshop check-in logistics."}]


@pytest.mark.parametrize("suffix", ["", "/v1/"])
@pytest.mark.parametrize("json_mode_env", [None, "0"], ids=["default", "disabled"])
@respx.mock
def test_chat_json_mode(suffix: str, json_mode_env: str | None, monkeypatch: pytest.MonkeyPatch) -> None:
    if json_mode_env is None:
        monkeypatch.delenv("LLM_JSON_MODE", raising=False)
    else:
        monkeypatch.setenv("LLM_JSON_MODE", json_mode_env)
    route = respx.post(f"{BASE}/v1/chat/completions").respond(
        json={"choices": [{"message": {"content": '{"check_in": "09:00"}'}}]}
    )
    with LocalLLMClient(BASE + suffix, "workshop-model") as client:
        assert client.chat(MESSAGES, json_mode=True) == {"check_in": "09:00"}
    expected = {"model": "workshop-model", "messages": MESSAGES}
    if json_mode_env is None:
        expected["response_format"] = {"type": "json_object"}
    assert json.loads(route.calls.last.request.content) == expected


@respx.mock
def test_chat_plain_text_and_invalid_json() -> None:
    respx.post(f"{BASE}/v1/chat/completions").respond(
        json={"choices": [{"message": {"content": "Check-in opens at 9 a.m."}}]}
    )
    with LocalLLMClient(BASE, "workshop-model") as client:
        assert client.chat(MESSAGES) == "Check-in opens at 9 a.m."
        with pytest.raises(LocalLLMError, match="invalid JSON content"):
            client.chat(MESSAGES, json_mode=True)


def test_fallback_model_used_on_invalid_json(monkeypatch):
    import httpx
    import respx

    from revel8_agent.llm_client import LocalLLMClient

    monkeypatch.setenv("LLM_FALLBACK_MODEL", "backup-model")
    calls = []

    def handler(request):
        body = __import__("json").loads(request.content)
        calls.append(body["model"])
        content = "not json" if body["model"] == "main-model" else '{"ok": true}'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    with respx.mock:
        respx.post("http://llm.test/v1/chat/completions").mock(side_effect=handler)
        client = LocalLLMClient(base_url="http://llm.test", model="main-model", api_key="k")
        out = client.chat([{"role": "user", "content": "hi"}], json_mode=True)
    assert out == {"ok": True}
    assert calls == ["main-model", "backup-model"]


def test_no_fallback_on_bad_request(monkeypatch):
    import httpx
    import pytest
    import respx

    from revel8_agent.llm_client import LocalLLMClient, LocalLLMError

    monkeypatch.setenv("LLM_FALLBACK_MODEL", "backup-model")
    with respx.mock:
        route = respx.post("http://llm.test/v1/chat/completions").mock(return_value=httpx.Response(400, json={}))
        client = LocalLLMClient(base_url="http://llm.test", model="main-model", api_key="k")
        with pytest.raises(LocalLLMError):
            client.chat([{"role": "user", "content": "hi"}])
    assert route.call_count == 1


def test_reasoning_effort_sent_and_blank_json_retried_on_fallback(monkeypatch):
    import json as _json

    import httpx
    import respx

    from revel8_agent.llm_client import LocalLLMClient

    monkeypatch.setenv("LLM_FALLBACK_MODEL", "backup")
    seen = []

    def handler(request):
        body = _json.loads(request.content)
        seen.append((body["model"], body.get("reasoning_effort")))
        content = "   " if body["model"] == "main" else '{"ok": 1}'   # DeepSeek JSON mode blanks non-JSON output
        return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})

    with respx.mock:
        respx.post("http://llm.test/v1/chat/completions").mock(side_effect=handler)
        c = LocalLLMClient(base_url="http://llm.test", model="main", api_key="k")
        assert c.chat([{"role": "user", "content": "json please"}], json_mode=True, reasoning="high") == {"ok": 1}
    assert seen == [("main", "high"), ("backup", "high")]
