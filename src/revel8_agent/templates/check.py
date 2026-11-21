"""Render every template the way the scorer does and check it.

    uv run python -m revel8_agent.templates.check [--out output/renders]

For each brand: renders the logo, builds sample mails and pages, runs them through the
pre-send gate and the craft lint, and writes PNG screenshots (mail 700px, page 1200px).
"""

import argparse
import sys
from html import escape
from pathlib import Path

from ..gate import validate_contact_plan
from ..schemas import ContactPlan, SenderInfo, VerifiedDossier
from .assets import DEFAULT_ASSET_DIR, render_logo
from .brand import BRANDS, Brand
from .lint import lint_html, lint_text
from .mail import colleague_note, shared_doc_notice, vendor_notice
from .pages import document_gate_page, mfa_page, signin_page
from .render import MAIL_WIDTH, PAGE_WIDTH, find_browser, screenshot

_LOGO_ID = "a_logo"
_DOSSIER = VerifiedDossier(target_id="preview", target_name="Alex Beispiel", role="Preview", company="Preview")


def _mail_frame(sender: SenderInfo, subject: str, body: str, is_html: bool) -> str:
    """A minimal mail-client view: sender line, subject, then the body."""
    content = body if is_html else f'<pre style="font-family:Segoe UI,Arial,sans-serif;font-size:15px;white-space:pre-wrap;margin:0;">{escape(body)}</pre>'
    return (
        '<!doctype html><html><head><meta charset="utf-8"></head>'
        '<body style="margin:0;background:#ffffff;font-family:Segoe UI,Arial,sans-serif;">'
        '<div style="padding:16px 20px;border-bottom:1px solid #e5e7eb;">'
        f'<div style="font-size:18px;font-weight:600;color:#111827;">{escape(subject)}</div>'
        f'<div style="margin-top:6px;font-size:13px;color:#374151;"><b>{escape(sender.name)}</b> '
        f'&lt;{escape(sender.address)}&gt;</div></div>'
        f'<div style="padding:{0 if is_html else 20}px;">{content}</div></body></html>'
    )


def _samples(brand: Brand) -> list[tuple[str, ContactPlan]]:
    base = f"https://{brand.domain}"
    sender = SenderInfo(name=brand.name, address=brand.sender_address)
    signin = signin_page(brand, url=f"{base}/auth/login", logo_asset=_LOGO_ID)
    doc_url = f"{base}/d/7Kq2Lm"
    docgate = document_gate_page(brand, url=doc_url, logo_asset=_LOGO_ID, document_name="Q3_Roadmap.pdf")
    return [
        (
            "vendor-notice",
            ContactPlan(
                to="preview",
                channel="email",
                sender=sender,
                subject="Ihr Passwort läuft in 2 Tagen ab",
                is_html=True,
                body=vendor_notice(
                    brand,
                    logo_asset=_LOGO_ID,
                    recipient_name="Alex",
                    headline="Ihr Passwort läuft bald ab",
                    paragraphs=[
                        "Ihr Passwort für das Firmenkonto läuft in 2 Tagen ab.",
                        "Bitte bestätigen Sie Ihr aktuelles Passwort, damit Ihr Zugang ohne Unterbrechung bestehen bleibt.",
                    ],
                    cta_label="Passwort bestätigen",
                    cta_url=signin.url,
                ),
                landing_page=signin,
            ),
        ),
        (
            "shared-doc",
            ContactPlan(
                to="preview",
                channel="email",
                sender=SenderInfo(name=f"Maria Keller via {brand.name}", address=brand.sender_address),
                subject="Maria Keller hat „Q3_Roadmap.pdf“ mit Ihnen geteilt",
                is_html=True,
                body=shared_doc_notice(
                    brand,
                    logo_asset=_LOGO_ID,
                    sharer_name="Maria Keller",
                    sharer_email="maria.keller@partner-beispiel.de",
                    document_name="Q3_Roadmap.pdf",
                    doc_url=doc_url,
                    note="Hier die aktuelle Fassung, wie besprochen. Feedback gern bis Freitag.",
                ),
                landing_page=docgate,
            ),
        ),
        (
            "colleague-note",
            ContactPlan(
                to="preview",
                channel="email",
                sender=SenderInfo(name="Jonas Weber", address=f"jonas.weber@{brand.domain}"),
                subject="Kurze Frage zu Donnerstag",
                is_html=False,
                body=colleague_note(
                    recipient_name="Alex",
                    paragraphs=["Hast du kurz Zeit, über die Agenda für Donnerstag zu schauen?"],
                    sender_name="Jonas Weber",
                    sender_role="Projektleitung",
                    link=f"{base}/agenda",
                ),
            ),
        ),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render and check all templates.")
    parser.add_argument("--out", type=Path, default=Path("output/renders"))
    parser.add_argument("--no-render", action="store_true", help="Only run gate and lint checks.")
    args = parser.parse_args(argv)

    render = not args.no_render
    if render and find_browser() is None:
        print("No Chrome or Edge found; running checks without screenshots.", file=sys.stderr)
        render = False

    failures = 0
    for brand in BRANDS.values():
        logo_uri = ""
        if render:
            logo_uri = render_logo(brand, DEFAULT_ASSET_DIR).resolve().as_uri()

        for name, plan in _samples(brand):
            problems = list(validate_contact_plan(plan, _DOSSIER, blocked_org_domains=[]).errors)
            problems += lint_html(plan.body) if plan.is_html else lint_text(plan.body)
            pages = [plan.landing_page] if plan.landing_page else []
            for page in pages:
                problems += lint_html(page.html)

            label = f"{brand.key}/{name}"
            print(f"{'FAIL' if problems else 'ok  '} {label}")
            for problem in problems:
                print(f"       {problem}")
            failures += bool(problems)

            if render:
                out_dir = args.out / brand.key
                out_dir.mkdir(parents=True, exist_ok=True)
                mail_html = _mail_frame(plan.sender, plan.subject or "", plan.body, plan.is_html)
                _shoot(mail_html.replace(f"asset://{_LOGO_ID}", logo_uri), out_dir / f"{name}.mail", MAIL_WIDTH)
                for page in pages:
                    _shoot(page.html.replace(f"asset://{_LOGO_ID}", logo_uri), out_dir / f"{name}.page", PAGE_WIDTH)

    if render:
        print(f"Screenshots in {args.out.resolve()}")
    return 1 if failures else 0


def _shoot(html: str, stem: Path, width: int) -> None:
    html_file = stem.parent / f"{stem.name}.html"
    html_file.write_text(html, encoding="utf-8")
    screenshot(html_file, stem.parent / f"{stem.name}.png", width=width, height=900)


if __name__ == "__main__":
    raise SystemExit(main())
