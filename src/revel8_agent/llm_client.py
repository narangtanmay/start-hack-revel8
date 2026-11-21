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
        self._timeout = timeout
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
        deadline: float | None = None,
    ) -> str: ...

    @overload
    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        json_mode: bool,
        temperature: float | None = None,
        deadline: float | None = None,
    ) -> JsonValue: ...

    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        json_mode: bool = False,
        temperature: float | None = None,
        deadline: float | None = None,
    ) -> JsonValue:
        """`deadline` (a time.monotonic() value) bounds the whole call: request timeouts and retry waits are
        cut to the time left, and no attempt starts after it. Used by research to keep its time budget."""
        payload: dict[str, JsonValue] = {"model": self.model, "messages": list(messages)}
        if temperature is not None:
            payload["temperature"] = temperature
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        for attempt in range(6):
            left = None if deadline is None else deadline - time.monotonic()
            if left is not None and left <= 0:
                raise LocalLLMError("Local LLM deadline reached.")
            try:
                response = self._client.post(
                    "chat/completions", json=payload,
                    **({} if left is None else {"timeout": min(self._timeout, max(0.1, left))}))
            except httpx.TimeoutException:
                raise LocalLLMError("Local LLM request timed out.") from None
            except httpx.RequestError:
                raise LocalLLMError("Local LLM request failed.") from None
            if response.status_code not in {429, 502, 503, 504} or attempt == 5:
                break
            retry_after = response.headers.get("retry-after", "")
            delay = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else min(30.0, 2.0 * 2**attempt)
            if deadline is not None and time.monotonic() + delay >= deadline:
                break  # no time for another attempt: report this response
            time.sleep(delay)
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


def api_keys_from_env() -> list[str]:
    """All Token Factory keys: LLM_API_KEYS (comma-separated) plus LLM_API_KEY, de-duplicated, in order."""
    load_dotenv()
    keys = [k.strip() for k in os.getenv("LLM_API_KEYS", "").split(",") if k.strip()]
    single = os.getenv("LLM_API_KEY", "").strip()
    if single:
        keys.insert(0, single)
    return list(dict.fromkeys(keys))


class LLMPool:
    """One client per API key (each key = one teammate's GPU quota).

    `lane(i)` returns a client that prefers key i and falls back to the other keys when that key is
    rate-limited or failing, so parallel research lanes never queue behind one key's limit.
    """

    def __init__(self, timeout: float = 90.0, model: str | None = None) -> None:
        keys = api_keys_from_env() or [""]
        self.clients = [LocalLLMClient(api_key=k, timeout=timeout, model=model) for k in keys]
        self.model = self.clients[0].model

    def __len__(self) -> int:
        return len(self.clients)

    def lane(self, i: int) -> "PooledClient":
        return PooledClient(self, i % len(self.clients))

    def close(self) -> None:
        for c in self.clients:
            c.close()


class PooledClient:
    """Drop-in for LocalLLMClient.chat(): tries its preferred key, then the others."""

    def __init__(self, pool: LLMPool, preferred: int) -> None:
        self.pool, self.preferred = pool, preferred
        self.model = pool.model

    def chat(self, messages: Sequence[ChatMessage], *, json_mode: bool = False,
             temperature: float | None = None, deadline: float | None = None) -> JsonValue:
        n = len(self.pool.clients)
        last: LocalLLMError | None = None
        for k in range(n):
            if deadline is not None and last is not None and time.monotonic() >= deadline:
                break  # out of time: do not fail over to another key
            client = self.pool.clients[(self.preferred + k) % n]
            try:
                return client.chat(messages, json_mode=json_mode, temperature=temperature, deadline=deadline)
            except LocalLLMError as error:
                last = error
                if error.status_code not in (None, 429, 500, 502, 503, 504):
                    break  # a real request problem: another key will not fix it
        assert last is not None
        raise last


def _strip_fences(content: str) -> str:
    text = content.strip()
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1].strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text.strip()
