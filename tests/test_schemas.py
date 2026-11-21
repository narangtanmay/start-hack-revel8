import pytest
from pydantic import ValidationError

from revel8_agent.schemas import AttachmentSpec, ContactPlan, HookHypothesis, ReevalDecision


def test_contact_plan_parses_nested_types_and_round_trips(plan: ContactPlan) -> None:
    assert isinstance(plan.attachments[1], AttachmentSpec)
    assert ContactPlan.model_validate_json(plan.model_dump_json()) == plan


def test_hypothesis_defaults_and_confidence_bounds() -> None:
    fields = {"id": "schedule", "topic": "Check-in", "rationale": "Published schedule"}
    hypothesis = HookHypothesis(**fields, confidence=0.5)
    assert hypothesis.is_own_angle is False
    assert hypothesis.supporting_fact_ids == []
    with pytest.raises(ValidationError, match="confidence"):
        HookHypothesis(**fields, confidence=1.1)


def test_reeval_action_is_restricted() -> None:
    assert ReevalDecision(action="STOP", reason="Workshop complete").action == "STOP"
    with pytest.raises(ValidationError, match="action"):
        ReevalDecision.model_validate({"action": "SKIP", "reason": "Workshop complete"})
