"""Landing pages, registered with the API as LandingPageSpec.

Each page matches the brand of the mail that links to it and is laid out for a
~1200px browser window.
"""

from html import escape

from ..schemas import LandingPageSpec
from .brand import Brand, Lang

_FONT = "Segoe UI,Helvetica,Arial,sans-serif"

_TEXT = {
    "de": {
        "signin": "Anmelden",
        "signin_title": "{brand}: Anmelden",
        "signin_sub": "Melden Sie sich mit der E-Mail-Adresse an, mit der Sie registriert sind.",
        "email": "E-Mail-Adresse",
        "password": "Passwort",
        "code": "Bestätigungscode",
        "mfa_title": "{brand}: Bestätigung",
        "mfa_head": "Anmeldung bestätigen",
        "mfa_sub": "Geben Sie den 6-stelligen Code aus Ihrer Authenticator-App ein.",
        "confirm": "Bestätigen",
        "doc_title": "{brand}: {doc}",
        "doc_head": "Dokument ansehen",
        "doc_sub": "Melden Sie sich an, um „{doc}“ zu öffnen.",
        "meeting_title": "{brand}: Besprechung beitreten",
        "meeting_head": "Besprechung beitreten",
        "meeting_sub": "{meeting}. Melden Sie sich an, um der Besprechung beizutreten.",
        "join": "Anmelden und beitreten",
        "privacy": "Datenschutz",
        "imprint": "Impressum",
    },
    "en": {
        "signin": "Sign in",
        "signin_title": "{brand}: Sign in",
        "signin_sub": "Sign in with the email address you registered with.",
        "email": "Email address",
        "password": "Password",
        "code": "Verification code",
        "mfa_title": "{brand}: Verification",
        "mfa_head": "Confirm sign-in",
        "mfa_sub": "Enter the 6-digit code from your authenticator app.",
        "confirm": "Confirm",
        "doc_title": "{brand}: {doc}",
        "doc_head": "View document",
        "doc_sub": "Sign in to open “{doc}”.",
        "meeting_title": "{brand}: Join meeting",
        "meeting_head": "Join meeting",
        "meeting_sub": "{meeting}. Sign in to join the meeting.",
        "join": "Sign in and join",
        "privacy": "Privacy",
        "imprint": "Legal notice",
    },
}

_FIELD_TYPES = {"email": "email", "password": "password", "code": "text"}


def _field(name: str, label: str) -> str:
    kind = _FIELD_TYPES.get(name, "text")
    return (
        f'<label for="{name}" style="display:block;margin:0 0 6px;font-size:14px;font-weight:600;color:#374151;">'
        f"{escape(label)}</label>"
        f'<input id="{name}" name="{name}" type="{kind}" style="box-sizing:border-box;width:100%;margin:0 0 18px;'
        'padding:11px 12px;font-size:15px;border:1px solid #d1d5db;border-radius:6px;font-family:inherit;">'
    )


def _submit(brand: Brand, label: str) -> str:
    return (
        '<button type="submit" style="width:100%;padding:12px;font-size:15px;font-weight:600;color:#ffffff;'
        f'background:{brand.color};border:0;border-radius:6px;font-family:inherit;">{escape(label)}</button>'
    )


def _page(brand: Brand, lang: Lang, title: str, logo_asset: str, heading: str, sub: str, form: str) -> str:
    t = _TEXT[lang]
    return (
        f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><title>{escape(title)}</title></head>'
        f'<body style="margin:0;min-height:100vh;background:#f3f4f6;font-family:{_FONT};color:#111827;">'
        f'<div style="height:4px;background:{brand.color};"></div>'
        '<div style="max-width:420px;margin:72px auto 0;padding:0 16px;">'
        f'<img src="asset://{escape(logo_asset)}" alt="{escape(brand.name)}" '
        'style="display:block;height:40px;margin:0 0 28px;">'
        '<div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:10px;padding:32px;'
        'box-shadow:0 1px 3px rgba(0,0,0,0.06);">'
        f'<h1 style="margin:0 0 8px;font-size:22px;">{escape(heading)}</h1>'
        f'<p style="margin:0 0 24px;font-size:14px;line-height:1.5;color:#6b7280;">{escape(sub)}</p>'
        f'<form method="post" action="">{form}</form></div>'
        '<p style="margin:24px 0;font-size:12px;line-height:1.6;color:#6b7280;text-align:center;">'
        + (f"{escape(brand.postal_address)}<br>" if brand.postal_address else "")
        + f'{escape(t["privacy"])} · {escape(t["imprint"])}</p>'
        "</div></body></html>"
    )


def signin_page(brand: Brand, *, url: str, logo_asset: str, lang: Lang = "de") -> LandingPageSpec:
    t = _TEXT[lang]
    title = t["signin_title"].format(brand=brand.name)
    form = _field("email", t["email"]) + _field("password", t["password"]) + _submit(brand, t["signin"])
    html = _page(brand, lang, title, logo_asset, t["signin"], t["signin_sub"], form)
    return LandingPageSpec(url=url, title=title, html=html, fields=["email", "password"])


def mfa_page(brand: Brand, *, url: str, logo_asset: str, lang: Lang = "de") -> LandingPageSpec:
    t = _TEXT[lang]
    title = t["mfa_title"].format(brand=brand.name)
    form = _field("code", t["code"]) + _submit(brand, t["confirm"])
    html = _page(brand, lang, title, logo_asset, t["mfa_head"], t["mfa_sub"], form)
    return LandingPageSpec(url=url, title=title, html=html, fields=["code"])


def document_gate_page(
    brand: Brand, *, url: str, logo_asset: str, document_name: str, lang: Lang = "de"
) -> LandingPageSpec:
    t = _TEXT[lang]
    title = t["doc_title"].format(brand=brand.name, doc=document_name)
    form = _field("email", t["email"]) + _field("password", t["password"]) + _submit(brand, t["signin"])
    html = _page(brand, lang, title, logo_asset, t["doc_head"], t["doc_sub"].format(doc=document_name), form)
    return LandingPageSpec(url=url, title=title, html=html, fields=["email", "password"])


def meeting_page(
    brand: Brand, *, url: str, logo_asset: str, meeting_name: str, lang: Lang = "de"
) -> LandingPageSpec:
    """Join page for a meeting the target asked us to send a link for ("Bitte schicken Sie den Link zum Termin")."""
    t = _TEXT[lang]
    title = t["meeting_title"].format(brand=brand.name)
    form = _field("email", t["email"]) + _field("password", t["password"]) + _submit(brand, t["join"])
    html = _page(brand, lang, title, logo_asset, t["meeting_head"], t["meeting_sub"].format(meeting=meeting_name), form)
    return LandingPageSpec(url=url, title=title, html=html, fields=["email", "password"])
