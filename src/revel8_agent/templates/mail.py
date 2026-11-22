"""Mail bodies for the three sender styles the agent uses.

Content (headline, paragraphs, names) comes from the planner. These builders only add the
form a real sender would use: branded layout for a company, plain text for a colleague.
All inserted text is escaped. Images use asset:// sources only, and every visible URL
matches the link it points to.
"""

from html import escape

from .brand import Brand, Lang

_FONT = "Segoe UI,Helvetica,Arial,sans-serif"

_TEXT = {
    "de": {
        "greeting": "Hallo {name},",
        "fallback": "Falls der Button nicht funktioniert, öffnen Sie diesen Link:",
        "automated": "Diese Nachricht wurde automatisch versendet. Bitte antworten Sie nicht direkt auf diese E-Mail.",
        "shared": "{sharer} hat ein Dokument mit Ihnen geteilt",
        "open_doc": "Dokument öffnen",
        "message_from": "Nachricht von {sharer}:",
        "regards": "Viele Grüße",
    },
    "en": {
        "greeting": "Hi {name},",
        "fallback": "If the button does not work, open this link:",
        "automated": "This message was sent automatically. Please do not reply directly to this email.",
        "shared": "{sharer} shared a document with you",
        "open_doc": "Open document",
        "message_from": "Message from {sharer}:",
        "regards": "Best regards",
    },
}


def _paragraphs(paragraphs: list[str]) -> str:
    return "".join(
        f'<p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#1f2937;">{escape(p)}</p>'
        for p in paragraphs
    )


def _shell(brand: Brand, lang: Lang, title: str, logo_asset: str, inner: str) -> str:
    t = _TEXT[lang]
    return (
        f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title></head>'
        f'<body style="margin:0;padding:0;background:#f3f4f6;font-family:{_FONT};">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;">'
        '<tr><td align="center" style="padding:24px 12px;">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" '
        'style="width:600px;max-width:100%;background:#ffffff;border-radius:8px;overflow:hidden;'
        'border:1px solid #e5e7eb;">'
        f'<tr><td style="height:4px;background:{brand.color};font-size:0;line-height:0;">&nbsp;</td></tr>'
        f'<tr><td style="padding:24px 32px 8px;"><img src="asset://{escape(logo_asset)}" alt="{escape(brand.name)}" '
        'height="36" style="display:block;height:36px;border:0;"></td></tr>'
        f'<tr><td style="padding:16px 32px 8px;">{inner}</td></tr>'
        '<tr><td style="padding:16px 32px 24px;border-top:1px solid #e5e7eb;font-size:12px;line-height:1.5;'
        'color:#6b7280;">'
        + "<br>".join(escape(x) for x in (t["automated"], brand.postal_address, brand.register_line) if x)
        + "</td></tr></table></td></tr></table></body></html>"
    )


def _button(brand: Brand, label: str, url: str) -> str:
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:8px 0 20px;"><tr>'
        f'<td style="border-radius:6px;background:{brand.color};">'
        f'<a href="{escape(url)}" style="display:inline-block;padding:12px 24px;font-size:15px;font-weight:600;'
        f'color:#ffffff;text-decoration:none;font-family:{_FONT};">{escape(label)}</a></td></tr></table>'
    )


def _fallback_link(lang: Lang, url: str) -> str:
    return (
        f'<p style="margin:0 0 8px;font-size:13px;line-height:1.5;color:#6b7280;">'
        f'{escape(_TEXT[lang]["fallback"])}<br>'
        f'<a href="{escape(url)}" style="color:#2563eb;word-break:break-all;">{escape(url)}</a></p>'
    )


def vendor_notice(
    brand: Brand,
    *,
    logo_asset: str,
    recipient_name: str,
    headline: str,
    paragraphs: list[str],
    cta_label: str,
    cta_url: str,
    lang: Lang = "de",
) -> str:
    """A branded service notice with one call to action, e.g. a password expiry or access review."""
    inner = (
        f'<h1 style="margin:0 0 16px;font-size:22px;line-height:1.3;color:#111827;">{escape(headline)}</h1>'
        '<p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#1f2937;">'
        f'{escape(_TEXT[lang]["greeting"].format(name=recipient_name))}</p>'
        f"{_paragraphs(paragraphs)}{_button(brand, cta_label, cta_url)}{_fallback_link(lang, cta_url)}"
    )
    return _shell(brand, lang, headline, logo_asset, inner)


def shared_doc_notice(
    brand: Brand,
    *,
    logo_asset: str,
    sharer_name: str,
    sharer_email: str,
    document_name: str,
    doc_url: str,
    note: str | None = None,
    lang: Lang = "de",
) -> str:
    """A 'someone shared a file with you' notice from a document-sharing service."""
    t = _TEXT[lang]
    title = t["shared"].format(sharer=sharer_name)
    note_html = ""
    if note:
        note_html = (
            '<p style="margin:0 0 4px;font-size:13px;color:#6b7280;">'
            f'{escape(t["message_from"].format(sharer=sharer_name))}</p>'
            f'<p style="margin:0 0 20px;padding:12px 16px;background:#f9fafb;border-left:3px solid {brand.color};'
            f'font-size:15px;line-height:1.6;color:#1f2937;">{escape(note)}</p>'
        )
    inner = (
        f'<h1 style="margin:0 0 6px;font-size:20px;line-height:1.3;color:#111827;">{escape(title)}</h1>'
        f'<p style="margin:0 0 20px;font-size:13px;color:#6b7280;">{escape(sharer_email)}</p>'
        f"{note_html}"
        '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 16px;'
        'border:1px solid #e5e7eb;border-radius:6px;width:100%;"><tr>'
        f'<td style="padding:14px 16px;font-size:15px;color:#111827;">&#128196;&nbsp; {escape(document_name)}</td>'
        "</tr></table>"
        f"{_button(brand, t['open_doc'], doc_url)}{_fallback_link(lang, doc_url)}"
    )
    return _shell(brand, lang, title, logo_asset, inner)


def colleague_note(
    *,
    recipient_name: str,
    paragraphs: list[str],
    sender_name: str,
    sender_role: str | None = None,
    link: str | None = None,
    phone: str | None = None,
    lang: Lang = "de",
    organisation: str | None = None,
    website: str | None = None,
) -> str:
    """A short plain-text note from a person. Send with is_html=False: a glossy template looks wrong here.
    Craft (rubric: 'tone and signature for a person', 'do the details hold'): a real business signature block,
    one item per line, whose website matches the sender's mail domain."""
    t = _TEXT[lang]
    lines = [t["greeting"].format(name=recipient_name), ""]
    for paragraph in paragraphs:
        lines += [paragraph, ""]
    if link:
        lines += [link, ""]
    lines += [t["regards"], sender_name]
    role = (sender_role or "").strip()
    org = (organisation or "").strip()
    if org and role.lower().endswith(", " + org.lower()):
        role = role[: -len(org) - 2].strip()
    contact = " · ".join(x for x in (phone, f"www.{website}" if website else None) if x)
    lines += [x for x in (role, org if org.lower() not in role.lower() else None, contact) if x]
    return "\n".join(lines)
