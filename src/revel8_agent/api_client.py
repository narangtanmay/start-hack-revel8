"""Read-only client for the Revel8 API."""

import os
from time import sleep
from urllib.parse import quote

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

    def _get[T](self, path: str, schema: TypeAdapter[T]) -> T:
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = self._client.get(path)
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

    def get_scenarios(self) -> JSONArray:
        return self._get("scenarios", _ARRAY)

    def get_channels(self) -> JSONArray | JSONObject:
        return self._get("channels", _ARRAY_OR_OBJECT)

    def get_session(self, session_id: str) -> JSONObject:
        return self._get(f"sessions/{_path_segment(session_id)}", _OBJECT)

    def list_sessions(self) -> JSONArray:
        return self._get("sessions", _ARRAY)

    def get_session_events(self, session_id: str) -> JSONObject:
        return self._get(f"sessions/{_path_segment(session_id)}/events", _OBJECT)


def _path_segment(value: str) -> str:
    if not value or value in {".", ".."}:
        raise Revel8APIError("A valid session ID is required.")
    return quote(value, safe="")
