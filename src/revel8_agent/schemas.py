"""Data models shared by validation and trace logging."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, JsonValue


class VerifiedFact(BaseModel):
    id: str
    fact: str
    category: str
    source_url: str
    verbatim_quote: str
    recency: str
    # research v2 (optional, backward compatible)
    lane: str = ""                                                   # web | news | media | social | academic | expansion
    published: str = ""                                              # source publish date if the search engine knew it
    corroborated_by: list[str] = Field(default_factory=list)        # other source URLs saying the same thing
    conflicts_with: list[str] = Field(default_factory=list)         # fact ids that contradict this one
    conflict_note: str = ""


class Theme(BaseModel):
    """What the person keeps talking about: counted over their own posts, talks and interviews."""

    topic: str
    count: int
    latest: str = ""
    fact_ids: list[str] = Field(default_factory=list)


class HookHypothesis(BaseModel):
    id: str
    topic: str
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)
    is_own_angle: bool = False
    supporting_fact_ids: list[str] = Field(default_factory=list)


class VerifiedDossier(BaseModel):
    target_id: str
    target_name: str
    role: str
    company: str
    facts: list[VerifiedFact] = Field(default_factory=list)
    hypotheses: list[HookHypothesis] = Field(default_factory=list)
    themes: list[Theme] = Field(default_factory=list)
    anchors: list[str] = Field(default_factory=list)  # identity anchors used to tell this person from namesakes


class SenderInfo(BaseModel):
    name: str
    address: str


class LandingPageSpec(BaseModel):
    url: str
    title: str
    html: str
    fields: list[str] = Field(default_factory=list)


class AttachmentSpec(BaseModel):
    filename: str
    transcript: str | None = None


class ContactPlan(BaseModel):
    to: str
    channel: str
    sender: SenderInfo | None = None
    subject: str | None = None
    body: str
    is_html: bool = False
    attachments: list[str | AttachmentSpec] = Field(default_factory=list)
    landing_page: LandingPageSpec | None = None
    cited_fact_ids: list[str] = Field(default_factory=list)
    rationale: str = ""
    discarded_alternatives: list[str] = Field(default_factory=list)


class GateVerdict(BaseModel):
    passed: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ReevalDecision(BaseModel):
    action: Literal["STAY", "PIVOT_CHANNEL", "PIVOT_HOOK", "ESCALATE_CALL", "STOP"]
    reason: str
    discarded_options: list[str] = Field(default_factory=list)
    updated_channel_status: dict[str, str] = Field(default_factory=dict)


class RunTraceEntry(BaseModel):
    run_id: str
    session_id: str
    turn: int
    timestamp: datetime
    belief_state: dict[str, JsonValue] = Field(default_factory=dict)
    contact_plan: ContactPlan | None = None
    gate_verdict: GateVerdict | None = None
    api_response: JsonValue = None
    reeval_decision: ReevalDecision | None = None
