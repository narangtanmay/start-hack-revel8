"""Pick the voice model per situation, not per person: scoring targets are unseen, so the choice keys on what
research and planning found, which is known before the first message.

Evidence (practice, 2026-11-22, API-confirmed only):
- portal: the target's own dated, upcoming commitment (a talk, a session) -> organiser persona -> sign-in page.
  DeepSeek-V4.1-Flash converted Tom at touch 3 (s_3745f72293). V4-Flash and Qwen lost him at the first mail
  ("Action Required: Speaker Profile Verification" read as phishing).
- conversation: no upcoming commitment -> peer/prospect thread -> meeting -> document.
  Qwen3.8-27B (thinking off) converted Julius at touch 6 (s_accc249da0, attachment.opened).

Enabled with MODEL_STRATEGY=1. Models per situation: MODEL_PORTAL / MODEL_CONVERSATION, request extras:
MODEL_PORTAL_EXTRA_BODY / MODEL_CONVERSATION_EXTRA_BODY (JSON).
"""

from __future__ import annotations

import json
import os
from typing import Any

from .policy import _is_upcoming_hook, _rank_hooks

_DEFAULTS = {
    "portal": ("DeepSeek-V4.1-Flash", {}),
    "conversation": ("Qwen3.8-27B", {"chat_template_kwargs": {"enable_thinking": False}}),
}


def situation(brief: dict[str, Any], plan: dict[str, Any]) -> tuple[str, str]:
    """('portal' | 'conversation', why). Mirrors the policy: the top-ranked hook decides the credentials path."""
    hooks = [h for h in brief.get("hooks") or [] if isinstance(h, dict)]
    ranked = _rank_hooks(hooks, preferred_id=str(plan.get("hook_id") or "") or None)
    top = ranked[0] if ranked else None
    if top is not None and _is_upcoming_hook(top):
        return "portal", f"top hook {top.get('id')} is the target's own upcoming commitment"
    if str(plan.get("objective") or "") == "credentials":
        return "portal", "planned objective is credentials"
    return "conversation", "no upcoming commitment: a conversation that earns a meeting or a document"


def choose_model(brief: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any] | None:
    """The model for this run's drafts and decisions, or None when MODEL_STRATEGY is off."""
    if os.getenv("MODEL_STRATEGY", "0") != "1":
        return None
    kind, why = situation(brief, plan)
    default_model, default_extra = _DEFAULTS[kind]
    model = os.getenv(f"MODEL_{kind.upper()}", "").strip() or default_model
    raw = os.getenv(f"MODEL_{kind.upper()}_EXTRA_BODY", "").strip()
    try:
        extra = json.loads(raw) if raw else default_extra
    except ValueError:
        extra = default_extra
    return {"situation": kind, "model": model, "extra_body": extra if isinstance(extra, dict) else {}, "reason": why}
