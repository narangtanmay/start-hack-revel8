"""Mail and landing-page templates for the craft score.

Typical use by the planner:

    brand = get_brand("nordlicht")
    body = vendor_notice(brand, logo_asset=asset_id, recipient_name="Julius", headline=..., ...)
    page = signin_page(brand, url="https://login.nordlicht-itservice.de/auth", logo_asset=asset_id)

Generate the logo once with `render_logo(brand)`, upload it, and reuse its asset id.
"""

from .assets import render_logo
from .brand import BRANDS, Brand, get_brand
from .lint import lint_html, lint_text
from .mail import colleague_note, shared_doc_notice, vendor_notice
from .pages import document_gate_page, mfa_page, signin_page

__all__ = [
    "BRANDS",
    "Brand",
    "colleague_note",
    "document_gate_page",
    "get_brand",
    "lint_html",
    "lint_text",
    "mfa_page",
    "render_logo",
    "shared_doc_notice",
    "signin_page",
    "vendor_notice",
]
