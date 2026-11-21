"""Sender identities: fixed fictitious brands, plus lookalikes of organisations a target knows.

Every domain is one an attacker could register. `lookalike_brand` refuses any domain that is,
or sits under, a real organisation's domain: that would void the run.
"""

import re
from collections.abc import Collection
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict

from ..schemas import VerifiedDossier

type Lang = Literal["de", "en"]

# Only email bodies and landing pages are rendered and rated for craft. Other channels
# (SMS, chat, social, calls) get plain text, never these templates.
CRAFT_CHANNELS = frozenset({"email"})


class Brand(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    name: str
    domain: str
    sender_address: str
    color: str
    color_dark: str
    postal_address: str = ""
    register_line: str = ""

    @property
    def logo_filename(self) -> str:
        return f"{self.key}-logo.png"


BRANDS: dict[str, Brand] = {
    brand.key: brand
    for brand in (
        Brand(
            key="nordlicht",
            name="Nordlicht IT-Servicedesk",
            domain="nordlicht-itservice.de",
            sender_address="servicedesk@nordlicht-itservice.de",
            color="#0B5CAD",
            color_dark="#08427D",
            postal_address="Nordlicht IT-Services GmbH · Leopoldstraße 41 · 80802 München",
            register_line="Amtsgericht München HRB 258413",
        ),
        Brand(
            key="helixsign",
            name="Helix Sign",
            domain="helixsign-docs.de",
            sender_address="no-reply@helixsign-docs.de",
            color="#5B3FD1",
            color_dark="#432CA3",
            postal_address="Helix Sign Technologies GmbH · Torstraße 118 · 10119 Berlin",
            register_line="Amtsgericht Charlottenburg HRB 197264 B",
        ),
        Brand(
            key="eventcrew",
            name="EventCrew München",
            domain="eventcrew-muc.de",
            sender_address="team@eventcrew-muc.de",
            color="#C2410C",
            color_dark="#9A3412",
            postal_address="EventCrew München UG · Schwanthalerstraße 73 · 80336 München",
            register_line="Amtsgericht München HRB 271905",
        ),
    )
}


def get_brand(key: str) -> Brand:
    try:
        return BRANDS[key]
    except KeyError:
        raise ValueError(f"Unknown brand {key!r}. Known: {', '.join(BRANDS)}") from None


def _normalize(domain: str) -> str:
    return domain.strip().rstrip(".").lower()


def _under(host: str, domain: str) -> bool:
    host, domain = _normalize(host), _normalize(domain)
    return bool(domain) and (host == domain or host.endswith("." + domain))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower().replace("ü", "ue").replace("ö", "oe").replace("ä", "ae")).strip("-")


def _darken(hex_color: str, factor: float = 0.75) -> str:
    r, g, b = (int(hex_color.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    return "#{:02X}{:02X}{:02X}".format(*(round(c * factor) for c in (r, g, b)))


def lookalike_brand(
    name: str,
    *,
    real_domains: Collection[str],
    color: str,
    domain: str | None = None,
    suffix: str = "portal",
    tld: str = "de",
    mailbox: str = "no-reply",
    postal_address: str = "",
    register_line: str = "",
) -> Brand:
    """A brand that looks like an organisation the target knows (a partner, vendor, investor).

    `real_domains` are that organisation's own domains. The brand's domain is derived as
    `<name>-<suffix>.<tld>` unless given, and is rejected if it equals or sits under any of them.
    """
    slug = _slug(name)
    domain = _normalize(domain or f"{slug}-{suffix}.{tld}")
    if not re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z]{2,}", domain):
        raise ValueError(f"{domain!r} is not a valid domain.")
    if any(_under(domain, real) for real in real_domains):
        raise ValueError(f"{domain!r} is a real organisation's domain; use a lookalike.")
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
        raise ValueError("color must be #RRGGBB.")
    return Brand(
        key=slug,
        name=name,
        domain=domain,
        sender_address=f"{mailbox}@{domain}",
        color=color,
        color_dark=_darken(color),
        postal_address=postal_address,
        register_line=register_line,
    )


def org_domains_from_dossier(dossier: VerifiedDossier, extra: Collection[str] = ()) -> set[str]:
    """Real domains of the target's company, to pass to the gate as blocked_org_domains.

    Taken from dossier source URLs whose host contains the company name (e.g. revel8.ai),
    plus any `extra` the planner knows (partners or vendors it imitates).
    """
    company = _slug(dossier.company).replace("-", "")
    domains = {_normalize(d) for d in extra if d.strip()}
    for fact in dossier.facts:
        host = _normalize(urlsplit(fact.source_url).hostname or "")
        labels = host.split(".")
        if company and len(labels) >= 2 and company in labels[-2].replace("-", ""):
            domains.add(".".join(labels[-2:]))
    return domains
