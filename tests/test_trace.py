import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from revel8_agent.schemas import ContactPlan, GateVerdict, ReevalDecision, RunTraceEntry
from revel8_agent.trace import RunTraceLogger


def test_trace_jsonl_round_trip(tmp_path: Path, plan: ContactPlan) -> None:
    logger = RunTraceLogger("workshop", tmp_path / "runs")
    assert logger.read() == []
    entry = RunTraceEntry(
        run_id="workshop",
        session_id="s_workshop",
        turn=1,
        timestamp=datetime(2026, 11, 21, 9, tzinfo=UTC),
        belief_state={"schedule": {"published": True}},
        contact_plan=plan,
        gate_verdict=GateVerdict(passed=True),
        api_response={"events": []},
        reeval_decision=ReevalDecision(action="STOP", reason="Workshop complete"),
    )
    second_entry = entry.model_copy(update={"turn": 2})
    logger.append(entry)
    logger.append(second_entry)

    lines = (tmp_path / "runs" / "workshop.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["turn"] for line in lines] == [1, 2]
    assert RunTraceLogger("workshop", tmp_path / "runs").read() == [entry, second_entry]


def test_trace_rejects_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="filename component"):
        RunTraceLogger("../workshop", tmp_path)
