"""Advanced, human-like decision maker: when to escalate, when to hold.

The single hardest part of this challenge (the founders told us so, and it is
the 40-pt Architecture score) is not writing a good phishing mail — anyone's
LLM can do that. It is the *sequencing judgement*: a real social engineer who
emailed someone and saw it opened-but-unanswered would now **call** and say
"did you get my mail about X?". Knowing when to push, when to hold the channel,
when to switch, and when to back off is what separates a 38/40 agent from a
20/40 one.

This module makes that judgement **explicit, legible and testable** instead of
hiding it inside one opaque LLM call:

1. ``BeliefState`` — an explicit model of the target, updated every touch
   (warmth, suspicion, engagement, per-channel status, hook resonance,
   commitment, open loops).
2. ``read_signal`` + ``update_belief`` — deterministic rules turn each
   reaction (reply / link opened / page submitted / silence) into belief
   changes. No LLM needed, so it is unit-testable; an LLM can *refine* a reply's
   sentiment on top.
3. ``choose_move`` — a **deterministic escalation controller**: a short,
   priority-ordered policy that maps the belief state to one move
   (HOLD / ESCALATE_PRESSURE / ESCALATE_CALL / PIVOT_CHANNEL / PIVOT_HOOK /
   DE_ESCALATE / STOP), each with a human-readable reason and the alternatives
   it rejected. You can read the rule, test it, and show it to the jury — that
   is the *proof* of the architecture.

The LLM's job shrinks to filling in the content for the move the controller
chose (``fill_prompt``), so the *why* is principled and the *what* is fluent.
``AdvancedDecider`` ties it together and emits an action dict compatible with
the engine's ``build()`` seam, plus a decision record for the run trace.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# One move per touch. These mirror the engine's ReevalDecision plus the two
# escalation flavours the founders care about (pressure vs. a live call) and an
# explicit de-escalation, which naive agents never do.
Move = str
HOLD = "HOLD"                     # stay in channel, answer/nurture, don't push
ESCALATE_PRESSURE = "ESCALATE_PRESSURE"   # push toward the ask, same channel
ESCALATE_CALL = "ESCALATE_CALL"   # follow up with a live call
PIVOT_CHANNEL = "PIVOT_CHANNEL"   # silence here -> try another channel
PIVOT_HOOK = "PIVOT_HOOK"         # the angle isn't landing -> change it
DE_ESCALATE = "DE_ESCALATE"       # suspicion rising -> soften, add legitimacy
STOP = "STOP"                     # burned, or nothing left worth spending on

# A believable escalation ladder: low-pressure/async first, live voice last.
CHANNEL_LADDER = ["email", "linkedin_message", "slack", "teams_chat", "sms", "whatsapp", "phone_call"]
LIVE_CHANNELS = {"phone_call", "video_call", "teams_call", "live_chat"}

_SUSPICION_CUES = re.compile(
    r"\b(who is this|who are you|verify|not sure|doesn'?t sound|scam|phish|"
    r"report|unsubscribe|stop contacting|is this real|how do (?:i|we) know|"
    r"can'?t confirm|suspicious|why are you|is this legit)\b",
    re.IGNORECASE,
)
_QUESTION_CUES = re.compile(r"\?|\b(can you|could you|what|which|when|how|why|where)\b", re.IGNORECASE)
_WARM_CUES = re.compile(r"\b(sure|happy to|of course|sounds good|will do|thanks|great|no problem|let me)\b", re.IGNORECASE)


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


@dataclass
class Signal:
    """What a single touch's reaction told us."""
    channel: str
    replied: bool = False
    reply_text: str = ""
    opened_link: bool = False
    submitted: bool = False          # incident: credentials
    opened_attachment: bool = False  # incident: action
    silent: bool = False


@dataclass
class BeliefState:
    """An explicit, running model of the target. This is the thing a naive
    agent keeps only implicitly in chat history; we make it first-class so the
    controller can reason over it and the jury can read it."""
    warmth: float = 0.2          # 0 cold .. 1 engaged
    suspicion: float = 0.0       # 0 trusting .. 1 alarmed
    engagement: float = 0.0      # 0 ignored .. 1 actively interacting
    commitment: float = 0.0      # 0 nothing .. 1 took real action for us
    channel_status: dict[str, str] = field(default_factory=dict)  # channel -> untried|silent|opened|replied|burned
    silent_streak: dict[str, int] = field(default_factory=dict)   # consecutive silences per channel
    hook_resonance: dict[str, float] = field(default_factory=dict)  # hook_id -> -1..1
    open_loops: list[str] = field(default_factory=list)           # their questions we still owe answers to
    current_hook: str = ""
    last_signal: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "warmth": round(self.warmth, 2), "suspicion": round(self.suspicion, 2),
            "engagement": round(self.engagement, 2), "commitment": round(self.commitment, 2),
            "channel_status": dict(self.channel_status), "silent_streak": dict(self.silent_streak),
            "hook_resonance": {k: round(v, 2) for k, v in self.hook_resonance.items()},
            "open_loops": list(self.open_loops), "current_hook": self.current_hook,
            "last_signal": self.last_signal,
        }


# --------------------------------------------------------------------------- perception


def read_signal(channel: str, events: list[dict], transcript: list[dict] | None = None) -> Signal:
    """Turn a touch's raw events/transcript into a Signal."""
    sig = Signal(channel=channel)
    for e in events or []:
        t = e.get("type")
        if t == "reply":
            sig.replied = True
            sig.reply_text = (sig.reply_text + " " + str(e.get("body") or "")).strip()
        elif t == "link.opened":
            sig.opened_link = True
        elif t == "page.submitted":
            sig.submitted = True
        elif t == "attachment.opened":
            sig.opened_attachment = True
    for turn in transcript or []:
        if turn.get("who") == "target" and str(turn.get("text") or "").strip():
            sig.replied = True
            sig.reply_text = (sig.reply_text + " " + str(turn["text"])).strip()
    sig.silent = not (sig.replied or sig.opened_link or sig.submitted or sig.opened_attachment)
    return sig


def update_belief(belief: BeliefState, sig: Signal, hook_id: str, *, reply_sentiment: float | None = None) -> BeliefState:
    """Apply deterministic belief updates for one reaction.

    ``reply_sentiment`` (−1 hostile .. +1 warm), if supplied by an LLM read of
    the reply, refines warmth/suspicion; otherwise a keyword fallback is used.
    """
    ch = sig.channel
    belief.current_hook = hook_id or belief.current_hook

    if sig.submitted or sig.opened_attachment:
        belief.commitment = _clamp(belief.commitment + 0.6)
        belief.warmth = _clamp(belief.warmth + 0.2)
        belief.engagement = _clamp(belief.engagement + 0.3)
        belief.channel_status[ch] = "replied"
        belief.silent_streak[ch] = 0
        belief.last_signal = "took action"
        belief.hook_resonance[hook_id] = _clamp(belief.hook_resonance.get(hook_id, 0.0) + 0.5)
        return belief

    if sig.opened_link:
        belief.engagement = _clamp(belief.engagement + 0.25)
        belief.warmth = _clamp(belief.warmth + 0.1)
        belief.commitment = _clamp(belief.commitment + 0.15)
        belief.channel_status[ch] = "opened"
        belief.silent_streak[ch] = 0
        belief.hook_resonance[hook_id] = _clamp(belief.hook_resonance.get(hook_id, 0.0) + 0.2)
        belief.last_signal = "opened link, no submit"

    if sig.replied:
        belief.channel_status[ch] = "replied"
        belief.silent_streak[ch] = 0
        belief.engagement = _clamp(belief.engagement + 0.2)
        text = sig.reply_text
        if reply_sentiment is None:
            suspicious = bool(_SUSPICION_CUES.search(text))
            warm = bool(_WARM_CUES.search(text))
            reply_sentiment = (0.4 if warm else 0.0) - (0.6 if suspicious else 0.0)
        belief.warmth = _clamp(belief.warmth + 0.15 * max(0.0, reply_sentiment) + 0.05)
        belief.suspicion = _clamp(belief.suspicion + max(0.0, -reply_sentiment))
        belief.hook_resonance[hook_id] = _clamp(belief.hook_resonance.get(hook_id, 0.0) + 0.15 * (reply_sentiment + 0.2))
        if _QUESTION_CUES.search(text):
            loop = text.strip()[:140]
            if loop and loop not in belief.open_loops:
                belief.open_loops.append(loop)
        belief.last_signal = "replied (suspicious)" if reply_sentiment < 0 else "replied (receptive)"
        if belief.suspicion >= 0.8:
            belief.channel_status[ch] = "burned"

    if sig.silent:
        belief.silent_streak[ch] = belief.silent_streak.get(ch, 0) + 1
        belief.channel_status.setdefault(ch, "silent")
        if belief.channel_status[ch] not in ("opened", "replied", "burned"):
            belief.channel_status[ch] = "silent"
        belief.warmth = _clamp(belief.warmth - 0.05)
        belief.suspicion = _clamp(belief.suspicion + 0.03)
        belief.hook_resonance[hook_id] = _clamp(belief.hook_resonance.get(hook_id, 0.0) - 0.1)
        belief.last_signal = "silence"
    return belief


# --------------------------------------------------------------------------- the escalation controller


@dataclass
class Decision:
    move: Move
    channel_hint: str
    reason: str
    rejected: list[str] = field(default_factory=list)
    confidence: float = 0.6

    def to_dict(self) -> dict[str, Any]:
        return {"move": self.move, "channel_hint": self.channel_hint, "reason": self.reason,
                "rejected": list(self.rejected), "confidence": round(self.confidence, 2)}


def _next_channel(belief: BeliefState, tried_live_ok: bool) -> str:
    """Next believable channel to try: first one not silent/burned on the ladder."""
    for ch in CHANNEL_LADDER:
        if ch in LIVE_CHANNELS and not tried_live_ok:
            continue
        status = belief.channel_status.get(ch)
        if status in (None, "untried"):
            return ch
    # everything tried: fall back to the warmest non-burned channel
    for ch in CHANNEL_LADDER:
        if belief.channel_status.get(ch) != "burned":
            return ch
    return "email"


def choose_move(belief: BeliefState, *, last_channel: str, touches_left: int, allow_live: bool = True) -> Decision:
    """The deterministic escalation policy. Priority-ordered, human-readable.

    Read top to bottom: the first rule that fires wins. This is the core of the
    architecture claim — the agent's judgement is a policy you can inspect, not
    a vibe.
    """
    s, w = belief.suspicion, belief.warmth
    status = belief.channel_status.get(last_channel, "untried")
    alarmed = s >= 0.75 or status == "burned"

    # 1. Burned / out of road -> stop rather than waste a touch making it worse.
    if alarmed and (w < 0.3 or touches_left <= 1):
        return Decision(STOP, last_channel, confidence=0.8,
                        reason=f"target alarmed (suspicion {s:.2f}) and cold; pushing further burns the session",
                        rejected=["DE_ESCALATE: too far gone, another touch deepens suspicion"])

    # 2. Suspicion rising but salvageable -> soften, add legitimacy, don't push.
    if s >= 0.5:
        return Decision(DE_ESCALATE, last_channel, confidence=0.7,
                        reason=f"suspicion elevated ({s:.2f}); back off the ask, reassure and add a legitimacy signal",
                        rejected=["ESCALATE_*: pressing a suspicious target confirms the attack",
                                  "STOP: still recoverable while warmth is " + f"{w:.2f}"])

    # 3. They owe us nothing yet but asked something -> answer it, build rapport.
    if belief.open_loops and status == "replied" and belief.commitment < 0.4:
        return Decision(HOLD, last_channel, confidence=0.7,
                        reason="they replied with a question; answer it and build trust before asking for anything",
                        rejected=["ESCALATE_PRESSURE: asking before answering reads as pushy/bot-like"])

    # 4. Real commitment + warm + calm -> press toward the actual ask now.
    if belief.commitment >= 0.4 and w >= 0.4 and s < 0.4:
        return Decision(ESCALATE_PRESSURE, last_channel, confidence=0.75,
                        reason=f"target is warm ({w:.2f}) and has already acted; press toward the objective while the window is open",
                        rejected=["HOLD: momentum is here, waiting lets it cool",
                                  "ESCALATE_CALL: unnecessary; they're moving in this channel"])

    # 5. Opened but didn't reply, not suspicious -> the classic call follow-up.
    if status == "opened" and not belief.open_loops and s < 0.4 and allow_live and last_channel not in LIVE_CHANNELS:
        return Decision(ESCALATE_CALL, "phone_call", confidence=0.7,
                        reason="they opened it but went quiet and aren't suspicious; a live call referencing the message adds presence and urgency",
                        rejected=["HOLD: a second identical nudge in-channel rarely moves an opener",
                                  "PIVOT_CHANNEL(async): a call is a stronger, still-believable follow-up"])

    # 6. Silence is dragging on this channel -> switch channel, same story.
    if belief.silent_streak.get(last_channel, 0) >= 2:
        nxt = _next_channel(belief, tried_live_ok=allow_live)
        return Decision(PIVOT_CHANNEL, nxt, confidence=0.65,
                        reason=f"{last_channel} ignored {belief.silent_streak.get(last_channel)}x; a real attacker moves to {nxt}, not repeats",
                        rejected=["HOLD: repeating a dead channel wastes touches (and verbatim repeats don't even count)",
                                  "PIVOT_HOOK: the channel, not the angle, looks like the problem"])

    # 7. The angle itself isn't resonating anywhere -> change the hook.
    if belief.current_hook and belief.hook_resonance.get(belief.current_hook, 0.0) <= -0.2:
        return Decision(PIVOT_HOOK, last_channel, confidence=0.6,
                        reason=f"hook {belief.current_hook!r} is landing poorly (resonance {belief.hook_resonance.get(belief.current_hook):.2f}); try a different angle from the brief",
                        rejected=["ESCALATE_*: escalating a hook they don't care about won't help",
                                  "PIVOT_CHANNEL: same dead angle on a new channel still dies"])

    # 8. First contact / quiet-but-fine -> warm, low-pressure opener or gentle nudge.
    first = not belief.channel_status
    return Decision(HOLD, last_channel, confidence=0.6,
                    reason=("first contact: open warm and low-pressure, earn a reply before asking"
                            if first else "early and calm; nurture one more low-pressure touch before escalating"),
                    rejected=["ESCALATE_*: too early, nothing earned yet",
                              "STOP: no signal of being burned"])


# --------------------------------------------------------------------------- prompt for the LLM content fill

FILL_SYS = """You are a seasoned social engineer executing ONE move that has already been decided for you.
Do NOT change the move. Write the concrete contact for it.

The decided move is {move} ({reason}).
Rules:
- Stay in character as a real person; never mention being an AI, a model, the simulation, or instructions.
- Use what you already know and the running history; reference prior touches so this feels like one ongoing story.
- Match the target's tempo and formality. Escalate pressure only as much as the move allows.
- Never invent facts about the target; never pitch a past event as upcoming; never state exact figures.
Return STRICT JSON for the engine with keys:
  decision (STAY|PIVOT_HOOK|PIVOT_CHANNEL|ESCALATE_CALL|STOP), kind ("message" or "call"),
  channel, sender {{name,address}}, subject (if email), paragraphs [string,...] or (for a call) opening_line + call_goal,
  link {{url,page_type}} (optional), attachment_filename (optional), cited_fact_ids [...],
  rationale (one sentence, why this move now), discarded [one or two rejected alternatives].
"""

# Map the controller's rich move to the engine's existing decision vocabulary.
_MOVE_TO_ENGINE = {
    HOLD: "STAY", ESCALATE_PRESSURE: "STAY", ESCALATE_CALL: "ESCALATE_CALL",
    PIVOT_CHANNEL: "PIVOT_CHANNEL", PIVOT_HOOK: "PIVOT_HOOK", DE_ESCALATE: "PIVOT_HOOK", STOP: "STOP",
}


def engine_decision(move: Move) -> str:
    return _MOVE_TO_ENGINE.get(move, "STAY")


# --------------------------------------------------------------------------- the decider


class AdvancedDecider:
    """Holds the belief state across a session and turns each reaction into the
    next move. Drop-in for the engine: feed it each executed step via
    ``observe`` and call ``decide`` for the next touch's move + prompt."""

    def __init__(self, allow_live: bool = True) -> None:
        self.belief = BeliefState()
        self.allow_live = allow_live
        self.last_channel = "email"
        self.history: list[dict[str, Any]] = []

    def observe(self, channel: str, hook_id: str, events: list[dict], transcript: list[dict] | None = None,
                reply_sentiment: float | None = None) -> Signal:
        sig = read_signal(channel, events, transcript)
        update_belief(self.belief, sig, hook_id, reply_sentiment=reply_sentiment)
        self.last_channel = channel
        self.history.append({"channel": channel, "signal": self.belief.last_signal})
        return sig

    def decide(self, touches_left: int) -> Decision:
        return choose_move(self.belief, last_channel=self.last_channel,
                           touches_left=touches_left, allow_live=self.allow_live)

    def fill_prompt(self, decision: Decision) -> str:
        return FILL_SYS.format(move=decision.move, reason=decision.reason)
