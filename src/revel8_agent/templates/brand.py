"""Fictitious lookalike brands used as sender identities.

Every domain here is one an attacker could register. None belongs to a real organisation.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

type Lang = Literal["de", "en"]


class Brand(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    name: str
    domain: str
    sender_address: str
    color: str
    color_dark: str
    postal_address: str
    register_line: str

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
