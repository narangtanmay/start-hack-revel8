"""Counterfactual branch evaluator: score safe/balanced/bold next moves deterministically, pick the best.

No LLM calls and no randomness: the same (brief, steps, plan, today) always yields the same selection, so it adds
no latency and every decision is replayable from the logged payload.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .policy import (
    _ATTACHMENT_DECLINE_CUES,
    _LIVE_CHANNELS,
    _channel_ladder,
    _cited_facts_for_hook,
    _executed_steps,
    _is_past_hook,
    _is_uncertain_hook,
    _rank_hooks,
    _step_channel,
    _step_hook,
    _step_sentiment,
    _NEGATIVE_SENTIMENTS,
)

Tier = Literal["safe", "balanced", "bold"]
Reaction = Literal["engage", "question", "stall", "ignore", "suspicious", "incident"]

_TIERS: tuple[Tier, ...] = ("safe", "balanced", "bold")
_PHONE_SWITCH = frozenset({"sms", "whatsapp", "phone_call"})
_PHONE_NUMBER = re.compile(r"\+?\d[\d\s\-/().]{6,}\d")
_BASE_PROGRESS = {"safe": 0.30, "balanced": 0.35, "bold": 0.35}
_BASE_SUSPICION = {"safe": 0.05, "balanced": 0.10, "bold": 0.20}


class ShadowForecast(BaseModel):
    risk_tier: Tier
    predicted_reaction: Reaction
    progress_prob: float = Field(ge=0.0, le=1.0)
    suspicion_risk: float = Field(ge=0.0, le=1.0)
    social_norm_violation: float = Field(ge=0.0, le=1.0)
    verifiability_risk: float = Field(ge=0.0, le=1.0)
    rationale: str


def score_forecast(f: ShadowForecast) -> float:
    return round(f.progress_prob - 0.8 * f.suspicion_risk - 1.0 * f.social_norm_violation - 0.7 * f.verifiability_risk, 3)


def _clamp(x: float) -> float:
    return round(min(1.0, max(0.0, x)), 3)


def _replies(step: dict[str, Any]) -> list[str]:
    return [str(e.get("body") or "") for e in step.get("events") or [] if isinstance(e, dict) and e.get("type") == "reply"]


def _forecast(tier: Tier, c: dict[str, Any], channel: str, hook: dict[str, Any] | None, objective: str) -> ShadowForecast:
    is_call = channel in _LIVE_CHANNELS
    weekend = c["today"].weekday() >= 5
    notes: list[str] = []

    progress = _BASE_PROGRESS[tier]
    if channel == c["last_replied_channel"]:
        progress += 0.20
        notes.append("continues the active thread")
    if hook and not _is_past_hook(hook) and not _is_uncertain_hook(hook):
        progress += 0.10
        notes.append("hook is current/upcoming")
    if c["attachment_blocked"] and objective in ("credentials", "disclosure"):
        progress += 0.15
        notes.append(f"{objective} avoids declined attachments")
    if is_call and not weekend and c["silent_message_touches"] >= 3:
        progress += 0.30
        notes.append(f"weekday call after {c['silent_message_touches']} silent message touches")

    suspicion = _BASE_SUSPICION[tier]
    if c["consecutive_negative"] >= 1 and (tier == "bold" or is_call):
        suspicion += 0.45
        notes.append("aggressive escalation after a negative verdict")
    if objective == "action" and c["attachment_blocked"]:
        suspicion += 0.45
        notes.append("attachment ask after attachments were declined")

    norm = 0.0
    if is_call and weekend:
        norm += 0.65
        notes.append("call on a weekend")
    if c["last_replied_channel"] == "email" and channel in _PHONE_SWITCH and not c["phone_offered"]:
        norm += 0.65
        notes.append(f"switches to {channel} although target replied on email and offered no number")
    if channel == "sms" and c["last_channel"] == "sms":
        norm += 0.65
        notes.append("repeats sms back-to-back")

    verifiability = 0.0
    timing = str((hook or {}).get("timing", "")).strip().lower()
    if hook and (_is_past_hook(hook) or timing.startswith("uncertain-date") or _is_uncertain_hook(hook)):
        verifiability = 0.55
        notes.append("hook is past or date-uncertain")

    suspicion, norm = _clamp(suspicion), _clamp(norm)
    reaction: Reaction
    if suspicion >= 0.5:
        reaction = "suspicious"
    elif norm >= 0.5:
        reaction = "ignore"
    elif channel == c["last_replied_channel"]:
        reaction = "engage"
    elif is_call or c["silent_message_touches"] >= 2:
        reaction = "stall"
    else:
        reaction = "question"
    return ShadowForecast(
        risk_tier=tier, predicted_reaction=reaction, progress_prob=_clamp(progress), suspicion_risk=suspicion,
        social_norm_violation=norm, verifiability_risk=_clamp(verifiability),
        rationale="; ".join(notes) or "no notable risk or momentum signals",
    )


def _context(brief: dict[str, Any], steps: list[dict[str, Any]], plan: dict[str, Any], today: datetime | None) -> dict[str, Any]:
    history = _executed_steps(steps)
    channels = [_step_channel(s) for s in history if _step_channel(s)]
    sentiments = [_step_sentiment(s) for s in history]
    reply_text = " ".join(t for s in history for t in _replies(s))
    sent_text = " ".join(str(((s.get("payload") or {}).get("body") or "")) for s in history)
    blob = f"{reply_text} {sent_text}".casefold()

    silent_msgs = 0
    for s, sent in zip(reversed(history), reversed(sentiments)):
        if sent != "silent":
            break
        if _step_channel(s) not in _LIVE_CHANNELS:
            silent_msgs += 1
    negative = 0
    for sent in reversed(sentiments):
        if sent not in _NEGATIVE_SENTIMENTS:
            break
        negative += 1

    return {
        "today": today or datetime.now(),
        "history": history,
        "used_channels": channels,
        "used_hooks": [_step_hook(s) for s in history if _step_hook(s)],
        "last_channel": channels[-1] if channels else "",
        "last_replied_channel": next((_step_channel(s) for s in reversed(history) if _step_channel(s) and _replies(s)), None),
        "attachment_blocked": any(cue in blob for cue in _ATTACHMENT_DECLINE_CUES),
        "phone_offered": bool(_PHONE_NUMBER.search(reply_text)),
        "silent_message_touches": silent_msgs,
        "consecutive_negative": negative,
    }


def select_shadow_twin_move(
    brief: dict[str, Any],
    steps: list[dict[str, Any]],
    touch: int,
    max_touches: int,
    plan: dict[str, Any],
    base_move: dict[str, Any] | None = None,
    today: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    c = _context(brief, steps, plan, today)
    ranked = _rank_hooks(list(brief.get("hooks") or []), preferred_id=str(plan.get("hook_id") or "") or None)
    non_past = [h for h in ranked if not _is_past_hook(h)]
    top = (non_past or ranked or [None])[0]
    unused_hook = next((h for h in non_past if str(h["id"]) not in c["used_hooks"]), top)
    message_channels, live_channels = _channel_ladder(plan)
    primary = "email" if "email" in message_channels or not message_channels else message_channels[0]
    active = c["last_replied_channel"] or c["last_channel"] or primary

    plan_objective = str(plan.get("objective") or "disclosure")
    if c["attachment_blocked"] and plan_objective == "action":
        plan_objective = "credentials"

    safe_channel = c["last_replied_channel"] or primary
    balanced_channel = active
    if active == "sms" == c["last_channel"]:  # never repeat sms back-to-back
        balanced_channel = next((m for m in message_channels if m != "sms"), "email")
    unused = [m for m in message_channels if m not in c["used_channels"] and m != c["last_channel"]]
    call_channel = live_channels[0] if live_channels else "phone_call"
    bold_channel = call_channel if (c["silent_message_touches"] >= 3 or not unused) else unused[0]

    specs: dict[Tier, tuple[str, dict[str, Any] | None, str, str, str]] = {
        "safe": (safe_channel, top, plan_objective,
                 "Stay in-thread with one low-friction clarifying question.",
                 f"stay on {safe_channel} with the top current hook"),
        "balanced": (balanced_channel, unused_hook, plan_objective,
                     "Advance the objective directly with one concrete, single-purpose request.",
                     f"advance {plan_objective} on {balanced_channel}"),
        "bold": (bold_channel, top, plan_objective,
                 "Escalate to a live call or an unused channel with a higher-commitment ask.",
                 f"escalate to {bold_channel}"),
    }

    candidates: list[dict[str, Any]] = []
    for tier in _TIERS:
        channel, hook, objective, _ask, summary = specs[tier]
        fc = _forecast(tier, c, channel, hook, objective)
        candidates.append({
            "risk_tier": tier, "selected": False, "channel": channel,
            "kind": "call" if channel in _LIVE_CHANNELS else "message",
            "ev_score": score_forecast(fc), "summary": summary, "forecast": fc.model_dump(),
        })
    winner = max(candidates, key=lambda x: x["ev_score"])  # first max wins ties: safe > balanced > bold
    winner["selected"] = True

    tier: Tier = winner["risk_tier"]
    channel, hook, objective, ask, _ = specs[tier]
    hook_id = str(hook["id"]) if hook else str(plan.get("hook_id") or "")
    if channel in _LIVE_CHANNELS:
        move_type = "ESCALATE_CALL"
    elif c["history"] and channel != c["last_channel"]:
        move_type = "PIVOT_CHANNEL"
    elif c["history"] and c["used_hooks"] and hook_id != c["used_hooks"][-1]:
        move_type = "PIVOT_HOOK"
    else:
        move_type = "STAY"
    alternatives = [
        {"move_type": "STAY", "channel": o["channel"], "hook_id": hook_id,
         "reason": f"Rejected: {o['risk_tier']} branch EV {o['ev_score']} < {winner['ev_score']}."}
        for o in candidates if not o["selected"]
    ]
    if base_move:
        alternatives.append({k: str(base_move.get(k) or "") for k in ("move_type", "channel", "hook_id")}
                            | {"reason": "Rejected: replaced by the shadow-twin winner."})
    selected_move = {
        "move_type": move_type, "hook_id": hook_id, "channel": channel, "objective": objective, "ask": ask,
        "cited_fact_ids": _cited_facts_for_hook(brief, hook),
        "promises": ["Keep persona and prior details consistent", "Keep the ask concrete and single-purpose"],
        "rationale": f"Shadow twin picked {tier} (EV {winner['ev_score']}): {winner['forecast']['rationale']}.",
        "alternatives_considered": alternatives,
    }
    return selected_move, {"selected_tier": tier, "candidates": candidates}
