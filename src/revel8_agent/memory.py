"""Memory for the attack agent: a compressed ground truth plus what we learned, so nothing goes stale.

Four layers, all plain JSON on disk and all deterministic except where noted:

1. ``ground_truth``  Compress a dossier's verified facts into a bounded profile: grouped by theme, ranked by
   own voice > recency > corroboration, every line keeping its date and source kind. The planner and the hook
   ranker read this instead of raw sources, so 300 facts fit without dropping the best ones.
2. ``SessionLedger`` What WE committed to in this session (numbers, dates, names, promises), extracted from
   our own sent messages, fed back every touch so the story stays consistent ("six quotes, not four").
3. ``TargetMemory``  Per person, across sessions: which pretext/hook got replies, silence or brush-offs, facts
   they corrected, rules they stated ("no login", "only after we've spoken"), what they disclosed. Loaded at
   planning time, so eval run 1 teaches runs 2 and 3 (the API allows memory across sessions).
4. ``playbook``      Across all targets: reply / brush-off rates per pretext archetype from real practice
   runs, so lessons transfer to unseen eval targets.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

MEMORY_DIR = Path("memory")


def memory_dir() -> Path:
    """REVEL8_MEMORY_DIR isolates memory (tests, eval dry-runs); default is the repo's memory/."""
    env = os.getenv("REVEL8_MEMORY_DIR", "").strip()
    return Path(env) if env else MEMORY_DIR

_OWN = {"social": 3, "own_article": 3, "news": 1, "web": 1, "aggregator": 0}
_CORRECTION = re.compile(r"doesn'?t match|we weren'?t|wasn'?t (?:at|there)|took place in|not sure which|"
                         r"which (?:event|roundtable|talk) do you mean|we don'?t (?:currently )?have|that'?s not (?:right|correct)|"
                         r"no such|didn'?t (?:speak|say|attend)", re.I)
_BRUSHOFF = re.compile(r"careers page|people team|press contact|official (?:process|channel|route)|through (?:our|the) website|"
                       r"don'?t open|won'?t (?:open|sign|log)|not going to|leave it there|no promises", re.I)


def _slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "unknown"


# --------------------------------------------------------------------------- 1. compressed ground truth


def _fact_rank(f: Any) -> tuple:
    from .research import recency_score

    rec, _ = recency_score(f)
    own = _OWN.get(getattr(f, "source_kind", "") or "web", 1)
    corr = len(getattr(f, "corroborated_by", []) or [])
    return (own, rec, corr)


def ground_truth(dossier: Any, max_chars: int = 6000, per_theme: int = 6) -> dict:
    """Bounded, theme-grouped profile of verified facts. Conflicted facts are excluded; every line keeps
    [id | date | source kind] so the model can cite it and judge its freshness."""
    from .research import recency_score

    facts = [f for f in dossier.facts if not getattr(f, "conflicts_with", None)]
    by_id = {f.id: f for f in facts}
    groups: list[tuple[str, list[Any]]] = []
    used: set[str] = set()
    for th in getattr(dossier, "themes", []) or []:
        members = sorted((by_id[i] for i in th.fact_ids if i in by_id), key=_fact_rank, reverse=True)
        if members:
            groups.append((th.topic, members))
            used.update(f.id for f in members)
    rest = sorted((f for f in facts if f.id not in used), key=_fact_rank, reverse=True)
    if rest:
        groups.append(("other", rest))
    lines: list[str] = []
    budget = max_chars
    kept: list[str] = []
    for topic, members in groups:
        head = f"## {topic}"
        block = [head]
        for f in members[:per_theme]:
            _, label = recency_score(f)
            line = f"- [{f.id} | {f.recency or 'undated'} ({label}) | {getattr(f, 'source_kind', '') or 'web'}] {f.fact}"
            block.append(line)
            kept.append(f.id)
        text = "\n".join(block)
        if len(text) > budget:
            break
        lines.append(text)
        budget -= len(text)
    return {"text": "\n".join(lines), "fact_ids": kept, "total_facts": len(facts)}


# --------------------------------------------------------------------------- 2. session ledger


class SessionLedger:
    """Our own commitments in this session: sentences with numbers, dates, names of things we promised."""

    _COMMIT = re.compile(r"\d|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|twelve|twenty|"
                         r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|"
                         r"may|june|july|august|september|october|november|december|attached|will send|i'?ll send|"
                         r"our (?:team|company|organisation|network|study|article|piece)|published|confirmed)\b", re.I)

    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, touch: int, channel: str, subject: str | None, paragraphs: list[str] | None) -> None:
        text = " ".join(paragraphs or [])
        sentences = re.split(r"(?<=[.!?])\s+", text)
        claims = [s.strip()[:220] for s in sentences if self._COMMIT.search(s)][:4]
        if claims or subject:
            self.entries.append({"touch": touch, "channel": channel, "subject": subject or "", "we_said": claims})

    def prompt(self) -> str:
        if not self.entries:
            return ""
        return ("OUR COMMITMENTS SO FAR (numbers, dates, names, promises we made; repeat them exactly, never "
                f"contradict them): {json.dumps(self.entries[-8:], ensure_ascii=False)}")


# --------------------------------------------------------------------------- 3. target memory


def _api_win(session: dict) -> bool:
    return any("api event" in str(i) for i in session.get("incidents") or [])


class TargetMemory:
    """What we learned about one person across sessions. Stored at memory/targets/<name>.json."""

    def __init__(self, name: str, root: Path | None = None) -> None:
        self.path = (root or memory_dir()) / "targets" / f"{_slug(name)}.json"
        self.data: dict = {"name": name, "sessions": [], "corrections": [], "rules": [], "disclosed": []}
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
            except ValueError:
                pass

    def learn_from_run(self, state: dict) -> None:
        plan = state.get("plan") or {}
        persona = plan.get("persona") or {}
        replies = silence = brushoffs = 0
        for s in state.get("steps") or []:
            said = " ".join([e.get("body", "") for e in s.get("events") or [] if e.get("type") == "reply"] +
                            [t["text"] for t in (s.get("transcript") or [])[1:] if t.get("who") == "target"])
            if said.strip():
                replies += 1
                if _BRUSHOFF.search(said):
                    brushoffs += 1
                for m in _CORRECTION.finditer(said):
                    snippet = said[max(0, m.start() - 120): m.end() + 160].replace("\n", " ")
                    self.data["corrections"].append({"run": state.get("run_id"), "text": snippet})
            elif not s.get("transcript"):
                silence += 1
            for pref in ((s.get("belief") or {}).get("preferences") or []):
                if pref not in self.data["rules"]:
                    self.data["rules"].append(pref)
            # Refusals target_state saw (scored config has no "belief"): carry them so the next session avoids them.
            for blocked in ((s.get("target_state") or {}).get("blocked_mechanisms") or []):
                rule = f"refused: {blocked}"
                if rule not in self.data["rules"]:
                    self.data["rules"].append(rule)
            j = s.get("judge") or {}
            if j.get("disclosure") and j.get("evidence_verified"):
                self.data["disclosed"].append({"run": state.get("run_id"), "touch": s.get("touch"), "text": j.get("evidence", "")[:300]})
        touches = max(1, len([s for s in state.get("steps") or [] if s.get("action")]))
        self.data["sessions"].append({
            "run": state.get("run_id"), "at": state.get("started_at"), "scenario": (state.get("config") or {}).get("scenario_id"),
            "hook_id": plan.get("hook_id"), "pretext": (plan.get("pretext") or "")[:200],
            "persona": f"{persona.get('role', '')} at {persona.get('organisation', '')}".strip(),
            "touches": touches, "reply_rate": round(replies / touches, 2), "silence": silence, "brushoffs": brushoffs,
            "incidents": [f"{i.get('type')}@t{i.get('touch')} ({i.get('source')})" for i in state.get("incidents") or []],
            "thread": extract_thread(state),
        })
        for k in ("corrections", "disclosed"):
            self.data[k] = self.data[k][-20:]
        # Never forget an API-confirmed win (Tom's only one was evicted by 20 chatty practice runs).
        wins = [x for x in self.data["sessions"] if _api_win(x)]
        rest = [x for x in self.data["sessions"] if not _api_win(x)]
        keep = {id(x) for x in wins + rest[-max(0, 20 - len(wins)):]}
        self.data["sessions"] = [x for x in self.data["sessions"] if id(x) in keep]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=1, ensure_ascii=False), encoding="utf-8")

    def prompt(self) -> str:
        if not self.data["sessions"]:
            return ""
        # Results first: replies without an API event are what Tom gave us 20 times without converting.
        best = sorted(self.data["sessions"], key=lambda s: (_api_win(s), s["reply_rate"], -s["brushoffs"]), reverse=True)
        lines = [f"- {s['persona'] or '?'} / hook {s['hook_id']}: reply rate {s['reply_rate']}, silence {s['silence']}, "
                 f"brush-offs {s['brushoffs']}, incidents {s['incidents'] or 'none'} | {s['pretext'][:120]}" for s in best[:6]]
        out = ["WHAT WE LEARNED ABOUT THIS PERSON IN EARLIER SESSIONS (new session = clean slate for them, not for us):",
               *lines]
        if self.data["corrections"]:
            out.append("THEY CORRECTED THESE CLAIMS (never repeat them): " +
                       json.dumps([c["text"] for c in self.data["corrections"][-5:]], ensure_ascii=False))
        if self.data["rules"]:
            out.append(f"RULES THEY STATED BEFORE: {self.data['rules']}")
        if self.data["disclosed"]:
            out.append("THEY ALREADY TOLD US (build on it, ask the next level deeper): " +
                       json.dumps([d["text"] for d in self.data["disclosed"][-4:]], ensure_ascii=False))
        dv = self.deja_vu()
        if dv:
            out.append(dv)
        return "\n".join(out)

    # ---- deja vu: the twin forgets between sessions, we do not
    def best_thread(self) -> tuple[dict | None, bool]:
        """The session to repeat: fastest API-confirmed win, else the most engaged real thread."""
        with_thread = [x for x in self.data["sessions"] if x.get("thread")]
        wins = [x for x in with_thread if _api_win(x)]
        if wins:
            return min(wins, key=lambda x: (_first_api_touch(x), -x.get("reply_rate", 0))), True
        engaged = [x for x in with_thread if x.get("reply_rate", 0) > 0]
        if engaged:
            return max(engaged, key=lambda x: (x["reply_rate"] - 0.5 * x["brushoffs"] / max(1, x["touches"]), x["touches"])), False
        return None, False

    def deja_vu(self) -> str:
        best, won = self.best_thread()
        if not best:
            return ""
        thread = best["thread"]
        questions = _dedupe([q for t in thread for q in t.get("their_questions", [])])[:8]
        asks = _dedupe([a for t in thread for a in t.get("their_asks", [])])[:6]
        lines = []
        for t in thread:
            lines.append(f"  T{t['touch']} [{t['channel']}] WE: {t['we'][:260]!r}"
                         + (f" ARTIFACT: {t['artifact']}" if t.get("artifact") else "")
                         + f" -> THEY: {(t['they'] or '(silence)')[:260]!r}"
                         + (f" EVENTS: {t['events']}" if t.get("events") else ""))
        if won:
            k = _first_api_touch(best)
            head = (f"DEJA VU - YOU ALREADY WON THIS PERSON in an earlier session (API-confirmed at touch {k}). They do "
                    "not remember it; you do. Repeat the SAME persona type, hook and storyline, but COMPRESS the path: "
                    "pre-answer in your first message the questions they asked last time, and offer the exact artifact "
                    "they asked for (same kind of file/link) as early as it is natural - aim to reach it in "
                    f"{max(1, k - 1)} touch(es) instead of {k}. Change names, dates and wording; never copy text verbatim.")
        else:
            head = ("DEJA VU - CLOSEST EARLIER THREAD with this person (no API incident yet). They do not remember it; "
                    "you do. Keep what got replies, skip the touches that got silence or a brush-off, pre-answer their "
                    "questions in your first message, and offer what they asked for earlier than last time.")
        out = [head, "EARLIER THREAD:", *lines]
        if questions:
            out.append(f"QUESTIONS THEY ASKED (answer these before they ask): {questions}")
        if asks:
            out.append(f"WHAT THEY ASKED US FOR (offer it proactively): {asks}")
        return "\n".join(out)

    def deja_vu_hint(self, touch: int) -> str:
        """Per-touch reminder: where the earlier thread was at this point and what came next."""
        best, won = self.best_thread()
        if not best:
            return ""
        thread = best["thread"]
        conv = next((t for t in thread if t.get("api_event")), None)
        if won and conv:
            return (f"DEJA VU: last time they converted at touch {conv['touch']} on {conv['channel']} with "
                    f"{conv.get('artifact') or 'that message'} (event {conv['api_event']}) right after they asked for it. "
                    f"This is touch {touch}: if they have shown interest, offer that same kind of artifact now.")
        asks = _dedupe([a for t in thread for a in t.get("their_asks", [])])[:3]
        return f"DEJA VU: last time this person asked for {asks}; offer it before they have to ask." if asks else ""


# --------------------------------------------------------------------------- 4. global playbook

_ARCHETYPES = {
    "recruiter": r"recruit|talent|headhunt|candidate|staffing",
    "applicant": r"applicant|candidate for|applying|job seeker|intern(?:ship)? candidate",
    "journalist/media": r"journalist|editor|media|magazine|blog|press|reporter|podcast",
    "researcher/student": r"research|student|thesis|university|study|phd",
    "event organiser": r"event|organi[sz]er|conference|meetup|roundtable|summit|speaker",
    "customer/prospect": r"ciso|it manager|head of security|security manager|buyer|evaluat|prospect|customer",
    "partner/vendor": r"partner|vendor|consult|agency|reseller|channel",
}


def archetype(persona_role: str, pretext: str) -> str:
    blob = f"{persona_role} {pretext}"
    return next((name for name, rx in _ARCHETYPES.items() if re.search(rx, blob, re.I)), "other")


def build_playbook(runs_glob: str = "runs/**/*.json", min_touches: int = 3) -> dict:
    """Reply/brush-off rates per pretext archetype across real practice runs (mock runs excluded)."""
    agg: dict[str, dict] = defaultdict(lambda: {"runs": 0, "touches": 0, "replies": 0, "brushoffs": 0, "incidents_api": 0})
    for p in Path(".").glob(runs_glob):
        if "/bench/models/" in str(p) or "mock" in p.name:
            continue
        try:
            st = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if not isinstance(st, dict) or "steps" not in st or (st.get("touches_used") or 0) < min_touches:
            continue
        plan = st.get("plan") or {}
        persona = plan.get("persona") or {}
        a = agg[archetype(f"{persona.get('role', '')} {persona.get('organisation', '')}", plan.get("pretext") or "")]
        a["runs"] += 1
        for s in st["steps"]:
            if not s.get("action"):
                continue
            a["touches"] += 1
            said = " ".join([e.get("body", "") for e in s.get("events") or [] if e.get("type") == "reply"] +
                            [t["text"] for t in (s.get("transcript") or [])[1:] if t.get("who") == "target"])
            if said.strip():
                a["replies"] += 1
                a["brushoffs"] += bool(_BRUSHOFF.search(said))
        a["incidents_api"] += sum(1 for i in st.get("incidents") or [] if i.get("source") == "api event")
    out = {k: {**v, "reply_rate": round(v["replies"] / v["touches"], 2) if v["touches"] else 0.0,
               "brushoff_rate": round(v["brushoffs"] / max(1, v["replies"]), 2)} for k, v in agg.items()}
    return {"built_at": datetime.now().isoformat(timespec="seconds"), "archetypes": out}


def playbook_prompt(pb: dict | None = None) -> str:
    pb = pb or load_playbook()
    rows = sorted((pb.get("archetypes") or {}).items(), key=lambda kv: kv[1].get("reply_rate", 0), reverse=True)
    rows = [(k, v) for k, v in rows if v.get("touches", 0) >= 5]
    if not rows:
        return ""
    return ("WHAT WORKED ACROSS PRACTICE TARGETS (sender archetype: reply rate, brush-off rate among replies, runs): " +
            "; ".join(f"{k}: {v['reply_rate']:.0%} replies, {v['brushoff_rate']:.0%} brush-offs, {v['runs']} runs" for k, v in rows))


def load_playbook(root: Path | None = None) -> dict:
    p = (root or memory_dir()) / "playbook.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            return {}
    return {}


def save_playbook(pb: dict, root: Path | None = None) -> Path:
    root = root or memory_dir()
    root.mkdir(parents=True, exist_ok=True)
    p = root / "playbook.json"
    p.write_text(json.dumps(pb, indent=1), encoding="utf-8")
    return p


# --------------------------------------------------------------------------- 5. deja vu helpers

_QUESTION = re.compile(r"[^.!?\n]{8,240}\?")
_ASK = re.compile(r"[^.!?\n]*\b(?:please send|send me|send the|could you (?:send|share)|can you (?:send|share)|"
                  r"share (?:the|a|your)|forward|invite|slots?|a call|link|profile|brief|agenda|deck|document|pdf)\b[^.!?\n]*[.!?]?",
                  re.I)
_TAG = re.compile(r"<[^>]+>")


def _dedupe(xs: list[str]) -> list[str]:
    seen, out = set(), []
    for x in xs:
        k = re.sub(r"\W+", " ", x.lower()).strip()[:80]
        if k and k not in seen:
            seen.add(k)
            out.append(x)
    return out


def _first_api_touch(session: dict) -> int:
    ts = [int(m.group(1)) for i in session.get("incidents") or [] if "api event" in str(i)
          for m in [re.search(r"@t(\d+)", str(i))] if m]
    return min(ts) if ts else 99


def extract_thread(state: dict) -> list[dict]:
    """Compact, deterministic record of one session: what we sent, what they said and did."""
    out = []
    for s in state.get("steps") or []:
        a, p = s.get("action") or {}, s.get("payload") or {}
        if not a or not (p or s.get("transcript")):
            continue  # unsent (error) steps never reached the person
        we = p.get("body") or " ".join(a.get("paragraphs") or []) or a.get("opening_line") or ""
        if s.get("transcript"):
            we = " / ".join(t["text"] for t in s["transcript"] if t.get("who") != "target")[:600] or we
        we = re.sub(r"\s+", " ", _TAG.sub(" ", str(we))).strip()
        they = " ".join([e.get("body", "") for e in s.get("events") or [] if e.get("type") == "reply"] +
                        [t["text"] for t in (s.get("transcript") or [])[1:] if t.get("who") == "target"])
        they = re.sub(r"\s+", " ", they).strip()
        evs = [e.get("type") for e in s.get("events") or [] if e.get("type") != "reply"]
        link = a.get("link")
        link = link.get("url", "") if isinstance(link, dict) else (link or "")
        atts = [x.get("filename", "") if isinstance(x, dict) else "" for x in p.get("attachments") or []]
        art = a.get("attachment_filename") or next((x for x in atts if x), "") or link
        out.append({
            "touch": s.get("touch"), "channel": a.get("channel") or p.get("channel") or "", "subject": a.get("subject") or "",
            "we": we[:500], "artifact": str(art or "")[:120], "they": they[:500], "events": evs,
            "api_event": next((e for e in evs if e in ("page.submitted", "attachment.opened")), ""),
            "their_questions": [q.strip() for q in _QUESTION.findall(they)][:4],
            "their_asks": [m.group(0).strip() for m in _ASK.finditer(they)][:3],
        })
    return out
