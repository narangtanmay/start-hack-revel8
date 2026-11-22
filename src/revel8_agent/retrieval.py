"""Use what we scraped: de-duplicate the dossier and retrieve the facts relevant to the current touch.

Measured 22 Nov: only 17-22% of scraped facts ever reached a prompt (Julius 68/389, Tom 47/224, Robert 56/253).
The planner's profile was cut at 6,000 characters / 6 facts per theme, and the per-touch writer saw only the
16 brief facts - so when a target mentioned a colleague, a customer, a project or an event, the writer could not
use what research had already found about it. Deterministic, no extra LLM call: IDF-weighted word overlap.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

_STOP = set("""about above after again also among another because been before being between both could does
doing during each either every from further have having here into itself just more most much must other over
please really same should since some such than that their them then there these they this those through under
until very want were what when where which while whom whose will with within would your yours their the and for
with company team revel8""".split())


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-zäöüß0-9][a-zäöüß0-9-]{3,}", (text or "").lower()) if w not in _STOP]


def dedupe(facts: list[Any], threshold: float = 0.6) -> list[Any]:
    """Drop near-duplicate facts (same story from ten articles), keeping the first (callers pass best-first)."""
    kept, sigs = [], []
    for f in facts:
        s = set(_words(getattr(f, "fact", "")))
        if not s:
            continue
        if any(len(s & t) / max(1, len(s | t)) >= threshold for t in sigs):
            continue
        kept.append(f)
        sigs.append(s)
    return kept


class FactIndex:
    def __init__(self, dossier: Any) -> None:
        facts = [f for f in getattr(dossier, "facts", []) or [] if not getattr(f, "conflicts_with", None)]
        self.facts = dedupe(facts)
        self.docs = [Counter(_words(f"{f.fact} {getattr(f, 'verbatim_quote', '')}")) for f in self.facts]
        df = Counter(w for d in self.docs for w in d)
        n = max(1, len(self.docs))
        self.idf = {w: math.log(1 + n / c) for w, c in df.items()}

    def search(self, query: str, k: int = 12, exclude: set[str] | None = None) -> list[Any]:
        q = set(_words(query))
        if not q:
            return []
        exclude = exclude or set()
        scored = []
        for f, d in zip(self.facts, self.docs):
            if f.id in exclude:
                continue
            s = sum(self.idf.get(w, 0.0) for w in q if w in d)
            if s > 0:
                scored.append((s, f))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [f for _, f in scored[:k]]

    def prompt(self, query: str, k: int = 12, exclude: set[str] | None = None) -> str:
        hits = self.search(query, k, exclude)
        if not hits:
            return ""
        lines = [f"- [{f.id} | {f.category} | {f.recency or 'undated'}] {f.fact[:260]}" for f in hits]
        return ("FACTS RELEVANT TO THIS TOUCH (verified research matching what they just said and the current story; "
                "use them to answer precisely and to name real people/projects/events - cite ids, state nothing else "
                "about them):\n" + "\n".join(lines))
