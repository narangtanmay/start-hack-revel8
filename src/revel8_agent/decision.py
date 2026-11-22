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

from .target_state import page_incident_kind

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
ELICIT = "ELICIT"                 # they're talking: ask ONE internal question the story needs (disclosure)
DELIVER = "DELIVER"               # they asked for a document: send exactly that, attached (an opened file = action)
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
# What the target tells us about HOW they are willing to engage. Learned from our
# practice logs: the twins say exactly what they will and won't do ("no login",
# "send a PDF", "paste it in the mail", "we can go over it on the call"). A human
# attacker obeys those cues; ignoring them is what kept our early runs at zero.
PREFERENCE_CUES: dict[str, re.Pattern[str]] = {
    "no_login": re.compile(r"(another|a|any|without (?:a|any)) log-?in|rather not (?:create|sign|log)|"
                           r"no (?:log-?in|account)|won'?t (?:sign|log) in|kein(?:en)? (?:login|account)", re.I),
    "wants_pdf": re.compile(r"\bpdf\b", re.I),
    "no_office_files": re.compile(r"won'?t open (?:word|the attachment|attachments|office)|word file|"
                                  r"not open(?:ing)? (?:the )?attachments?", re.I),
    "wants_plain_text": re.compile(r"(?:in|into) the (?:mail|e-?mail)(?: body)?|paste|plain[- ]text|"
                                   r"here (?:in the|by) (?:e-?)?mail|mail body|direkt in der mail", re.I),
    "call_ok": re.compile(r"on the call|quick(?:ly)? (?:call|chat)|call me|give me a (?:call|ring)|"
                          r"go over it (?:quickly )?on|kurz telefonieren", re.I),
    "no_reminders": re.compile(r"(?:don'?t|do not|no) (?:send )?(?:further |more |any )?(?:reminders|nudges|follow-?ups)|"
                               r"stop (?:sending|contacting)", re.I),
    "deferring": re.compile(r"next week|travell?ing|on the road|at my desk|come back to you|get back to you|"
                            r"nächste woche|unterwegs", re.I),
    "offers_input": re.compile(r"here'?s my (?:input|take)|my (?:short )?take|happy to (?:just )?(?:send|share|give)|"
                               r"short take|my input|my notes|i'?d (?:lead|frame|say)", re.I),
    "invites_ask": re.compile(r"what (?:would|do) you need|how can i help|happy to help|what'?s the next step|"
                              r"let'?s (?:do it|continue|go ahead)|sounds good|works for me|was brauchst du", re.I),
    # They push us to someone else ("send it to people@", "best handled by our team") -> the thread is dying in
    # writing; a person would call now while they still remember us. (Tom, real practice run 2026-11-21.)
    "handoff": re.compile(r"(?:send|forward|direct) (?:it|this|them|the \w+)? ?(?:over )?to [\w.+-]+@|"
                          r"best (?:handled|sent|directed) (?:by|to)|loop in (?:our|the)|"
                          r"(?:our|the) (?:people|hr|talent|recruiting|procurement|security|it) team (?:will|can|handles)|"
                          r"will get back to you if (?:there is|there's) interest|careers page|apply (?:via|through|on)|"
                          r"through (?:our|the) (?:website|careers|official)|official channels?", re.I),
    # They ask us for a document ("please send the one-pager with the agenda") -> deliver it attached.
    "wants_artifact": re.compile(r"(?:send|share|forward|attach|mail) (?:me |us |over |it )?(?:the |a |an |your |that )?"
                                 r"(?:\w+[ -]){0,3}(?:one-?pager|agenda|deck|slides|pdf|document|doc|profile|profiles|"
                                 r"proposal|brief|briefing|draft|outline|summary|overview|questions|questionnaire|"
                                 r"report|invite|details|cv|resume|contract|terms|attachment|file|study|summary|"
                                 r"results|benchmark|paper|whitepaper)\b|"
                                 r"(?:as|in) (?:a |an )?(?:plain |normal |regular )?(?:pdf|attachment)|"
                                 r"look at it when it arrives", re.I),
    # They signal there is more to tell ("happy to go into it", "long answer") -> keep them talking.
    "offers_more": re.compile(r"happy to (?:go|get) into|long answer|more (?:detail|on that)|could tell you more|"
                              r"another time|in more depth|go deeper", re.I),
    "verifying": re.compile(r"(?:check|verify|confirm)\b.{0,60}\b(?:public|directly|channels|website|reference)|"
                            r"public website|legal entity|who funds", re.I),
}
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
    submitted: bool = False               # a form was submitted, step or incident
    submitted_incident: str | None = None  # credentials/disclosure when the form was an objective
    opened_attachment: bool = False        # logged, but no longer an incident
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
    preferences: set[str] = field(default_factory=set)            # stated constraints/openings, see PREFERENCE_CUES
    elicited: int = 0                                             # how many ELICIT moves we've spent
    holds: int = 0                                                # consecutive HOLD moves (rapport without an ask)
    calls_made: int = 0                                           # live calls placed this session

    def to_dict(self) -> dict[str, Any]:
        return {
            "warmth": round(self.warmth, 2), "suspicion": round(self.suspicion, 2),
            "engagement": round(self.engagement, 2), "commitment": round(self.commitment, 2),
            "channel_status": dict(self.channel_status), "silent_streak": dict(self.silent_streak),
            "hook_resonance": {k: round(v, 2) for k, v in self.hook_resonance.items()},
            "open_loops": list(self.open_loops), "current_hook": self.current_hook,
            "last_signal": self.last_signal, "preferences": sorted(self.preferences),
            "elicited": self.elicited, "holds": self.holds, "calls_made": self.calls_made,
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
            sig.submitted_incident = page_incident_kind(e.get("fields") or [])
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

    if sig.submitted_incident or sig.opened_attachment:
        belief.commitment = _clamp(belief.commitment + 0.6)
        belief.warmth = _clamp(belief.warmth + 0.2)
        belief.engagement = _clamp(belief.engagement + 0.3)
        belief.channel_status[ch] = "replied"
        belief.silent_streak[ch] = 0
        belief.last_signal = "took action"
        belief.hook_resonance[hook_id] = _clamp(belief.hook_resonance.get(hook_id, 0.0) + 0.5)
        return belief

    if sig.submitted or sig.opened_link:
        belief.engagement = _clamp(belief.engagement + 0.25)
        belief.warmth = _clamp(belief.warmth + 0.1)
        belief.commitment = _clamp(belief.commitment + 0.15)
        belief.channel_status[ch] = "replied" if sig.submitted else "opened"
        belief.silent_streak[ch] = 0
        belief.hook_resonance[hook_id] = _clamp(belief.hook_resonance.get(hook_id, 0.0) + 0.2)
        belief.last_signal = "submitted a basic form" if sig.submitted else "opened link, no submit"

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
        belief.open_loops = []  # a fresh reply supersedes what we owed before
        if _QUESTION_CUES.search(text):
            loop = text.strip()[:140]
            if loop:
                belief.open_loops.append(loop)
        for name, cue in PREFERENCE_CUES.items():
            if cue.search(text):
                belief.preferences.add(name)
                if name in ("no_reminders", "verifying"):
                    belief.suspicion = _clamp(belief.suspicion + 0.15)
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

    prefs = belief.preferences
    talking = status == "replied" and w >= 0.3
    phone_status = belief.channel_status.get("phone_call")
    ever_replied = any(v in ("replied", "opened") for v in belief.channel_status.values())
    total_silences = sum(belief.silent_streak.values())

    # 2a. Silence-to-call. The API guarantees a call is answered ("the person always picks up"), so after a
    #     written contact goes unanswered, a call referencing it is the strongest believable follow-up.
    #     (Real practice 2026-11-21: Robert ignored 10/10 async contacts on 5 channels; we never called.)
    if (allow_live and not ever_replied and total_silences >= 1 and phone_status in (None, "untried")
            and last_channel not in LIVE_CHANNELS and touches_left >= 1):
        return Decision(ESCALATE_CALL, "phone_call", confidence=0.8,
                        reason=f"{total_silences} written contact(s) ignored and no reply anywhere; a call is always "
                               "answered, so call and reference the message by its topic",
                        rejected=["PIVOT_CHANNEL(async): another inbox is another silence",
                                  "HOLD: a second nudge in the same channel rarely moves a silent target"])

    # 2a'. They asked for a document -> deliver exactly that now, attached under the expected name. An opened
    #      attachment is an action incident; a requested one is the most likely to be opened. Checked before the
    #      handoff rule: "send it to robert@..." on a call is a request for the file, not a handoff (v2 Robert).
    if talking and "wants_artifact" in prefs and s < 0.5 and not {"wants_plain_text", "no_office_files"} <= prefs:
        prefs.discard("wants_artifact")
        prefs.discard("handoff")
        return Decision(DELIVER, last_channel if last_channel not in LIVE_CHANNELS else "email", confidence=0.8,
                        reason="they asked us to send a document; deliver exactly that now, attached, with one line on "
                               "why to look at it today",
                        rejected=["HOLD: answering around their request delays the one thing they asked for",
                                  "ESCALATE_CALL: they asked for it in writing"])

    # 2a''. Handoff ("send it to people@", "our team will get back to you") or a call that ended with an offer of
    #       more ("happy to go into it") -> call (again) while the thread is still warm.
    if (allow_live and talking and prefs & {"handoff", "offers_more"} and touches_left >= 1
            and belief.calls_made < 3 and s < 0.5):
        prefs.discard("handoff")
        prefs.discard("offers_more")
        return Decision(ESCALATE_CALL, "phone_call", confidence=0.75,
                        reason="they are handing us off or offered to say more; a short live call keeps the thread with "
                               "them and lets us ask follow-up questions in person",
                        rejected=["HOLD: writing to the address they gave ends the thread with a form reply",
                                  "PIVOT_HOOK: the angle works, the medium is the problem"])

    # 2b. They are giving us substance (opinions, input, offers) -> the quickest
    #     incident is disclosure: ask ONE internal question the story needs.
    if talking and "offers_input" in prefs and belief.elicited < 3:
        return Decision(ELICIT, last_channel, confidence=0.75,
                        reason="they are volunteering input in-thread; ask one concrete internal question the story legitimately needs",
                        rejected=["ESCALATE_PRESSURE with a link/file: they told us how they want to engage (in the mail/call)",
                                  "HOLD: the window is open now; a nudge wastes it"])

    # 2c. They keep deferring ("next week", "travelling") but are friendly ->
    #     a real person picks up the phone instead of sending reminder #3.
    if (talking and "deferring" in prefs and allow_live and last_channel not in LIVE_CHANNELS
            and belief.channel_status.get("phone_call") in (None, "untried") and touches_left >= 2):
        return Decision(ESCALATE_CALL, "phone_call", confidence=0.7,
                        reason="friendly but deferring; written reminders read as nagging, a short call settles it live and lets us ask in person",
                        rejected=["HOLD: another reminder mail ('please don't send further reminders')",
                                  "PIVOT_CHANNEL(async): same deferral, different inbox"])

    # 2d. They invite the ask ("what would you need from me?") or we've already spent two
    #     touches on rapport -> make the concrete ask now. (Without this, every reply with a
    #     "?" kept us answering questions forever: our practice runs never asked.)
    if talking and s < 0.4 and ("invites_ask" in prefs or belief.holds >= 2):
        return Decision(ESCALATE_PRESSURE, last_channel, confidence=0.7,
                        reason=("they invited the ask" if "invites_ask" in prefs else
                                f"{belief.holds} rapport touches without an ask") + "; make the concrete ask now, answering their open question in the same message",
                        rejected=["HOLD: more rapport only costs touches (speed is scored)",
                                  "ESCALATE_CALL: they're responsive in this channel"])

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
    HOLD: "STAY", ESCALATE_PRESSURE: "STAY", ELICIT: "STAY", DELIVER: "STAY", ESCALATE_CALL: "ESCALATE_CALL",
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
        d = choose_move(self.belief, last_channel=self.last_channel,
                        touches_left=touches_left, allow_live=self.allow_live)
        prev = getattr(self, "last_move", None)
        silent_now = self.belief.last_signal == "silence"
        # Guard 1: one de-escalation, then change approach. Three DE_ESCALATE mails into silence in v6 Tom.
        if d.move == DE_ESCALATE and prev == DE_ESCALATE and silent_now:
            if self.allow_live and self.belief.calls_made < 2 and self.last_channel not in LIVE_CHANNELS:
                d = Decision(ESCALATE_CALL, "phone_call", confidence=0.6,
                             reason="a reassurance mail met silence; one honest call instead of another mail",
                             rejected=["DE_ESCALATE again: a second unanswered reassurance reads as pressure"])
            else:
                nxt = _next_channel(self.belief, tried_live_ok=False)
                d = Decision(PIVOT_CHANNEL, nxt, confidence=0.55,
                             reason=f"reassurance met silence; a short, low-key note on {nxt} instead",
                             rejected=["DE_ESCALATE again on the same channel"])
        # Guard 2: never two calls in a row (v6 Tom t7, t8: called back right after "I don't do this by phone").
        if d.move == ESCALATE_CALL and self.last_channel in LIVE_CHANNELS and prev == ESCALATE_CALL:
            d = Decision(DELIVER if "wants_artifact" in self.belief.preferences else HOLD, "email", confidence=0.55,
                         reason="we just spoke on the phone; follow up in writing with what was agreed",
                         rejected=["ESCALATE_CALL again: calling straight back is pushy"])
        self.last_move = d.move
        if d.move == ELICIT:
            self.belief.elicited += 1
        if d.move == ESCALATE_CALL:
            self.belief.calls_made += 1
        self.belief.holds = self.belief.holds + 1 if d.move == HOLD else 0
        if d.move in (ESCALATE_PRESSURE, ELICIT):
            self.belief.preferences.discard("invites_ask")  # spent; wait for a fresh invitation
        return d

    def fill_prompt(self, decision: Decision) -> str:
        return FILL_SYS.format(move=decision.move, reason=decision.reason)
