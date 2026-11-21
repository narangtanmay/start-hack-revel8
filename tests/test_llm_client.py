import json

import pytest
import respx

from revel8_agent.llm_client import ChatMessage, LocalLLMClient, LocalLLMError

BASE = "http://llm.example.test"
MESSAGES: list[ChatMessage] = [{"role": "user", "content": "Summarize workshop check-in logistics."}]


@pytest.mark.parametrize("suffix", ["", "/v1/"])
@respx.mock
def test_chat_json_mode(suffix: str) -> None:
    route = respx.post(f"{BASE}/v1/chat/completions").respond(
        json={"choices": [{"message": {"content": '{"check_in": "09:00"}'}}]}
    )
    with LocalLLMClient(BASE + suffix, "workshop-model") as client:
        assert client.chat(MESSAGES, json_mode=True) == {"check_in": "09:00"}
    assert json.loads(route.calls.last.request.content) == {
        "model": "workshop-model",
        "messages": MESSAGES,
        "response_format": {"type": "json_object"},
    }


@respx.mock
def test_chat_plain_text_and_invalid_json() -> None:
    respx.post(f"{BASE}/v1/chat/completions").respond(
        json={"choices": [{"message": {"content": "Check-in opens at 9 a.m."}}]}
    )
    with LocalLLMClient(BASE, "workshop-model") as client:
        assert client.chat(MESSAGES) == "Check-in opens at 9 a.m."
        with pytest.raises(LocalLLMError, match="invalid JSON content"):
            client.chat(MESSAGES, json_mode=True)


@respx.mock
def test_chat_stops_retrying_at_the_deadline() -> None:
    import time

    # Always rate-limited: without a deadline this retries 6 times with waits of 2, 4, 8, 16, 30 s.
    respx.post(f"{BASE}/v1/chat/completions").respond(status_code=429)
    with LocalLLMClient(BASE, "workshop-model") as client:
        t0 = time.monotonic()
        with pytest.raises(LocalLLMError):
            client.chat(MESSAGES, deadline=time.monotonic() + 1.0)
        assert time.monotonic() - t0 < 1.5
        with pytest.raises(LocalLLMError, match="deadline"):
            client.chat(MESSAGES, deadline=time.monotonic() - 1)  # already past: no request at all
