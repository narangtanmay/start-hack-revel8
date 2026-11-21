"""Client for a local OpenAI-compatible chat endpoint."""

import itertools
import json
import re
import os
import threading
import time
from collections import deque
from collections.abc import Sequence
from typing import Literal, TypedDict, overload

import httpx
from dotenv import load_dotenv
from pydantic import JsonValue, TypeAdapter, ValidationError


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class LocalLLMError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


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
        raw_max_tokens = os.getenv("LLM_MAX_TOKENS", "").strip()
        self.max_tokens: int | None = int(raw_max_tokens) if raw_max_tokens.isdigit() and int(raw_max_tokens) > 0 else None
        self.reasoning_effort: str | None = os.getenv("LLM_REASONING_EFFORT", "").strip() or None
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
        # add /v1 only when the URL carries no API version (Gemini's OpenAI endpoint is /v1beta/openai)
        if not re.search(r"/v\d+(?:beta|alpha)?\d*(?:/|$)", path + "/"):
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
        retry_rate_limit: bool = True,
        reasoning: str | None = None,
    ) -> str: ...

    @overload
    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        json_mode: bool,
        temperature: float | None = None,
        deadline: float | None = None,
        retry_rate_limit: bool = True,
        reasoning: str | None = None,
    ) -> JsonValue: ...

    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        json_mode: bool = False,
        temperature: float | None = None,
        deadline: float | None = None,
        retry_rate_limit: bool = True,
        reasoning: str | None = None,
    ) -> JsonValue:
        """`reasoning`: reasoning_effort for this call ("none" | "low" | "high"); Token Factory's DeepSeek runs without
        thinking unless asked (measured 2026-11-22), so judgement calls request "high". LLM_REASONING_DEFAULT
        overrides calls that pass nothing. `deadline` (a time.monotonic() value) bounds the whole call, for research's time budget.
        One call on LLM_MODEL; on a model-side failure (invalid/empty JSON, 5xx, timeout) retry once on
        LLM_FALLBACK_MODEL if set, so one bad generation never costs the agent a touch."""
        try:
            return self._chat_once(messages, json_mode=json_mode, temperature=temperature,
                                   model=self.model, extra=self.extra_body, deadline=deadline,
                                   retry_rate_limit=retry_rate_limit, reasoning=reasoning)
        except LocalLLMError as error:
            fallback = os.getenv("LLM_FALLBACK_MODEL", "").strip()
            if (not fallback or fallback == self.model or error.status_code in (400, 401, 403, 404, 429)
                    or (deadline is not None and time.monotonic() >= deadline)):
                raise
            extra_raw = os.getenv("LLM_FALLBACK_EXTRA_BODY", "").strip()
            try:
                extra = json.loads(extra_raw) if extra_raw else {}
            except ValueError:
                extra = {}
            self.fallbacks_used = getattr(self, "fallbacks_used", 0) + 1
            return self._chat_once(messages, json_mode=json_mode, temperature=temperature,
                                   model=fallback, extra=extra if isinstance(extra, dict) else {}, deadline=deadline,
                                   retry_rate_limit=retry_rate_limit, reasoning=reasoning)

    def _chat_once(
        self,
        messages: Sequence[ChatMessage],
        *,
        json_mode: bool,
        temperature: float | None,
        model: str,
        extra: dict,
        deadline: float | None = None,
        retry_rate_limit: bool = True,
        reasoning: str | None = None,
    ) -> JsonValue:
        payload: dict[str, JsonValue] = {**extra, "model": model, "messages": list(messages)}
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        # per-call effort (judgement calls ask "high") > LLM_REASONING_EFFORT > LLM_REASONING_DEFAULT
        effort = reasoning or self.reasoning_effort or os.getenv("LLM_REASONING_DEFAULT", "").strip() or None
        if effort and os.getenv("LLM_REASONING", "1") == "1":
            payload["reasoning_effort"] = effort
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
            retry_after = response.headers.get("retry-after", "")
            hinted = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else None
            if response.status_code not in {429, 502, 503, 504} or last:
                break
            if response.status_code == 429 and not retry_rate_limit:
                break  # the pool moves this call to another key instead of sleeping on this one
            if n > 1 and (attempt + 1) % n:
                continue  # fail over to the next endpoint right away; back off once all were tried
            delay = hinted if hinted is not None else min(30.0, 2.0 * 2**attempt)
            if deadline is not None and time.monotonic() + delay >= deadline:
                break  # no time for another attempt: report this response
            time.sleep(delay)
        if not response.is_success:
            raise LocalLLMError(
                f"Local LLM returned HTTP {response.status_code}.",
                status_code=response.status_code,
                retry_after=hinted,
            )

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, TypeError, IndexError, KeyError):
            raise LocalLLMError("Local LLM returned an invalid chat response.") from None
        if not isinstance(content, str):
            raise LocalLLMError("Local LLM returned an invalid chat response.")

        if not json_mode:
            return content
        finish = (response.json()["choices"][0] or {}).get("finish_reason")
        if finish == "length":
            raise LocalLLMError("Local LLM output was cut off (finish_reason=length): JSON incomplete.")
        if not content.strip():
            # DeepSeek JSON mode replaces non-JSON output with blanks: treat as a failed generation and retry
            raise LocalLLMError("Local LLM returned blank content in JSON mode.")
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


class KeyLimiter:
    """Sliding-window request limiter for one API key, plus a cooldown set by the server's 429s.

    Token Factory allows LLM_RPM_PER_KEY (default 20) requests per minute per key. We stay a little under it
    so the server never has to say no.
    """

    def __init__(self, rpm: int, window: float = 60.0) -> None:
        self.rpm, self.window = rpm, window
        self.sent: deque[float] = deque()
        self.cooldown_until = 0.0
        self.inflight = 0
        self.calls = self.rate_limited = self.errors = 0

    def wait(self, now: float) -> float:
        """Seconds until this key may take another request (0 = now)."""
        while self.sent and now - self.sent[0] >= self.window:
            self.sent.popleft()
        w = max(0.0, self.cooldown_until - now)
        if len(self.sent) >= self.rpm:
            w = max(w, self.sent[0] + self.window - now)
        return w


class LLMPool:
    """All Token Factory keys behind one scheduler.

    Each key is limited to ~20 requests/minute by the server (not by GPU capacity: the backend serves many
    requests at once). The pool sends every call to a key that has room in its window right now, preferring
    the caller's lane, so N keys give N x 20 requests/minute in parallel. A 429 parks that key until its
    retry-after and the call moves to another key at once; a thread only waits when every key is full.
    """

    def __init__(self, timeout: float = 90.0, model: str | None = None, rpm_per_key: int | None = None,
                 max_wait: float = 240.0, keys: list[str] | None = None) -> None:
        resolved_keys = [k.strip() for k in keys if k.strip()] if keys is not None else api_keys_from_env()
        resolved_keys = resolved_keys or [""]
        self.clients = [LocalLLMClient(api_key=k, timeout=timeout, model=model) for k in resolved_keys]
        self.model = self.clients[0].model
        rpm = rpm_per_key or int(os.getenv("LLM_RPM_PER_KEY", "18"))
        self.limits = [KeyLimiter(rpm) for _ in resolved_keys]
        self.max_wait = max_wait
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self.clients)

    def lane(self, i: int) -> "PooledClient":
        return PooledClient(self, i % len(self.clients))

    def close(self) -> None:
        for c in self.clients:
            c.close()

    def stats(self) -> list[dict]:
        return [{"key": i, "calls": L.calls, "rate_limited": L.rate_limited, "errors": L.errors}
                for i, L in enumerate(self.limits)]

    def _acquire(self, preferred: int, avoid: set[int]) -> tuple[int, float]:
        """Reserve a slot: (key index, 0) or (-1, seconds to wait before asking again)."""
        n = len(self.clients)
        with self._lock:
            now = time.monotonic()
            order = [(preferred + k) % n for k in range(n)]
            candidates = [i for i in order if i not in avoid] or order
            ready = [i for i in candidates if self.limits[i].wait(now) == 0.0]
            if ready:
                # preferred lane if it has room, else the key with the most room left in its window
                i = ready[0] if ready[0] == preferred else min(ready, key=lambda j: (len(self.limits[j].sent), self.limits[j].inflight))
                L = self.limits[i]
                L.sent.append(now)
                L.inflight += 1
                L.calls += 1
                return i, 0.0
            return -1, min(self.limits[i].wait(now) for i in candidates)

    def _release(self, i: int, error: LocalLLMError | None) -> None:
        with self._lock:
            L = self.limits[i]
            L.inflight -= 1
            if error is None:
                return
            if error.status_code == 429:
                L.rate_limited += 1
                L.cooldown_until = max(L.cooldown_until, time.monotonic() + (error.retry_after or 5.0))
            else:
                L.errors += 1
                if error.status_code in (500, 502, 503, 504):
                    L.cooldown_until = max(L.cooldown_until, time.monotonic() + 2.0)

    def chat(self, preferred: int, messages: Sequence[ChatMessage], *, json_mode: bool = False,
             temperature: float | None = None, deadline: float | None = None,
             reasoning: str | None = None) -> JsonValue:
        """`deadline` (time.monotonic()) is the caller's hard budget (research); otherwise max_wait applies."""
        call_deadline = deadline
        deadline = time.monotonic() + self.max_wait if deadline is None else min(deadline, time.monotonic() + self.max_wait)
        tried: set[int] = set()
        last: LocalLLMError | None = None
        failures = 0  # non-rate-limit failures (timeouts, 5xx, bad JSON): one try per key, as before
        while True:
            i, wait = self._acquire(preferred, tried)
            if i < 0:
                if time.monotonic() + wait > deadline:
                    raise last or LocalLLMError("All LLM keys are rate-limited.", status_code=429)
                time.sleep(min(wait, 5.0) + 0.05)
                tried.clear()  # windows moved on: every key is a candidate again
                continue
            try:
                extra = {} if call_deadline is None else {"deadline": call_deadline}
                out = self.clients[i].chat(messages, json_mode=json_mode, temperature=temperature,
                                           retry_rate_limit=False, reasoning=reasoning, **extra)
            except LocalLLMError as error:
                self._release(i, error)
                last = error
                if error.status_code not in (None, 429, 500, 502, 503, 504):
                    raise  # a real request problem: another key will not fix it
                tried.add(i)
                if error.status_code != 429:
                    failures += 1
                if failures >= len(self.clients) or time.monotonic() > deadline:
                    raise
                continue
            self._release(i, None)
            return out


class PooledClient:
    """Drop-in for LocalLLMClient.chat(): a lane prefers one key but uses any key with room."""

    def __init__(self, pool: LLMPool, preferred: int) -> None:
        self.pool, self.preferred = pool, preferred
        self.model = pool.model

    def chat(self, messages: Sequence[ChatMessage], *, json_mode: bool = False,
             temperature: float | None = None, deadline: float | None = None,
             reasoning: str | None = None) -> JsonValue:
        return self.pool.chat(self.preferred, messages, json_mode=json_mode, temperature=temperature,
                              deadline=deadline, reasoning=reasoning)


def _strip_fences(content: str) -> str:
    text = content.strip()
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1].strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text.strip()
