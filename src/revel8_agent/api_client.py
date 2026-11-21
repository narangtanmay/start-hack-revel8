"""Client for the Revel8 Target API."""

import os
from pathlib import Path
from time import sleep
from urllib.parse import quote
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from pydantic import JsonValue, TypeAdapter, ValidationError

type JSONObject = dict[str, JsonValue]
type JSONArray = list[JsonValue]

_OBJECT = TypeAdapter(JSONObject)
_ARRAY = TypeAdapter(JSONArray)
_ARRAY_OR_OBJECT = TypeAdapter(JSONArray | JSONObject)
_RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})
_MAX_RETRIES = 3


class Revel8APIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class Revel8Client:
    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        load_dotenv()
        base_url = (base_url if base_url is not None else os.getenv("REVEL8_API_BASE", "")).strip()
        api_key = (api_key if api_key is not None else os.getenv("REVEL8_API_KEY", "")).strip()
        if not base_url or not api_key:
            raise Revel8APIError("Set REVEL8_API_BASE and REVEL8_API_KEY.")
        if any(not 33 <= ord(character) <= 126 for character in api_key):
            raise Revel8APIError("REVEL8_API_KEY contains invalid characters.")

        try:
            url = httpx.URL(base_url)
        except httpx.InvalidURL:
            raise Revel8APIError("REVEL8_API_BASE must be an HTTP(S) API URL.") from None
        if (
            not url.host
            or url.scheme not in {"http", "https"}
            or url.userinfo
            or url.query
            or url.fragment
        ):
            raise Revel8APIError("REVEL8_API_BASE must be an HTTP(S) API URL.")

        self._client = httpx.Client(
            base_url=url,
            timeout=120.0,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        )

    def __enter__(self) -> "Revel8Client":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _request[T](
        self,
        method: str,
        path: str,
        schema: TypeAdapter[T],
        *,
        json_body: JSONObject | None = None,
        files: dict[str, object] | None = None,
        idempotent: bool = False,
        idempotency_key: str | None = None,
    ) -> T:
        headers: dict[str, str] = {}
        if idempotent:
            headers["Idempotency-Key"] = idempotency_key or str(uuid4())
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = self._client.request(method, path, json=json_body, files=files, headers=headers or None)
            except httpx.TimeoutException:
                if attempt == _MAX_RETRIES:
                    raise Revel8APIError("Revel8 API request timed out.") from None
            except httpx.RequestError:
                raise Revel8APIError("Revel8 API request failed.") from None
            else:
                if response.is_success:
                    try:
                        return schema.validate_json(response.content, strict=True)
                    except ValidationError:
                        raise Revel8APIError("Revel8 API returned unexpected JSON.") from None
                if response.status_code not in _RETRYABLE_STATUS_CODES or attempt == _MAX_RETRIES:
                    raise Revel8APIError(
                        f"Revel8 API returned HTTP {response.status_code}.",
                        status_code=response.status_code,
                    )

            sleep(2**attempt)

        raise AssertionError("Unreachable retry state")

    def _get[T](self, path: str, schema: TypeAdapter[T]) -> T:
        return self._request("GET", path, schema)

    def get_scenarios(self) -> JSONArray:
        return self._get("scenarios", _ARRAY)

    def get_channels(self) -> JSONArray | JSONObject:
        return self._get("channels", _ARRAY_OR_OBJECT)

    def get_session(self, session_id: str) -> JSONObject:
        return self._get(f"sessions/{_path_segment(session_id)}", _OBJECT)

    def list_sessions(self) -> JSONArray | JSONObject:
        return self._get("sessions", _ARRAY_OR_OBJECT)

    def get_session_events(self, session_id: str) -> JSONObject:
        return self._get(f"sessions/{_path_segment(session_id)}/events", _OBJECT)

    def create_session(self, scenario_id: str = "practice") -> JSONObject:
        return self._request("POST", "sessions", _OBJECT, json_body={"scenario_id": scenario_id})

    def end_session(self, session_id: str) -> JSONObject:
        return self._request("POST", f"sessions/{_path_segment(session_id)}/end", _OBJECT)

    def upload_asset(self, file_path: str | Path) -> JSONObject:
        p = Path(file_path)
        with p.open("rb") as fh:
            return self._request("POST", "assets", _OBJECT, files={"file": (p.name, fh)})

    def register_page(self, session_id: str, payload: JSONObject) -> JSONObject:
        return self._request("POST", f"sessions/{_path_segment(session_id)}/pages", _OBJECT, json_body=payload)

    def send_message(self, session_id: str, payload: JSONObject, *, idempotency_key: str | None = None) -> JSONObject:
        return self._request(
            "POST",
            f"sessions/{_path_segment(session_id)}/messages",
            _OBJECT,
            json_body=payload,
            idempotent=True,
            idempotency_key=idempotency_key,
        )

    def start_conversation(self, session_id: str, payload: JSONObject, *, idempotency_key: str | None = None) -> JSONObject:
        return self._request(
            "POST",
            f"sessions/{_path_segment(session_id)}/conversations",
            _OBJECT,
            json_body=payload,
            idempotent=True,
            idempotency_key=idempotency_key,
        )

    def send_turn(self, conversation_id: str, payload: JSONObject, *, idempotency_key: str | None = None) -> JSONObject:
        return self._request(
            "POST",
            f"conversations/{_path_segment(conversation_id)}/turns",
            _OBJECT,
            json_body=payload,
            idempotent=True,
            idempotency_key=idempotency_key,
        )

    def end_conversation(self, conversation_id: str) -> JSONObject:
        return self._request("POST", f"conversations/{_path_segment(conversation_id)}/end", _OBJECT)


def _path_segment(value: str) -> str:
    if not value or value in {".", ".."}:
        raise Revel8APIError("A valid session ID is required.")
    return quote(value, safe="")
