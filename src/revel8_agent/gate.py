"""Deterministic validation for contact drafts."""

import re
from collections.abc import Collection
from email.utils import parseaddr
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from .schemas import AttachmentSpec, ContactPlan, GateVerdict, VerifiedDossier

_META_TEXT = re.compile(
    r"\b(?:ignore\s+previous|ignore\s+your\s+instructions|system\s+prompt|"
    r"you\s+are\s+an\s+ai|as\s+an\s+ai|language\s+model|simulator)\b",
    re.IGNORECASE,
)

# Planner notes leaking into the copy, e.g. a signature "Brenner & Söhne GmbH (fiktiver Zulieferer, ...)".
_PRETEXT_LEAK = re.compile(
    # not "placeholder": organisers say "your entry still shows a placeholder abstract" (fast-S4, 2026-11-22);
    # bracketed placeholders like "[link]" are caught by engine._PLACEHOLDER
    r"\b(?:fiktiv\w*|erfunden\w*|fictional|fictitious|made[- ]up|"
    r"lookalike|pretext)\b",
    re.IGNORECASE,
)

_CREDENTIAL_FIELDS = frozenset({"password", "passcode", "otp"})
_NO_LOGIN_CLAIMS = (
    "public page",
    "no login",
    "no account",
    "without signing in",
    "without an account",
    "without logging in",
    "no sign-in",
    "no sign in",
)


class _DraftHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text: list[str] = []
        self.has_script = False
        self.has_non_asset_image = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self.has_script = True
        if tag == "img":
            for name, value in attrs:
                if name == "src" and not (value or "").strip().lower().startswith("asset://"):
                    self.has_non_asset_image = True
                if name == "srcset":
                    self.has_non_asset_image = True

    def handle_data(self, data: str) -> None:
        self.text.append(data)


def _normalize_domain(domain: str) -> str:
    domain = domain.strip().rstrip(".").lower()
    try:
        return domain.encode("idna").decode("ascii")
    except UnicodeError:
        return domain


def _is_blocked(host: str, blocked_domains: set[str]) -> bool:
    host = _normalize_domain(host)
    return any(host == domain or host.endswith(f".{domain}") for domain in blocked_domains)


_NAME = r"[A-ZÄÖÜ][\w'’-]+\s+[A-ZÄÖÜ][\w'’-]+"
_COLLEAGUE_RE = re.compile(rf"(?i:colleague|coworker|co-worker|teammate|kolleg(?:e|in))\s+({_NAME})")
# Capitalised German articles/pronouns/nouns that look like a first name ("Ihre Arbeit", "Die Human-Firewall-Mission").
_NOT_A_NAME = frozenset(
    "der die das den dem des ein eine einen einem einer eines ihr ihre ihren ihrem ihrer ihres sein seine seinen "
    "seinem seiner unser unsere unseren unserem unserer euer eure dein deine mein meine arbeit mission team".split()
)
_PHONE_RE = re.compile(r"\+?\d[\d\s()/.-]{6,}\d|\b(?:phone|telefon|handy|mobile|whatsapp|call me)\b", re.IGNORECASE)
_LIVE_CHANNELS = frozenset({"sms", "whatsapp", "phone_call"})


def _looks_like_person(name: str) -> bool:
    return name.split()[0].casefold() not in _NOT_A_NAME


def _social_norm_error(plan: ContactPlan, steps: list[dict[str, Any]]) -> str | None:
    """Email-only targets who never offered a phone number must not be pulled onto sms/whatsapp."""
    if plan.channel not in ("sms", "whatsapp"):
        return None
    replied: set[str] = set()
    said = ""
    for s in steps:
        action = s.get("action") if isinstance(s.get("action"), dict) else {}
        for e in s.get("events") or []:
            if e.get("type") == "reply":
                replied.add(str(e.get("channel") or action.get("channel") or ""))
                said += f" {e.get('body') or ''}"
    if "email" in replied and not (replied & _LIVE_CHANNELS) and not _PHONE_RE.search(said):
        return ("Social-norm violation: target has only replied by email and never offered a phone number; "
                "stay on email instead of jumping to sms/whatsapp.")
    return None


_UPCOMING_PITCH = ("upcoming", "next month", "register for", "join us at", "invite you to")
_NO_ATTACHMENT_CLAIMS = ("no attachment", "kein anhang", "without attachment", "no pdf")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text)).casefold()


def _draft_text(plan: ContactPlan) -> str:
    parts = [plan.subject or ""]
    for markup in (plan.body, plan.landing_page.html if plan.landing_page else ""):
        parser = _DraftHTML()
        parser.feed(markup)
        parser.close()
        parts.append(" ".join(parser.text))
    return re.sub(r"\s+", " ", " ".join(parts))


def _sent_text(step: dict[str, Any]) -> str:
    payload = step.get("payload")
    if not isinstance(payload, dict):
        return ""
    return _norm(f"{payload.get('subject') or ''} {payload.get('body') or ''}")


def validate_session_consistency(
    plan: ContactPlan,
    dossier: VerifiedDossier,
    brief: dict[str, Any],
    steps: list[dict[str, Any]],
    persona: dict[str, Any] | None = None,
    hook_id: str = "",
) -> list[str]:
    """Deterministic entity, date and cross-turn checks. Returns rejection strings (empty when clean)."""
    from .policy import _is_past_hook, _is_uncertain_hook

    errors: list[str] = []
    persona = persona or {}
    text = _draft_text(plan)
    low = _norm(text)

    # 1. Ungrounded person claim
    known = _norm(" ".join(
        [dossier.target_name, str(persona.get("name") or ""), plan.sender.name if plan.sender else ""]
        + [f"{f.fact} {f.verbatim_quote}" for f in dossier.facts]
        + [f"{f.get('fact', '')} {f.get('verbatim_quote', '')}" for f in brief.get("facts") or [] if isinstance(f, dict)]
    ))
    orgs = [o for o in (dossier.company, str(persona.get("organisation") or "")) if o.strip()]
    claimed = [m.group(1) for m in _COLLEAGUE_RE.finditer(text)]
    for org in orgs:
        claimed += [m.group(1) for m in re.finditer(
            rf"({_NAME})\s+(?i:at|from|von|bei)\s+{re.escape(org)}", text)]
    for name in dict.fromkeys(claimed):
        if _looks_like_person(name) and _norm(name) not in known:
            errors.append(
                f"Ungrounded person claim: {name!r} is not the target, the persona or named in the brief facts. "
                "Do not name people you cannot source."
            )

    if err := _social_norm_error(plan, steps):
        errors.append(err)

    # 2. PAST / uncertain-date hook pitched as upcoming
    hook = next((h for h in brief.get("hooks") or [] if isinstance(h, dict) and str(h.get("id")) == hook_id), None)
    if hook and (_is_past_hook(hook) or _is_uncertain_hook(hook)):
        hit = [p for p in _UPCOMING_PITCH if p in low]
        if hit:
            errors.append(
                f"Past-hook upcoming pitch: hook {hook_id!r} is past or of uncertain date but the draft says "
                f"{hit[0]!r}. Refer to it only as something that already happened."
            )

    # 3. Cross-turn commitments
    prior = [(_sent_text(s), s.get("payload") or {}) for s in steps]
    prior = [(t, p) for t, p in prior if t]
    if plan.attachments and any(c in t for t, _ in prior for c in _NO_ATTACHMENT_CLAIMS):
        errors.append("Cross-turn contradiction: an earlier message promised no attachment but this draft attaches a file.")
    if plan.landing_page:
        fields = {f.strip().lower() for f in plan.landing_page.fields}
        if (fields & _CREDENTIAL_FIELDS or {"email", "password"} <= fields) and any(
            c in t for t, _ in prior for c in _NO_LOGIN_CLAIMS
        ):
            errors.append("Cross-turn contradiction: an earlier message promised a public/no-login page but this draft sends a credential form.")
    return errors


def validate_contact_plan(
    plan: ContactPlan, dossier: VerifiedDossier, blocked_org_domains: Collection[str]
) -> GateVerdict:
    errors: list[str] = []
    blocked_domains = {_normalize_domain(domain) for domain in blocked_org_domains} - {""}
    text = [plan.body, plan.subject or ""]
    html = [plan.body]

    if plan.sender:
        sender_domain = parseaddr(plan.sender.address)[1].rpartition("@")[2]
        if sender_domain and _is_blocked(sender_domain, blocked_domains):
            errors.append("Sender address uses a blocked organization domain.")
        text.append(plan.sender.name)

    if plan.landing_page:
        try:
            host = urlsplit(plan.landing_page.url).hostname
        except ValueError:
            host = None
        if not host:
            errors.append("Landing page URL must have a host.")
        elif _is_blocked(host, blocked_domains):
            errors.append("Landing page uses a blocked organization domain.")
        text.extend([plan.landing_page.title, plan.landing_page.html, *plan.landing_page.fields])
        html.append(plan.landing_page.html)

    for attachment in plan.attachments:
        if isinstance(attachment, AttachmentSpec):
            text.extend([attachment.filename, attachment.transcript or ""])

    parsers = []
    for markup in html:
        parser = _DraftHTML()
        parser.feed(markup)
        parser.close()
        parsers.append(parser)
        text.extend(["".join(parser.text), " ".join(parser.text)])

    if any(_META_TEXT.search(unescape(content)) for content in text):
        errors.append("Draft contains simulator or instruction-override language.")
    if any(_PRETEXT_LEAK.search(unescape(content)) for content in text):
        errors.append(
            "Draft reveals the pretext is invented (e.g. 'fiktiver Zulieferer', 'fictional', 'placeholder'). "
            "Write the persona and organisation as real; never label them fictional or invented."
        )
    if any(parser.has_script for parser in parsers):
        errors.append("HTML contains a script tag.")
    if any(parser.has_non_asset_image for parser in parsers):
        errors.append("HTML images must use asset:// sources.")

    if plan.landing_page:
        fields_lower = {field.strip().lower() for field in plan.landing_page.fields}
        requests_credentials = bool(fields_lower & _CREDENTIAL_FIELDS) or (
            {"email", "password"} <= fields_lower
        )
        if requests_credentials:
            msg_candidates = [
                plan.subject or "",
                "".join(parsers[0].text),
                " ".join(parsers[0].text),
            ]
            normalized_msg = [
                re.sub(r"\s+", " ", unescape(part)).casefold() for part in msg_candidates
            ]
            if any(claim in part for part in normalized_msg for claim in _NO_LOGIN_CLAIMS):
                errors.append(
                    "Message promises a public/no-login page but landing page requests credentials."
                )

    fact_by_id = {fact.id: fact for fact in dossier.facts}
    for fact_id in dict.fromkeys(plan.cited_fact_ids):
        fact = fact_by_id.get(fact_id)
        if fact is None:
            errors.append(f"Cited fact {fact_id!r} is missing from the dossier.")
        elif not fact.source_url.strip() or not fact.verbatim_quote.strip():
            errors.append(f"Cited fact {fact_id!r} requires a source URL and verbatim quote.")

    return GateVerdict(passed=not errors, errors=errors)
