"""Data models shared by validation and trace logging."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationInfo, field_validator, model_validator


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
    source_kind: str = ""          # social | own_article | aggregator | news | web (classified by source domain)


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
    # Hook v2: an evidence-backed attack angle (optional, backward compatible)
    open_signal: str = ""                 # verbatim quote showing they are open to this right now (checked in source)
    timing: str = ""                      # current | upcoming | this-year | undated | past (from supporting facts)
    sender_archetype: str = ""            # who would naturally contact them about this
    natural_ask: str = ""                 # the small, natural thing they would do for that sender
    answers_personally: str = ""          # yes | maybe | no: LLM judgement whether THEY handle the ask or hand it off
    handed_to: str = ""                   # who they would hand it to (LLM), when not "yes"
    incident_path: str = ""               # disclosure | action | credentials
    first_line: str = ""                  # opener grounded in one cited fact
    verify_risk: str = ""                 # what they could check about the sender, and how to stay plausible
    avoid: list[str] = Field(default_factory=list)   # claims not to make (past as upcoming, conflicting facts)
    score: float = 0.0                    # deterministic ranking score (see research.score_hook)
    score_breakdown: dict = Field(default_factory=dict)


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


class PersonaSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    organisation: str = ""
    role: str = ""
    email: str = ""
    phone: str = ""
    website_domain: str = ""
    brand_color: str = "#1F4E8C"
    story: str = ""

    @model_validator(mode="after")
    def _validate_required(self) -> "PersonaSpec":
        if not self.name.strip():
            raise ValueError("persona.name must be a non-empty string")
        if not self.organisation.strip() and not self.role.strip():
            raise ValueError("persona must include a non-empty organisation or role")
        return self


class CampaignPlan(BaseModel):
    model_config = ConfigDict(extra="allow")

    hook_id: str
    objective: Literal["credentials", "action", "disclosure"]
    persona: PersonaSpec
    pretext: str = ""
    language: str = "en"
    sequence: list[dict[str, Any]] = Field(default_factory=list)
    fallbacks: list[str] = Field(default_factory=list)
    rationale: str = ""

    @model_validator(mode="before")
    @classmethod
    def _normalize_hook_alias(cls, data: Any) -> Any:
        if isinstance(data, dict):
            out = dict(data)
            if not out.get("hook_id") and out.get("hook"):
                out["hook_id"] = out["hook"]
            return out
        return data

    @field_validator("hook_id")
    @classmethod
    def _non_empty_hook_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("hook_id must be a non-empty string")
        return cleaned

    @model_validator(mode="after")
    def _check_valid_hook_ids(self, info: ValidationInfo) -> "CampaignPlan":
        valid_hook_ids = (info.context or {}).get("valid_hook_ids")
        if valid_hook_ids and self.hook_id not in valid_hook_ids:
            raise ValueError(f"hook_id {self.hook_id!r} must be one of {sorted(valid_hook_ids)}")
        return self


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
