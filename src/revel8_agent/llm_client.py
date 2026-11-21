"""Client for a local OpenAI-compatible chat endpoint."""

import os
import time
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
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        load_dotenv()
        if base_url is None:
            base_url = os.getenv("LLM_BASE_URL") or os.getenv("LOCAL_LLM_BASE_URL", "")
        if model is None:
            model = os.getenv("LLM_MODEL") or os.getenv("LOCAL_LLM_MODEL", "")
        if api_key is None:
            api_key = os.getenv("LLM_API_KEY", "")
        base_url, self.model, api_key = base_url.strip(), model.strip(), api_key.strip()
        if not base_url or not self.model:
            raise LocalLLMError("Set LLM_BASE_URL and LLM_MODEL (or the LOCAL_LLM_* variants).")

        try:
            url = httpx.URL(base_url)
        except httpx.InvalidURL:
            raise LocalLLMError("LOCAL_LLM_BASE_URL must be an HTTP(S) URL.") from None
        if not url.host or url.scheme not in {"http", "https"} or url.query or url.fragment:
            raise LocalLLMError("LOCAL_LLM_BASE_URL must be an HTTP(S) URL.")

        path = url.path.rstrip("/")
        if not path.endswith("/v1"):
            path += "/v1"
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.Client(base_url=url.copy_with(path=path), timeout=timeout, headers=headers)

    def __enter__(self) -> "LocalLLMClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    @overload
    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        json_mode: Literal[False] = False,
        temperature: float | None = None,
    ) -> str: ...

    @overload
    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        json_mode: bool,
        temperature: float | None = None,
    ) -> JsonValue: ...

    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> JsonValue:
        payload: dict[str, JsonValue] = {"model": self.model, "messages": list(messages)}
        if temperature is not None:
            payload["temperature"] = temperature
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        for attempt in range(3):
            try:
                response = self._client.post("chat/completions", json=payload)
            except httpx.TimeoutException:
                raise LocalLLMError("Local LLM request timed out.") from None
            except httpx.RequestError:
                raise LocalLLMError("Local LLM request failed.") from None
            if response.status_code not in {429, 502, 503, 504} or attempt == 2:
                break
            time.sleep(2 * (attempt + 1))
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
        content = _strip_fences(content)
        try:
            return _JSON.validate_json(content, strict=True)
        except ValidationError:
            raise LocalLLMError("Local LLM returned invalid JSON content.") from None


def _strip_fences(content: str) -> str:
    text = content.strip()
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1].strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text.strip()
