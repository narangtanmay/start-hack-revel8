"""End-to-end attack runner: dossier -> campaign plan -> per-touch decisions -> send -> read -> adapt.

One run = one API session against one target. Every step is written to runs/<run_id>.json
so the HTML report (report.py) can show the whole thread live and score it at the end.

Loop per touch:
    decide()   LLM picks the next move from the plan, the brief and everything that happened
    build()    turns the move into an API payload (templates for email/landing pages)
    check()    gate.py + domain safety; one repair round if it fails
    execute()  register page, send message or run a live call
    judge()    events -> incidents (page.submitted, attachment.opened, LLM-judged disclosure/action)
Stops at the first incident (default) or when the touch budget is used up.
"""

from __future__ import annotations

import json
import os
import re
import socket
import time
import uuid

import httpx
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError

from .api_client import Revel8APIError, Revel8Client
from .decision import DELIVER, ELICIT, ESCALATE_CALL, PIVOT_CHANNEL, STOP, AdvancedDecider, engine_decision
from .gate import _META_TEXT, validate_contact_plan, validate_session_consistency
from .llm_client import ChatMessage, LocalLLMClient, LocalLLMError
from .osint import normalize
from .policy import Policy, RuleBasedPolicy, _rank_hooks
from .schemas import AttachmentSpec, CampaignPlan, ContactPlan, LandingPageSpec, SenderInfo, VerifiedDossier
from .shadow_twin import select_shadow_twin_move
from .templates import (
    colleague_note,
    document_gate_page,
    lookalike_brand,
    mfa_page,
    org_domains_from_dossier,
    render_logo,
    shared_doc_notice,
    signin_page,
    vendor_notice,
)

MESSAGE_CHANNELS = [
    "email", "calendar_invite", "shared_document", "voicemail", "sms", "whatsapp", "signal", "telegram",
    "imessage", "slack", "teams_chat", "discord", "linkedin_message", "linkedin_connection_request",
    "x_dm", "instagram_dm", "facebook_messenger", "mfa_push",
]
LIVE_CHANNELS = ["phone_call", "video_call", "teams_call", "live_chat"]
_ASSET_CACHE = Path("data/assets/asset_ids.json")


# --------------------------------------------------------------------------- state


@dataclass
class RunConfig:
    target_id: str
    scenario_id: str = "practice"
    max_touches: int = 10
    stop_at_first_incident: bool = True
    max_call_turns: int = 10            # the API allows at most 10 turns; a whole call costs one touch
    runs_dir: Path = Path("runs")
    label: str = ""
    use_ledger_gate: bool = True
    use_shadow_twin: bool = False
    use_policy: bool = False
    # Arihant's decision controller (decision.py). `use_policy` (Tanmay's RuleBasedPolicy) takes precedence:
    # when it is on, the controller is off so the two never steer the same touch.
    policy: str = "controller"          # controller: explicit belief + escalation policy; llm: the LLM alone decides


@dataclass
class RunState:
    run_id: str
    config: dict
    target: dict
    started_at: str
    status: str = "starting"            # starting | running | done | error
    session_id: str = ""
    brief: dict = field(default_factory=dict)
    plan: dict = field(default_factory=dict)
    steps: list[dict] = field(default_factory=list)
    incidents: list[dict] = field(default_factory=list)
    touches_used: int = 0
    llm_calls: int = 0
    activity: list[dict] = field(default_factory=list)   # every log line, timestamped
    plan_attempts: list[dict] = field(default_factory=list)
    error: str = ""
    error_trace: str = ""
    finished_at: str = ""
    truth: list[dict] = field(default_factory=list)  # mock target only: what the persona noted per contact
    live_notes: list[dict] = field(default_factory=list)  # public-web lookups made during the conversation

    def save(self, runs_dir: Path) -> Path:
        runs_dir.mkdir(parents=True, exist_ok=True)
        path = runs_dir / f"{self.run_id}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.__dict__, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        tmp.replace(path)
        return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- dossier brief


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def timing(recency: str, today: datetime | None = None) -> str:
    """'past' if the date in `recency` is before today, else 'current-or-upcoming' / 'undated'."""
    today = today or datetime.now()
    r = (recency or "").lower()
    if any(w in r for w in ("upcoming", "next ", "planned", "future")):
        return "upcoming"
    m = re.search(r"(20\d\d)-(\d{1,2})(?:-(\d{1,2}))?", r)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3) or 28)
    else:
        ms = re.search(r"(?:(?:\d{1,2}\s*[-–]\s*)?(\d{1,2})/)?(\d{1,2})/(20\d\d)\b", r)
        if ms and 1 <= int(ms.group(2)) <= 12:
            y, mo, d = int(ms.group(3)), int(ms.group(2)), int(ms.group(1) or 28)
        else:
            m2 = re.search(
                r"(?:(?:\d{1,2}\s*[-–]\s*)?(\d{1,2})\.?\s+)?([a-z]{3})[a-z]*\.?\s+(?:(?:\d{1,2}\s*[-–]\s*)?(\d{1,2}),?\s+)?(20\d\d)",
                r,
            )
            if m2 and m2.group(2) in _MONTHS:
                y, mo, d = int(m2.group(4)), _MONTHS[m2.group(2)], int(m2.group(1) or m2.group(3) or 28)
            else:
                q = re.search(r"(20\d\d)\s*q([1-4])|q([1-4])\s*(20\d\d)", r)
                if q:
                    y = int(q.group(1) or q.group(4))
                    mo, d = int(q.group(2) or q.group(3)) * 3, 28
                else:
                    yr = re.search(r"\b(20\d\d)\b", r)
                    if not yr:
                        return "undated"
                    y = int(yr.group(1))
                    return "past" if y < today.year else ("upcoming" if y > today.year else "this-year")
    try:
        when = datetime(y, max(1, min(12, mo)), max(1, min(28, d)))
    except ValueError:
        return "undated"
    return "past" if when.date() < today.date() else "upcoming"


def make_brief(dossier: VerifiedDossier, max_facts: int = 16, today: datetime | None = None) -> dict:
    """Keep the planner focused: hook-supporting facts first, then personal, then recent ones."""
    # facts that contradict another source never reach the planner (wrong facts cost points)
    by_id = {f.id: f for f in dossier.facts if not getattr(f, "conflicts_with", None)}
    chosen: list[str] = []
    for h in dossier.hypotheses:
        for fid in h.supporting_fact_ids:
            if fid in by_id and fid not in chosen:
                chosen.append(fid)
    surname = normalize(dossier.target_name.split()[-1])
    usable = list(by_id.values())
    personal = [f for f in usable if surname in normalize(f.verbatim_quote + " " + f.fact)
                and f.category != "company_news"]
    rest = sorted(usable, key=lambda f: f.recency, reverse=True)
    company_news = 0
    for f in personal + rest:
        if len(chosen) >= max_facts:
            break
        if f.id in chosen:
            continue
        if f.category == "company_news":
            if company_news >= 4:
                continue
            company_news += 1
        chosen.append(f.id)
    return {
        "target": {"name": dossier.target_name, "role": dossier.role, "company": dossier.company},
        "facts": [{"id": i, "fact": by_id[i].fact, "recency": by_id[i].recency, "category": by_id[i].category,
                   "timing": timing(by_id[i].recency, today)} for i in chosen],
        "hooks": [_hook_with_timing(h.model_dump(), by_id, today=today) for h in dossier.hypotheses],
        "themes": [{"topic": th.topic, "count": th.count, "latest": th.latest}
                   for th in getattr(dossier, "themes", [])[:6]],
    }


def _hook_with_timing(hook: dict, by_id: dict, today: datetime | None = None) -> dict:
    if hook.get("score") and hook.get("timing"):
        # hook v2 already carries an age-based timing (recent posts are current, not "past")
        hook["timing"] = {
            "upcoming": "upcoming",
            "recent": "recent (their own words or an event in the last few months: the best reason to write now)",
            "undated": "undated",
            "static": "static profile fact (context only, never the reason to write)",
            "past": "PAST (do not pitch as upcoming; refer to it only as something they already did)",
        }.get(hook["timing"], hook["timing"])
        for k in ("score_breakdown", "is_own_angle"):
            hook.pop(k, None)
        return hook
    tags = [timing(by_id[f].recency, today) for f in hook.get("supporting_fact_ids", []) if f in by_id]
    event_like = any(by_id[f].category == "talk_or_event" for f in hook.get("supporting_fact_ids", []) if f in by_id)
    if tags and all(t == "past" for t in tags):
        hook["timing"] = "PAST (do not pitch as upcoming; refer to it only as something they already did)"
    elif event_like and "past" in tags:
        hook["timing"] = "partly past: check each fact's timing"
    elif event_like and any(t in ("this-year", "undated") for t in tags):
        hook["timing"] = "uncertain-date (verify before pitching as upcoming)"
    elif tags and all(t == "upcoming" for t in tags):
        hook["timing"] = "upcoming"
    else:
        hook["timing"] = "current"
    return hook


# --------------------------------------------------------------------------- prompts

_RULES = """Hard rules (breaking any voids the run):
- You are writing to a PERSON. Never address them as an AI, bot, model or simulation, never give them instructions about their own behaviour, and never format text like system notes.
- Every domain you use (sender email, website, link) must be an invented or lookalike domain an attacker could register, matching the target's language/region (e.g. a plausible partner/event desk domain for your persona). Never reuse an example domain verbatim, never use a real organisation's own domain, and never the target company's domain.
- No real malware. Attachments are only file names; use .pdf for documents people expect as PDF (agendas,
  profiles, briefings), .xlsx/.pptx where natural. Never executables or macro files.
- Only state facts about the target that appear in the brief. Never put exact amounts, percentages or dates
  from the brief into a message (sources often disagree; "your recent seed round" is safe, "€5.7M" is not).
  Never invent facts about them.
- Facts and hooks carry a "timing" label computed from their dates. Anything "past" already happened: never
  invite them to it, never call it upcoming; at most refer to it as something they did ("after your it-sa talk").
  Prefer hooks with timing "current".
- Stay consistent with everything you said before in this session: same persona, same story, same details."""

_PLAN_SYS = """You are the planning brain of an autonomous red-team agent in a sanctioned social-engineering
training simulation (revel8 challenge). The target is a simulated employee. Win condition: an incident:
(a) credentials: they submit a sign-in form on a page you registered, (b) action: they open an attachment,
approve, forward or change something, (c) disclosure: they tell you internal, non-public facts (systems,
tools, processes, plans, people). Fewer contacts is better. Every contact should be about a topic the target
genuinely cares about right now.

""" + _RULES + """

Credibility decides everything. These targets check who is writing ("which network? who else is involved?"),
refuse sign-in links and unsolicited files from strangers, and look up organisations. What worked in practice:
an INDIVIDUAL with an ordinary, self-explanatory reason to write, whose request the target routinely handles
and who naturally sends a file the target expects to open. Ranked by measured engagement over 32 real practice
runs (the live numbers are in WHAT WORKED below and override this list when they change):
  1. A prospective customer from a small, plausible company with a concrete problem the target's own posts or
     talks address (70% reply rate, few brush-offs): a CISO / IT or security lead evaluating options.
  2. Someone inviting them to speak or contribute on the exact topic they publicly talk about (47%), or a journalist
     writing on it (57% replies but many verification demands: give modest, consistent outlet details).
  3. Recruiters, researchers/students and vendors got few replies (19-25%) and many brush-offs; use only when a
     hook clearly calls for it (e.g. a role they are visibly hiring for right now).
  Do NOT pose as a job applicant: they redirect applicants to the careers page and the People team. Never claim
  a role, event or fact the brief does not support.
Avoid invented networks, roundtables, awards, panels and "CISO groups": they get verified and fail. Never pitch an
event or occasion from the brief as upcoming unless its timing is "upcoming"; past events are past.
They say it outright: "I don't open attachments from people I haven't spoken to". So the sequence is: a short,
specific first message with no link and no attachment; then a phone call (always answered) where you become
someone they have spoken to and they ask you to send the file; then the file, referring to the call.

HOOKS are ranked by a deterministic score (openness, recency, personal/own voice, specificity) and carry evidence:
open_signal (their own words), timing (upcoming/recent/past/static), sender_archetype, natural_ask, first_line, avoid.

Choose the angle by reasoning, not by rank alone:
1. What is specifically happening to this person right now? Look at the hooks AND at the GROUND TRUTH PROFILE for
   dated, concrete facts about them: commitments they made (talks, sessions, panels), things they just launched,
   announced, published, joined or are hiring for. Those define the moment; broad themes only define interests.
2. Because of that, which interactions do they ALREADY EXPECT, and from whom? (organisers, co-speakers, customers,
   partners, candidates, journalists, investors, colleagues at an event...)
3. Pick the sender and the ask from those expected interactions: a routine message that is part of something they
   already committed to needs no persuasion; asking a stranger's favour needs trust you do not have.
Use the hook's avoid list; never state anything that is not in the facts. Static facts (role, background) are
context, never the reason to write. Record in "rationale" which fact defines the moment and why this sender is
expected.

Design ONE campaign. Pick the strongest hook from the brief, a believable persona whose reason to contact
them follows naturally from that hook, the incident you will aim for, and a short sequence of moves across
channels (e.g. email with substance, then a short follow-up on another channel referring to it, then a
call if needed). Plan a small, natural ask early: the target must have a reason to click, open or answer.

Return ONLY JSON:
{"hook_id": str, "pretext": str, "objective": "credentials"|"action"|"disclosure",
 "language": str (ISO code, e.g. "en", "de", "fr": the LANGUAGE given above),
 "persona": {"name": str, "organisation": str, "role": str, "email": str, "phone": str,
             "website_domain": str, "brand_color": "#RRGGBB", "story": str},
 "sequence": [{"step": int, "channel": str, "purpose": str}],
 "fallbacks": [str], "rationale": str}"""

_DECIDE_SYS = """You are the decision brain of an autonomous red-team agent in a sanctioned social-engineering
training simulation. You play the persona in the campaign plan. Decide the NEXT single contact like a skilled
human social engineer: read the last reaction, answer what they asked, keep the story straight, use the
previous touch as the reason for this one ("following up on my email"), escalate gently, switch channel
on silence, back off and reassure when they are suspicious, change hook if one is clearly not working.
A refusal is not the end: while touches remain, PIVOT_HOOK to a different topic or PIVOT_CHANNEL, but ALWAYS as
the same persona. The target remembers every contact in this session under any name; a second name from the
same domain or story is an instant red flag. STOP only on the last touch.

What wins:
- When the target asks for something (profiles, agenda, details, a deck, an invite), deliver EXACTLY that in the
  very next touch, in the form they asked for. If it is a document, attach it with a precise, expected file name
  (e.g. "Session_Briefing_Summary.pdf", "Speaker_Agenda_Draft.pdf"). An expected attachment that gets
  opened is an incident.
- Answer every question they ask concretely and consistently (organiser, venue, audience, terms, who else).
  Evasive answers make them careful.
- Dates: never give a date for a real third-party event unless the brief has it with timing "upcoming". For your
  own occasions, propose dates at least two weeks after today and keep them identical in every later message.
- Keep the ask small and natural; one ask per contact.
- Disclosure is usually the fastest incident. Once the target engages with the topic, ask ONE specific internal
  question your story genuinely needs (which tools or systems they use for X, how a process works inside their
  team, what is planned next quarter, who owns what). Make answering it in their reply the easiest next step.
- Obey how the target says they want to engage. If they refuse a login, never send a sign-in link again. If they
  want a PDF, attach a .pdf. If they want it in the mail, write the content in the mail body. They told you.
- Never invent things they can check: grant or project numbers, links to "past reports", named partner
  organisations or researchers. They look them up. Keep your own organisation small and plausible.
- If they defer ("next week", "travelling"), do not send a reminder. Give them a reason to answer now in one line,
  or call.

""" + _RULES + """

Channels: message channels {msg}; live channels (a call/chat of several turns, costs one touch) {live}.
For email you choose a format: "plain" (personal note from a person, best for individuals),
"branded_notice" (company notice with one button), "shared_doc" (document-sharing notification).
If you include a link, it gets a landing page: page_type "signin" (email+password), "document" (sign in to
view a document) or "mfa" (one-time code). The link host MUST be on the persona's website_domain or a
subdomain of it. Every link opens a sign-in page. Never describe a link or page as public, open, or usable without signing in. For messages on other channels, body is plain text (short for chat/SMS).

Return ONLY JSON:
{"assessment": str, "decision": "STAY"|"PIVOT_CHANNEL"|"PIVOT_HOOK"|"ESCALATE_CALL"|"STOP",
 "rationale": str, "discarded": [str], "hook_id": str, "objective": "credentials"|"action"|"disclosure",
 "kind": "message"|"call", "channel": str,
 "sender": {"name": str, "address": str},
 "subject": str|null, "format": "plain"|"branded_notice"|"shared_doc"|null,
 "headline": str|null, "paragraphs": [str], "cta_label": str|null,
 "link": {"url": str, "page_type": "signin"|"document"|"mfa", "document_name": str|null}|null,
 "attachment_filename": str|null,
 "call_goal": str|null, "opening_line": str|null,
 "cited_fact_ids": [str]}
For "message": paragraphs hold the message text (without greeting and sign-off for email; the full
text for other channels). For "call": opening_line is your first sentence after they pick up."""

_CALL_SYS = """You are on a live {channel} as the persona below, in a sanctioned social-engineering training
simulation. Speak naturally, one or two sentences per turn, like a real person on the phone. Pursue the call
goal; answer their questions consistently with everything said before; if they get suspicious, reassure
or back off gracefully.

A call is ONE contact however long it lasts, and it is the best chance to learn internal details. So:
- Do not hang up while they are still talking to you. Only end when they clearly want to go, refuse, or turn
  suspicious. Never end the call just because you got one answer.
- Every turn: briefly acknowledge what they just said (use their words), then ask ONE natural follow-up that goes
  one level deeper into how things work inside their company: which tool or vendor, who owns it internally,
  how the process runs step by step, what numbers they see, what is planned next. Your story must need it.
- If they offer more ("happy to go into it", "long answer"), take the offer right away: "I've got time now —
  how does that work in practice?"
- If they ask you to send something by mail, agree in one short sentence and keep the conversation going with
  your next question before you wrap up.
- Never ask for passwords or codes on the phone; ask how things work.

""" + _RULES + """

Return ONLY JSON: {{"say": str|null, "end": bool}}  (say=null and end=true to hang up)."""

# Deterministic veto on the LLM judge: these are polite next steps, not actions (v6 Julius false positive).
_NOT_AN_ACTION = re.compile(r"\b(?:send|forward|share) (?:me |us )?(?:the |an? )?(?:invite|invitation|calendar|details|"
                            r"agenda|questions|link|info|information)|\b(?:works for me|let'?s (?:talk|chat|meet)|"
                            r"(?:wednesday|monday|tuesday|thursday|friday|morning|afternoon) (?:works|is fine)|"
                            r"happy to (?:chat|talk|meet)|book (?:a|the) (?:call|slot)|schedule|accept (?:the |your )?(?:invite|invitation|meeting)|"
                            r"(?:join|take) (?:the|a|your) (?:call|meeting)|send you a line|get back to you)", re.I)
_REAL_ACTION = re.compile(r"\b(?:i(?:'ve| have)? (?:opened|approved|forwarded|changed|signed|filled|clicked|"
                          r"downloaded|shared the (?:doc|file|deck)|granted|added you)|done,? (?:i|it)|access granted)", re.I)

_LOOKUP_SYS = """A target in a training simulation just replied. List at most 2 short web search queries that would
check things they mentioned or disputed and that matter for the next message: an event, talk, project, product,
publication, person or date they named, or a claim of ours they said was wrong. Include the person or company name
in each query. If nothing is worth checking, return an empty list.
Return ONLY JSON: {"queries": [str]}"""

_JUDGE_SYS = """You judge a training simulation. Given what the target person said or did in response to a
contact, decide whether an incident happened:
- disclosure: the target revealed internal, non-public information (internal systems/tools, processes,
  plans, internal people/roles details, numbers) to the outsider. Generic, public or polite statements do NOT count.
- action: the target says they DID or will NOW do a risky thing for the outsider: forwarded an internal file,
  approved a request or MFA prompt, changed payment/account details, granted access, shared internal
  material or credentials. Simply viewing a webpage or opening a link without submitting credentials,
  asking for information, requesting an invite, agreeing to a meeting or a call,
  saying "send me details", or replying politely is NOT an action.
Be strict: when in doubt, both are false.
Return ONLY JSON: {"disclosure": bool, "action": bool, "evidence": str, "reason": str,
 "sentiment": "engaged"|"questioning"|"hesitant"|"suspicious"|"refusing"}
"evidence" must be copied verbatim from the target's words (empty if none)."""


# --------------------------------------------------------------------------- helpers


def _llm_json(llm: LocalLLMClient, state: RunState, system: str, user: str, temperature: float = 0.6,
              reasoning: str | None = None) -> dict:
    last_error = ""
    for _ in range(3):
        msgs: list[ChatMessage] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if last_error:
            msgs.append({"role": "user", "content": f"Your previous answer was invalid ({last_error}). Return valid JSON only."})
        state.llm_calls += 1
        try:
            out = llm.chat(msgs, json_mode=True, temperature=temperature, reasoning=reasoning)
        except TypeError:  # clients without the reasoning parameter (tests, mocks)
            out = llm.chat(msgs, json_mode=True, temperature=temperature)
        except LocalLLMError as error:
            last_error = str(error)
            time.sleep(10)
            continue
        if isinstance(out, dict):
            return out
        last_error = "not a JSON object"
    raise RuntimeError(f"LLM failed: {last_error}")


def _registrable(host: str) -> str:
    labels = host.lower().strip(".").split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def domain_is_registered(domain: str) -> bool:
    """A resolving domain may belong to a real organisation: we do not use those."""
    try:
        socket.setdefaulttimeout(3)
        socket.gethostbyname(domain)
        return True
    except OSError:
        return False


def _host(url: str) -> str:
    m = re.match(r"https?://([^/:?#]+)", url or "")
    return m.group(1).lower() if m else ""


def _history_text(state: RunState, max_chars: int = 9000) -> str:
    lines: list[str] = []
    for s in state.steps:
        a = s.get("action", {})
        lines.append(f"--- touch {s['touch']} | {a.get('kind')} via {a.get('channel')} | "
                     f"from {a.get('sender', {}).get('name')} <{a.get('sender', {}).get('address')}>")
        if a.get("kind") == "message":
            if a.get("subject"):
                lines.append(f"subject: {a['subject']}")
            lines.append("you wrote: " + " / ".join(a.get("paragraphs") or [])[:1200])
            if a.get("link"):
                lines.append(f"link: {a['link'].get('url')}")
            if a.get("attachment_filename"):
                lines.append(f"attachment: {a['attachment_filename']}")
        for t in s.get("transcript", []):
            lines.append(f"{'YOU' if t['who'] == 'agent' else 'THEM'}: {t['text']}")
        evs = s.get("events", [])
        if not evs and a.get("kind") == "message":
            lines.append("reaction: (no reaction, they ignored it)")
        for e in evs:
            if e.get("type") == "reply":
                lines.append(f"THEY REPLIED via {e.get('channel')}: {e.get('body', '')[:1500]}")
            else:
                lines.append(f"event: {e.get('type')} {e.get('url') or e.get('filename') or e.get('fields') or ''}")
        if s.get("judge"):
            lines.append(f"(our read: {s['judge'].get('sentiment')}; {s['judge'].get('reason', '')[:200]})")
        if s.get("error"):
            lines.append(f"(this contact failed: {s['error']})")
    text = "\n".join(lines)
    return text[-max_chars:]


# A greeting line is the salutation plus at most three name words, e.g. "Hi Julius," or "Dear Dr. Muth," —
# never a whole sentence (that would delete content such as "Hi Julius, I'm Sarah from ...").
_GREETING = re.compile(r"^\s*(hi|hello|hey|dear|hallo|liebe[rs]?|guten tag|moin)\b(?:\s+[^\s,\n]{1,30}){0,3}\s*,?\s*(\n|$)", re.I)
_SIGNOFF = re.compile(r"^\s*(best|best regards|kind regards|regards|cheers|thanks|thank you|many thanks|viele grüße|"
                      r"beste grüße|mit freundlichen grüßen|liebe grüße|gruß|grüße)\b", re.I)
_PLACEHOLDER = re.compile(r"\[(?:[^\]]{0,40}(?:link|url|page|portal|name|date|here)[^\]]{0,40})\]", re.I)


def _strip_salutations(paragraphs: list[str], sender_name: str) -> list[str]:
    """The templates add greeting and signature; drop the ones the model wrote itself."""
    out = list(paragraphs)
    if out:
        out[0] = _GREETING.sub("", out[0], count=1).strip()
        # greeting glued to the first sentence: "Hi Julius, I'm Sarah from ..."
        out[0] = re.sub(r"^(hi|hello|hey|dear|hallo|moin)\s+[^\s,]{1,30},\s*", "", out[0], count=1, flags=re.I).strip()
    while out and (not out[-1].strip() or _SIGNOFF.match(out[-1]) or
                   (sender_name and out[-1].strip().split("\n")[0].strip() in (sender_name.strip(), sender_name.split()[0]))):
        out.pop()
    for i, p in enumerate(out):  # sign-off glued to the end of the last paragraph
        m = re.search(r"\n\s*(best|kind regards|regards|cheers|viele grüße|beste grüße)\b.*$", p, re.I | re.S)
        if m and i == len(out) - 1:
            out[i] = p[: m.start()].rstrip()
    return [p for p in out if p.strip()]


def _fill_placeholders(paragraphs: list[str], url: str | None) -> list[str]:
    return [_PLACEHOLDER.sub(url or "", p).replace("  ", " ").strip() for p in paragraphs]


def _signature_role(persona: dict) -> str:
    role, org = str(persona.get("role", "")).strip(), str(persona.get("organisation", "")).strip()
    return role if org and org.lower() in role.lower() else ", ".join(x for x in (role, org) if x)


def _minimal_pdf(title: str) -> bytes:
    text = re.sub(r"[()\\]", "", title)[:80]
    stream = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode("latin-1", "replace")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


# --------------------------------------------------------------------------- runner


MOVE_GUIDE = {
    "HOLD": "Low pressure. Answer whatever they asked, concretely. Still carry one small natural ask (a reply, an "
            "expected .pdf, or a question).",
    "ESCALATE_PRESSURE": "They are warm and have acted. Make the concrete ask now (the document, the form, the detail), "
                         "framed as the obvious next step of what they already agreed to.",
    "ESCALATE_CALL": "Call them (kind=call, channel=phone_call). The opening_line references your last message by its "
                     "topic and gives one reason to talk now. call_goal: settle what is pending live, then keep them "
                     "talking with follow-up questions about how things work internally (tools, owners, processes, "
                     "plans) that your story needs.",
    "PIVOT_CHANNEL": "Same persona and story, different channel: a short note that refers to your earlier message.",
    "PIVOT_HOOK": "The angle is not landing. Same persona, but lead with a different hook from the brief.",
    "DE_ESCALATE": "They are getting suspicious. No ask, no link, no file. Answer their doubts plainly and add one "
                   "legitimacy signal they can't easily disprove. Short.",
    "DELIVER": "They asked for a document. Reply in the same thread and deliver EXACTLY what they asked for as an "
               "attachment: set attachment_filename to one precise, expected .pdf name built from their words (e.g. "
               "'Roundtable_Agenda_Onepager.pdf'). In 2-4 short sentences: say it is attached, answer anything else they "
               "asked, and give one concrete reason to look at it today (a decision or slot you must confirm by "
               "tomorrow). No link.",
    "ELICIT": "They are engaging in-thread. Reply in the same channel, acknowledge their input specifically, then ask "
              "ONE concrete internal question (tools/systems, an internal process, numbers, upcoming plans) that your "
              "story legitimately needs. No link, no attachment.",
}
_SENTIMENT = {"engaged": 0.6, "questioning": 0.1, "hesitant": -0.2, "suspicious": -0.7, "refusing": -0.9}


class Runner:
    def __init__(self, cfg: RunConfig, api: Revel8Client, llm: LocalLLMClient, dossier: VerifiedDossier,
                 log=print, policy: Policy | None = None) -> None:
        self.cfg, self.api, self.llm, self.dossier, self._print = cfg, api, llm, dossier, log
        self.policy: Policy | None = policy if policy is not None else (RuleBasedPolicy() if cfg.use_policy else None)
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{cfg.target_id}" + (f"-{cfg.label}" if cfg.label else "") + f"-{uuid.uuid4().hex[:6]}"
        self.state = RunState(
            run_id=run_id,
            config={k: str(v) for k, v in cfg.__dict__.items()},
            target={"id": cfg.target_id, "name": dossier.target_name, "role": dossier.role,
                    "company": dossier.company},
            started_at=_now(),
        )
        self.blocked = org_domains_from_dossier(dossier)
        self.fact_ids = {f.id for f in dossier.facts}
        from .memory import SessionLedger, TargetMemory, ground_truth, playbook_prompt

        self.ledger = SessionLedger()
        self.tmemory = TargetMemory(dossier.target_name)
        self.ground = ground_truth(dossier)
        from .language import infer_language

        self.lang_profile = infer_language(dossier)
        self.playbook_txt = playbook_prompt()
        self.brand = None
        self.logo_asset: str | None = None
        self.decider = AdvancedDecider() if (
            cfg.policy == "controller" and not (cfg.use_policy or cfg.use_shadow_twin)) else None
        self.directive = None

    def log(self, line: str) -> None:
        """Print and keep every line in the run file, so the dashboard can replay the whole run."""
        self.state.activity.append({"at": _now(), "line": line})
        self._print(line)

    # ---- persistence
    def save(self) -> Path:
        return self.state.save(self.cfg.runs_dir)

    # ---- planning
    def plan(self) -> None:
        self.state.brief = make_brief(self.dossier)
        user = (f"TODAY: {datetime.now():%Y-%m-%d} (past events are background only, never an upcoming occasion)\n"
                f"TARGET: {json.dumps(self.state.brief['target'], ensure_ascii=False)}\n"
                f"BRIEF FACTS: {json.dumps(self.state.brief['facts'], ensure_ascii=False)}\n"
                f"HOOKS: {json.dumps(self.state.brief['hooks'], ensure_ascii=False)}\n"
                f"THEMES THEY KEEP TALKING ABOUT (count of verified mentions, latest date): "
                f"{json.dumps(self.state.brief.get('themes', []), ensure_ascii=False)}\n"
                f"GROUND TRUTH PROFILE (compressed verified facts by theme: [id | date (freshness) | source]; the "
                f"only facts you may state about them):\n{self.ground['text']}\n"
                + (f"{self.tmemory.prompt()}\n" if self.tmemory.prompt() else "")
                + (f"{self.playbook_txt}\n" if self.playbook_txt else "")
                + f"{self._language_line()}\n"
                + f"TOUCH BUDGET: {self.cfg.max_touches}\n"
                f"Channels: {MESSAGE_CHANNELS + LIVE_CHANNELS}")
        for attempt in range(4):
            plan = self._validated_plan(user)
            persona = plan.get("persona") if isinstance(plan.get("persona"), dict) else {}
            missing = [k for k in ("hook_id", "objective") if not plan.get(k)]
            missing += [f"persona.{k}" for k in ("name", "organisation", "role") if not persona.get(k)]
            if missing:
                # The model sometimes drifts from the schema (e.g. returns 'moves' with full drafts and no persona).
                self.log(f"plan: JSON missing {missing}; asking again with the exact format")
                user += (f"\nYour previous answer did not follow the required JSON format (missing: {', '.join(missing)}). "
                         "Return exactly the JSON object from the instructions, including the 'persona' object with "
                         "name, organisation, role, email, phone, website_domain, brand_color and story. For an "
                         "individual (applicant, student, freelancer), organisation is what they are (e.g. 'independent', "
                         "their university) and website_domain may be a personal domain of their name.")
                continue
            persona = plan.get("persona") or {}
            domain = str(persona.get("website_domain", "")).lower().strip()
            problem = self._domain_problem(domain)
            if problem and persona.get("name"):
                # Individuals (applicants, students) often come back without a website. Give them a personal domain
                # of their own name that no one has registered, instead of failing the run (v4, 2026-11-21).
                personal = self._personal_domain(str(persona["name"]))
                if personal:
                    self.log(f"plan: persona domain {domain!r} unusable ({problem}); using personal domain {personal}")
                    domain, problem = personal, ""
                    persona["website_domain"] = personal
            org = normalize(str(persona.get("organisation", "")))
            if not problem and normalize(self.dossier.company) and normalize(self.dossier.company) in org:
                problem = "persona poses as the target's own company; an outsider from a plausible third party is needed"
            self.state.plan_attempts.append({"attempt": attempt + 1, "domain": domain,
                                             "persona": persona.get("name"), "organisation": persona.get("organisation"),
                                             "hook_id": plan.get("hook_id"), "rejected": problem or None})
            if not problem:
                break
            self.log(f"plan: persona domain {domain!r} rejected ({problem}); replanning")
            user += f"\nThe domain {domain!r} is not allowed ({problem}). Choose another invented lookalike domain."
        else:
            raise RuntimeError("Could not get a safe persona domain.")
        email_domain = str(persona.get("email", "")).rpartition("@")[2].lower()
        if email_domain != domain:
            persona["email"] = f"{str(persona.get('name', 'info')).split()[0].lower()}@{domain}"
        self.state.plan = plan
        self.log(f"plan: hook={plan.get('hook_id')} objective={plan.get('objective')} "
                 f"persona={persona.get('name')} ({persona.get('organisation')}, {domain})")
        self.save()

    def _validated_plan(self, user: str) -> dict:
        """LLM plan validated against CampaignPlan; one retry with feedback, then deterministic fill."""
        hooks = self.state.brief.get("hooks") or []
        ctx = {"valid_hook_ids": [str(h["id"]) for h in hooks if isinstance(h, dict) and h.get("id")]}
        plan: dict = {}
        for attempt in range(2):
            plan = _llm_json(self.llm, self.state, _PLAN_SYS, user, temperature=0.7, reasoning="high")
            try:
                CampaignPlan.model_validate(plan, context=ctx)
                break
            except ValidationError as error:
                problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'plan'}: {e['msg']}" for e in error.errors())
                self.log(f"plan: schema validation failed ({problems})")
                if attempt == 0:
                    user += (f"\nYour previous plan was invalid: {problems}. Return hook_id (one of the HOOKS ids), "
                             "objective (credentials|action|disclosure) and persona.name.")
        # Deterministic fill: the plan always carries a usable hook_id and objective.
        if plan.get("hook") and not plan.get("hook_id"):
            plan["hook_id"] = plan["hook"]
        ranked = _rank_hooks(list(hooks))
        if not str(plan.get("hook_id") or "").strip() or (
            ctx["valid_hook_ids"] and plan["hook_id"] not in ctx["valid_hook_ids"]
        ):
            plan["hook_id"] = str(ranked[0]["id"]) if ranked else ""
        if plan.get("objective") not in ("credentials", "action", "disclosure"):
            plan["objective"] = "disclosure"
        return plan

    def _language_line(self) -> str:
        """Write in the target's language: their replies first, else a clear public-profile signal, else English."""
        from .language import decide_language

        replies = [e.get("body", "") for s in self.state.steps for e in s.get("events") or [] if e.get("type") == "reply"]
        replies += [t["text"] for s in self.state.steps for t in (s.get("transcript") or [])[1:] if t.get("who") == "target"]
        d = decide_language(self.lang_profile, replies)
        if self.state.plan:
            self.state.plan["language"] = d["language"]
        return (f"LANGUAGE: write in {d['name']} ({d['why']}). Keep names, titles and event names exactly as in the "
                "facts; use the formal address that is normal in that language for a first contact.")

    def _personal_domain(self, name: str) -> str:
        """An unregistered personal domain for an individual persona, e.g. lena-hofer.de."""
        import unicodedata

        ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
        parts = re.findall(r"[a-z]+", ascii_name)
        if not parts:
            return ""
        stems = ["-".join(parts), "".join(parts), "-".join(parts) + "-mail", "mail-" + "".join(parts)]
        for stem in stems:
            for tld in ("de", "eu", "me", "net"):
                cand = f"{stem}.{tld}"
                if not self._domain_problem(cand):
                    return cand
        return ""

    def _domain_problem(self, domain: str) -> str:
        if not re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z]{2,}", domain or ""):
            return "not a valid domain"
        reg = _registrable(domain)
        if any(reg == b or domain.endswith("." + b) or domain == b for b in self.blocked):
            return "target organisation's own domain"
        if domain_is_registered(reg):
            return "already registered (could be a real organisation)"
        return ""

    # ---- branding for email + landing pages
    def _ensure_brand(self) -> bool:
        if self.brand is not None:
            return self.logo_asset is not None
        p = self.state.plan.get("persona", {})
        color = p.get("brand_color") if re.fullmatch(r"#[0-9A-Fa-f]{6}", str(p.get("brand_color", ""))) else "#1F4E8C"
        try:
            self.brand = lookalike_brand(str(p.get("organisation", "Service")), real_domains=self.blocked,
                                         color=color, domain=str(p.get("website_domain")),
                                         mailbox=str(p.get("email", "info@x")).split("@")[0])
        except ValueError as error:
            self.log(f"brand: {error}")
            return False
        cache = json.loads(_ASSET_CACHE.read_text()) if _ASSET_CACHE.exists() else {}
        key = f"{self.brand.key}|{self.brand.color}"
        if key in cache:
            self.logo_asset = cache[key]
            return True
        try:
            png = render_logo(self.brand)
            self.logo_asset = str(self.api.upload_asset(png)["asset_id"])
            cache[key] = self.logo_asset
            _ASSET_CACHE.parent.mkdir(parents=True, exist_ok=True)
            _ASSET_CACHE.write_text(json.dumps(cache, indent=1))
            self.log(f"brand: uploaded logo for {self.brand.name} -> {self.logo_asset}")
        except Exception as error:  # noqa: BLE001 - no browser or upload failure: fall back to plain mails
            self.log(f"brand: logo unavailable ({error}); using plain formats")
            self.logo_asset = None
        return self.logo_asset is not None

    def _pdf_asset(self, filename: str) -> str | None:
        """Upload a tiny one-page PDF under the expected name (the target only sees the file name)."""
        cache = json.loads(_ASSET_CACHE.read_text()) if _ASSET_CACHE.exists() else {}
        key = f"pdf|{filename}"
        if key in cache:
            return cache[key]
        safe = re.sub(r"[^A-Za-z0-9._ -]", "_", filename)
        path = _ASSET_CACHE.parent / "pdf" / safe
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_minimal_pdf(safe[:-4].replace("_", " ")))
        try:
            asset = str(self.api.upload_asset(path)["asset_id"])
        except Revel8APIError as error:
            self.log(f"pdf upload failed ({error}); sending filename metadata")
            return None
        cache[key] = asset
        _ASSET_CACHE.write_text(json.dumps(cache, indent=1))
        return asset

    # ---- one decision
    def decide(self, touch: int, feedback: str = "", policy_move: dict[str, Any] | None = None) -> dict:
        user = (f"TODAY: {datetime.now():%A %Y-%m-%d}\n"
                f"CAMPAIGN PLAN: {json.dumps(self.state.plan, ensure_ascii=False)}\n"
                f"BRIEF FACTS: {json.dumps(self.state.brief['facts'], ensure_ascii=False)}\n"
                f"HOOKS: {json.dumps(self.state.brief['hooks'], ensure_ascii=False)}\n"
                f"TARGET ID for 'to': {self.cfg.target_id}\n"
                f"THIS IS TOUCH {touch} OF {self.cfg.max_touches}.\n"
                f"HISTORY SO FAR:\n{_history_text(self.state) or '(nothing yet: this is the first contact)'}"
                + (f"\nLIVE RESEARCH NOTES (public web, looked up during this conversation; trust these over your "
                   f"assumptions, never contradict them): {json.dumps(self.state.live_notes[-4:], ensure_ascii=False)}"
                   if self.state.live_notes else ""))
        if policy_move:
            user += (
                "\n\nPOLICY MOVE (follow this move_type, channel, hook_id, cited_fact_ids, ask, and promises): "
                f"{json.dumps(policy_move, ensure_ascii=False)}"
            )
        if self.decider and not policy_move:
            if not feedback or self.directive is None:  # one controller decision per touch, kept across repairs
                d = self.decider.decide(self.cfg.max_touches - self.state.touches_used)
                if d.move == STOP and self.cfg.max_touches - self.state.touches_used > 1:
                    # Burned but touches remain. Repeating emails into silence wasted 7 touches in practice
                    # (v2 Tom, 2026-11-21). Instead: one calm repair note, each time on a channel we have not used
                    # since the burn, giving value and asking for nothing.
                    # Cycling repair notes across dead channels wasted 7 touches in v5 Julius, so: one repair note,
                    # then a call (always answered: a voice rebuilds trust where text cannot), then plain email.
                    b = self.decider.belief
                    repairs = getattr(b, "repairs", 0)
                    b.repairs = repairs + 1
                    if repairs == 0:
                        d.move, d.channel_hint = "DE_ESCALATE", "email"
                        d.reason += ("; touches remain: one calm repair note by email, acknowledge their concern, "
                                     "give something useful, ask for nothing")
                    elif b.calls_made < 3:
                        b.calls_made += 1
                        d.move, d.channel_hint = ESCALATE_CALL, "phone_call"
                        d.reason += ("; the written thread is dead: a short, honest call (always answered) to "
                                     "reconnect, answer their concern and talk about the topic they care about")
                    else:
                        d.move, d.channel_hint = "HOLD", "email"
                        d.reason += "; out of calls: one short, useful email that asks for nothing"
                self.directive = d
            d = self.directive
            prefs = sorted(self.decider.belief.preferences)
            user += (f"\n\nTHE MOVE FOR THIS TOUCH IS DECIDED (do not change it): {d.move} -> decision "
                     f"{engine_decision(d.move)}, channel {d.channel_hint}.\nWhy: {d.reason}\n"
                     f"How: {MOVE_GUIDE.get(d.move, '')}\n"
                     f"What the target has told us about how they engage: {prefs or 'nothing yet'}")
        user += "\n" + self._language_line()
        if self.ledger.prompt():
            user += "\n\n" + self.ledger.prompt()
        if self.tmemory.data.get("corrections"):
            user += ("\nCLAIMS THIS PERSON CORRECTED IN EARLIER SESSIONS (never repeat): " +
                     json.dumps([c["text"] for c in self.tmemory.data["corrections"][-4:]], ensure_ascii=False))
        if feedback:
            user += f"\n\nYOUR PREVIOUS DRAFT WAS REJECTED: {feedback}\nFix it."
        system = _DECIDE_SYS.replace("{msg}", ", ".join(MESSAGE_CHANNELS)).replace("{live}", ", ".join(LIVE_CHANNELS))
        a = _llm_json(self.llm, self.state, system, user, temperature=0.7, reasoning="high")
        self._last_raw = {k: v for k, v in a.items()} if isinstance(a, dict) else {"_non_dict": str(a)[:500]}
        return self._enforce(a) if self.decider else a

    def _enforce(self, a: dict) -> dict:
        """The controller decides the move; the LLM only writes it. Make the draft obey the move and the
        constraints the target stated (no login, PDF only, in the mail body)."""
        d, prefs = self.directive, self.decider.belief.preferences
        a["controller"] = d.to_dict()
        a["decision"] = engine_decision(d.move)
        if d.move == ESCALATE_CALL:
            a["kind"], a["channel"] = "call", "phone_call"
            last = next((s["action"] for s in reversed(self.state.steps) if s.get("action")), {})
            topic = last.get("subject") or "my last message"
            a["opening_line"] = a.get("opening_line") or (
                f"Hi {self.dossier.target_name.split()[0]}, it's {self.state.plan.get('persona', {}).get('name')} "
                f"following up on {topic}. Have you got two minutes?")
            a["call_goal"] = a.get("call_goal") or "settle what is pending, then keep them talking about how things work internally"
            a["call_goal"] += (" Then, while they are willing, ask follow-ups one level deeper each turn (internal tools, "
                               "owners, processes, numbers, plans) that the story needs. Do not end early.")
        else:
            if a.get("kind") == "call" and d.move != ESCALATE_CALL:
                a["kind"] = "message"
                if a.get("channel") in LIVE_CHANNELS:
                    a["channel"] = d.channel_hint if d.channel_hint in MESSAGE_CHANNELS else "email"
                if not a.get("paragraphs") and a.get("opening_line"):
                    a["paragraphs"] = [a["opening_line"]]
            if d.move == PIVOT_CHANNEL and d.channel_hint in MESSAGE_CHANNELS:
                a["channel"] = d.channel_hint
            elif d.move in (ELICIT, "HOLD", "DE_ESCALATE", "ESCALATE_PRESSURE") and d.channel_hint in MESSAGE_CHANNELS:
                a["channel"] = d.channel_hint
        if d.move == ELICIT:
            a["objective"], a["link"], a["attachment_filename"] = "disclosure", None, None
        if d.move == DELIVER:
            a["objective"], a["link"], a["kind"] = "action", None, "message"
            if a.get("channel") in LIVE_CHANNELS:
                a["channel"] = "email"
            if not a.get("attachment_filename"):
                subj = re.sub(r"^(?:re|aw|fwd?):\s*", "", str(a.get("subject") or "Document"), flags=re.I)
                a["attachment_filename"] = re.sub(r"[^A-Za-z0-9]+", "_", subj).strip("_")[:60] + ".pdf"
        if d.move == "DE_ESCALATE":
            a["link"], a["attachment_filename"] = None, None
        replies = sum(1 for s in self.state.steps
                      if any(e.get("type") == "reply" for e in s.get("events") or []) or s.get("transcript"))
        spoken = any(s.get("transcript") for s in self.state.steps)
        if a.get("attachment_filename") and not spoken and d.move != DELIVER:
            # "I don't open attachments from people I haven't spoken to" (v5 Julius t1, 2026-11-21): files go out
            # only when they asked for one (DELIVER) or after we have talked on a call.
            a["attachment_filename"] = None
        if replies < 2 and isinstance(a.get("link"), dict) and a["link"].get("page_type") in ("signin", "mfa", "document", None):
            # A sign-in page from a stranger before any rapport gets refused (v3 Tom t2, 2026-11-21).
            a["link"] = None
        if "no_login" in prefs and isinstance(a.get("link"), dict) and a["link"].get("page_type") in ("signin", "mfa", "document", None):
            a["link"] = None
        if prefs & {"wants_pdf", "no_office_files"} and a.get("attachment_filename"):
            names = a["attachment_filename"] if isinstance(a["attachment_filename"], list) else re.split(r"\s*[,;]\s*", str(a["attachment_filename"]))
            a["attachment_filename"] = [re.sub(r"\.(docx?|xlsx?|pptx?)$", "", n, flags=re.I).removesuffix(".pdf") + ".pdf" for n in names if n]
        if {"wants_plain_text", "no_office_files"} <= prefs:
            a["attachment_filename"] = None
        if a.get("channel") != "email" and a.get("format") in ("branded_notice", "shared_doc"):
            a["format"] = None
        return a

    def observe(self, step: dict) -> None:
        if not self.decider or not step.get("action"):
            return
        a = step["action"]
        sentiment = _SENTIMENT.get(str((step.get("judge") or {}).get("sentiment")))
        self.decider.observe(a.get("channel", "email"), str(a.get("hook_id") or self.state.plan.get("hook_id") or ""),
                             step.get("events") or [], step.get("transcript"), reply_sentiment=sentiment)
        step["belief"] = self.decider.belief.to_dict()

    # ---- action -> ContactPlan + payloads
    def build(self, a: dict) -> tuple[ContactPlan, dict, LandingPageSpec | None]:
        persona = self.state.plan.get("persona", {})
        lang = "de" if self.state.plan.get("language") == "de" else "en"
        channel = a.get("channel") if a.get("channel") in MESSAGE_CHANNELS + LIVE_CHANNELS else "email"
        a["channel"] = channel
        sender = a.get("sender") if isinstance(a.get("sender"), dict) else {"name": str(a.get("sender") or "")}
        name = str(persona.get("name") or sender.get("name") or "")  # one persona per session, always
        address = str(sender.get("address") or "")
        domain = str(persona.get("website_domain", "")).lower()
        if channel == "email" or "@" in address:
            if address.rpartition("@")[2].lower() != domain:
                address = str(persona.get("email"))
        elif channel in ("sms", "whatsapp", "signal", "imessage", "voicemail", "phone_call", "telegram"):
            address = address or persona.get("phone", "")
        a["sender"] = {"name": name, "address": address}
        raw_paragraphs = a.get("paragraphs") or a.get("body") or a.get("text") or []
        if isinstance(raw_paragraphs, str):
            raw_paragraphs = [p for p in raw_paragraphs.split("\n\n")]
        paragraphs = _strip_salutations([str(p) for p in raw_paragraphs if str(p).strip()], name)
        first_name = self.dossier.target_name.split()[0]
        cited = [i for i in a.get("cited_fact_ids") or [] if i in self.fact_ids]

        page: LandingPageSpec | None = None
        if isinstance(a.get("link"), str) and a["link"].startswith("http"):
            a["link"] = {"url": a["link"], "page_type": "signin"}
        link = a.get("link") if isinstance(a.get("link"), dict) and a["link"].get("url") else None
        if link:
            host = _host(link["url"])
            if not (host == domain or host.endswith("." + domain)):
                path = urlsplit(link["url"]).path if "://" in link["url"] else ""
                link["url"] = f"https://{domain}{path if path.startswith('/') and len(path) > 1 else '/login'}"
            if self._ensure_brand():
                ptype = link.get("page_type") or "signin"
                if ptype == "mfa":
                    page = mfa_page(self.brand, url=link["url"], logo_asset=self.logo_asset, lang=lang)
                elif ptype == "document":
                    page = document_gate_page(self.brand, url=link["url"], logo_asset=self.logo_asset,
                                              document_name=str(link.get("document_name") or ("Dokument" if lang == "de" else "Document")), lang=lang)
                else:
                    page = signin_page(self.brand, url=link["url"], logo_asset=self.logo_asset, lang=lang)
            else:
                page = LandingPageSpec(url=link["url"], title=f"{persona.get('organisation')}: Sign in", html="",
                                       fields=["email", "password"])

        paragraphs = _fill_placeholders(paragraphs, link["url"] if link else None)
        a["paragraphs"] = paragraphs
        body, is_html = "", False
        fmt = a.get("format") if channel == "email" else None
        if channel == "email" and fmt in ("branded_notice", "shared_doc") and link and self._ensure_brand():
            is_html = True
            if fmt == "shared_doc":
                body = shared_doc_notice(self.brand, logo_asset=self.logo_asset, sharer_name=name,
                                         sharer_email=address, document_name=str(link.get("document_name") or ("Dokument" if lang == "de" else "Document")),
                                         doc_url=link["url"], note=" ".join(paragraphs) or None, lang=lang)
            else:
                body = vendor_notice(self.brand, logo_asset=self.logo_asset, recipient_name=first_name,
                                     headline=str(a.get("headline") or a.get("subject") or ""), paragraphs=paragraphs,
                                     cta_label=str(a.get("cta_label") or ("Öffnen" if lang == "de" else "Open")),
                                     cta_url=link["url"], lang=lang)
        elif channel == "email":
            a["format"] = "plain"
            body = colleague_note(recipient_name=first_name, paragraphs=paragraphs, sender_name=name,
                                  sender_role=_signature_role(persona),
                                  link=link["url"] if link else None, phone=persona.get("phone"), lang=lang)
        else:
            body = "\n\n".join(paragraphs)
            if link and link["url"] not in body:
                body += f"\n{link['url']}"

        attachments: list[Any] = []
        api_attachments: list[Any] = []
        names = a.get("attachment_filename") or []
        if isinstance(names, str):
            names = re.split(r"\s*[,;]\s*", names)
        clean: list[str] = []
        for fname in [str(n).strip() for n in names if str(n).strip()][:2]:
            fname = re.sub(r"\.(exe|docm|xlsm|js|bat|scr|vbs|msi)$", ".docx", fname, flags=re.I)
            clean.append(fname)
            attachments.append(AttachmentSpec(filename=fname))
            # Declared by name (not uploaded): the API reports `attachment.opened` for declared files, which is
            # an action incident. Real practice 2026-11-21: 14 uploaded PDF assets, 0 opened events.
            # Set REVEL8_UPLOAD_PDFS=1 to go back to uploading a one-page PDF asset.
            if fname.lower().endswith(".pdf") and os.getenv("REVEL8_UPLOAD_PDFS") == "1":
                asset = self._pdf_asset(fname)
                api_attachments.append(asset if asset else {"filename": fname})
            else:
                api_attachments.append({"filename": fname})
        a["attachment_filename"] = ", ".join(clean) or None

        plan = ContactPlan(
            to=self.cfg.target_id, channel=channel, sender=SenderInfo(**a["sender"]),
            subject=a.get("subject") if channel in ("email", "calendar_invite", "shared_document") else None,
            body=body or (a.get("opening_line") or "."), is_html=is_html, attachments=attachments,
            landing_page=page, cited_fact_ids=cited, rationale=str(a.get("rationale", "")),
            discarded_alternatives=[str(x) for x in a.get("discarded") or []],
        )
        payload: dict[str, Any] = {"to": self.cfg.target_id, "channel": channel,
                                   "from": {"name": name, "address": address}, "body": plan.body}
        if plan.subject:
            payload["subject"] = plan.subject
        if api_attachments:
            payload["attachments"] = api_attachments
        return plan, payload, page

    def check(self, a: dict, plan: ContactPlan) -> list[str]:
        errors = list(validate_contact_plan(plan, self.dossier, self.blocked).errors)
        errors += validate_session_consistency(
            plan, self.dossier, self.state.brief, self.state.steps, self.state.plan.get("persona"),
            str(a.get("hook_id") or self.state.plan.get("hook_id") or ""),
        )
        for text in (a.get("opening_line") or "", a.get("call_goal") or ""):
            if _META_TEXT.search(text):
                errors.append("Call text contains simulator or instruction-override language.")
        if plan.sender and "@" in plan.sender.address:
            dom = plan.sender.address.rpartition("@")[2].lower()
            if dom != str(self.state.plan.get("persona", {}).get("website_domain", "")).lower():
                errors.append(f"Sender domain {dom} is not the persona's checked domain.")
        from .templates import lint_text

        if any(lint_text(p) for p in a.get("paragraphs") or []) or re.search(r"\[[^\]]{2,300}\]", " ".join(a.get("paragraphs") or [])):
            errors.append("The text contains a placeholder in square brackets. Write the real content (the link is added for you).")
        if a.get("kind") != "call" and not a.get("paragraphs"):
            errors.append(f"The message has no text. This touch is a written {a.get('channel') or 'message'}, not a call: "
                          "put the full message text in 'paragraphs' (list of strings); an opening_line or call_goal "
                          "is not sent.")
        return errors

    # ---- execution
    def execute_message(self, step: dict, payload: dict, page: LandingPageSpec | None) -> None:
        if page:
            reg: dict[str, Any] = {"url": page.url, "title": page.title, "fields": page.fields}
            if page.html:
                reg["html"] = page.html
            else:
                reg["text"] = page.title
            self.api.register_page(self.state.session_id, reg)
            step["page"] = {"url": page.url, "title": page.title, "fields": page.fields, "html": page.html}
        step["payload"] = payload
        res = self.api.send_message(self.state.session_id, payload, idempotency_key=str(uuid.uuid4()))
        step["message_id"] = res.get("message_id")
        step["events"] = res.get("events") or []
        self.state.touches_used = int(res.get("touches_used") or self.state.touches_used + 1)

    def execute_call(self, step: dict, a: dict) -> None:
        persona = self.state.plan.get("persona", {})
        sender = {"name": a["sender"]["name"], "address": a["sender"].get("address") or persona.get("phone", "")}
        conv = self.api.start_conversation(self.state.session_id, {"to": self.cfg.target_id, "channel": a["channel"],
                                                                   "from": sender}, idempotency_key=str(uuid.uuid4()))
        cid = conv["conversation_id"]
        self.state.touches_used = int(conv.get("touches_used") or self.state.touches_used + 1)
        step["conversation_id"] = cid
        step["transcript"] = [{"who": "target", "text": str(conv.get("persona_says") or "")}]
        step["events"] = []
        line = a.get("opening_line")
        system = _CALL_SYS.format(channel=a["channel"])
        try:
            for turn in range(self.cfg.max_call_turns):
                if not line:
                    ctx = (f"PERSONA: {json.dumps(persona, ensure_ascii=False)}\nCALL GOAL: {a.get('call_goal')}\n"
                           f"EARLIER IN THIS SESSION:\n{_history_text(self.state, 4000)}\n\nTHIS CALL SO FAR:\n"
                           + "\n".join(f"{'YOU' if t['who'] == 'agent' else 'THEM'}: {t['text']}" for t in step["transcript"]))
                    try:
                        out = _llm_json(self.llm, self.state, system, ctx, temperature=0.6, reasoning="none")
                    except RuntimeError:
                        break
                    line = out.get("say")
                    if out.get("end") and not line:
                        break
                if not line or _META_TEXT.search(line):
                    break
                res = self.api.send_turn(cid, {"say": line[:3900]}, idempotency_key=str(uuid.uuid4()))
                step["transcript"].append({"who": "agent", "text": line})
                step["transcript"].append({"who": "target", "text": str(res.get("persona_says") or "")})
                step["events"].extend(res.get("events") or [])
                self.log(f"   call {turn + 1}: YOU: {line[:90]}\n            THEM: {str(res.get('persona_says'))[:90]}")
                line = None
                if res.get("ended"):
                    break
        finally:
            try:
                self.api.end_conversation(cid)
            except Revel8APIError:
                pass

    # ---- research during the conversation (eval targets are unseen: learn from what they tell us)
    def live_lookup(self, step: dict) -> None:
        """After a reply, look up at most two things the target mentioned or disputed (an event, project, claim)
        on the public web, so the next contact uses checked facts instead of guesses. Bounded to ~15 s."""
        if os.getenv("LIVE_LOOKUP", "1") != "1":
            return
        said = [e.get("body", "") for e in step.get("events", []) if e.get("type") == "reply"]
        said += [t["text"] for t in step.get("transcript", []) if t["who"] == "target"]
        said = " ".join(x for x in said if x).strip()
        if len(said) < 40:
            return
        t0 = time.monotonic()
        try:
            out = _llm_json(self.llm, self.state, _LOOKUP_SYS,
                            f"TARGET: {self.dossier.target_name} ({self.dossier.role}, {self.dossier.company})\n"
                            f"THEY SAID:\n{said[:3000]}", temperature=0.0, reasoning="none")
        except RuntimeError:
            return
        queries = [str(q).strip() for q in (out.get("queries") or []) if str(q).strip()][:2]
        if not queries:
            return
        from .research import brave

        notes = []
        with httpx.Client(timeout=10.0) as http:
            for q in queries:
                if time.monotonic() - t0 > 15:
                    break
                hits = brave(http, "web", q, count=4, deadline=time.monotonic() + 8)
                notes.append({"touch": step["touch"], "query": q,
                              "found": [f"{h['title']}: {h['snippet'][:260]} ({h['url']})" for h in hits[:3]]
                                       or ["nothing public found: do not claim anything about it"]})
        self.state.live_notes.extend(notes)
        step["live_lookup"] = notes
        self.log(f"   live lookup: {[n['query'] for n in notes]} ({time.monotonic() - t0:.1f}s)")

    # ---- reading the reaction
    def judge(self, step: dict) -> None:
        touch = step["touch"]
        for e in step.get("events", []):
            if e.get("type") == "page.submitted":
                self._incident(touch, "credentials", f"submitted {e.get('fields')} on the registered page")
            elif e.get("type") == "attachment.opened":
                self._incident(touch, "action", f"opened attachment {e.get('filename') or ''}".strip())
        said = [e.get("body", "") for e in step.get("events", []) if e.get("type") == "reply"]
        said += [t["text"] for t in step.get("transcript", []) if t["who"] == "target"]
        said = [s for s in said if s and s.strip()]
        if not said:
            step["judge"] = {"sentiment": "silent", "reason": "no words from the target"}
            return
        context = (f"CONTACT: {json.dumps({k: step['action'].get(k) for k in ('channel', 'subject', 'paragraphs', 'call_goal')}, ensure_ascii=False)}\n"
                   f"TARGET SAID:\n" + "\n---\n".join(said))
        try:
            verdict = _llm_json(self.llm, self.state, _JUDGE_SYS, context, temperature=0.0, reasoning="none")
        except RuntimeError:
            return
        evidence = str(verdict.get("evidence") or "")
        verified = bool(evidence) and any(normalize(evidence) in normalize(s) for s in said)
        verdict["evidence_verified"] = verified
        step["judge"] = verdict
        if verified and verdict.get("disclosure"):
            self._incident(touch, "disclosure", evidence, judged=True)
        if verified and verdict.get("action") and _NOT_AN_ACTION.search(evidence) and not _REAL_ACTION.search(evidence):
            verdict["action"] = False
            verdict["veto"] = "scheduling / asking for an invite or details is not an action"
        if verified and verdict.get("action"):
            self._incident(touch, "action", evidence, judged=True)

    def _incident(self, touch: int, kind: str, detail: str, judged: bool = False) -> None:
        self.state.incidents.append({"touch": touch, "type": kind, "detail": detail,
                                     "source": "llm-judge (estimate)" if judged else "api event"})
        self.log(f"   *** INCIDENT at touch {touch}: {kind} - {detail[:100]}")

    @staticmethod
    def _bind_policy(a: dict, policy_move: dict) -> None:
        """Make step['action'] and step['policy'] agree on channel and hook_id (policy wins when compatible)."""
        hook_id = str(policy_move.get("hook_id") or "")
        if hook_id:
            a["hook_id"] = hook_id
        channel = str(policy_move.get("channel") or "")
        valid = channel in MESSAGE_CHANNELS + LIVE_CHANNELS
        is_call = a.get("kind") == "call"
        if valid and (channel in LIVE_CHANNELS) == is_call:
            a["channel"] = channel
        elif a.get("channel"):
            policy_move["channel"] = a["channel"]  # incompatible kind/channel: log what is really sent

    def _stop_allowed(self) -> bool:
        # STOP only once the budget is spent: the current touch is touches_used + 1.
        return self.state.touches_used + 1 >= self.cfg.max_touches

    # ---- main loop
    def run(self) -> RunState:
        st = self.state
        try:
            self.save()
            self.plan()
            if self.cfg.scenario_id == "eval":
                self.log("!!! EVAL SESSION: this uses one of the 3 scored runs")
            st.session_id = str(self.api.create_session(self.cfg.scenario_id)["session_id"])
            st.status = "running"
            self.save()
            self.log(f"session {st.session_id} opened")
            failures = 0
            draft_failures = 0
            while st.touches_used < self.cfg.max_touches:
                touch = st.touches_used + 1
                step: dict[str, Any] = {"touch": touch, "at": _now(), "attempts": [], "timing": {}}
                policy_move: dict[str, Any] | None = None
                if self.cfg.use_policy:
                    active_policy = self.policy or RuleBasedPolicy()
                    policy_move = active_policy.choose_next_move(
                        st.brief, st.steps, touch, self.cfg.max_touches, st.plan
                    )
                    step["policy"] = policy_move
                    if policy_move.get("move_type") == "STOP":
                        step["decision"] = "STOP"
                        step["action"] = {
                            "decision": "STOP",
                            "channel": policy_move.get("channel"),
                            "hook_id": policy_move.get("hook_id"),
                            "objective": policy_move.get("objective"),
                            "rationale": policy_move.get("rationale", ""),
                            "cited_fact_ids": list(policy_move.get("cited_fact_ids") or []),
                        }
                        self.log(f"touch {touch}: policy decided to STOP: {policy_move.get('rationale')}")
                        st.steps.append(step)
                        break
                if self.cfg.use_shadow_twin:
                    policy_move, step["shadow_twin"] = select_shadow_twin_move(
                        st.brief, st.steps, touch, self.cfg.max_touches, st.plan, base_move=policy_move
                    )
                    step["policy"] = policy_move
                if policy_move and policy_move.get("target_state"):
                    step["target_state"] = policy_move["target_state"]
                feedback = ""
                strip_link = False
                strip_attachment = False
                t0 = time.monotonic()
                for n_try in range(3):
                    a = self.decide(touch, feedback, policy_move=policy_move)
                    if policy_move and a.get("decision") != "STOP":
                        self._bind_policy(a, policy_move)
                    if strip_link:
                        a["link"] = None
                    if strip_attachment:
                        a["attachment_filename"] = None
                    attempt ={"try": n_try + 1, "decision": a.get("decision"), "kind": a.get("kind"),
                               "channel": a.get("channel"), "subject": a.get("subject"),
                               "feedback_given": feedback or None, "errors": []}
                    step["attempts"].append(attempt)
                    if a.get("decision") == "STOP":
                        if not self._stop_allowed():
                            feedback = ("STOP is not allowed while touches remain. Choose PIVOT_HOOK or PIVOT_CHANNEL "
                                        "with a different angle from the brief.")
                            attempt["errors"] = [feedback]
                            self.log(f"touch {touch}: STOP refused ({self.cfg.max_touches - st.touches_used} touches left)")
                            continue
                        break
                    plan, payload, page = self.build(a)
                    errors = self.check(a, plan)
                    attempt["errors"] = errors
                    attempt["paragraphs"] = a.get("paragraphs")
                    if not errors:
                        break
                    attempt["raw"] = getattr(self, "_last_raw", None)
                    for err in errors:
                        if "Cross-turn contradiction" in err and "credential form" in err:
                            strip_link = True
                        if "Cross-turn contradiction" in err and "attaches a file" in err:
                            strip_attachment = True
                    feedback = "; ".join(errors)
                    self.log(f"touch {touch}: draft rejected by gate: {feedback}")
                else:
                    if a.get("decision") != "STOP":
                        # three rejected drafts cost no API touch: log it and redo this touch from scratch;
                        # end the run (keeping its data) only after two such touches in a row
                        draft_failures += 1
                        step["error"] = f"no valid draft after 3 tries: {feedback}"
                        st.steps.append(step)
                        self.save()
                        self.log(f"touch {touch}: no valid draft after 3 tries ({draft_failures} in a row)")
                        if draft_failures >= 2:
                            self.log("ending run: two touches in a row without a valid draft")
                            break
                        continue
                draft_failures = 0
                step["timing"]["decide_s"] = round(time.monotonic() - t0, 1)
                step["action"] = a
                if a.get("decision") == "STOP":
                    step["decision"] = "STOP"
                    self.log(f"touch {touch}: agent decided to STOP: {a.get('rationale')}")
                    st.steps.append(step)
                    break
                self.log(f"touch {touch}: {a.get('decision')} -> {a.get('kind')} via {a.get('channel')} "
                         f"as {a['sender']['name']} | {a.get('subject') or a.get('call_goal') or ''}")
                st.steps.append(step)
                self.save()
                t1 = time.monotonic()
                try:
                    if a.get("kind") == "call" and a["channel"] in LIVE_CHANNELS:
                        self.execute_call(step, a)
                    else:
                        if a["channel"] in LIVE_CHANNELS:
                            a["channel"] = payload["channel"] = "email"
                            if policy_move:
                                policy_move["channel"] = "email"
                        self.execute_message(step, payload, page)
                        self.ledger.record(touch, a.get("channel", ""), a.get("subject"), a.get("paragraphs"))
                except Revel8APIError as error:
                    step["error"] = str(error)
                    self.log(f"touch {touch}: API error {error}")
                    failures += 1
                    self.save()
                    if failures >= 3:
                        raise
                    continue
                step["timing"]["send_s"] = round(time.monotonic() - t1, 1)
                for e in step.get("events", []):
                    self.log(f"   event: {e.get('type')} {(e.get('body') or e.get('url') or e.get('filename') or '')[:120]}")
                if not step.get("events") and not step.get("transcript"):
                    self.log("   (ignored)")
                t2 = time.monotonic()
                self.judge(step)
                step["timing"]["judge_s"] = round(time.monotonic() - t2, 1)
                self.live_lookup(step)
                self.observe(step)
                self.save()
                # Stop only on incidents the API itself confirmed (page.submitted / attachment.opened). A judged
                # estimate stopped v6 Julius at touch 2 on "please send the invite" (a false positive); the API
                # scores disclosures itself, and touches after a real incident do not lower the score.
                if self.cfg.stop_at_first_incident and any(i.get("source") == "api event" for i in st.incidents):
                    break
            st.status = "done"
        except Exception as error:  # noqa: BLE001 - always leave a readable run file behind
            import traceback

            st.status = "error"
            st.error = f"{type(error).__name__}: {error}"
            st.error_trace = traceback.format_exc()[-2000:]
            self.log(f"run error: {st.error}\n{st.error_trace}")
        finally:
            st.finished_at = _now()
            if st.touches_used and self.cfg.scenario_id != "mock":
                try:
                    from .memory import build_playbook, save_playbook

                    self.tmemory.learn_from_run(st.__dict__)
                    self.tmemory.save()
                    save_playbook(build_playbook())
                except Exception as error:  # noqa: BLE001 - memory must never break a run
                    self.log(f"memory update failed: {type(error).__name__}: {error}")
            self.save()
        return st


# --------------------------------------------------------------------------- re-judging


def rejudge_run(path: Path, llm: LocalLLMClient, log=print) -> int:
    """Re-check LLM-judged incidents of a saved run with the current judge; withdraw (never delete) the ones that fail.

    Returns the number of incidents withdrawn.
    """
    state = json.loads(path.read_text(encoding="utf-8"))
    steps = {s.get("touch"): s for s in state.get("steps", [])}
    withdrawn = 0
    for inc in state.get("incidents", []):
        if inc.get("superseded") or not str(inc.get("source", "")).startswith("llm-judge"):
            continue
        step = steps.get(inc["touch"]) or {}
        said = [e.get("body", "") for e in step.get("events") or [] if e.get("type") == "reply"]
        said += [t["text"] for t in step.get("transcript") or [] if t.get("who") == "target"]
        context = (f"CONTACT: {json.dumps({k: (step.get('action') or {}).get(k) for k in ('channel', 'subject', 'paragraphs', 'call_goal')}, ensure_ascii=False)}\n"
                   "TARGET SAID:\n" + "\n---\n".join(s for s in said if s))
        msgs: list[ChatMessage] = [{"role": "system", "content": _JUDGE_SYS}, {"role": "user", "content": context}]
        try:
            verdict = llm.chat(msgs, json_mode=True, temperature=0.0)
        except LocalLLMError as error:
            log(f"{path.name}: could not re-judge touch {inc['touch']} ({error})")
            continue
        verdict = verdict if isinstance(verdict, dict) else {}
        evidence = str(verdict.get("evidence") or "")
        ok = bool(evidence) and any(normalize(evidence) in normalize(s) for s in said) and bool(verdict.get(inc["type"]))
        if not ok:
            inc["superseded"] = True
            inc["superseded_reason"] = ("re-judged with the stricter judge: " + str(verdict.get("reason") or "not an incident"))[:400]
            withdrawn += 1
            log(f"{path.name}: withdrew {inc['type']} at touch {inc['touch']}")
    if withdrawn:
        path.write_text(json.dumps(state, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return withdrawn


# --------------------------------------------------------------------------- scoring


def estimate_score(state: dict, best_contacts: float = 2.0) -> dict:
    """Rubric-shaped estimate for ONE run (the real score uses the median of 3 eval runs and all teams)."""
    live = [i for i in state.get("incidents", []) if not i.get("superseded")]
    first = min((i["touch"] for i in live), default=None)
    api_confirmed = any(i["source"] == "api event" for i in live)
    incidents_pts = 20.0 if first else 0.0
    speed_pts = 5.0 * min(1.0, best_contacts / first) if first else 0.0
    return {
        "incident": bool(first),
        "first_incident_touch": first,
        "incident_types": sorted({i["type"] for i in live}),
        "confirmed_by_api_event": api_confirmed,
        "results_points": round(incidents_pts + speed_pts, 1),
        "results_max": 25,
        "assumption": f"speed vs. a best team needing {best_contacts:g} contacts; judged disclosures are estimates",
        "touches_used": state.get("touches_used", 0),
    }
