"""Which language does this person work in? Inferred from their own words, never assumed.

Held-out eval targets can be anyone, so the agent writes in the language the target actually uses: we score the
verbatim quotes in their dossier with stop-word counts per language, weighting their own voice (posts, own
articles) over facts that merely name them over general web pages, plus a weak hint from source domains.
During the conversation their replies are the strongest signal: if they answer in another language, we switch.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any
from urllib.parse import urlsplit

# Short, high-frequency function words that are rare in other languages.
_STOP: dict[str, set[str]] = {
    "en": {"the", "and", "of", "to", "is", "in", "that", "for", "with", "we", "our", "are", "this", "it", "you", "on", "be", "how", "what"},
    "de": {"der", "die", "das", "und", "ist", "nicht", "mit", "wir", "ein", "eine", "für", "auf", "sich", "auch", "unsere", "ich", "zu", "den", "dem", "wie", "bei"},
    "fr": {"le", "la", "les", "et", "est", "des", "une", "pour", "dans", "nous", "avec", "pas", "que", "qui", "sur", "au", "du", "ce"},
    "es": {"el", "los", "las", "y", "es", "una", "para", "con", "por", "que", "del", "nuestro", "como", "más", "pero", "su", "lo"},
    "it": {"il", "lo", "gli", "e", "è", "una", "per", "con", "che", "della", "nostro", "come", "più", "sono", "anche", "non", "del"},
    "nl": {"de", "het", "een", "en", "is", "van", "voor", "met", "wij", "onze", "niet", "ook", "dat", "op", "zijn", "bij"},
    "pt": {"o", "os", "as", "e", "é", "uma", "para", "com", "que", "não", "nosso", "como", "mais", "do", "da", "em"},
    "pl": {"i", "w", "nie", "na", "się", "jest", "że", "do", "to", "z", "jak", "dla", "nasz", "oraz"},
    "sv": {"och", "är", "att", "det", "en", "för", "med", "inte", "vi", "vår", "som", "på", "av"},
    "da": {"og", "er", "at", "det", "en", "for", "med", "ikke", "vi", "vores", "som", "på", "af"},
}
_NAMES = {"en": "English", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian", "nl": "Dutch",
          "pt": "Portuguese", "pl": "Polish", "sv": "Swedish", "da": "Danish"}
_TLD = {"de": "de", "at": "de", "ch": "de", "fr": "fr", "es": "es", "it": "it", "nl": "nl", "be": "nl", "pt": "pt",
        "br": "pt", "pl": "pl", "se": "sv", "dk": "da"}
_WORD = re.compile(r"[a-zäöüßéèêàâçñóòôúùíìîïëåøæąćęłńśźż]+", re.I)


def detect(text: str) -> tuple[str, float]:
    """(language code, confidence 0..1) for one text by stop-word share; ('', 0) if too short to tell."""
    words = [w.lower() for w in _WORD.findall(text or "")]
    if len(words) < 4:
        return "", 0.0
    counts = {lang: sum(1 for w in words if w in stops) for lang, stops in _STOP.items()}
    best = max(counts, key=counts.get)
    total = sum(counts.values())
    if counts[best] == 0:
        return "", 0.0
    return best, counts[best] / total


def infer_language(dossier: Any) -> dict:
    """The target's working language from their dossier: own voice x3, facts naming them x2, other facts x1,
    plus a small hint per source domain (.de, .fr, ...). Returns {"language", "name", "confidence", "evidence"}."""
    votes: Counter = Counter()
    surname = (dossier.target_name.split() or [""])[-1].lower()
    n_texts = 0
    for f in dossier.facts:
        lang, conf = detect(f.verbatim_quote)
        kind = getattr(f, "source_kind", "") or "web"
        weight = 3.0 if kind in ("social", "own_article") else (2.0 if surname and surname in f.verbatim_quote.lower() else 1.0)
        if lang and conf >= 0.5:
            votes[lang] += weight * conf
            n_texts += 1
        tld = (urlsplit(f.source_url).hostname or "").rsplit(".", 1)[-1]
        if tld in _TLD:
            votes[_TLD[tld]] += 0.15
    if not votes:
        return {"language": "en", "name": "English", "confidence": 0.0, "evidence": "no usable text: default English"}
    total = sum(votes.values())
    lang, score = votes.most_common(1)[0]
    share = score / total
    top = ", ".join(f"{_NAMES.get(k, k)} {v / total:.0%}" for k, v in votes.most_common(3))
    return {"language": lang, "name": _NAMES.get(lang, lang), "confidence": round(share, 2),
            "evidence": f"{n_texts} quotes scored ({top})"}


def decide_language(profile: dict, replies: list[str] | None = None, threshold: float = 0.6) -> dict:
    """What to write in. Their replies win (they chose the language); otherwise the profile if it is clear
    (share >= threshold); otherwise English."""
    for text in reversed(replies or []):
        lang, conf = detect(text)
        if lang and conf >= 0.5 and len(text.split()) >= 6:
            return {"language": lang, "name": _NAMES.get(lang, lang), "why": "they replied in this language"}
    if profile.get("confidence", 0) >= threshold:
        return {"language": profile["language"], "name": profile["name"],
                "why": f"their public profile is mostly {profile['name']} ({profile['evidence']})"}
    return {"language": "en", "name": "English",
            "why": f"profile language unclear ({profile.get('evidence', 'no evidence')}): English is the safe default"}
