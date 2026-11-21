"""Generate brand logos as PNG files, which is what the API accepts for upload."""

import tempfile
from html import escape
from pathlib import Path

from .brand import Brand
from .render import screenshot

DEFAULT_ASSET_DIR = Path("data/assets")


def _logo_html(brand: Brand) -> str:
    initial = escape(brand.name[0])
    return (
        '<!doctype html><html><head><meta charset="utf-8"></head>'
        '<body style="margin:0;background:transparent;">'
        '<div style="display:flex;align-items:center;height:72px;padding:0 4px;'
        'font-family:Segoe UI,Arial,sans-serif;">'
        f'<div style="width:48px;height:48px;border-radius:12px;background:{brand.color};color:#fff;'
        f'font-size:28px;font-weight:700;display:flex;align-items:center;justify-content:center;">{initial}</div>'
        f'<div style="margin-left:12px;font-size:26px;font-weight:600;color:{brand.color_dark};'
        f'white-space:nowrap;">{escape(brand.name)}</div></div></body></html>'
    )


def render_logo(brand: Brand, out_dir: Path = DEFAULT_ASSET_DIR) -> Path:
    """Write the brand logo PNG (about 2x resolution) and return its path."""
    out_png = out_dir / brand.logo_filename
    with tempfile.TemporaryDirectory() as tmp:
        html_file = Path(tmp) / "logo.html"
        html_file.write_text(_logo_html(brand), encoding="utf-8")
        screenshot(html_file, out_png, width=460, height=72, scale=2, transparent=True)
    return out_png
