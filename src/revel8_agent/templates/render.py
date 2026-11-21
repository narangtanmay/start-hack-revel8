"""Render HTML to PNG with headless Chromium (Chrome or Edge), the way the scorer does.

The network is blocked, so only local files appear. Scripts are not disabled by flag
(--blink-settings=scriptEnabled=false stops Edge writing screenshots); the gate already
rejects any <script>, so the result is the same.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

MAIL_WIDTH = 700
PAGE_WIDTH = 1200


def find_browser() -> Path | None:
    candidates = [
        shutil.which("chrome"),
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("msedge"),
    ]
    for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")):
        if root:
            candidates += [
                str(Path(root) / "Google/Chrome/Application/chrome.exe"),
                str(Path(root) / "Microsoft/Edge/Application/msedge.exe"),
            ]
    return next((Path(c) for c in candidates if c and Path(c).is_file()), None)


def screenshot(
    html_file: Path, out_png: Path, *, width: int, height: int = 900, scale: int = 1, transparent: bool = False
) -> None:
    browser = find_browser()
    if browser is None:
        raise RuntimeError("No Chrome or Edge found for rendering.")
    out_png = out_png.resolve()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as profile:
        args = [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            f"--user-data-dir={profile}",
            "--host-resolver-rules=MAP * ~NOTFOUND",
            f"--window-size={width},{height}",
            f"--force-device-scale-factor={scale}",
            f"--screenshot={out_png}",
        ]
        if transparent:
            args.append("--default-background-color=00000000")
        args.append(html_file.resolve().as_uri())
        result = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if not out_png.is_file():
        output = (result.stdout + result.stderr).strip()[-800:]
        raise RuntimeError(f"Browser did not write {out_png} (exit {result.returncode}). {output}")
