"""Client for a local OpenAI-compatible chat endpoint."""

import os
from collections.abc import Sequence
from typing import Literal, TypedDict, overload

import httpx
from dotenv import load_dotenv
from pydantic import JsonValue, TypeAdapter, ValidationError


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class LocalLLMError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


_JSON = TypeAdapter(JsonValue)


class LocalLLMClient:
    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        load_dotenv()
        base_url = (base_url if base_url is not None else os.getenv("LOCAL_LLM_BASE_URL", "")).strip()
        self.model = (model if model is not None else os.getenv("LOCAL_LLM_MODEL", "")).strip()
        if not base_url or not self.model:
            raise LocalLLMError("Set LOCAL_LLM_BASE_URL and LOCAL_LLM_MODEL.")

        try:
            url = httpx.URL(base_url)
        except httpx.InvalidURL:
            raise LocalLLMError("LOCAL_LLM_BASE_URL must be an HTTP(S) URL.") from None
        if not url.host or url.scheme not in {"http", "https"} or url.query or url.fragment:
            raise LocalLLMError("LOCAL_LLM_BASE_URL must be an HTTP(S) URL.")

        path = url.path.rstrip("/")
        if not path.endswith("/v1"):
            path += "/v1"
        self._client = httpx.Client(base_url=url.copy_with(path=path), timeout=120.0)

    def __enter__(self) -> "LocalLLMClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    @overload
    def chat(self, messages: Sequence[ChatMessage], *, json_mode: Literal[False] = False) -> str: ...

    @overload
    def chat(self, messages: Sequence[ChatMessage], *, json_mode: bool) -> JsonValue: ...

    def chat(self, messages: Sequence[ChatMessage], *, json_mode: bool = False) -> JsonValue:
        payload = {"model": self.model, "messages": list(messages)}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            response = self._client.post("chat/completions", json=payload)
        except httpx.TimeoutException:
            raise LocalLLMError("Local LLM request timed out.") from None
        except httpx.RequestError:
            raise LocalLLMError("Local LLM request failed.") from None
        if not response.is_success:
            raise LocalLLMError(
                f"Local LLM returned HTTP {response.status_code}.",
                status_code=response.status_code,
            )

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, TypeError, IndexError, KeyError):
            raise LocalLLMError("Local LLM returned an invalid chat response.") from None
        if not isinstance(content, str):
            raise LocalLLMError("Local LLM returned an invalid chat response.")

        if not json_mode:
            return content
        try:
            return _JSON.validate_json(content, strict=True)
        except ValidationError:
            raise LocalLLMError("Local LLM returned invalid JSON content.") from None
