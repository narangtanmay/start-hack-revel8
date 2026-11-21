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
import re
import socket
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .api_client import Revel8APIError, Revel8Client
from .gate import _META_TEXT, validate_contact_plan
from .llm_client import ChatMessage, LocalLLMClient, LocalLLMError
from .osint import normalize
from .policy import Policy, RuleBasedPolicy
from .schemas import AttachmentSpec, ContactPlan, LandingPageSpec, SenderInfo, VerifiedDossier
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
    max_call_turns: int = 8
    runs_dir: Path = Path("runs")
    label: str = ""
    use_ledger_gate: bool = True
    use_shadow_twin: bool = False
    use_policy: bool = False


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
    finished_at: str = ""

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
        m2 = re.search(r"(?:(\d{1,2})\.?\s+)?([a-z]{3})[a-z]*\.?\s+(?:(\d{1,2}),?\s+)?(20\d\d)", r)
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
- Every domain you use (sender email, website, link) must be an invented or lookalike domain an attacker could register, e.g. "eventcrew-muc.de" or "stackit-marketplace-portal.de". Never use a real organisation's own domain, and never the target company's domain.
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

Design ONE campaign. Pick the strongest hook from the brief, a believable persona whose reason to contact
them follows naturally from that hook, the incident you will aim for, and a short sequence of moves across
channels (e.g. email with substance, then a short follow-up on another channel referring to it, then a
call if needed). Plan a small, natural ask early: the target must have a reason to click, open or answer.

Return ONLY JSON:
{"hook_id": str, "pretext": str, "objective": "credentials"|"action"|"disclosure",
 "language": "de"|"en",
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
  (e.g. "Anonymised_Profiles_GTM_revel8.docx", "Panel_Briefing_Munich.docx"). An expected attachment that gets
  opened is an incident.
- Answer every question they ask concretely and consistently (organiser, venue, audience, terms, who else).
  Evasive answers make them careful.
- Dates: never give a date for a real third-party event unless the brief has it with timing "upcoming". For your
  own occasions, propose dates at least two weeks after today and keep them identical in every later message.
- Keep the ask small and natural; one ask per contact.

""" + _RULES + """

Channels: message channels {msg}; live channels (a call/chat of several turns, costs one touch) {live}.
For email you choose a format: "plain" (personal note from a person, best for individuals),
"branded_notice" (company notice with one button), "shared_doc" (document-sharing notification).
If you include a link, it gets a landing page: page_type "signin" (email+password), "document" (sign in to
view a document) or "mfa" (one-time code). The link host MUST be on the persona's website_domain or a
subdomain of it. For messages on other channels, body is plain text (short for chat/SMS).

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
or back off gracefully. End politely once the goal is reached or clearly impossible.

""" + _RULES + """

Return ONLY JSON: {{"say": str|null, "end": bool}}  (say=null and end=true to hang up)."""

_JUDGE_SYS = """You judge a training simulation. Given what the target person said or did in response to a
contact, decide whether an incident happened:
- disclosure: the target revealed internal, non-public information (internal systems/tools, processes,
  plans, internal people/roles details, numbers) to the outsider. Generic, public or polite statements do NOT count.
- action: the target says they DID or will NOW do a risky thing for the outsider: opened or forwarded a file/link,
  approved a request or MFA prompt, changed payment/account details, granted access, shared internal
  material or credentials. Asking for information, requesting an invite, agreeing to a meeting or a call,
  saying "send me details", or replying politely is NOT an action.
Be strict: when in doubt, both are false.
Return ONLY JSON: {"disclosure": bool, "action": bool, "evidence": str, "reason": str,
 "sentiment": "engaged"|"questioning"|"hesitant"|"suspicious"|"refusing"}
"evidence" must be copied verbatim from the target's words (empty if none)."""


# --------------------------------------------------------------------------- helpers


def _llm_json(llm: LocalLLMClient, state: RunState, system: str, user: str, temperature: float = 0.6) -> dict:
    last_error = ""
    for _ in range(3):
        msgs: list[ChatMessage] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if last_error:
            msgs.append({"role": "user", "content": f"Your previous answer was invalid ({last_error}). Return valid JSON only."})
        state.llm_calls += 1
        try:
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
                   (sender_name and out[-1].strip().split("\n")[0].strip() == sender_name.strip())):
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


class Runner:
    def __init__(self, cfg: RunConfig, api: Revel8Client, llm: LocalLLMClient, dossier: VerifiedDossier,
                 log=print, policy: Policy | None = None) -> None:
        self.cfg, self.api, self.llm, self.dossier, self._print = cfg, api, llm, dossier, log
        self.policy: Policy | None = policy if policy is not None else (RuleBasedPolicy() if cfg.use_policy else None)
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{cfg.target_id}" + (f"-{cfg.label}" if cfg.label else "")
        self.state = RunState(
            run_id=run_id,
            config={k: str(v) for k, v in cfg.__dict__.items()},
            target={"id": cfg.target_id, "name": dossier.target_name, "role": dossier.role,
                    "company": dossier.company},
            started_at=_now(),
        )
        self.blocked = org_domains_from_dossier(dossier)
        self.fact_ids = {f.id for f in dossier.facts}
        self.brand = None
        self.logo_asset: str | None = None

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
                f"THEMES THEY KEEP TALKING ABOUT (count of verified mentions): "
                f"{json.dumps(self.state.brief.get('themes', []), ensure_ascii=False)}\n"
                f"TOUCH BUDGET: {self.cfg.max_touches}\n"
                f"Channels: {MESSAGE_CHANNELS + LIVE_CHANNELS}")
        for attempt in range(3):
            plan = _llm_json(self.llm, self.state, _PLAN_SYS, user, temperature=0.7)
            persona = plan.get("persona") or {}
            domain = str(persona.get("website_domain", "")).lower().strip()
            problem = self._domain_problem(domain)
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
                f"HISTORY SO FAR:\n{_history_text(self.state) or '(nothing yet: this is the first contact)'}")
        if policy_move:
            user += (
                "\n\nPOLICY MOVE (follow this move_type, channel, hook_id, cited_fact_ids, ask, and promises): "
                f"{json.dumps(policy_move, ensure_ascii=False)}"
            )
        if feedback:
            user += f"\n\nYOUR PREVIOUS DRAFT WAS REJECTED: {feedback}\nFix it."
        system = _DECIDE_SYS.replace("{msg}", ", ".join(MESSAGE_CHANNELS)).replace("{live}", ", ".join(LIVE_CHANNELS))
        return _llm_json(self.llm, self.state, system, user, temperature=0.7)

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
                                              document_name=str(link.get("document_name") or "Dokument"), lang=lang)
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
                                         sharer_email=address, document_name=str(link.get("document_name") or "Dokument"),
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
            if fname.lower().endswith(".pdf"):
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
        for text in (a.get("opening_line") or "", a.get("call_goal") or ""):
            if _META_TEXT.search(text):
                errors.append("Call text contains simulator or instruction-override language.")
        if plan.sender and "@" in plan.sender.address:
            dom = plan.sender.address.rpartition("@")[2].lower()
            if dom != str(self.state.plan.get("persona", {}).get("website_domain", "")).lower():
                errors.append(f"Sender domain {dom} is not the persona's checked domain.")
        from .templates import lint_text

        if any(lint_text(p) for p in a.get("paragraphs") or []) or re.search(r"\[[^\]]{2,40}\]", " ".join(a.get("paragraphs") or [])):
            errors.append("The text contains a placeholder in square brackets. Write the real content (the link is added for you).")
        if a.get("kind") != "call" and not a.get("paragraphs"):
            errors.append("The message has no text. Put the full message text in 'paragraphs' (list of strings).")
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
                    out = _llm_json(self.llm, self.state, system, ctx, temperature=0.6)
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
            verdict = _llm_json(self.llm, self.state, _JUDGE_SYS, context, temperature=0.0)
        except RuntimeError:
            return
        evidence = str(verdict.get("evidence") or "")
        verified = bool(evidence) and any(normalize(evidence) in normalize(s) for s in said)
        verdict["evidence_verified"] = verified
        step["judge"] = verdict
        if verified and verdict.get("disclosure"):
            self._incident(touch, "disclosure", evidence, judged=True)
        if verified and verdict.get("action"):
            self._incident(touch, "action", evidence, judged=True)

    def _incident(self, touch: int, kind: str, detail: str, judged: bool = False) -> None:
        self.state.incidents.append({"touch": touch, "type": kind, "detail": detail,
                                     "source": "llm-judge (estimate)" if judged else "api event"})
        self.log(f"   *** INCIDENT at touch {touch}: {kind} - {detail[:100]}")

    def _stop_allowed(self) -> bool:
        if self.cfg.use_policy or self.cfg.max_touches - self.state.touches_used <= 1:
            return True
        executed = [
            s for s in self.state.steps
            if s.get("decision") != "STOP" and (s.get("action") or {}).get("decision") != "STOP"
        ]
        sentiments = [str((s.get("judge") or {}).get("sentiment") or "").lower() for s in executed]
        consec_neg = 0
        for sent in reversed(sentiments):
            if sent in ("refusing", "suspicious"):
                consec_neg += 1
            else:
                break
        if consec_neg >= 2:
            return True
        consec_silent = 0
        for sent in reversed(sentiments):
            if sent == "silent":
                consec_silent += 1
            else:
                break
        return consec_silent >= 3

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
                feedback = ""
                t0 = time.monotonic()
                for n_try in range(3):
                    a = self.decide(touch, feedback, policy_move=policy_move)
                    attempt = {"try": n_try + 1, "decision": a.get("decision"), "kind": a.get("kind"),
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
                    feedback = "; ".join(errors)
                    self.log(f"touch {touch}: draft rejected by gate: {feedback}")
                else:
                    if a.get("decision") != "STOP":
                        raise RuntimeError(f"Could not produce a valid draft: {feedback}")
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
                        self.execute_message(step, payload, page)
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
                self.save()
                if st.incidents and self.cfg.stop_at_first_incident:
                    break
            st.status = "done"
        except Exception as error:  # noqa: BLE001 - always leave a readable run file behind
            st.status = "error"
            st.error = f"{type(error).__name__}: {error}"
            self.log(f"run error: {st.error}")
        finally:
            st.finished_at = _now()
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
