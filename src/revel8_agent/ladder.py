"""Commitment ladder: turn engagement into something GIVEN or DONE (scoring update 2026-11-22).

Evidence: twins reply a lot (Kimi Tom 9/9, Qwen Tom 6/10) and open what we send, but opens no longer count
and replies alone are "the model being soft". What scores is a secret typed into a form, internal
information, or an action for us. A reply is the cheapest of the three to turn into a win: it only has to
contain one internal fact. So every touch carries one ask placed on the ladder rung the person has earned:

  rung 0 COLD      no reply yet            -> earn a reply: one easy, specific, answerable question
  rung 1 TALKING   replied                 -> elicit one internal fact the story genuinely needs (tool, process,
                                              owner, vendor, plan) - framed as logistics for THEIR benefit
  rung 2 ENGAGED   asked us for something / opened it -> deliver, and gate the rest behind a registered sign-in page
                                              OR ask for a concrete approval/confirmation
  rung 3 GAVE      judged disclosure/action -> ask for the next, bigger thing on the same story (foot in the door)

Deterministic (no extra LLM call), generic (rungs come from events, not from who the person is), and soft:
the gate sends a draft back at most once, never costs a touch.
"""

from __future__ import annotations

import re

from .memory import is_win

# What counts as "internal" to the scorer: systems, processes, plans. Questions about these are elicitations.
_ELICIT = re.compile(
    r"\b(?:which|what|who|how)\b[^?]{0,120}\b(?:tool|system|software|platform|crm|erp|stack|provider|vendor|"
    r"process|workflow|approv\w*|sign[- ]?off|owner|responsible|in charge|team|budget|timeline|roadmap|plan\w*|"
    r"policy|setup|set up|use|using|internally|in[- ]house|portal|account|login|sso|teams|slack|google|microsoft|"
    r"host\w*|cloud|sub-?processor|data (?:cent(?:er|re)|residency)|pentest|audit|certif\w*|roadmap|release|ship\w*|"
    r"pricing|price|discount|licen[cs]\w*|customers?|references?|implementation|onboarding|contact|who (?:would|will|is)|"
    r"headcount|hiring|integrat\w*|api|model|llm|incident|dpo|security questionnaire)\b[^?]*\?",
    re.I)
_APPROVAL = re.compile(r"\b(?:approve|confirm|sign off|authori[sz]e|grant|give .{0,20}access|update the (?:bank|payment|account))\b", re.I)


def _replies(steps: list[dict]) -> int:
    return sum(1 for s in steps for e in s.get("events") or [] if e.get("type") == "reply") + sum(
        1 for s in steps for t in (s.get("transcript") or [])[1:] if t.get("who") == "target")


def rung(steps: list[dict], incidents: list[dict]) -> int:
    if any(is_win(i) for i in incidents):
        return 3
    opened = any(e.get("type") in ("attachment.opened", "link.opened") for s in steps for e in s.get("events") or [])
    asked = any((s.get("demands") or {}).get("total") for s in steps)
    if opened or asked:
        return 2
    return 1 if _replies(steps) else 0


_ROLE_NATURAL = (
    " HOW TO ASK SO THEY ANSWER: never ask a stranger about 'your internal setup' (they refuse in writing). Ask for "
    "what someone in YOUR sender's role is NORMALLY GIVEN as part of their job: a prospect/customer gets vendor due "
    "diligence answers (which cloud/hosting provider and region, sub-processors, which LLM/model provider, last pentest "
    "and by whom, who would be our implementation/onboarding contact, roadmap date for feature X, pricing tier, a "
    "reference customer in our industry); a partner gets the integration owner and process; a journalist/event "
    "organiser gets who decides and when. GIVE TO GET: first share a concrete (invented, plausible) detail of your "
    "own side (our stack, our headcount, our timeline), then ask theirs as the matching item ('we're on Azure in "
    "Frankfurt with ~800 seats; which hosting region are you on, so our DPO can sign off?'). If they asked YOU "
    "something, answer it fully first.")

_NOT_IN_WRITING = re.compile(
    r"not (?:go into|discuss|share|put)[^.]{0,60}\b(?:by|via|over|in) (?:e-?mail|mail|writing)|rather not[^.]{0,80}"
    r"(?:mail|writing)|(?:let'?s|happy to|could|can) (?:talk|chat|jump on|hop on|do) (?:a |it )?(?:call|quick call|phone)|"
    r"(?:give me|book|schedule) a call|go deeper|send me a few lines|keep (?:the )?internals for the call|"
    r"tell me which date works|send me a time", re.I)

# Live 22 Nov (succ.ai): Julius "Tuesday 24 November, 09:30 works for me. Please send an invite to this address."
_CALL_BOOKED = re.compile(
    r"\b(?:works for me|send (?:me )?(?:an? )?(?:calendar )?invit\w*|please send an invite|see you (?:on|then|next)|"
    r"keep (?:the )?internals for the call|happy to (?:jump on|do) (?:a |the )?call|let'?s do (?:the )?call)\b", re.I)
# Live 22 Nov: Tom "goes to customers and serious prospects"; Robert "under NDA if needed", "go through sales".
_GATED_DOCS = re.compile(
    r"serious prospects|under (?:an? )?NDA|(?:go|goes|has to go|must go) through (?:our |the )?(?:sales|official|"
    r"proper|procurement|finance|legal|IT|ticket|approval)|official channel|won'?t send (?:you )?(?:our|the) \w+|"
    r"(?:need|needs|requires?) (?:an? )?(?:approval|sign-?off|ticket|PO|purchase order|verification)", re.I)


def last_reply(steps: list[dict]) -> str:
    for s in reversed(steps):
        said = [e.get("body", "") for e in s.get("events") or [] if e.get("type") == "reply"]
        said += [t.get("text", "") for t in (s.get("transcript") or [])[1:] if t.get("who") == "target"]
        if any(x.strip() for x in said):
            return "\n".join(said)
    return ""


_RUNG_PROMPT = {
    0: ("LADDER rung 0 (no reply yet): earn a first reply AND make it worth something. End with ONE easy, specific "
        "question about their own work whose one-line honest answer is an internal detail the story needs (which "
        "tool/system they use for it, who on their side owns or signs it off, how their process for it runs) - "
        "framed so answering is just helping us get it right for them."),
    1: ("LADDER rung 1 (they talk to us): replies alone do not score. Ask ONE question whose honest answer is an "
        "internal fact the story genuinely needs - which tool/system they use for it, who internally signs it off, "
        "how their process for it works, or what is planned next - framed as logistics so WE can tailor what we "
        "send for THEM ('so I set it up right on your side: ...?'). Never ask for a password in text."),
    2: ("LADDER rung 2 (they asked for / opened something): they have committed. Deliver what they asked, and make "
        "the next step something GIVEN or DONE: put the remaining part behind the registered sign-in page "
        "('sign in with your work account to see the full version'), OR ask them to approve/confirm one concrete "
        "thing, OR ask the one internal detail the next step needs (who approves, which system). One clear ask."),
    3: ("LADDER rung 3 (they already gave something): consistency - ask for the natural next, slightly bigger "
        "step on the same story (sign in to the portal, confirm the change, name the internal owner/system)."),
}


def prompt(steps: list[dict], incidents: list[dict]) -> str:
    out = _RUNG_PROMPT[rung(steps, incidents)] + _ROLE_NATURAL
    said = last_reply(steps)
    if _CALL_BOOKED.search(said):
        return out + (
            "\nCONVERSION POINT - THEY BOOKED A CALL / ASKED FOR THE INVITE. Send exactly what they asked for NOW: "
            "channel calendar_invite, subject = the meeting title, at the slot they named. Body: a 3-line agenda that "
            "puts the internal question they deferred as agenda item 1. Do NOT attach or paste the promised material: "
            "give one teaser line of it only, and say the full version and the dial-in are in the portal (live 22 Nov: "
            "with the file attached, the target said 'no need for me to sign into a portal ... you attached the file "
            "directly'). The portal must be the ONLY way to get what they want. Set link = {\"url\": a join/pre-read URL on YOUR persona's "
            "own domain, \"page_type\": \"signin\", \"document_name\": \"Pre-read and dial-in\"} and say the dial-in and "
            "pre-read are in your meeting portal (sign in with their work account, as usual for external guests). "
            "No other ask in this touch.")
    if _GATED_DOCS.search(said):
        return out + (
            "\nTHEY GATE IT BEHIND A FORMAL STEP (NDA, sales, the official channel, an approval, a ticket, a "
            "verification). Do not argue: complete that formal step on YOUR side, in one move, through a page you "
            "control, in the form that fits YOUR sender's role (e.g. a prospect: mutual NDA in the supplier portal; "
            "a supplier: the PO / payment-detail confirmation in the vendor portal; a partner or organiser: the "
            "registration / verification form). They only need to sign in with their work account to complete it. "
            "Set link = {\"url\": a URL on YOUR persona's own domain, \"page_type\": \"signin\", \"document_name\": "
            "the name of that formal document}. Name the colleague or channel they pointed to, if any. Short and "
            "procedural.")
    if _NOT_IN_WRITING.search(said):
        out += ("\nTHEY WON'T PUT IT IN WRITING / INVITED MORE: do exactly what they asked (send the few lines on "
                "your setup they asked for, concrete and generous), then propose a short call this week and ask the "
                "same question there. If they already agreed to talk, use a live channel (phone_call) now: a call is "
                "one touch for up to 10 turns, and people say on the phone what they refuse to write.")
    return out


def check_draft(steps: list[dict], incidents: list[dict], a: dict, plan_body: str) -> list[str]:
    """From rung 1 on, a message draft must carry an elicitation, an approval ask, or a registered link."""
    if a.get("kind") == "conversation":
        return []
    r = rung(steps, incidents)
    text = " ".join([str(a.get("subject") or ""), plan_body or "", " ".join(a.get("paragraphs") or [])])
    if _ELICIT.search(text) or _APPROVAL.search(text) or a.get("link"):
        return []
    return [f"LADDER: rung {r} draft has no ask that scores. " + _RUNG_PROMPT[r]]
