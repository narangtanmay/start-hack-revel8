import httpx
import pytest
import respx

from revel8_agent import api_client
from revel8_agent.api_client import Revel8APIError, Revel8Client
from revel8_agent.cli import main

BASE = "https://events.example.test/v1"
KEY = "example-test-key"


@pytest.fixture
def delays(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []
    monkeypatch.setattr(api_client, "sleep", recorded.append)
    return recorded


@respx.mock
def test_read_endpoints_use_documented_paths_and_auth() -> None:
    scenarios = [{"id": "workshop", "open": True}]
    channels = ["email"]
    session = {"session_id": "s_workshop", "scenario_id": "workshop", "status": "active"}
    events = {"events": []}
    for path, data in [
        ("scenarios", scenarios),
        ("channels", channels),
        ("sessions", [session]),
        ("sessions/s_workshop", session),
        ("sessions/s_workshop/events", events),
    ]:
        respx.get(f"{BASE}/{path}").respond(json=data)

    with Revel8Client(BASE, KEY) as client:
        assert client.get_scenarios() == scenarios
        assert client.get_channels() == channels
        assert client.list_sessions() == [session]
        assert client.get_session("s_workshop") == session
        assert client.get_session_events("s_workshop") == events

    for call in respx.calls:
        assert call.request.headers["Authorization"] == f"Bearer {KEY}"
        assert call.request.extensions["timeout"]["read"] == 120.0


@respx.mock
def test_retries_transient_status_and_timeout(delays: list[float]) -> None:
    route = respx.get(f"{BASE}/scenarios").mock(
        side_effect=[httpx.Response(503), httpx.ReadTimeout("Example timeout"), httpx.Response(200, json=[])]
    )
    with Revel8Client(BASE, KEY) as client:
        assert client.get_scenarios() == []
    assert route.call_count == 3
    assert delays == [1, 2]


@pytest.mark.parametrize("status", [429, 502, 503, 504])
@respx.mock
def test_retry_limit(status: int, delays: list[float]) -> None:
    route = respx.get(f"{BASE}/scenarios").respond(status)
    with Revel8Client(BASE, KEY) as client, pytest.raises(Revel8APIError) as caught:
        client.get_scenarios()
    assert caught.value.status_code == status
    assert route.call_count == 4
    assert delays == [1, 2, 4]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 413, 415, 422, 500])
@respx.mock
def test_fails_fast_without_exposing_server_body(status: int, delays: list[float]) -> None:
    route = respx.get(f"{BASE}/scenarios").respond(status, text=KEY)
    with Revel8Client(BASE, KEY) as client, pytest.raises(Revel8APIError) as caught:
        client.get_scenarios()
    assert caught.value.status_code == status
    assert KEY not in str(caught.value)
    assert route.call_count == 1
    assert delays == []


@respx.mock
def test_status_counts_scenarios_and_channels(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("REVEL8_API_BASE", BASE)
    monkeypatch.setenv("REVEL8_API_KEY", KEY)
    respx.get(f"{BASE}/scenarios").respond(json=[{"open": True}, {"open": False}])
    respx.get(f"{BASE}/channels").respond(json={"channels": ["email"]})
    assert main(["status"]) == 0
    output = capsys.readouterr()
    assert output.out.splitlines() == [
        "Revel8 API reachable",
        "Scenarios: 2 (1 open)",
        "Channel entries: 1",
    ]
    assert output.err == ""
