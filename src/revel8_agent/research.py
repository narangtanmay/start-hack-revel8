"""Research v2: person-first, multi-lane OSINT with identity resolution, corroboration and conflict detection.

Lanes run in parallel, each on its own Token Factory key (LLMPool.lane(i)):

    web        person-centred web queries (name, interviews, talks, podcasts, role)
    news       Brave news vertical, with publish dates
    media      Brave video + image verticals; image results are used as LEADS to their source pages
               (event recaps, podcast pages), never for face matching
    social     LinkedIn posts/articles, X, YouTube, Medium/Substack, speaker and event platforms
    academic   OpenAlex authors and GitHub users, accepted only if an identity anchor matches
    expansion  round 2: the LLM proposes follow-up queries and identity anchors (earlier employers,
               universities, co-founders, handles) from round-1 facts; anchors must appear in a verified quote

Then, for every source that passes the identity check (full name + an anchor, or surname + company):
LLM extraction -> deterministic verbatim-quote verification -> near-duplicate merge (corroboration)
-> LLM conflict detection over facts with numbers/dates -> themes (what they keep talking about) -> hooks.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote_plus, urlsplit

import httpx

from .engine import timing
from .llm_client import ChatMessage, LLMPool, LocalLLMError, PooledClient
from .osint import _CATEGORIES, _UA, Target, fetch_text, normalize
from .schemas import HookHypothesis, Theme, VerifiedDossier, VerifiedFact

_CACHE = Path(os.getenv("SEARCH_CACHE_DIR", ".cache/search"))
_TTL = float(os.getenv("SEARCH_CACHE_TTL_H", "12")) * 3600
_SNIPPET_ONLY = ("linkedin.com", "x.com", "twitter.com", "crunchbase.com", "facebook.com", "instagram.com",
                 "tiktok.com", "xing.com")
_SKIP = ("duckduckgo.com", "bing.com/ck", "google.com/search")
# Where a fact comes from, for picking the best source among duplicates (person's own words first).
_SOURCE_RANK = {"social": 0, "media": 1, "academic": 2, "news": 3, "web": 4, "expansion": 4}


# --------------------------------------------------------------------------- data


@dataclass
class Hit:
    url: str
    title: str
    snippet: str
    query: str
    lane: str
    published: str = ""


@dataclass
class Doc:
    id: str
    url: str
    title: str
    text: str
    lane: str
    published: str = ""
    snippet_only: bool = False


@dataclass
class Research:
    target: Target
    anchors: list[str]
    hits: list[Hit] = field(default_factory=list)
    docs: list[Doc] = field(default_factory=list)
    facts: list[VerifiedFact] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- identity


def fold(text: str) -> str:
    """Lowercase, NFKC, German umlauts transliterated, accents stripped, whitespace collapsed."""
    t = normalize(text).replace("ü", "ue").replace("ö", "oe").replace("ä", "ae").replace("ß", "ss")
    return "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))


def _variants(word: str) -> set[str]:
    n = normalize(word)
    plain = "".join(c for c in unicodedata.normalize("NFKD", n.replace("ß", "ss")) if not unicodedata.combining(c))
    return {fold(word), plain}


class Identity:
    """Is this text about OUR person? Full name + an identity anchor, or surname + the company."""

    def __init__(self, t: Target, anchors: list[str] | None = None) -> None:
        parts = t.name.split()
        self.first, self.last = parts[0], parts[-1]
        self.company = t.company
        self.anchors: list[str] = []
        for a in [t.company, *(anchors or [])]:
            self.add_anchor(a)

    def add_anchor(self, anchor: str) -> bool:
        a = fold(anchor).strip()
        if len(a) < 3 or a in (fold(x) for x in self.anchors) or a in {fold(self.first), fold(self.last)}:
            return False
        self.anchors.append(anchor.strip())
        return True

    def _hay(self, text: str) -> tuple[str, str]:
        return fold(text), "".join(c for c in unicodedata.normalize("NFKD", normalize(text)) if not unicodedata.combining(c))

    def full_name(self, text: str) -> bool:
        firsts, lasts = _variants(self.first), _variants(self.last)
        for hay in self._hay(text):
            for f in firsts:
                for la in lasts:
                    if re.search(rf"\b{re.escape(f)}\b(?:\s+\S+){{0,2}}\s+{re.escape(la)}\b", hay):
                        return True
        return False

    def surname(self, text: str) -> bool:
        return any(v in h for v in _variants(self.last) for h in self._hay(text))

    def anchor(self, text: str) -> str | None:
        hay = " ".join(self._hay(text))
        return next((a for a in self.anchors if fold(a) in hay), None)

    def about(self, text: str) -> bool:
        if not self.surname(text):
            return False
        a = self.anchor(text)
        return bool(a) and (self.full_name(text) or fold(self.company) == fold(a))


# --------------------------------------------------------------------------- search backends


def _cached(key: str, fn) -> list[dict]:
    path = _CACHE / f"v2_{hashlib.sha1(key.encode()).hexdigest()[:20]}.json"
    if os.getenv("SEARCH_CACHE", "1") != "0" and path.exists() and time.time() - path.stat().st_mtime < _TTL:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            pass
    rows = fn()
    if rows:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return rows


def _until(deadline: float | None, cap: float) -> float:
    """Per-request timeout: at most `cap`, never past the deadline (0 = no time left)."""
    return cap if deadline is None else max(0.0, min(cap, deadline - time.monotonic()))


def brave(http: httpx.Client, vertical: str, q: str, count: int = 10, deadline: float | None = None) -> list[dict]:
    """Brave Search API verticals: web | news | images | videos. Returns plain dicts."""
    key = os.getenv("SEARCH_API_KEY", "").strip()
    if not key:
        return []

    def call() -> list[dict]:
        for attempt in range(3):
            if _until(deadline, 15) <= 0:
                return []
            try:
                r = http.get(f"https://api.search.brave.com/res/v1/{vertical}/search", timeout=_until(deadline, 15),
                             params={"q": q, "count": count},
                             headers={"X-Subscription-Token": key, "Accept": "application/json"})
            except httpx.HTTPError:
                return []
            if r.status_code == 429:
                if _until(deadline, 99) <= 1.5 * (attempt + 1):
                    return []
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code != 200:
                return []
            data = r.json()
            items = (data.get("web") or {}).get("results", []) if vertical == "web" else data.get("results", [])
            out = []
            for it in items:
                url = str(it.get("url") or "")
                if vertical == "images":
                    url = str(it.get("url") or (it.get("properties") or {}).get("url") or "")
                desc = " ".join([str(it.get("description") or "")] + [str(x) for x in it.get("extra_snippets") or []])
                out.append({"url": url, "title": re.sub(r"<[^>]+>", "", str(it.get("title") or "")),
                            "snippet": re.sub(r"<[^>]+>", "", desc).strip()[:600],
                            "published": str(it.get("page_age") or it.get("age") or "")[:10]})
            return [o for o in out if o["url"].startswith("http") and not any(s in o["url"] for s in _SKIP)]
        return []

    return _cached(f"brave|{vertical}|{count}|{q}", call)


def openalex(http: httpx.Client, name: str, deadline: float | None = None) -> list[dict]:
    def call() -> list[dict]:
        try:
            if _until(deadline, 15) <= 0:
                return []
            r = http.get(f"https://api.openalex.org/authors?search={quote_plus(name)}&per-page=5",
                         timeout=_until(deadline, 15))
            items = r.json().get("results", []) if r.status_code == 200 else []
        except (httpx.HTTPError, ValueError):
            return []
        out = []
        for a in items:
            insts = ", ".join(i.get("display_name", "") for i in a.get("last_known_institutions") or [])
            topics = ", ".join(t.get("display_name", "") for t in (a.get("topics") or [])[:6])
            out.append({"url": a.get("id", ""), "title": a.get("display_name", ""),
                        "snippet": f"{a.get('display_name')} — institutions: {insts}. Works: {a.get('works_count')}. "
                                   f"Topics: {topics}.", "published": ""})
        return out
    return _cached(f"openalex|{name}", call)


def gh_users(http: httpx.Client, name: str, deadline: float | None = None) -> list[dict]:
    def call() -> list[dict]:
        try:
            if _until(deadline, 15) <= 0:
                return []
            r = http.get("https://api.github.com/search/users", params={"q": f'fullname:"{name}"'},
                         timeout=_until(deadline, 15))
            logins = [u["login"] for u in (r.json().get("items") or [])[:4]] if r.status_code == 200 else []
        except (httpx.HTTPError, ValueError):
            return []
        out = []
        for login in logins:
            try:
                if _until(deadline, 15) <= 0:
                    break
                u = http.get(f"https://api.github.com/users/{login}", timeout=_until(deadline, 15)).json()
            except (httpx.HTTPError, ValueError):
                continue
            out.append({"url": u.get("html_url", ""), "title": f"{u.get('name')} (@{login}) on GitHub",
                        "snippet": f"{u.get('name')} — company: {u.get('company')}; bio: {u.get('bio')}; "
                                   f"location: {u.get('location')}; blog: {u.get('blog')}; "
                                   f"public repos: {u.get('public_repos')}.", "published": ""})
        return out
    return _cached(f"gh|{name}", call)


def plan_queries(t: Target) -> list[tuple[str, str, str, int]]:
    """(lane, vertical, query, count). Person first; the company is context, not the subject."""
    n = f'"{t.name}"'
    role = t.role.split("(")[-1].rstrip(")") if "(" in t.role else t.role.split(",")[0]
    return [
        ("web", "web", f"{n} {t.company}", 10),
        ("web", "web", f"{n} interview", 10),
        ("web", "web", f"{n} keynote OR talk OR panel OR speaker", 10),
        ("web", "web", f"{n} {role}", 10),
        ("web", "web", f"{n} studied OR university OR alumni OR previously", 10),
        ("news", "news", n, 20),
        ("media", "videos", n, 10),
        ("media", "images", f"{n} {t.company}", 20),
        ("social", "web", f"site:linkedin.com/posts {n}", 20),
        ("social", "web", f"site:linkedin.com/pulse {n}", 10),
        ("social", "web", f"site:linkedin.com/in {n}", 5),
        ("social", "web", f"(site:x.com OR site:twitter.com) {n}", 10),
        ("social", "web", f"(site:youtube.com OR site:podcasts.apple.com OR site:open.spotify.com OR site:podbean.com) {n}", 10),
        ("social", "web", f"(site:medium.com OR site:substack.com) {n}", 10),
        ("social", "web", f"(site:sessionize.com OR site:luma.com OR site:lu.ma OR site:eventbrite.com OR site:meetup.com) {n}", 10),
    ]


# --------------------------------------------------------------------------- LLM steps

_EXTRACT = """You are an OSINT analyst building a profile of ONE person from a public source.
Person: {name} ({role} at {company}). Other names on the page may be different people.
Return ONLY JSON: {{"facts": [{{"fact": str, "category": str, "verbatim_quote": str, "recency": str}}]}}
- Facts about the PERSON first: what they said, opinions, talks, podcasts, posts, projects, past jobs, education,
  awards, hobbies, causes, people they work with, tools they use, plans, travel, events they attend.
  Company facts only if this person is clearly involved right now.
- verbatim_quote: 5-40 consecutive words copied EXACTLY from the source (no ellipsis, no translation).
- recency: a date or period stated in the source (e.g. "2026-03", "April 2026"), else the publish date "{published}", else "unknown".
- category: one of {cats}.
- At most 12 facts. Nothing from your own knowledge."""

_CONFLICTS = """Below are verified facts about {name}, each with an id. Some may contradict each other (different amounts,
dates, counts, titles, or places for the same thing). Return ONLY JSON:
{{"conflicts": [{{"fact_ids": [str], "note": str}}]}}
Only real contradictions about the same thing (e.g. "seed round €5.7M" vs "raised €7M"); different things are not conflicts.
note: one short sentence naming the competing values."""

_THEMES = """Below are verified facts about {name}. Group them into the THEMES this person keeps coming back to
(topics of their talks, posts, interviews, projects, opinions). Return ONLY JSON:
{{"themes": [{{"topic": str, "fact_ids": [str]}}]}}
- 3 to 8 themes, most frequent first; a theme needs at least 2 facts. Use short topic names."""

_HOOKS = """You plan a sanctioned red-team social-engineering SIMULATION against an AI twin of {name} ({role} at {company}).
The twin has 1-2 topics it is open to right now. Using ONLY the verified facts and themes below, rank what matters to
this person RIGHT NOW. TODAY is {today}.
Return ONLY JSON: {{"hooks": [{{"topic": str, "rationale": str, "confidence": float, "supporting_fact_ids": [str]}}],
"own_angle": {{"topic": str, "rationale": str, "confidence": float, "supporting_fact_ids": [str]}}}}
- 3-5 hooks, best first. Prefer themes they repeat (count) and facts with timing "upcoming" or "this-year".
- Facts with timing "past" are background ("after your talk at ..."), never an upcoming occasion.
- Never build a hook on a fact marked CONFLICT. Personal topics beat company news.
- own_angle: one less obvious, personal topic still grounded in the facts. supporting_fact_ids must be ids listed."""


def _json(llm: PooledClient, system: str, user: str, temperature: float = 0.1) -> dict:
    msgs: list[ChatMessage] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        out = llm.chat(msgs, json_mode=True, temperature=temperature)
    except LocalLLMError:
        return {}
    return out if isinstance(out, dict) else {}


def extract(llm: PooledClient, t: Target, doc: Doc) -> list[dict]:
    sys = _EXTRACT.format(name=t.name, role=t.role, company=t.company, published=doc.published or "unknown",
                          cats=", ".join(_CATEGORIES))
    out = _json(llm, sys, f"URL: {doc.url}\nTITLE: {doc.title}\nPUBLISHED: {doc.published or 'unknown'}\n\n"
                          f"SOURCE:\n{doc.text[:12000]}")
    facts = out.get("facts")
    return [f for f in facts if isinstance(f, dict)] if isinstance(facts, list) else []


def verify(raw: dict, doc: Doc, ident: Identity) -> VerifiedFact | None:
    quote = str(raw.get("verbatim_quote") or "").strip().strip('"“”').strip()
    fact = str(raw.get("fact") or "").strip()
    if len(quote.split()) < 4 or not fact or "..." in quote or "…" in quote:
        return None
    if normalize(quote) not in normalize(doc.text):
        return None
    if not ident.about(doc.text):
        return None
    cat = str(raw.get("category") or "other").strip().lower()
    rec = str(raw.get("recency") or "").strip()
    if not rec or rec.lower() == "unknown":
        rec = doc.published or "unknown"
    return VerifiedFact(id="", fact=fact, category=cat if cat in _CATEGORIES else "other", source_url=doc.url,
                        verbatim_quote=quote, recency=rec, lane=doc.lane, published=doc.published)


# --------------------------------------------------------------------------- consolidation


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9€$%]+", fold(s)) if len(w) > 2}


def merge_duplicates(facts: list[VerifiedFact]) -> list[VerifiedFact]:
    """Same claim from several sources -> one fact (best source) with corroborated_by = the others."""
    kept: list[VerifiedFact] = []
    for f in sorted(facts, key=lambda x: _SOURCE_RANK.get(x.lane, 5)):
        tf = _tokens(f.fact)
        for k in kept:
            tk = _tokens(k.fact)
            if tf and tk and len(tf & tk) / len(tf | tk) >= 0.6:
                if f.source_url != k.source_url and f.source_url not in k.corroborated_by:
                    k.corroborated_by.append(f.source_url)
                break
        else:
            kept.append(f)
    return kept


def mark_conflicts(llm: PooledClient, name: str, facts: list[VerifiedFact]) -> int:
    numeric = [f for f in facts if re.search(r"\d", f.fact)]
    if len(numeric) < 2:
        return 0
    listing = "\n".join(f"[{f.id}] {f.fact} (source: {urlsplit(f.source_url).hostname}, {f.recency})" for f in numeric[:80])
    out = _json(llm, _CONFLICTS.format(name=name), listing)
    by_id = {f.id: f for f in facts}
    n = 0
    for c in out.get("conflicts") or []:
        ids = [i for i in (c.get("fact_ids") or []) if i in by_id] if isinstance(c, dict) else []
        if len(ids) < 2:
            continue
        n += 1
        for i in ids:
            by_id[i].conflicts_with = sorted(set(by_id[i].conflicts_with) | (set(ids) - {i}))
            by_id[i].conflict_note = str(c.get("note") or "")[:300]
    return n


def find_themes(llm: PooledClient, name: str, facts: list[VerifiedFact]) -> list[Theme]:
    listing = "\n".join(f"[{f.id}] ({f.category}, {f.recency}) {f.fact}" for f in facts[:150])
    out = _json(llm, _THEMES.format(name=name), listing, temperature=0.2)
    by_id = {f.id: f for f in facts}
    themes = []
    for t in out.get("themes") or []:
        if not isinstance(t, dict) or not t.get("topic"):
            continue
        ids = [i for i in (t.get("fact_ids") or []) if i in by_id]
        if len(ids) < 2:
            continue
        latest = max((by_id[i].published or by_id[i].recency for i in ids), default="")
        themes.append(Theme(topic=str(t["topic"]), count=len(ids), latest=latest if latest != "unknown" else "", fact_ids=ids))
    return sorted(themes, key=lambda x: -x.count)


def rank_hooks(llm: PooledClient, t: Target, facts: list[VerifiedFact], themes: list[Theme]) -> list[HookHypothesis]:
    usable = [f for f in facts if not f.conflicts_with]
    listing = "\n".join(f"[{f.id}] ({f.category}; timing {timing(f.recency)}; {len(f.corroborated_by) + 1} source(s)) {f.fact}"
                        for f in usable[:140])
    conflicted = "\n".join(f"[{f.id}] CONFLICT: {f.fact} ({f.conflict_note})" for f in facts if f.conflicts_with)
    theme_txt = "\n".join(f"- {th.topic}: {th.count} facts, latest {th.latest or 'unknown'} ({', '.join(th.fact_ids[:6])})" for th in themes)
    out = _json(llm, _HOOKS.format(name=t.name, role=t.role, company=t.company, today=time.strftime("%Y-%m-%d")),
                f"THEMES:\n{theme_txt}\n\nFACTS:\n{listing}\n\nDO NOT USE:\n{conflicted}", temperature=0.3)
    known = {f.id for f in usable}
    hooks: list[HookHypothesis] = []

    def build(raw: object, hid: str, own: bool) -> HookHypothesis | None:
        if not isinstance(raw, dict) or not raw.get("topic"):
            return None
        ids = [i for i in raw.get("supporting_fact_ids") or [] if isinstance(i, str) and i in known]
        if not ids:
            return None
        try:
            conf = min(1.0, max(0.0, float(raw.get("confidence", 0.5))))
        except (TypeError, ValueError):
            conf = 0.5
        return HookHypothesis(id=hid, topic=str(raw["topic"]), rationale=str(raw.get("rationale", "")),
                              confidence=conf, is_own_angle=own, supporting_fact_ids=ids)

    for i, raw in enumerate((out.get("hooks") or [])[:5]):
        if (h := build(raw, f"h{i + 1}", False)):
            hooks.append(h)
    if (own := build(out.get("own_angle"), "own1", True)):
        hooks.append(own)
    return hooks


# --------------------------------------------------------------------------- orchestration


def _doc_id(url: str) -> str:
    return "d_" + hashlib.sha1(url.encode()).hexdigest()[:10]


# Time plan for the default 90 s budget; every window scales with the budget (budget_s / 90).
#   search <= 15 s (25 s kept for pages + extraction after it) | pages <= 20 s | round-1 extraction until 45 s remain | snowball rounds while 50 s remain
#   (each needs 30 s) | the last 20 s for conflicts + themes (in parallel, until 12 s remain), then hooks.
_CONSOLIDATE_S = 20.0


class _DeadlineLane:
    """An LLM lane whose every call (retries and key failover included) ends at the research deadline,
    so calls abandoned by a closed window stop instead of competing with the attack for the keys."""

    def __init__(self, lane: object, deadline: float) -> None:
        self.lane, self.deadline = lane, deadline

    def chat(self, messages, *, json_mode: bool = False, temperature: float | None = None):
        return self.lane.chat(messages, json_mode=json_mode, temperature=temperature, deadline=self.deadline)


def _bounded(workers: int, jobs: dict, timeout: float):
    """Run `jobs` ({key: (fn, *args)}) in parallel and yield (key, future) for those done within `timeout`.

    Never waits past the timeout: unfinished work is abandoned (its result is dropped) instead of joined,
    which is what keeps research inside its time budget when a site or the model is slow.
    """
    ex = ThreadPoolExecutor(max(1, workers))
    futs = {ex.submit(fn, *args): key for key, (fn, *args) in jobs.items()}
    try:
        for fut in as_completed(futs, timeout=max(0.0, timeout)):
            yield futs[fut], fut
    except TimeoutError:
        pass
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


def research(t: Target, pool: LLMPool | None = None, *, budget_s: float = 90.0, max_docs: int = 45,
             anchors: list[str] | None = None, log=print) -> tuple[VerifiedDossier, dict]:
    """Research one target and return its dossier within `budget_s` seconds of being called.

    The budget covers this whole function: search, page fetching, extraction, snowball rounds, conflict
    check, themes and hooks. Every phase waits only until its own deadline; slow searches, pages or model
    calls are abandoned, so a slow network or model yields a thinner dossier, never a late one.
    """
    pool = pool or LLMPool()
    start = time.monotonic()
    left = lambda: budget_s - (time.monotonic() - start)  # noqa: E731
    scale = budget_s / 90.0
    deadline = start + budget_s
    lane = lambda i: _DeadlineLane(pool.lane(i), deadline)  # noqa: E731
    reserve_end = _CONSOLIDATE_S * scale  # kept free for conflicts, themes and hooks
    ident = Identity(t, anchors)
    st: dict = {"version": 2, "lanes": {}, "search": [], "sources": {}, "rejected": [], "anchors_added": [],
                "expansion_queries": [], "keys": len(pool), "timings": {}}
    seen_urls: set[str] = set()
    facts: list[VerifiedFact] = []
    seen_quotes: set[str] = set()

    with httpx.Client(headers={"User-Agent": _UA, "Accept-Language": "en,de;q=0.8"}, follow_redirects=True) as http:

        def search_window() -> float:
            """Searches get at most 15 s, and never eat into the time later phases need."""
            return max(0.5, min(15.0 * scale, left() - reserve_end - 25 * scale))

        def run_queries(plan: list[tuple[str, str, str, int]], timeout: float | None = None) -> list[Hit]:
            hits: list[Hit] = []
            jobs = {(ln, v, q): (brave, http, v, q, c, deadline) for ln, v, q, c in plan}
            done = 0
            for (ln, v, q), fut in _bounded(6, jobs, search_window() if timeout is None else timeout):
                done += 1
                rows = (fut.result() if not fut.exception() else None) or []
                st["search"].append({"query": q, "lane": ln, "vertical": v, "hits": [
                    {"url": r["url"], "title": r["title"], "snippet": r["snippet"][:300], "published": r["published"],
                     "about_target": ident.about(f"{r['title']} {r['snippet']} {r['url']}")} for r in rows]})
                hits += [Hit(r["url"], r["title"], r["snippet"], q, ln, r["published"]) for r in rows]
            if done < len(jobs):
                st.setdefault("abandoned", []).append({"phase": "search", "count": len(jobs) - done})
                log(f"[{t.id}] search window closed: {len(jobs) - done} slow queries dropped")
            return hits

        def academic() -> list[Hit]:
            rows = ([("academic", r) for r in openalex(http, t.name, deadline)]
                    + [("academic", r) for r in gh_users(http, t.name, deadline)])
            st["search"].append({"query": f"OpenAlex + GitHub: {t.name}", "lane": "academic", "vertical": "api", "hits": [
                {"url": r["url"], "title": r["title"], "snippet": r["snippet"][:300], "published": "",
                 "about_target": bool(ident.anchor(r["snippet"]))} for _, r in rows]})
            return [Hit(r["url"], r["title"], r["snippet"], "academic", lane) for lane, r in rows]

        def to_docs(hits: list[Hit]) -> list[Doc]:
            """Identity-checked documents: fetched page text, or the snippet for login-walled/API sources."""
            fresh: dict[str, Hit] = {}
            for h in hits:
                u = h.url.split("#")[0]
                if u and u not in seen_urls and u not in fresh:
                    fresh[u] = h
            docs: list[Doc] = []
            to_fetch: list[Hit] = []
            for u, h in fresh.items():
                seen_urls.add(u)
                host = urlsplit(u).hostname or ""
                blob = f"{h.title}\n{h.snippet}"
                if h.lane == "academic" or any(s in host for s in _SNIPPET_ONLY):
                    ok = ident.about(f"{blob} {u}") if h.lane != "academic" else (ident.full_name(blob) and bool(ident.anchor(blob)))
                    st["sources"][u] = {"title": h.title, "kind": "snippet", "lane": h.lane, "published": h.published,
                                        "status": "about target (snippet)" if ok else "dropped: not this person"}
                    if ok:
                        docs.append(Doc(_doc_id(u), u, h.title, f"{h.title}\n{h.snippet}\n{u}", h.lane, h.published, True))
                else:
                    to_fetch.append(h)
            jobs = {i: (fetch_text, http, h.url) for i, h in enumerate(to_fetch[: max_docs * 2])}
            got: set[int] = set()
            # Pages get at most 20 s (30% of what is left), never the time later phases need.
            for i, fut in _bounded(10, jobs, max(0.5, min(20.0 * scale, left() * 0.3, left() - reserve_end - 10 * scale))):
                got.add(i)
                h = to_fetch[i]
                res = fut.result() if not fut.exception() else None
                if not res:
                    # keep the snippet if the page cannot be fetched but the snippet is clearly about them
                    ok = ident.about(f"{h.title} {h.snippet} {h.url}")
                    st["sources"][h.url] = {"title": h.title, "kind": "snippet", "lane": h.lane, "published": h.published,
                                            "status": "page blocked; snippet used" if ok else "not fetched"}
                    if ok:
                        docs.append(Doc(_doc_id(h.url), h.url, h.title, f"{h.title}\n{h.snippet}", h.lane, h.published, True))
                    continue
                title, text = res
                ok = ident.about(text)
                st["sources"][h.url] = {"title": title or h.title, "kind": "page", "lane": h.lane, "chars": len(text),
                                        "published": h.published,
                                        "status": "about target" if ok else "dropped: no full name + identity anchor"}
                if ok:
                    docs.append(Doc(_doc_id(h.url), h.url, title or h.title, text, h.lane, h.published))
            for i in set(jobs) - got:  # too slow: fall back to the search snippet, like a blocked page
                h = to_fetch[i]
                ok = ident.about(f"{h.title} {h.snippet} {h.url}")
                st["sources"][h.url] = {"title": h.title, "kind": "snippet", "lane": h.lane, "published": h.published,
                                        "status": "page too slow; snippet used" if ok else "page too slow"}
                if ok:
                    docs.append(Doc(_doc_id(h.url), h.url, h.title, f"{h.title}\n{h.snippet}", h.lane, h.published, True))
            if len(got) < len(jobs):
                log(f"[{t.id}] fetch window closed: {len(jobs) - len(got)} slow pages dropped")
            return docs

        def extract_all(docs: list[Doc], reserve: float | None = None) -> None:
            """Extract until `reserve` seconds remain (round 1 keeps 45 s of 90 free for the snowball)."""
            reserve = 45.0 * scale if reserve is None else reserve
            n = len(pool)
            jobs = {i: (extract, lane(i % n), t, d) for i, d in enumerate(docs)}
            finished = 0
            for i, fut in _bounded(max(4, 3 * n), jobs, left() - reserve):
                finished += 1
                d = docs[i]
                src = st["sources"].setdefault(d.url, {"title": d.title, "kind": "page", "lane": d.lane})
                src.update(proposed=0, verified=0, rejected=0)
                for raw in (fut.result() if not fut.exception() else None) or []:
                    src["proposed"] += 1
                    vf = verify(raw, d, ident)
                    if vf is None:
                        src["rejected"] += 1
                        st["rejected"].append({"url": d.url, "quote": raw.get("verbatim_quote"), "fact": raw.get("fact")})
                        continue
                    key = normalize(vf.verbatim_quote)
                    if key in seen_quotes:
                        continue
                    seen_quotes.add(key)
                    src["verified"] += 1
                    facts.append(vf)
            if finished < len(jobs):
                st.setdefault("abandoned", []).append({"phase": "extract", "count": len(jobs) - finished})
                log(f"[{t.id}] extraction window closed: {len(jobs) - finished} sources skipped; keeping verified facts")

        # ---- round 1: all lanes in parallel
        t0 = time.monotonic()
        window = search_window()
        acad_ex = ThreadPoolExecutor(1)
        f_acad = acad_ex.submit(academic)
        hits = run_queries(plan_queries(t), timeout=window)
        try:
            hits += f_acad.result(timeout=max(0.0, window - (time.monotonic() - t0)))
        except (TimeoutError, Exception):  # noqa: BLE001 - the academic lane is optional
            log(f"[{t.id}] academic lane too slow or failed; skipped")
        acad_ex.shutdown(wait=False, cancel_futures=True)
        st["timings"]["search_s"] = round(time.monotonic() - t0, 1)
        docs = to_docs(hits)
        docs.sort(key=lambda d: (d.snippet_only, _SOURCE_RANK.get(d.lane, 5)))
        docs = docs[:max_docs]
        log(f"[{t.id}] round 1: {len(hits)} results -> {len(docs)} sources about the person "
            f"({sum(d.snippet_only for d in docs)} snippets) in {time.monotonic() - start:.0f}s")
        t1 = time.monotonic()
        extract_all(docs)
        st["timings"]["extract1_s"] = round(time.monotonic() - t1, 1)
        log(f"[{t.id}] round 1: {len(facts)} verified facts ({time.monotonic() - start:.0f}s)")

        # ---- round 2+: snowball expansion from what we learned (see snowball.py)
        from .snowball import run_snowball

        t2 = time.monotonic()
        docs += run_snowball(t, lane(0), ident, facts, st, run_queries=run_queries, to_docs=to_docs,
                             extract_all=lambda d: extract_all(d, reserve=reserve_end + 3 * scale), left=left, log=log,
                             max_docs=max(10, max_docs // 2), reserve_s=reserve_end,
                             min_round_s=30.0 * scale, plan_timeout_s=15.0 * scale)
        st["timings"]["round2_s"] = round(time.monotonic() - t2, 1)
        log(f"[{t.id}] expansion done -> {len(facts)} verified facts ({time.monotonic() - start:.0f}s)")

    # ---- consolidation
    proposed = sum(s.get("proposed", 0) for s in st["sources"].values())
    verified_raw = len(facts)
    merged = merge_duplicates(facts)
    merged.sort(key=lambda f: (_SOURCE_RANK.get(f.lane, 5), f.category == "company_news"))
    for i, f in enumerate(merged, 1):
        f.id = f"f{i}"
    # Conflicts and themes are independent: run them together; hooks need both. Conflicts and themes may use
    # the time up to 12 s before the deadline; hooks get whatever is left. Nothing waits past the deadline.
    # Conflict marks are written onto the facts by the worker thread, so the facts are copied first: an
    # abandoned conflict check cannot change the dossier after it has been returned.
    t3 = time.monotonic()
    ex = ThreadPoolExecutor(2)
    conf_facts = [f.model_copy(deep=True) for f in merged]
    f_conf = ex.submit(mark_conflicts, lane(1), t.name, conf_facts)
    f_themes = ex.submit(find_themes, lane(2), t.name, merged)
    n_conf, themes = 0, []
    try:
        n_conf = f_conf.result(timeout=max(0.0, left() - 12 * scale))
        merged = conf_facts
    except (TimeoutError, Exception):  # noqa: BLE001 - the conflict check is optional
        log(f"[{t.id}] conflict check over budget or failed; skipped")
    try:
        themes = f_themes.result(timeout=max(0.0, left() - 12 * scale))
    except (TimeoutError, Exception):  # noqa: BLE001 - themes are optional
        log(f"[{t.id}] themes over budget or failed; skipped")
    ex.shutdown(wait=False, cancel_futures=True)
    ex = ThreadPoolExecutor(1)
    try:
        hooks = ex.submit(rank_hooks, lane(3), t, merged, themes).result(timeout=max(0.0, left()))
    except (TimeoutError, Exception):  # noqa: BLE001
        hooks = []
        log(f"[{t.id}] hook ranking over budget or failed; no hooks")
    ex.shutdown(wait=False, cancel_futures=True)
    st["timings"]["consolidate_s"] = round(time.monotonic() - t3, 1)

    lanes: dict[str, dict] = {}
    for q in st["search"]:
        L = lanes.setdefault(q["lane"], {"queries": 0, "results": 0, "facts": 0})
        L["queries"] += 1
        L["results"] += len(q["hits"])
    for f in merged:
        lanes.setdefault(f.lane, {"queries": 0, "results": 0, "facts": 0})["facts"] += 1
    st["lanes"] = lanes
    st.update(queries=len(st["search"]), hits=sum(len(q["hits"]) for q in st["search"]),
              docs_relevant=len(docs), facts_proposed=proposed, facts_verified_raw=verified_raw,
              facts_verified=len(merged), duplicates_merged=verified_raw - len(merged), conflicts=n_conf,
              elapsed_s=round(time.monotonic() - start, 1), budget_s=budget_s)
    st["within_budget"] = st["elapsed_s"] <= budget_s + 1.0
    log(f"[{t.id}] done: {len(merged)} facts ({verified_raw - len(merged)} duplicates merged, {n_conf} conflicts), "
        f"{len(themes)} themes, {len(hooks)} hooks in {st['elapsed_s']}s of a {budget_s:.0f}s budget"
        + ("" if st["within_budget"] else "  ** OVER BUDGET **"))
    dossier = VerifiedDossier(target_id=t.id, target_name=t.name, role=t.role, company=t.company,
                              facts=merged, hypotheses=hooks, themes=themes, anchors=ident.anchors)
    return dossier, st
