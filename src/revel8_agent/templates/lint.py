"""Craft checks the gate does not cover: leftover placeholders and link text that lies."""

import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

_PLACEHOLDER = re.compile(
    r"\{\{|\}\}|\{[a-z_]+\}|\bTODO\b|\bLorem\b|\bXXX\b|\[(?:name|link|url|company)\]", re.IGNORECASE
)
_URLISH = re.compile(r"^(?:https?://)?[\w.-]+\.[a-z]{2,}(?:[/?#]\S*)?$", re.IGNORECASE)


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self.text: list[str] = []
        self._href: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href") or ""
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.links.append((self._href, "".join(self._buf).strip()))
            self._href = None

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self._href is not None:
            self._buf.append(data)


def _host(url: str) -> str:
    if "://" not in url:
        url = "https://" + url
    return (urlsplit(url).hostname or "").lower()


def lint_html(html: str) -> list[str]:
    parser = _Links()
    parser.feed(html)
    parser.close()
    problems = []
    if _PLACEHOLDER.search(" ".join(parser.text)):
        problems.append("Visible text contains a placeholder.")
    for href, text in parser.links:
        if not href:
            problems.append(f"Link {text!r} has no href.")
        elif _URLISH.match(text) and _host(text) != _host(href):
            problems.append(f"Link text {text!r} does not match its target {href!r}.")
    return problems


def lint_text(text: str) -> list[str]:
    return ["Text contains a placeholder."] if _PLACEHOLDER.search(text) else []
