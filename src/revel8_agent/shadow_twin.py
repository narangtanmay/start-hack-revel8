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
    _LIVE_CHANNELS,
    _NEGATIVE_SENTIMENTS,
    _channel_ladder,
    _cited_facts_for_hook,
    _executed_steps,
    _is_past_hook,
    _is_uncertain_hook,
    _rank_hooks,
    _step_channel,
    _step_hook,
    _step_sentiment,
)
from .target_state import extract_target_state

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
    ts = c["target_state"]
    blocked = set(ts["blocked_mechanisms"])
    open_doors = set(ts["open_doors"])
    attachments_blocked = bool(blocked & {"attachments", "weekend_files"})
    login_blocked = "login_wall" in blocked
    notes: list[str] = []

    progress = _BASE_PROGRESS[tier]
    if channel == c["last_replied_channel"]:
        progress += 0.20
        notes.append("continues the active thread")
    if hook and not _is_past_hook(hook) and not _is_uncertain_hook(hook):
        progress += 0.10
        notes.append("hook is current/upcoming")
    if attachments_blocked and objective in ("credentials", "disclosure"):
        progress += 0.15
        notes.append(f"{objective} avoids declined attachments")
    if login_blocked and objective in ("action", "disclosure"):
        progress += 0.10
        notes.append(f"{objective} avoids blocked login wall")
    if objective == "action" and "wants_pdf" in open_doors and not attachments_blocked:
        progress += 0.20
        notes.append("matches target request for PDF attachment")
    if objective == "disclosure" and (open_doors & {"wants_email_body", "wants_details"}):
        progress += 0.10
        notes.append("matches target pull for details in email body")
    if ts["reaction_tag"] == "LINK_OPENED_BOUNCE" and objective in ("action", "disclosure"):
        progress += 0.15
        notes.append("pivots away from login wall after link-open bounce")
    call_invited = "wants_call" in open_doors and not ts.get("call_completed") and "phone_switch" not in blocked
    if is_call and call_invited:
        progress += 0.45
        notes.append("target explicitly invited a call before reviewing files")
    elif is_call and not weekend and c["silent_message_touches"] >= 3:
        progress += 0.30
        notes.append(f"weekday call after {c['silent_message_touches']} silent message touches")

    suspicion = _BASE_SUSPICION[tier]
    if c["consecutive_negative"] >= 1 and (tier == "bold" or is_call):
        suspicion += 0.45
        notes.append("aggressive escalation after a negative verdict")
    if objective == "action" and attachments_blocked:
        suspicion += 0.45
        notes.append("attachment ask after attachments/weekend files were declined")
    if objective == "credentials" and login_blocked:
        suspicion += 0.45
        notes.append("credential ask after login wall was blocked")
    if objective == "credentials" and ts["reaction_tag"] == "LINK_OPENED_BOUNCE":
        suspicion += 0.35
        notes.append("repeats credential link after link-open bounce")

    norm = 0.0
    if is_call and weekend and not call_invited:
        norm += 0.65
        notes.append("call on a weekend")
    if channel in _PHONE_SWITCH and "phone_switch" in blocked:
        norm += 0.65
        notes.append(f"switches to {channel} after target requested email-only")
    elif c["last_replied_channel"] == "email" and channel in _PHONE_SWITCH and not c["phone_offered"] and not (is_call and call_invited):
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


_STALL_REPLIES = 2


def _unproductive_replies_on_hook(history: list[dict[str, Any]]) -> int:
    """Replies on the current hook that moved nothing: no first reply, no new open door, no link/incident.

    Wording-independent backstop for deflections _ROUTED_RE does not know (Robert v3: six polite
    "send it to info@" replies, zero pivots).
    """
    hook = _step_hook(history[-1]) if history else ""
    count, prev = 0, extract_target_state([])
    for k, s in enumerate(history, start=1):
        cur = extract_target_state(history[:k])  # ponytail: O(n^2) over <=10 touches
        if hook and _step_hook(s) == hook and _replies(s):
            # Target pulling on an ask we have not delivered (Tom task-1805) is our delay, not a dead hook.
            # ponytail: wants_pdf never clears once seen, so a PDF-asker never stalls; track delivery if that bites.
            pending_ask = ("wants_call" in cur["open_doors"] and not cur["call_completed"]) or "wants_pdf" in cur["open_doors"]
            progressed = (prev["engagement_stage"] == "cold" or pending_ask
                          or set(cur["open_doors"]) - set(prev["open_doors"])
                          or cur["reaction_tag"] in ("INCIDENT_CONFIRMED", "LINK_OPENED_BOUNCE"))
            count = 0 if prev["engagement_stage"] == "cold" else count + (not progressed)
        elif hook and _step_hook(s) == hook and prev["engagement_stage"] != "cold":
            # Silence after they engaged counts too (Robert final: deflected at T2, then 4 silent touches on h4).
            # Cold-open silence stays with the channel ladder.
            pending_ask = ("wants_call" in cur["open_doors"] and not cur["call_completed"]) or "wants_pdf" in cur["open_doors"]
            count += not pending_ask
        elif _step_hook(s) != hook:
            count = 0
        prev = cur
    return count


def _context(brief: dict[str, Any], steps: list[dict[str, Any]], plan: dict[str, Any], today: datetime | None) -> dict[str, Any]:
    history = _executed_steps(steps)
    channels = [_step_channel(s) for s in history if _step_channel(s)]
    sentiments = [_step_sentiment(s) for s in history]
    reply_text = " ".join(t for s in history for t in _replies(s))
    target_state = extract_target_state(history)
    blocked = set(target_state["blocked_mechanisms"])

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
    # Handoff letters that nobody answered: the thread must shorten, not re-send the same letter.
    ignored_on = bool(target_state.get("call_handoff")) or bool(target_state.get("call_completed"))
    handoff_ignored = 0
    if ignored_on:
        for s in reversed(history):
            if _replies(s):
                break
            handoff_ignored += 1

    return {
        "today": today or datetime.now(),
        "history": history,
        "used_channels": channels,
        "used_hooks": [_step_hook(s) for s in history if _step_hook(s)],
        "last_channel": channels[-1] if channels else "",
        "last_replied_channel": target_state["last_replied_channel"],
        "attachment_blocked": bool(blocked & {"attachments", "weekend_files"}),
        "phone_offered": bool(_PHONE_NUMBER.search(reply_text)) or bool(target_state["phone_offered"]),
        "silent_message_touches": silent_msgs,
        "consecutive_negative": negative,
        "handoff_ignored": handoff_ignored,
        "target_state": target_state,
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
    last_hook_id = c["used_hooks"][-1] if c["used_hooks"] else None
    current_hook = next((h for h in ranked if str(h["id"]) == last_hook_id), top)
    unused_hook = next((h for h in non_past if str(h["id"]) not in c["used_hooks"]), top)
    # Only the touch that got the routing reply pivots; the tag stays ROUTED through silence (Robert smoke T5/T6).
    routed = c["target_state"]["reaction_tag"] == "ROUTED" and bool(c["history"]) and bool(_replies(c["history"][-1]))
    if _unproductive_replies_on_hook(c["history"]) >= _STALL_REPLIES:
        current_hook = unused_hook  # stalled hook is dead for every tier, not just balanced
    balanced_hook = unused_hook if (routed or not c["last_replied_channel"]) else current_hook
    message_channels, live_channels = _channel_ladder(plan)
    primary = "email" if "email" in message_channels or not message_channels else message_channels[0]
    replied_msg_channel = next(
        (_step_channel(s) for s in reversed(c["history"])
         if _step_channel(s) and _step_channel(s) not in _LIVE_CHANNELS
         and _step_channel(s) != "linkedin_connection_request" and _replies(s)),
        None,
    )
    active = replied_msg_channel or (c["last_channel"] if c["last_channel"] not in _LIVE_CHANNELS else None) or primary

    target_state = c["target_state"]
    blocked = set(target_state["blocked_mechanisms"])
    open_doors = set(target_state["open_doors"])
    attachments_blocked = bool(blocked & {"attachments", "weekend_files"})
    login_blocked = "login_wall" in blocked

    plan_objective = str(plan.get("objective") or "disclosure")
    if plan_objective == "action" and attachments_blocked:
        plan_objective = "disclosure" if login_blocked else "credentials"
    elif plan_objective == "credentials" and login_blocked:
        plan_objective = "action" if ("wants_pdf" in open_doors and not attachments_blocked) else "disclosure"
    elif plan_objective == "credentials" and target_state["reaction_tag"] == "LINK_OPENED_BOUNCE":
        plan_objective = "action" if not attachments_blocked else "disclosure"

    safe_channel = replied_msg_channel or primary
    balanced_channel = active
    if active in ("sms", "linkedin_connection_request") and active == c["last_channel"]:
        balanced_channel = next((m for m in message_channels if m not in ("sms", "linkedin_connection_request")), "email")
    unused = [m for m in message_channels if m not in c["used_channels"] and m != c["last_channel"] and m != "linkedin_connection_request"]
    call_channel = live_channels[0] if live_channels else "phone_call"
    call_invited = "wants_call" in open_doors and not target_state.get("call_completed") and "phone_switch" not in blocked
    # A target who keeps answering is never silent, so silence could never escalate them: robert
    # answered all ten mails with intent to keep it there (live 2026-11-22). Slots on the table
    # and repeated engaged replies are progression signals, not a reason to keep writing.
    engaged_replies = int(target_state.get("engaged_replies") or 0)
    slots_accepted = (bool(target_state.get("call_proposed")) and bool(target_state.get("call_accepted"))
                      and not target_state.get("call_completed"))
    propose_slots = (call_invited or engaged_replies >= 2) and not slots_accepted and not target_state.get("call_completed")
    await_acceptance = (bool(target_state.get("call_proposed")) and not slots_accepted
                        and not target_state.get("call_completed"))
    # He answered the phone and handed us to sales: the next mail goes to that person, not to him.
    handoff = str(target_state.get("call_handoff") or "")
    # A handoff is a handoff whether it arrived by mail or on the call (loop6-robert T1: "I'm passing
    # this to them" — the old gate needed a call and the next touch pivoted the hook anyway).
    after_handoff = bool(handoff)
    # Call happened and nobody was named: the follow-through is material + one written line, not a
    # hook pivot and not a second dial (loop5-julius churned PIVOT_CHANNEL/PIVOT_HOOK for six touches).
    after_call = bool(target_state.get("call_completed")) and not handoff
    bold_channel = call_channel if (
        call_invited or slots_accepted or c["silent_message_touches"] >= 3 or not unused) else unused[0]

    specs: dict[Tier, tuple[str, dict[str, Any] | None, str, str, str]] = {
        "safe": (safe_channel, current_hook if c["last_replied_channel"] else top, plan_objective,
                 "Stay in-thread with one low-friction clarifying question.",
                 f"stay on {safe_channel} with the active hook"),
        "balanced": (balanced_channel, balanced_hook, plan_objective,
                     f"One line only: the time stands, {handoff} has it, ask them to confirm it and send the "
                     f"invite; say you will stop and wait if you hear nothing."
                     if after_handoff and c["handoff_ignored"] >= 3 else
                     f"Shorten to two lines: {handoff} owns it, one sentence of substance, one yes/no question."
                     if after_handoff and c["handoff_ignored"] >= 2 else
                     # No recipient/cc field exists, so the mail still lands on the target's thread: greet the
                     # target, name the owner in the first sentence, and stop claiming a cc that is not sent.
                     f"Keep the target's greeting and thread, and name {handoff} in the first sentence as "
                     f'the owner ("Robert, for Claudia:"); put the concrete detail in that mail and quote '
                     f"the target's own words as the reason for writing."
                     if after_handoff else
                     "One line only: the material is with them, say you will hold the slot and stop writing "
                     "until they answer."
                     if c["handoff_ignored"] >= 3 else
                     "Shorten to two lines: the material stands, one yes/no question, no second dial."
                     if c["handoff_ignored"] >= 2 else
                     "Send what was promised on the call, ask for one written line back and say when you "
                     "will check in; no second dial and no hook change."
                     if after_call else
                     "Repeat the two times already offered, ask which one they will hold and say you will "
                     "call then; no new slots until they answer."
                     if await_acceptance else
                     "Answer what they asked, then propose a short fifteen-minute call and name two or three "
                     "concrete slots instead of asking whether a call suits."
                     if propose_slots else
                     # First touch on a router (robert: "not by mail with me") needs a slot to accept, not
                     # an internal question alone — loop7 T1 got one routing answer and then silence.
                     "Open with the specific reason you are writing, name two or three concrete slots for "
                     "the fifteen-minute call, and add the one internal detail their site does not state. "
                     "Advance the objective directly with one concrete, single-purpose request."
                     if not c["history"] else
                     "Advance the objective directly with one concrete, single-purpose request. "
                     "Ask for one internal detail their site does not state \u2014 who owns it, how they "
                     "run it, or the number behind it.",
                     f"advance {plan_objective} on {balanced_channel}"),
        "bold": (bold_channel, current_hook if c["last_replied_channel"] else top, plan_objective,
                 "Place the call now that the slots are on the table; confirm the agreed time in one line, then "
                 "ask the one internal question the site cannot answer (owner, process or number)."
                 if slots_accepted else
                 "Place the brief call the target asked for so they can review the document right after."
                 if call_invited else "Escalate to a live call or an unused channel with a higher-commitment ask, and ask for the "
                 "internal detail of theirs the website does not state.",
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
    if slots_accepted:
        # The slots are already accepted in the thread; a further mail only adds a round-trip.
        winner = next(c for c in candidates if c["risk_tier"] == "bold")
        for cand in candidates:
            cand["selected"] = cand is winner
    elif after_call or after_handoff:
        # Straight after a call the channel change is not a pivot; hold the thread on mail.
        winner = next(c for c in candidates if c["risk_tier"] == "balanced")
        for cand in candidates:
            cand["selected"] = cand is winner
    winner["selected"] = True

    tier: Tier = winner["risk_tier"]
    channel, hook, objective, ask, _ = specs[tier]
    hook_id = str(hook["id"]) if hook else str(plan.get("hook_id") or "")
    if slots_accepted and not target_state.get("call_completed"):
        # An address handoff ("send the invite to tom@revel8.ai") must not talk us out of the dial.
        move_type = "ESCALATE_CALL"
    elif after_call or after_handoff:
        move_type = "STAY"
    elif channel in _LIVE_CHANNELS:
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
        "forbidden_artifacts": list(c["target_state"]["blocked_mechanisms"]),
        "target_state": c["target_state"],
    }
    return selected_move, {"selected_tier": tier, "candidates": candidates, "target_state": c["target_state"]}
