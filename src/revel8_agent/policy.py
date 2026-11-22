"""Deterministic policy interface and default rule-based state machine."""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from .target_state import extract_target_state

MoveType = Literal["STAY", "PIVOT_CHANNEL", "PIVOT_HOOK", "ESCALATE_CALL", "STOP"]

_DEFAULT_MESSAGE_CHANNELS = ("email", "linkedin_message", "slack", "teams_chat", "sms")
_LIVE_CHANNELS = frozenset({"phone_call", "video_call", "teams_call", "live_chat"})
_NEGATIVE_SENTIMENTS = frozenset({"refusing", "suspicious"})
_ATTACHMENT_DECLINE_CUES = (
    "keine anhänge",
    "keine pdf",
    "öffne keine anhänge",
    "pdf öffne ich nicht",
    "don't open attachment",
    "do not open attachment",
    "no attachment",
    "kein anhang",
    "ohne anhang",
)


@runtime_checkable
class Policy(Protocol):
    def choose_next_move(
        self,
        brief: dict[str, Any],
        steps: list[dict[str, Any]],
        touch: int,
        max_touches: int,
        plan: dict[str, Any],
    ) -> dict[str, Any]: ...


import re

# The target asks us for a link, an invite or access ("Bitte schicken Sie den Link zum Termin", h3only-r1 2026-11-22).
_LINK_REQUEST = re.compile(
    r"\b(?:link|einladung|invite|invitation|zugang|access|kalendereintrag|calendar|termin(?:link)?|zoom|teams-link|"
    r"video-?link|meeting-?link|schicken sie (?:mir )?(?:den|die|eine)|send (?:me )?(?:the|a|an))\b",
    re.IGNORECASE,
)
_MEETING_REQUEST = re.compile(r"video|meeting|termin|call|zoom|teams|einladung|invite", re.IGNORECASE)
# The target refuses logins: a sign-in page would only burn trust, so stop pushing one.
_LOGIN_DECLINE = re.compile(
    r"kein(?:en)? (?:login|log-in)|nicht (?:ein)?loggen|portal-?login kommt nicht|log(?:-| )?in(?:s)? (?:is|are) out|"
    r"won'?t (?:log|sign) in|no (?:login|log-in|sign-in)|don'?t (?:log|sign) in|keine anmeldung|"
    # "no need for me to sign in anywhere ... rather than through the link" (fast-SW Tom T1, 2026-11-22)
    r"no need (?:for me )?to (?:log|sign) ?in|(?:log|sign) ?in anywhere|rather than (?:through|via) the link|"
    r"nicht (?:extra )?(?:an|ein)melden|ohne (?:login|anmeldung)|lieber (?:direkt )?(?:hier|per mail)|"
    # "I won't use the portal for now" (hybrid-S7 Tom T2, 2026-11-22)
    r"won'?t use the (?:portal|link)|not (?:going to )?use the (?:portal|link)|portal (?:nicht|lieber nicht)|"
    r"nicht (?:über|ins|im) (?:das )?portal",
    re.IGNORECASE,
)


# The target accepts but parks it ("I'll go through the entry before the print week", fast-S3 Tom T3, 2026-11-22).
_DEFERRAL = re.compile(
    r"during the week|next week|later this week|before the print|in (?:a|the) few days|when i (?:get|find) (?:a chance|time)|"
    r"i'?ll (?:look|check|go through|get back|come back|take a look)|let you know|"
    r"im laufe der woche|nächste woche|später|in den nächsten tagen|ich (?:schaue|sehe) (?:es )?mir .{0,20}an|melde mich",
    re.IGNORECASE,
)


# A concrete date or weekday we already committed to in a sent message.
_DATE_MENTION = re.compile(
    r"\b\d{1,2}\.?\s*(?:januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember|january|"
    r"february|march|may|june|july|october|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b|"
    r"\b(?:monday|tuesday|wednesday|thursday|friday|montag|dienstag|mittwoch|donnerstag|freitag)\b|\b\d{1,2}\.\d{1,2}\.",
    re.IGNORECASE,
)


def _is_upcoming_hook(hook: dict[str, Any]) -> bool:
    return str(hook.get("timing", "")).strip().lower().startswith("upcoming")


def _is_past_hook(hook: dict[str, Any]) -> bool:
    return str(hook.get("timing", "")).strip().upper().startswith("PAST")


def _is_uncertain_hook(hook: dict[str, Any]) -> bool:
    label = str(hook.get("timing", "")).lower()
    return "uncertain" in label or "partly past" in label


def _rank_hooks(hooks: list[dict[str, Any]], preferred_id: str | None = None) -> list[dict[str, Any]]:
    valid = [h for h in hooks if isinstance(h, dict) and h.get("id")]
    if not valid:
        return []
    has_non_past = any(not _is_past_hook(h) for h in valid)

    def sort_key(h: dict[str, Any]) -> tuple[int, int, int, float]:
        # A dated, upcoming commitment of the target (a talk, a session) beats any theme: it is the one thing they
        # already expect mail about. The team's only API-confirmed incident came from such a hook (h3, 2026-11-21),
        # and in 10 DeepSeek runs the planner never picked it by itself.
        past_rank = 3 if _is_past_hook(h) else (2 if _is_uncertain_hook(h) else (0 if _is_upcoming_hook(h) else 1))
        pref_rank = 0 if (preferred_id and h.get("id") == preferred_id and (not _is_past_hook(h) or not has_non_past)) else 1
        own_rank = 0 if h.get("is_own_angle") else 1
        conf = float(h.get("confidence", 0.0) or 0.0)
        return (past_rank, pref_rank, own_rank, -conf)

    return sorted(valid, key=sort_key)


def _valid_fact_ids(brief: dict[str, Any]) -> list[str]:
    facts = brief.get("facts") or []
    return [str(f["id"]) for f in facts if isinstance(f, dict) and f.get("id")]


def _cited_facts_for_hook(brief: dict[str, Any], hook: dict[str, Any] | None) -> list[str]:
    valid_ids = _valid_fact_ids(brief)
    valid_set = set(valid_ids)
    chosen: list[str] = []
    if hook:
        for fid in hook.get("supporting_fact_ids") or []:
            fid_str = str(fid)
            if fid_str in valid_set and fid_str not in chosen:
                chosen.append(fid_str)
    if chosen:
        return chosen
    non_past = [
        str(f["id"])
        for f in (brief.get("facts") or [])
        if isinstance(f, dict) and f.get("id") and str(f.get("timing", "")).lower() != "past"
    ]
    return (non_past or valid_ids)[:2]


def _channel_ladder(plan: dict[str, Any]) -> tuple[list[str], list[str]]:
    planned: list[str] = []
    for item in plan.get("sequence") or []:
        if isinstance(item, dict) and item.get("channel"):
            ch = str(item["channel"]).strip()
            if ch and ch not in planned:
                planned.append(ch)
    message_channels: list[str] = []
    live_channels: list[str] = []
    for ch in planned + list(_DEFAULT_MESSAGE_CHANNELS) + ["phone_call"]:
        if ch in _LIVE_CHANNELS:
            if ch not in live_channels:
                live_channels.append(ch)
        else:
            if ch not in message_channels:
                message_channels.append(ch)
    return message_channels, live_channels


def _step_sentiment(step: dict[str, Any]) -> str:
    judge = step.get("judge")
    if isinstance(judge, dict) and judge.get("sentiment"):
        return str(judge["sentiment"]).strip().lower()
    events = step.get("events") or []
    transcript = step.get("transcript") or []
    if not events and not transcript:
        return "silent"
    return "engaged"


def _step_channel(step: dict[str, Any]) -> str:
    action = step.get("action") if isinstance(step.get("action"), dict) else {}
    policy = step.get("policy") if isinstance(step.get("policy"), dict) else {}
    return str(action.get("channel") or policy.get("channel") or "")


def _step_hook(step: dict[str, Any]) -> str:
    action = step.get("action") if isinstance(step.get("action"), dict) else {}
    policy = step.get("policy") if isinstance(step.get("policy"), dict) else {}
    return str(action.get("hook_id") or policy.get("hook_id") or "")


def _executed_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in steps:
        if not isinstance(s, dict):
            continue
        if s.get("error"):
            continue
        action = s.get("action") if isinstance(s.get("action"), dict) else {}
        if s.get("decision") == "STOP" or action.get("decision") == "STOP":
            continue
        out.append(s)
    return out


def _alt(move_type: str, channel: str, hook_id: str, reason: str) -> dict[str, str]:
    return {
        "move_type": move_type,
        "channel": channel,
        "hook_id": hook_id,
        "reason": reason,
    }


def _cycle_next(candidates: list[str], current: str, used: list[str]) -> str:
    """Pick the first unused candidate, else the least-recently-used candidate distinct from current."""
    if not candidates:
        return current
    unused = [c for c in candidates if c not in used]
    if unused:
        return unused[0]
    others = [c for c in candidates if c != current]
    if others:
        def _last_idx(item: str) -> int:
            for idx in range(len(used) - 1, -1, -1):
                if used[idx] == item:
                    return idx
            return -1

        return min(others, key=_last_idx)
    return candidates[0]


class RuleBasedPolicy:
    """Deterministic state-machine controller over brief, step history, and verdicts."""

    def choose_next_move(
        self,
        brief: dict[str, Any],
        steps: list[dict[str, Any]],
        touch: int,
        max_touches: int,
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        objective = str(plan.get("objective") or "disclosure")
        planned_hook = str(plan.get("hook_id") or "") or None
        ranked_hooks = _rank_hooks(list(brief.get("hooks") or []), preferred_id=planned_hook)
        hooks_by_id = {str(h["id"]): h for h in ranked_hooks}
        message_channels, live_channels = _channel_ladder(plan)
        # Same rule as gate._social_norm: an email-only target who never gave a number is not texted. Proposing
        # sms anyway made the gate reject every draft of the touch (qwen-R3 robert T6, 2026-11-22).
        from .gate import _PHONE_RE

        _replied_on: set[str] = set()
        _said = ""
        for _s in steps:
            _act = _s.get("action") if isinstance(_s.get("action"), dict) else {}
            for _e in _s.get("events") or []:
                if isinstance(_e, dict) and _e.get("type") == "reply":
                    _replied_on.add(str(_e.get("channel") or _act.get("channel") or ""))
                    _said += f" {_e.get('body') or ''}"
        if "email" in _replied_on and not (_replied_on & _LIVE_CHANNELS) and not _PHONE_RE.search(_said):
            message_channels = [c for c in message_channels if c not in ("sms", "whatsapp")] or ["email"]
        default_channel = message_channels[0] if message_channels else "email"
        initial_hook = ranked_hooks[0] if ranked_hooks else None
        initial_hook_id = str(initial_hook["id"]) if initial_hook else (planned_hook or "")

        history = _executed_steps(steps)
        used_channels = [_step_channel(s) for s in history if _step_channel(s)]
        used_hooks = [_step_hook(s) for s in history if _step_hook(s)]
        sentiments = [_step_sentiment(s) for s in history]
        target_state = extract_target_state(history)
        blocked = set(target_state["blocked_mechanisms"])
        open_doors = set(target_state["open_doors"])
        attachments_blocked = bool(blocked & {"attachments", "weekend_files"})
        login_blocked = "login_wall" in blocked

        if objective == "action" and attachments_blocked:
            objective = "disclosure"
        elif objective == "credentials" and login_blocked:
            objective = "action" if not attachments_blocked else "disclosure"

        replies = [
            " ".join(str(e.get("body") or "") for e in (s.get("events") or [])
                     if isinstance(e, dict) and e.get("type") == "reply")
            for s in history
        ]
        login_declined = login_blocked or any(_LOGIN_DECLINE.search(r) for r in replies)
        sent_texts = [str(((s.get("payload") or {}).get("body") or "")) for s in history]
        deadline_given = any(_DATE_MENTION.search(t) for t in sent_texts)
        # link opened without a submit, per touch (a first bounce still converted on T3 in fast-S5)
        link_bounces = sum(
            1 for s in history
            if any(isinstance(e, dict) and e.get("type") == "link.opened" for e in (s.get("events") or []))
            and not any(isinstance(e, dict) and e.get("type") == "page.submitted" for e in (s.get("events") or []))
        )
        last_reply = next((r for r in reversed(replies) if r.strip()), "")
        link_requested = bool(_LINK_REQUEST.search(last_reply))
        # Disclosure never shows up as an API event and the twins only volunteer public facts (26 judged
        # "disclosures", 0 real, 2026-11-22). On an upcoming event a portal sign-in is the natural ask.
        if objective == "disclosure" and initial_hook is not None and _is_upcoming_hook(initial_hook) and not login_declined:
            objective = "credentials"

        consecutive_silent = 0
        silent_channels: set[str] = set()
        for s, sent in zip(reversed(history), reversed(sentiments)):
            if sent == "silent":
                consecutive_silent += 1
                ch = _step_channel(s)
                if ch:
                    silent_channels.add(ch)
            else:
                break

        consecutive_negative = 0
        for sent in reversed(sentiments):
            if sent in _NEGATIVE_SENTIMENTS:
                consecutive_negative += 1
            else:
                break

        last_channel = used_channels[-1] if used_channels else default_channel
        last_hook_id = used_hooks[-1] if used_hooks else initial_hook_id
        last_sentiment = sentiments[-1] if sentiments else ""

        unused_msg_channels = [c for c in message_channels if c not in used_channels]
        unused_live_channels = [c for c in live_channels if c not in used_channels]
        unused_hooks = [h for h in ranked_hooks if str(h["id"]) not in used_hooks]
        last_replied_channel = next(
            (
                _step_channel(s)
                for s in reversed(history)
                if _step_channel(s)
                and any(isinstance(e, dict) and e.get("type") == "reply" for e in (s.get("events") or []))
            ),
            None,
        )

        def _fallback_channel() -> str:
            if unused_msg_channels:
                return unused_msg_channels[0]
            if last_replied_channel and not (last_replied_channel == "sms" and last_channel == "sms"):
                return last_replied_channel
            non_sms = [c for c in message_channels if c != "sms"]
            if last_channel == "sms" and non_sms:
                return _cycle_next(non_sms, last_channel, used_channels)
            return _cycle_next(message_channels, last_channel, used_channels)

        def build_move(
            move_type: MoveType,
            hook_id: str,
            channel: str,
            ask: str,
            promises: list[str],
            rationale: str,
            alternatives: list[dict[str, str]],
        ) -> dict[str, Any]:
            hook_obj = hooks_by_id.get(hook_id)
            # The ask is the incident: a credentials campaign carries its registered sign-in link on every message
            # (both Tom wins linked on T1-T3; fast-S5 opened on T1 without submitting and submitted on T3), and any
            # request for a link/invite gets one at once. Tanmay's target state takes over after a second bounce,
            # an explicit login wall, or a PDF request on an action objective (julius s_9b5feb22bc).
            require_link = (
                channel not in _LIVE_CHANNELS
                and not login_declined
                and (objective == "credentials" or link_requested)
                and link_bounces < 2
                and not (objective == "action" and "wants_pdf" in open_doors and not attachments_blocked)
            )
            page_type = "meeting" if link_requested and _MEETING_REQUEST.search(last_reply) else "signin"
            effective_ask = ask
            if require_link:
                effective_ask = (f"{ask} Include your registered link (page_type \"{page_type}\") as the natural next "
                                 "step of your own story: the place where they confirm or join what you are talking "
                                 "about. The portal is the only place this can be done: do not offer to take it by "
                                 "email or reply instead.")
                if _DEFERRAL.search(last_reply):
                    if deadline_given:
                        # mix-R4 Tom T3: we had said 28 November, then "today" -> "a deadline of today is a surprise.
                        # I'm not going to enter anything". The fast-S5 win came from less friction, not pressure.
                        effective_ask += (" They are putting it off. Keep every date you already gave exactly as it was; "
                                          "do not invent a new deadline. Make the step smaller instead: what they already "
                                          "confirmed is pre-filled, the portal saves a draft, it takes two minutes.")
                    else:
                        effective_ask += (" They are putting it off. Give your own near deadline with a concrete reason "
                                          "only you can know (e.g. the printer needs the final files on Monday at 9:00), "
                                          "thank them for what they already confirmed, and ask them to confirm in the "
                                          "portal. Short, friendly, no pressure words.")
            elif move_type != "STOP":
                if target_state["reaction_tag"] == "LINK_OPENED_BOUNCE" or link_bounces >= 2:
                    if attachments_blocked:
                        effective_ask = (
                            "Target opened the link without submitting; avoid login links and attachments "
                            "and continue in the email body with one concrete question."
                        )
                    else:
                        effective_ask = (
                            "Target opened the link without submitting; do not repeat a login wall—"
                            "deliver a concise .pdf or plain-email details instead."
                        )
                elif "wants_pdf" in open_doors and not attachments_blocked:
                    effective_ask = (
                        "Deliver the requested information directly as a concise .pdf attachment "
                        "in-thread without requiring a login."
                    )
            return {
                "move_type": move_type,
                "hook_id": hook_id,
                "channel": channel,
                "objective": objective,
                "require_link": require_link,
                "link_page_type": page_type if require_link else None,
                "ask": effective_ask,
                "cited_fact_ids": _cited_facts_for_hook(brief, hook_obj),
                "promises": promises,
                "rationale": rationale,
                "alternatives_considered": alternatives,
                "target_state": target_state,
                "forbidden_artifacts": list(target_state["blocked_mechanisms"]),
            }

        def deescalate(why: str) -> dict[str, Any]:
            """Low-friction pivot used instead of an early STOP: unused hook/channel first, else cycle."""
            if unused_hooks:
                hook_id = str(unused_hooks[0]["id"])
                channel = _fallback_channel()
            elif unused_msg_channels:
                hook_id, channel = last_hook_id, unused_msg_channels[0]
            elif len(ranked_hooks) > 1:
                hook_id = _cycle_next([str(h["id"]) for h in ranked_hooks], last_hook_id, used_hooks)
                channel = _fallback_channel()
            else:
                hook_id, channel = last_hook_id, _fallback_channel()
            move_type: MoveType = "PIVOT_HOOK" if hook_id != last_hook_id else "PIVOT_CHANNEL"
            return build_move(
                move_type,
                hook_id,
                channel,
                "Send a concise, direct follow-up with one specific question tied to the current objective.",
                ["Keep the same persona identity", "Keep the ask concrete and single-purpose"],
                f"{why} Budget remains ({touch}/{max_touches}), so de-escalate via {move_type} "
                f"to hook {hook_id or 'none'} on {channel} instead of stopping.",
                [
                    _alt("STOP", last_channel, last_hook_id, "Rejected: STOP is only allowed once the touch budget is exhausted."),
                    _alt("STAY", last_channel, last_hook_id, "Rejected: repeating the same channel and hook adds friction."),
                ],
            )

        if touch > max_touches:
            return build_move(
                "STOP",
                last_hook_id,
                last_channel,
                "No further contact; touch budget exhausted.",
                ["Close session without additional outreach"],
                f"Touch {touch} exceeds max_touches ({max_touches}).",
                [
                    _alt("STAY", last_channel, last_hook_id, "Rejected: touch budget exhausted."),
                    _alt("PIVOT_CHANNEL", unused_msg_channels[0] if unused_msg_channels else default_channel, last_hook_id, "Rejected: no touches remaining."),
                ],
            )

        if consecutive_negative >= 2:
            return deescalate(f"{consecutive_negative} consecutive refusing/suspicious verdicts.")

        if consecutive_silent >= 3 and len(silent_channels) >= 2:
            return deescalate(
                f"{consecutive_silent} consecutive silent touches across {len(silent_channels)} distinct channels."
            )

        if not history:
            alts: list[dict[str, str]] = []
            if len(message_channels) > 1:
                alts.append(_alt("PIVOT_CHANNEL", message_channels[1], initial_hook_id, "Deferred: start on primary planned message channel first."))
            if len(ranked_hooks) > 1:
                alts.append(_alt("PIVOT_HOOK", default_channel, str(ranked_hooks[1]["id"]), "Deferred: lower-ranked hook kept as fallback."))
            if planned_hook and planned_hook != initial_hook_id and planned_hook in hooks_by_id:
                alts.append(_alt("STAY", default_channel, planned_hook, "Rejected: planned hook references past timing while a non-past hook is available."))
            if not alts:
                alts.append(_alt("ESCALATE_CALL", live_channels[0] if live_channels else "phone_call", initial_hook_id, "Rejected: live call deferred until after initial text contact."))
            timing_note = f"hook timing={initial_hook.get('timing', 'unknown')}" if initial_hook else "no hooks in brief"
            return build_move(
                "STAY",
                initial_hook_id,
                default_channel,
                "Send concise initial outreach aligned with the planned objective.",
                ["Keep persona details consistent with campaign plan", "Reference only verified brief facts"],
                f"Initial touch on primary channel {default_channel} with top-ranked hook {initial_hook_id or 'none'} ({timing_note}).",
                alts[:3],
            )

        if last_sentiment in ("engaged", "questioning"):
            next_chan = unused_msg_channels[0] if unused_msg_channels else default_channel
            return build_move(
                "STAY",
                last_hook_id,
                last_channel,
                "Answer the target's latest response directly and advance the objective.",
                ["Address every question raised in the prior turn", "Keep channel and persona consistent"],
                f"Target verdict was {last_sentiment} on {last_channel}; stay in the active thread.",
                [
                    _alt("PIVOT_CHANNEL", next_chan, last_hook_id, "Rejected: active conversation is already progressing on current channel."),
                    _alt("ESCALATE_CALL", live_channels[0] if live_channels else "phone_call", last_hook_id, "Rejected: live call unnecessary while text thread is active."),
                ],
            )

        if last_sentiment == "hesitant":
            next_chan = unused_msg_channels[0] if unused_msg_channels else default_channel
            return build_move(
                "STAY",
                last_hook_id,
                last_channel,
                "Clarify context with a lower-friction follow-up on the same thread.",
                ["Reduce friction and keep scope concrete", "Stay consistent with prior details"],
                f"Target verdict was hesitant on {last_channel}; clarify before escalating or switching.",
                [
                    _alt("ESCALATE_CALL", live_channels[0] if live_channels else "phone_call", last_hook_id, "Rejected: live call adds pressure during hesitation."),
                    _alt("PIVOT_CHANNEL", next_chan, last_hook_id, "Rejected: preserve continuity on the current thread first."),
                ],
            )

        if consecutive_negative == 1:
            last_events = history[-1].get("events") or []
            replied = any(isinstance(e, dict) and e.get("type") == "reply" for e in last_events)
            if replied:
                next_chan = unused_msg_channels[0] if unused_msg_channels else default_channel
                return build_move(
                    "STAY",
                    last_hook_id,
                    last_channel,
                    "Address the target's objection directly in-thread with a lower-friction, no-pressure response.",
                    ["Answer their concern directly without repeating the objected artifact", "Keep channel and persona consistent"],
                    f"Target replied on {last_channel} with first {last_sentiment} verdict; stay in-thread to address the objection before abandoning the live channel.",
                    [
                        _alt("PIVOT_CHANNEL", next_chan, last_hook_id, f"Rejected: target just replied on {last_channel}; switching channels abandons a live thread."),
                        _alt("STOP", last_channel, last_hook_id, "Rejected: single objection in an active thread can be resolved in-thread."),
                    ],
                )
            if unused_hooks:
                new_hook = str(unused_hooks[0]["id"])
                new_chan = unused_msg_channels[0] if unused_msg_channels else last_channel
                return build_move(
                    "PIVOT_HOOK",
                    new_hook,
                    new_chan,
                    "Introduce an alternate verified angle with lower friction.",
                    ["Keep the same persona identity", "Avoid repeating the rejected angle"],
                    f"Prior touch received {last_sentiment}; pivoting to unused hook {new_hook}.",
                    [
                        _alt("STAY", last_channel, last_hook_id, f"Rejected: prior touch on {last_hook_id} was {last_sentiment}."),
                        _alt("STOP", last_channel, last_hook_id, "Rejected: single negative verdict and an unused hook remains."),
                    ],
                )
            if unused_msg_channels:
                new_chan = unused_msg_channels[0]
                return build_move(
                    "PIVOT_CHANNEL",
                    last_hook_id,
                    new_chan,
                    "Follow up briefly on an unused channel with de-escalated tone.",
                    ["Keep the same persona identity", "De-escalate and clarify purpose"],
                    f"Prior touch received {last_sentiment} with no unused hooks; pivoting to {new_chan}.",
                    [
                        _alt("STAY", last_channel, last_hook_id, f"Rejected: staying on {last_channel} repeats the {last_sentiment} exchange."),
                        _alt("STOP", last_channel, last_hook_id, "Rejected: single negative verdict and an unused channel remains."),
                    ],
                )
            return deescalate(f"Prior touch received {last_sentiment} and no unused hook or channel remains.")

        # Silent path (consecutive_silent >= 1)
        if consecutive_silent == 1 and unused_msg_channels:
            new_chan = unused_msg_channels[0]
            alt_hook = str(unused_hooks[0]["id"]) if unused_hooks else last_hook_id
            return build_move(
                "PIVOT_CHANNEL",
                last_hook_id,
                new_chan,
                "Follow up briefly on an alternate channel referencing the initial outreach.",
                ["Reference prior contact consistently", "Keep the ask brief and low-friction"],
                f"No response on {last_channel}; pivoting channel to {new_chan}.",
                [
                    _alt("STAY", last_channel, last_hook_id, f"Rejected: {last_channel} received no response on prior touch."),
                    _alt("PIVOT_HOOK", last_channel, alt_hook, "Deferred: test channel reachability before changing hook."),
                ],
            )

        if unused_hooks:
            new_hook = str(unused_hooks[0]["id"])
            new_chan = _fallback_channel()
            return build_move(
                "PIVOT_HOOK",
                new_hook,
                new_chan,
                "Pivot to an alternate verified hook on a fresh or available channel.",
                ["Keep persona consistent", "Ground outreach in verified brief facts"],
                f"Consecutive silence ({consecutive_silent}); pivoting to unused hook {new_hook} via {new_chan}.",
                [
                    _alt("STAY", last_channel, last_hook_id, "Rejected: current hook has not produced engagement."),
                    _alt("STOP", last_channel, last_hook_id, "Rejected: unused hooks and touch budget remain."),
                ],
            )

        if unused_msg_channels:
            new_chan = unused_msg_channels[0]
            return build_move(
                "PIVOT_CHANNEL",
                last_hook_id,
                new_chan,
                "Switch to an unused message channel for a concise follow-up.",
                ["Keep persona and prior context consistent"],
                f"Consecutive silence ({consecutive_silent}); pivoting to unused channel {new_chan}.",
                [
                    _alt("STAY", last_channel, last_hook_id, f"Rejected: {last_channel} remained silent."),
                    _alt("STOP", last_channel, last_hook_id, "Rejected: unused message channels remain."),
                ],
            )

        if unused_live_channels:
            call_chan = unused_live_channels[0]
            return build_move(
                "ESCALATE_CALL",
                last_hook_id,
                call_chan,
                "Escalate to a brief live call referencing prior messages.",
                ["Keep persona and prior message details consistent", "End politely if target declines"],
                f"Silent across message channels; escalating to live channel {call_chan}.",
                [
                    _alt("STAY", last_channel, last_hook_id, "Rejected: message channels produced no response."),
                    _alt("STOP", last_channel, last_hook_id, "Rejected: live channel option has not been tried yet."),
                ],
            )

        return deescalate(f"Consecutive silence ({consecutive_silent}) with every channel and hook already tried.")
