"""Deterministic validation for contact drafts."""

import re
from collections.abc import Collection
from email.utils import parseaddr
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit

from .schemas import AttachmentSpec, ContactPlan, GateVerdict, VerifiedDossier

_META_TEXT = re.compile(
    r"\b(?:ignore\s+previous|ignore\s+your\s+instructions|system\s+prompt|"
    r"you\s+are\s+an\s+ai|as\s+an\s+ai|language\s+model|simulator)\b",
    re.IGNORECASE,
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
    if any(parser.has_script for parser in parsers):
        errors.append("HTML contains a script tag.")
    if any(parser.has_non_asset_image for parser in parsers):
        errors.append("HTML images must use asset:// sources.")

    fact_by_id = {fact.id: fact for fact in dossier.facts}
    for fact_id in dict.fromkeys(plan.cited_fact_ids):
        fact = fact_by_id.get(fact_id)
        if fact is None:
            errors.append(f"Cited fact {fact_id!r} is missing from the dossier.")
        elif not fact.source_url.strip() or not fact.verbatim_quote.strip():
            errors.append(f"Cited fact {fact_id!r} requires a source URL and verbatim quote.")

    return GateVerdict(passed=not errors, errors=errors)
