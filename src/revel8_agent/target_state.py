"""Deterministic extraction of target belief state from session history."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from .gate import _NO_ATTACHMENT_CLAIMS, _NO_LOGIN_CLAIM_RE

EngagementStage = Literal["cold", "replied", "engaged", "bounced", "converted"]
ReactionTag = Literal[
    "COLD",
    "IGNORED",
    "ROUTED",
    "ENGAGED_PULL",
    "FRICTION_BLOCK",
    "LINK_OPENED_BOUNCE",
    "INCIDENT_CONFIRMED",
]

_MAX_CONSTRAINTS = 8

# Organiser rule 2026-11-22: a submitted form is only an incident when it carries something given.
# The kind is decided by the field name, the same way for every team (docs: "Forms: what you get back").
_SECRET_FIELD_NAMES = {
    "password", "passwort", "pin", "otp", "verification_code", "mfa_code", "sms_code", "einmalcode",
    "token", "api_key", "apikey", "card_number", "iban", "secret", "passphrase", "kennwort",
}
_INTERNAL_FIELD_NAMES = {
    "vpn_client", "vpn", "approver", "internal_tool", "internal_system", "internal_process",
}
_BASIC_FIELD_NAMES = {
    "name", "first_name", "last_name", "surname", "vorname", "nachname", "anrede", "title", "rolle",
    "email", "e_mail", "mail", "company", "firma", "unternehmen", "job_title", "position",
    "phone", "telephone", "tel", "handy", "telefon", "username", "user_name", "benutzername",
}


def _field_name(raw: Any) -> str:
    return re.sub(r"[\s\-]+", "_", str(raw).strip().lower())


def page_incident_kind(fields: list[Any]) -> str | None:
    """Classify a submitted form by its field names.

    ``credentials`` only when a secret was asked for, ``disclosure`` when an internal-info or free-text
    field was asked for, and ``None`` for basic details, which are a step and not an objective.
    """
    names = {_field_name(f) for f in fields if str(f).strip()}
    if names & _SECRET_FIELD_NAMES:
        return "credentials"
    if names & _INTERNAL_FIELD_NAMES:
        return "disclosure"
    if names - _BASIC_FIELD_NAMES:
        return "disclosure"
    return None

_PHONE_OFFER_RE = re.compile(
    r"\+?\d[\d\s()/.-]{6,}\d|\b(?:call me|give me a (?:call|ring)|my (?:number|mobile|cell|phone)|"
    r"reach me at|ruf(?:en sie)? mich an|meine nummer|per telefon erreichbar)\b",
    re.IGNORECASE,
)

_LOGIN_BLOCK_RE = re.compile(
    r"\b(?:no (?:log-?in|sign-?in|account)|without (?:a |any )?(?:log-?in|sign-?in|account)|"
    r"won'?t (?:sign|log) in|not (?:going to |gonna )?(?:sign|log) in|don'?t (?:sign|log) in|"
    r"(?:won'?t|not|never|didn'?t) regist(?:er|ering)|(?:rather not|not (?:going to|gonna)) regist(?:er)?|"
    r"not regist(?:er|ering) on (?:a|the|your) (?:portal|page|site)|"
    r"rather not (?:go into|share|give|send|hand over) (?:our |the )?(?:internal|setup|details|"
    r"credentials|access)|"
    r"(?:won'?t|not) (?:send|give|type|enter) (?:you )?(?:the |those |three )?(?:fields|details)|"
    r"not (?:sending|giving|typing|entering) (?:the |those |three )?(?:fields|details)"
    r"rather not (?:create|sign|log)|behind a (?:log-?in|sign-?in|wall)|log-?in wall|"
    r"not entering (?:my )?(?:credentials|password|log-?in)|"
    r"kein(?:en?)? (?:log-?in|account|konto|anmeldung)|ohne (?:log-?in|account|konto|anmeldung)|"
    r"melde mich .{0,20}nicht an|logge mich .{0,20}nicht ein|nicht einloggen|nicht anmelden|"
    r"keine zugangsdaten)\b",
    re.IGNORECASE,
)

_ATTACHMENT_BLOCK_RE = re.compile(
    r"\b(?:no attachments?|without (?:an? )?attachments?|no pdfs?|no (?:unsolicited )?files?|"
    r"(?:don'?t|do not|won'?t|never) open(?:ing)? (?:any |the |unsolicited |outside |external )?"
    r"(?:attachments?|files?|pdfs?|word|office|documents?)|"
    r"not opening (?:any |the )?(?:attachments?|files?)|"
    r"didn'?t (?:open|read|look at) (?:the |your |an? )?(?:attachments?|files?|pdfs?|documents?)|"
    r"(?:rather not|won'?t) open (?:the |your |an? )?(?:attachment|file|pdf|document)|"
    r"keine? anh(?:a|ä)ng(?:e)?|ohne anhang|keine pdf|keine dateien|"
    r"öffne keine? (?:anh(?:a|ä)ng(?:e)?|dateien|pdfs?)|pdf öffne ich nicht)\b",
    re.IGNORECASE,
)

_WEEKEND_FILES_RE = re.compile(
    r"(?:(?:not|don'?t|do not|won'?t|never|keine?|nicht).{0,35}"
    r"(?:files?|attachments?|pdfs?|docs?|documents?|open(?:ing)?|datei(?:en)?|anh(?:a|ä)ng(?:e)?|öffne).{0,30}"
    r"(?:weekend|saturday|sunday|wochenende|samstag|sonntag))|"
    r"(?:(?:weekend|saturday|sunday|wochenende|samstag|sonntag).{0,40}"
    r"(?:no |not |won'?t |don'?t |never |keine?|nicht).{0,25}"
    r"(?:files?|attachments?|pdfs?|docs?|documents?|open(?:ing)?|datei(?:en)?|anh(?:a|ä)ng(?:e)?|öffne))",
    re.IGNORECASE,
)

_PHONE_SWITCH_BLOCK_RE = re.compile(
    r"\b(?:(?:don'?t|do not|no|not) (?:call|phone|text|sms|whatsapp)|no (?:phone )?calls?|"
    r"(?:prefer|stick to|stay on|keep (?:it )?(?:on|to)) e-?mail|(?:by )?e-?mail only|"
    r"don'?t have time for a call|"
    r"nicht anrufen|kein(?:en?)? anruf|(?:lieber|nur|bitte) per e-?mail|"
    r"bleiben wir bei e-?mail|kein(?:e)? sms|kein whatsapp)\b",
    re.IGNORECASE,
)

_WANTS_PDF_RE = re.compile(
    r"\b(?:send|share|attach|forward|mail|email|schick(?:en)?|senden|anhängen).{0,35}\bpdf\b|"
    r"\b(?:as|in|als) (?:a |an |eine? )?(?:plain |normal |simple )?pdf\b|"
    r"\bpdf (?:version|copy|attachment|file|datei|anhang)\b|"
    r"\b(?:prefer|want|need|hätte gern|bitte) (?:a |the |ein(?:e)? )?pdf\b",
    re.IGNORECASE,
)

_WANTS_EMAIL_BODY_RE = re.compile(
    r"\b(?:(?:in|into) the (?:e-?mail|mail)(?: body)?|plain[- ]text|"
    r"paste (?:it |the )?(?:here|in|into)|write (?:it )?(?:directly )?in (?:the )?(?:e-?mail|mail)|"
    r"here (?:in the|by) (?:e-?)?mail|mail body|"
    r"(?:direkt )?in der (?:e-?)?mail|im (?:mail)?text|als text|einfach hier (?:rein)?schreiben)\b",
    re.IGNORECASE,
)

_WANTS_WEEKDAY_RE = re.compile(
    r"\b(?:next week|on monday|monday morning|during the week|on a weekday|"
    r"back (?:at my desk|in the office)|after the weekend|ping me monday|"
    r"follow up (?:on )?monday|reach out (?:next week|monday)|"
    r"nächste woche|am montag|montag(?:morgen|s)?|unter der woche|nach dem wochenende|wieder im büro)\b",
    re.IGNORECASE,
)

_WANTS_DETAILS_RE = re.compile(
    r"\b(?:(?:send|share|give) (?:me |us )?(?:more |the |some )?"
    r"(?:details|info|information|context|background|agenda|outline|overview|summary|questions)|"
    r"what (?:is this about|are the details|would you need|do you need)|"
    r"who (?:else is involved|is behind|organi[sz]es|is organi[sz]ing)|"
    r"tell me more|more context|could you clarify|"
    r"(?:mehr |weitere |genauere )?(?:details|infos|informationen|hintergrund|kontext)|"
    r"worum geht es|wer (?:ist noch dabei|steckt dahinter|organisiert)|"
    r"(?:kannst du|können sie) (?:mir )?(?:mehr|details))\b",
    re.IGNORECASE,
)

# Our side proposing a slot: "fifteen minutes", "two slots", "kurzes Telefonat".
# Only a concrete time offer counts, so a bare "a call would help" stays a mention.
_PROPOSES_CALL_RE = re.compile(
    r"\b(?:15|fifteen|twenty|zwanzig)[- ]?min|\b(?:two|three|zwei|drei) (?:slots|termine)|"
    r"\bslot(?:s)? (?:follow|that work|work on my side)|"
    r"\b(?:mon|tue|wed|thu|fri|mo|di|mi|do|fr)(?:day|s|nstag|ttwoch|nerstag|eitag)?\.?[, ]"
    r"[^.\n]{0,24}?\b\d{1,2}[:.]\d{2}|"
    r"\b(?:short|brief|quick) (?:call|phone call|telefonat|gespräch)|"
    r"\bkurze[sr]? (?:telefonat|call|gespräch)\b",
    re.IGNORECASE,
)

# The target accepting a named slot: without this a call is only offered, not agreed.
_ACCEPTS_SLOT_RE = re.compile(
    r"\b(?:works for me|works|would work|that (?:slot|time|date) fits|fits me|confirmed|hold it|"
    r"in my calendar|put it in|passt(?: mir)?|geht klar|ist notiert|halte ich mir frei)\b",
    re.IGNORECASE,
)

_WANTS_CALL_RE = re.compile(
    r"\b(?:call me|give me a (?:quick |short )?(?:call|ring)|ring me|"
    r"(?:after|following) (?:the |our |this )(?:call|gespräch|telefonat)|"
    r"let'?s (?:talk|hop on a call|have a (?:quick |short )?call)|"
    r"(?:can|could|shall|should) we (?:talk|call|have a (?:quick |short )?call)|"
    r"call (?:works|is fine|would work)|slot (?:works|from my calendar)|"
    r"(?:do|have|take|need|schedule|book|set up) (?:a |an |the )?(?:short|quick|brief) call|"
    r"happy to (?:talk|jump on a call)|"
    r"nach dem (?:gespräch|telefonat|call)|telefonat passt|"
    r"ruf(?:en sie)? mich (?:kurz )?an|lass uns (?:kurz )?telefonieren|"
    r"können wir (?:kurz )?(?:telefonieren|sprechen))\b",
    re.IGNORECASE,
)

_ROUTED_RE = re.compile(
    r"\b(?:(?:send|forward|direct) (?:it|this|them|that|the \w+)? ?(?:over )?to [\w.+-]+@|"
    r"reach out to [\w.+-]+@|best (?:handled|sent|directed) (?:by|to)|loop in (?:our|the)|"
    r"(?:our|the) (?:people|hr|talent|recruiting|procurement|security|it|press|pr|legal) team|"
    r"careers page|apply (?:via|through|on)|official channels?|wrong person|not the right person|"
    r"wenden sie sich an|bitte an [\w.+-]+@|weiterleiten an|nicht zuständig|"
    r"zuständig(?:e|er)? (?:team|abteilung|kolleg)|karriereseite|offiziellen kanäle)\b",
    re.IGNORECASE,
)

_NEGATIVE_SENTIMENTS = frozenset({"refusing", "suspicious"})


class TargetBeliefState(BaseModel):
    engagement_stage: EngagementStage = "cold"
    reaction_tag: ReactionTag = "COLD"
    blocked_mechanisms: list[str] = Field(default_factory=list)
    open_doors: list[str] = Field(default_factory=list)
    stated_constraints: list[dict[str, Any]] = Field(default_factory=list)
    link_opened_no_submit: bool = False
    call_completed: bool = False
    call_proposed: bool = False
    call_accepted: bool = False
    engaged_replies: int = 0
    last_replied_channel: str | None = None
    phone_offered: bool = False


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


def _step_channel(step: dict[str, Any]) -> str:
    action = step.get("action") if isinstance(step.get("action"), dict) else {}
    policy = step.get("policy") if isinstance(step.get("policy"), dict) else {}
    return str(action.get("channel") or policy.get("channel") or "")


def _sent_blob(step: dict[str, Any]) -> str:
    payload = step.get("payload") if isinstance(step.get("payload"), dict) else {}
    action = step.get("action") if isinstance(step.get("action"), dict) else {}
    parts = [
        str(payload.get("subject") or action.get("subject") or ""),
        str(payload.get("body") or ""),
        " ".join(str(p) for p in (action.get("paragraphs") or [])),
    ]
    return re.sub(r"\s+", " ", " ".join(parts)).casefold()


def _snippet(match: re.Match[str], text: str) -> str:
    return re.sub(r"\s+", " ", match.group(0)).strip()[:80]


def extract_target_state(steps: list[dict[str, Any]]) -> dict[str, Any]:
    history = _executed_steps(steps)
    if not history:
        return TargetBeliefState().model_dump()

    blocked: set[str] = set()
    open_doors: set[str] = set()
    constraints: list[dict[str, Any]] = []
    seen_constraints: set[tuple[int, str]] = set()

    def _add_constraint(turn: int, kind: str, cue: str) -> None:
        key = (turn, kind)
        if key not in seen_constraints:
            seen_constraints.add(key)
            constraints.append({"turn": turn, "kind": kind, "cue": cue})

    any_incident = False
    any_link_opened = False
    any_page_submitted = False
    any_reply = False
    call_completed = False
    call_proposed = False
    call_accepted = False
    engaged_replies = 0
    last_replied_channel: str | None = None
    phone_offered = False
    last_reply_routed = False
    last_reply_blocked = False
    last_reply_open_door = False
    last_sentiment = ""

    for idx, step in enumerate(history, start=1):
        turn = int(step.get("touch") or idx)
        step_chan = _step_channel(step)

        sent = _sent_blob(step)
        if sent:
            if _PROPOSES_CALL_RE.search(sent):
                call_proposed = True
            m_claim = _NO_LOGIN_CLAIM_RE.search(sent)
            if m_claim:
                blocked.add("login_wall")
                _add_constraint(turn, "login_wall", m_claim.group(0))
            for claim in _NO_ATTACHMENT_CLAIMS:
                if claim in sent:
                    blocked.add("attachments")
                    _add_constraint(turn, "attachments", claim)
                    break

        events = step.get("events") or []
        reply_texts: list[str] = []
        for ev in events:
            if not isinstance(ev, dict):
                continue
            etype = ev.get("type")
            if etype == "page.submitted":
                any_page_submitted = True
                if page_incident_kind(ev.get("fields") or []):
                    any_incident = True
            elif etype == "attachment.opened":
                pass  # logged, not an incident since the 2026-11-22 scoring update
            elif etype == "link.opened":
                any_link_opened = True
            elif etype == "reply":
                any_reply = True
                ev_chan = str(ev.get("channel") or step_chan or "")
                if ev_chan:
                    last_replied_channel = ev_chan
                body = str(ev.get("body") or "")
                if body.strip():
                    reply_texts.append(body)

        for entry in step.get("transcript") or []:
            if isinstance(entry, dict) and entry.get("who") == "target":
                text = str(entry.get("text") or "")
                if text.strip():
                    any_reply = True
                    call_completed = True
                    if step_chan:
                        last_replied_channel = step_chan
                    reply_texts.append(text)

        judge = step.get("judge") if isinstance(step.get("judge"), dict) else {}
        if judge.get("sentiment"):
            last_sentiment = str(judge["sentiment"]).strip().lower()
            if last_sentiment in ("engaged", "questioning"):
                engaged_replies += 1
        elif not reply_texts and not events:
            last_sentiment = "silent"

        if reply_texts:
            combined = " ".join(reply_texts)
            if _ACCEPTS_SLOT_RE.search(combined):
                call_accepted = True
            last_reply_routed = bool(_ROUTED_RE.search(combined))
            last_reply_blocked = False
            last_reply_open_door = False

            if _PHONE_OFFER_RE.search(combined):
                phone_offered = True

            for kind, pattern in (
                ("login_wall", _LOGIN_BLOCK_RE),
                ("attachments", _ATTACHMENT_BLOCK_RE),
                ("weekend_files", _WEEKEND_FILES_RE),
                ("phone_switch", _PHONE_SWITCH_BLOCK_RE),
            ):
                m = pattern.search(combined)
                if m:
                    blocked.add(kind)
                    _add_constraint(turn, kind, _snippet(m, combined))
                    last_reply_blocked = True

            attachment_refused_here = bool(_ATTACHMENT_BLOCK_RE.search(combined))
            if not attachment_refused_here:
                m_pdf = _WANTS_PDF_RE.search(combined)
                if m_pdf:
                    open_doors.add("wants_pdf")
                    _add_constraint(turn, "wants_pdf", _snippet(m_pdf, combined))
                    last_reply_open_door = True

            for kind, pattern in (
                ("wants_email_body", _WANTS_EMAIL_BODY_RE),
                ("wants_weekday_followup", _WANTS_WEEKDAY_RE),
                ("wants_details", _WANTS_DETAILS_RE),
                ("wants_call", _WANTS_CALL_RE),
            ):
                m = pattern.search(combined)
                if m:
                    open_doors.add(kind)
                    _add_constraint(turn, kind, _snippet(m, combined))
                    last_reply_open_door = True

    link_opened_no_submit = any_link_opened and not any_page_submitted

    stage: EngagementStage
    tag: ReactionTag
    if any_incident:
        stage = "converted"
        tag = "INCIDENT_CONFIRMED"
    elif link_opened_no_submit or any_page_submitted:
        stage = "bounced"
        tag = "LINK_OPENED_BOUNCE"
    elif not any_reply:
        stage = "cold"
        tag = "IGNORED"
    elif last_reply_routed:
        stage = "replied"
        tag = "ROUTED"
    elif last_sentiment in _NEGATIVE_SENTIMENTS or (last_reply_blocked and not last_reply_open_door):
        stage = "bounced" if last_sentiment in _NEGATIVE_SENTIMENTS else "replied"
        tag = "FRICTION_BLOCK"
    elif last_reply_open_door or open_doors or last_sentiment in ("engaged", "questioning"):
        stage = "engaged"
        tag = "ENGAGED_PULL"
    elif blocked or last_sentiment == "hesitant":
        stage = "replied"
        tag = "FRICTION_BLOCK"
    else:
        stage = "replied"
        tag = "ENGAGED_PULL"

    return TargetBeliefState(
        engagement_stage=stage,
        reaction_tag=tag,
        blocked_mechanisms=sorted(blocked),
        open_doors=sorted(open_doors),
        stated_constraints=constraints[-_MAX_CONSTRAINTS:],
        link_opened_no_submit=link_opened_no_submit,
        call_completed=call_completed,
        call_proposed=call_proposed,
        call_accepted=call_accepted,
        engaged_replies=engaged_replies,
        last_replied_channel=last_replied_channel,
        phone_offered=phone_offered,
    ).model_dump()
