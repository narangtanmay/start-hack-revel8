"""Their real network: the people and organisations the target actually deals with, from verified research.

Why (live practice 22 Nov): every invented stranger got verified and failed ("I don't recognise 'Cyber27' or Jonas
Reimer", "who invited me?"), and links/attachments from unverified senders were refused. The research already
collects who the person works with (category "network", plus events/talks), but the planner treated those facts as
static background. This module turns them into a ranked list of real relationships the campaign can use: as the
sender (from an invented lookalike domain, which the engine's domain check enforces) or as the referrer.

Generic on purpose: relationship types come from the words of the facts, not from who the practice targets are.
"""
from __future__ import annotations

import re
from typing import Any

_REL = [  # (relationship, pattern) - first match wins, most useful senders first
    ("investor/angel", r"invest|backed|angel|seed|series [a-e]|venture|capital\b|fund\b|board"),
    ("colleague/co-founder", r"co-?found|works? with|colleague|team(?:mate)?|new hires?|joined|reports to|cto|ceo|cfo"),
    ("event host/co-speaker", r"panel|speaker|roundtable|hosted|host(?:s|ed)? by|conference|summit|keynote|podcast|hackathon"),
    ("partner/customer", r"partner|customer|client|pilot|integrat"),
    ("co-author/alumni", r"co-?author|chapter|paper|alumni|met at|former|ex-"),
]
_CATS = {"network", "talk_or_event", "current_project", "company_news", "publication", "hiring"}
_NAME = re.compile(r"\b([A-Z][a-zäöüé]+(?:[ -](?:von |van |de )?[A-Z][a-zäöüé]+){1,2})\b")


def _fact(f: Any, key: str) -> Any:
    return f.get(key) if isinstance(f, dict) else getattr(f, key, None)


def relationships(dossier: Any, limit: int = 18, per_rel: int = 4) -> list[dict]:
    target = str(getattr(dossier, "target_name", "") or "")
    own = {w.lower() for w in target.split()}
    out, seen = [], set()
    for f in getattr(dossier, "facts", []) or []:
        if _fact(f, "category") not in _CATS:
            continue
        text = str(_fact(f, "fact") or "")
        rel = next((r for r, rx in _REL if re.search(rx, text, re.I)), None)
        if not rel:
            continue
        names = [n for n in _NAME.findall(text) if not ({w.lower() for w in n.split()} & own)]
        key = (rel, tuple(sorted(names))[:3], text[:60])
        if not names or key in seen:
            continue
        seen.add(key)
        out.append({"id": _fact(f, "id"), "relationship": rel, "names": names[:6], "fact": text[:220]})
    order = [r for r, _ in _REL]
    out.sort(key=lambda x: (order.index(x["relationship"]), -len(x["names"])))
    # The same funding round is reported by ten articles: keep a fact only if it adds a new name, and at most
    # `per_rel` per relationship type so colleagues, hosts and co-authors are not crowded out.
    kept, named, per = [], set(), {}
    for r in out:
        new = [n for n in r["names"] if n not in named]
        if not new or per.get(r["relationship"], 0) >= per_rel:
            continue
        named.update(r["names"])
        per[r["relationship"]] = per.get(r["relationship"], 0) + 1
        kept.append(r)
    return kept[:limit]


def network_prompt(dossier: Any) -> str:
    rels = relationships(dossier)
    if not rels:
        return ""
    lines = [f"- [{r['id']}] {r['relationship']}: {', '.join(r['names'])} | {r['fact']}" for r in rels]
    return ("THEIR REAL NETWORK (verified facts; real people/organisations they deal with - the most credible senders "
            "or referrers; cite the fact id):\n" + "\n".join(lines))
