"""Client for a local OpenAI-compatible chat endpoint."""

import itertools
import json
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
_ROTATION = itertools.count()


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
            api_key = os.getenv("LLM_API_KEYS") or os.getenv("LLM_API_KEY", "")
        # Several endpoints (e.g. multiple Token Factory links) may be given comma-separated in
        # LLM_BASE_URL, with one key each in LLM_API_KEY (or one key for all). Requests rotate
        # across them and fail over to the next on 429/5xx/timeouts.
        self.model = model.strip()
        # Optional extra request fields, e.g. LLM_EXTRA_BODY='{"chat_template_kwargs":{"enable_thinking":false}}'
        # for reasoning models (Qwen3.x) whose thinking otherwise runs past the gateway's 60 s cutoff.
        extra = os.getenv("LLM_EXTRA_BODY", "").strip()
        try:
            self.extra_body: dict = json.loads(extra) if extra else {}
        except ValueError:
            raise LocalLLMError("LLM_EXTRA_BODY must be a JSON object.") from None
        if not isinstance(self.extra_body, dict):
            raise LocalLLMError("LLM_EXTRA_BODY must be a JSON object.")
        urls =[u.strip() for u in base_url.split(",") if u.strip()]
        keys = [k.strip() for k in api_key.split(",")] if api_key.strip() else [""]
        if not urls or not self.model:
            raise LocalLLMError("Set LLM_BASE_URL and LLM_MODEL (or the LOCAL_LLM_* variants).")
        if len(urls) > 1 and len(keys) not in (1, len(urls)):
            raise LocalLLMError("LLM_API_KEY must hold one key, or one per LLM_BASE_URL entry.")
        # one URL + several keys (LLM_API_KEYS) -> one client per key on that URL
        n = max(len(urls), len(keys))
        self._clients = [self._make_client(urls[i % len(urls)], keys[i % len(keys)], timeout) for i in range(n)]
        self._client = self._clients[0]
        self._timeout = timeout

    @staticmethod
    def _make_client(base_url: str, api_key: str, timeout: float) -> httpx.Client:
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
        return httpx.Client(base_url=url.copy_with(path=path), timeout=timeout, headers=headers)

    def __enter__(self) -> "LocalLLMClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        for client in self._clients:
            client.close()

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
        """`deadline` (a time.monotonic() value) bounds the whole call, for research's time budget.
        One call on LLM_MODEL; on a model-side failure (invalid/empty JSON, 5xx, timeout) retry once on
        LLM_FALLBACK_MODEL if set, so one bad generation never costs the agent a touch."""
        try:
            return self._chat_once(messages, json_mode=json_mode, temperature=temperature,
                                   model=self.model, extra=self.extra_body, deadline=deadline)
        except LocalLLMError as error:
            fallback = os.getenv("LLM_FALLBACK_MODEL", "").strip()
            if (not fallback or fallback == self.model or error.status_code in (400, 401, 403, 404)
                    or (deadline is not None and time.monotonic() >= deadline)):
                raise
            extra_raw = os.getenv("LLM_FALLBACK_EXTRA_BODY", "").strip()
            try:
                extra = json.loads(extra_raw) if extra_raw else {}
            except ValueError:
                extra = {}
            self.fallbacks_used = getattr(self, "fallbacks_used", 0) + 1
            return self._chat_once(messages, json_mode=json_mode, temperature=temperature,
                                   model=fallback, extra=extra if isinstance(extra, dict) else {}, deadline=deadline)

    def _chat_once(
        self,
        messages: Sequence[ChatMessage],
        *,
        json_mode: bool,
        temperature: float | None,
        model: str,
        extra: dict,
        deadline: float | None = None,
    ) -> JsonValue:
        payload: dict[str, JsonValue] = {**extra, "model": model, "messages": list(messages)}
        if temperature is not None:
            payload["temperature"] = temperature
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        n = len(self._clients)
        start = next(_ROTATION)
        attempts = max(6, 2 * n)
        for attempt in range(attempts):
            client = self._clients[(start + attempt) % n]
            last = attempt == attempts - 1
            left = None if deadline is None else deadline - time.monotonic()
            if left is not None and left <= 0:
                raise LocalLLMError("Local LLM deadline reached.")
            try:
                response = client.post("chat/completions", json=payload,
                                       **({} if left is None else {"timeout": min(self._timeout, max(0.1, left))}))
            except httpx.TimeoutException:
                if n > 1 and not last:
                    continue
                raise LocalLLMError("Local LLM request timed out.") from None
            except httpx.RequestError:
                if n > 1 and not last:
                    continue
                raise LocalLLMError("Local LLM request failed.") from None
            if response.status_code not in {429, 502, 503, 504} or last:
                break
            if n > 1 and (attempt + 1) % n:
                continue  # fail over to the next endpoint right away; back off once all were tried
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
    """One client per API key (each key has its own rate limit). `lane(i)` prefers key i and falls back to
    the others when that key is rate-limited or failing, so parallel research lanes never queue on one key.
    (Ported from research v2, feat/osint-snowball.)"""

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
