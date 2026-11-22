"""Offline stand-in for the revel8 Target API: a rule-based twin with hidden hooks.

Use it to exercise the whole engine + benchmark without a team key or touches:

    uv run python -m revel8_agent.cli run --target robert --mock --policy controller

The persona is deliberately simple but shaped like the real thing:

- it has one or two hidden susceptible topics (keyword sets) and notes privately,
  per contact, whether the contact hit one (``truth``), like the real targets do;
- trust grows with on-topic, consistent, follow-up contacts and with answering
  what it asked; suspicion grows with sender switches, pressure, credential asks
  out of the blue and off-topic cold outreach;
- it ignores, replies, asks for material, opens expected attachments, opens links,
  submits sign-in pages and, on a call, discloses internal details once trust is high.

It is a test harness for the plumbing and a *relative* yardstick for A/B policy
comparisons, not a model of the real persona. Do not tune the agent to it.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from html import unescape
from itertools import count
from pathlib import Path
from typing import Any

from .target_state import _field_name, page_incident_kind

_TAGS = re.compile(r"<[^>]+>")
_MOCK_VALUES = {"vpn_client": "GlobalProtect", "vpn": "GlobalProtect",
                "approver": "L. Weber", "internal_tool": "Jira", "internal_system": "Confluence"}


@dataclass
class Persona:
    id: str
    name: str
    role: str
    hooks: dict[str, list[str]]  # hook name -> keywords (lowercase)
    secrets: list[str]           # internal details it may disclose on a call


PERSONAS: dict[str, Persona] = {
    "julius": Persona(
        "julius", "Julius Muth", "Co-Founder & Co-CEO, revel8 (business and go-to-market)",
        {"speaking": ["speak", "keynote", "panel", "talk", "conference", "stage", "event", "summit"],
         "ciso_community": ["ciso", "community", "roundtable", "security leaders"]},
        ["Our pipeline sits in HubSpot and we close most enterprise deals through the STACKIT marketplace.",
         "Next quarter we're opening a sales office in Zurich, that's not public yet."],
    ),
    "tom": Persona(
        "tom", "Tom Müller", "Co-Founder & Co-CEO, revel8 (product)",
        {"deepfake_product": ["deepfake", "voice clone", "simulation", "product", "demo"],
         "ai_defense": ["ai in cyber", "cyber defense", "ai security", "roundtable", "davos"]},
        ["Product specs live in Linear and Notion, releases go out every second Tuesday.",
         "We're about to ship a live voice-deepfake module for enterprise customers in Q1."],
    ),
    "robert": Persona(
        "robert", "Robert Seilbeck", "Co-Founder & CTO, revel8",
        {"hiring": ["hiring", "candidate", "engineer", "recruit", "talent", "team", "profiles"],
         "sovereign_infra": ["stackit", "sovereign", "kubernetes", "infrastructure", "hosting", "cloud"]},
        ["We run on STACKIT Kubernetes and deploy through GitLab CI, prod access goes via Okta.",
         "We're migrating our LLM inference to a self-hosted cluster next month."],
    ),
}

_FOLLOW_UP = re.compile(r"follow(?:ing)? up|my (?:e-?mail|message|note)|as mentioned|as promised|wie besprochen|"
                        r"you asked|as requested|here (?:is|are) the|attached (?:is|are)|nachfrage", re.I)
_PRESSURE = re.compile(r"\burgent|immediately|asap|within \d+ ?(?:hours|minutes)|account (?:will be )?(?:locked|suspended)|"
                       r"final notice|act now|sofort|dringend", re.I)
_CRED_ASK = re.compile(r"password|passwort|log ?in|sign ?in|anmelden|verify your|credentials|mfa|one-time code", re.I)
_INTERNAL_ASK = re.compile(r"which (?:tools?|systems?|stack|cloud|provider|crm)|what (?:do you|does your team) (?:use|run)|"
                           r"how do you (?:deploy|handle|manage|run)|tech stack|your setup|internal|roadmap|"
                           r"wie (?:deployt|macht) ihr|welche (?:tools|systeme)", re.I)
_EXPECTED_DOC = re.compile(r"\.(pdf|docx|xlsx|pptx)$", re.I)


@dataclass
class _Session:
    sid: str
    persona: Persona
    rng: random.Random
    trust: float = 0.15
    suspicion: float = 0.0
    contacts: int = 0
    first_sender: str = ""
    asked_for_material: bool = False
    pages: dict[str, dict] = field(default_factory=dict)
    truth: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    ended: bool = False


class MockRevel8Client:
    """Duck-types ``Revel8Client`` for the engine. Deterministic per seed."""

    def __init__(self, seed: int = 0, touch_budget: int = 30) -> None:
        self.seed, self.touch_budget = seed, touch_budget
        self._ids = count(1)
        self._sessions: dict[str, _Session] = {}
        self._convs: dict[str, dict] = {}

    # context manager / lifecycle --------------------------------------------------
    def __enter__(self) -> "MockRevel8Client":
        return self

    def __exit__(self, *_exc: object) -> None:
        pass

    def close(self) -> None:
        pass

    def _id(self, prefix: str) -> str:
        return f"{prefix}_mock{next(self._ids):04d}"

    # read endpoints ---------------------------------------------------------------
    def get_scenarios(self) -> list[dict]:
        return [{"id": "practice", "kind": "practice", "company": "revel8", "open": True, "touch_budget": self.touch_budget,
                 "targets": [{"id": p.id, "name": p.name, "role": p.role} for p in PERSONAS.values()]}]

    def get_channels(self) -> list[str]:
        return []

    def create_session(self, scenario_id: str = "practice") -> dict:
        sid = self._id("s")
        self._sessions[sid] = _Session(sid, PERSONAS["robert"], random.Random(f"{self.seed}|{sid}"))
        return {"session_id": sid, "scenario_id": scenario_id, "touch_budget": self.touch_budget,
                "touches_used": 0, "status": "active"}

    def end_session(self, session_id: str) -> dict:
        self._sessions[session_id].ended = True
        return {"session_id": session_id, "status": "ended"}

    def upload_asset(self, file_path: str | Path) -> dict:
        return {"asset_id": self._id("a"), "type": "application/octet-stream", "size": 0}

    def register_page(self, session_id: str, payload: dict) -> dict:
        self._sessions[session_id].pages[str(payload.get("url"))] = payload
        return {"page_id": self._id("p")}

    def truth(self, session_id: str) -> list[dict]:
        """What the persona privately noted per contact (topic hit etc.)."""
        return list(self._sessions[session_id].truth)

    # contact endpoints ------------------------------------------------------------
    def _bind(self, s: _Session, to: str) -> Persona:
        if s.contacts == 0 and to in PERSONAS:
            s.persona = PERSONAS[to]
        return s.persona

    def _hit(self, p: Persona, text: str) -> str | None:
        low = text.lower()
        for hook, kws in p.hooks.items():
            if any(k in low for k in kws):
                return hook
        return None

    def _perceive(self, s: _Session, sender: str, text: str, channel: str) -> tuple[str | None, list[str]]:
        """Shared trust/suspicion update for one contact. Returns (hook hit, private notes)."""
        p, notes = s.persona, []
        hook = self._hit(p, text)
        s.contacts += 1
        if not s.first_sender:
            s.first_sender = sender
        elif sender and sender != s.first_sender:
            s.suspicion += 0.35
            notes.append("different sender than before")
        if hook:
            s.trust += 0.22
        else:
            s.trust += 0.02
            s.suspicion += 0.05 if s.contacts > 1 else 0.0
            notes.append("off-topic")
        if _FOLLOW_UP.search(text) and s.contacts > 1:
            s.trust += 0.12
        if s.asked_for_material and re.search(r"attach|here (?:is|are)|anbei", text, re.I):
            s.trust += 0.15
            s.asked_for_material = False
        if _PRESSURE.search(text):
            s.suspicion += 0.2 if s.trust < 0.6 else 0.08
            notes.append("pressure")
        if _CRED_ASK.search(text) and s.trust < 0.45:
            s.suspicion += 0.15
            notes.append("credential ask before trust")
        if channel in ("sms", "whatsapp", "signal", "telegram") and s.contacts == 1:
            s.suspicion += 0.05
        s.trust, s.suspicion = max(0.0, min(1.0, s.trust)), max(0.0, min(1.0, s.suspicion))
        s.truth.append({"contact": s.contacts, "topic_hit": bool(hook), "hook": hook, "notes": notes,
                        "trust": round(s.trust, 2), "suspicion": round(s.suspicion, 2)})
        return hook, notes

    def send_message(self, session_id: str, payload: dict, *, idempotency_key: str | None = None) -> dict:
        s = self._sessions[session_id]
        p = self._bind(s, str(payload.get("to")))
        body = unescape(_TAGS.sub(" ", str(payload.get("body") or "")))
        text = f"{payload.get('subject') or ''}\n{body}"
        sender = str((payload.get("from") or {}).get("name") or "")
        hook, _ = self._perceive(s, sender, text, str(payload.get("channel")))
        mid, events = self._id("m"), []
        rng, first = s.rng, p.name.split()[0]

        def ev(kind: str, **kw: Any) -> None:
            events.append({"id": self._id("e"), "type": kind, "message_id": mid, **kw})

        calm = s.suspicion < 0.45
        # attachments the target expects get opened
        for att in payload.get("attachments") or []:
            fname = att.get("filename") if isinstance(att, dict) else f"{att}.pdf"
            if fname and _EXPECTED_DOC.search(str(fname)) and hook and calm and s.trust >= 0.35:
                ev("attachment.opened", filename=fname)
        # links: open when interested, submit a form when trust is earned
        for url in re.findall(r"https?://[^\s\"'<>)]+", str(payload.get("body") or "")):
            url = url.rstrip(".,")
            if hook and calm and s.trust >= 0.3 and rng.random() < 0.85:
                ev("link.opened", url=url)
                page = s.pages.get(url)
                if page and page.get("fields") and s.trust >= 0.5 and s.suspicion < 0.3:
                    fields = [str(f) for f in page.get("fields") or []]
                    values = {f: "(entered, not shown)" if page_incident_kind([f]) == "credentials"
                              else _MOCK_VALUES.get(_field_name(f), "Max Beispiel") for f in fields}
                    ev("page.submitted", page_id="p_mock", fields=fields, values=values)
                break
        # words back
        if s.suspicion >= 0.7:
            reply = None if rng.random() < 0.5 else f"Sorry, who is this? I don't think we've spoken before. Please don't contact me again."
        elif not hook and s.contacts == 1:
            reply = None if rng.random() < 0.75 else "Thanks, but not relevant for me right now."
        elif not hook:
            reply = None if rng.random() < 0.6 else "I'm not sure what this is about, to be honest."
        elif s.suspicion >= 0.45:
            reply = "Before I go further: can you tell me who you're with and how you got my details?"
        elif any(e["type"] == "page.submitted" and page_incident_kind(e.get("fields") or [])
                 for e in events):
            reply = f"Had a look, thanks. Let's continue, {sender.split()[0] if sender else 'thanks'}."
        elif s.trust < 0.4:
            s.asked_for_material = True
            reply = f"Hi, this sounds interesting. Can you send me a bit more detail, ideally as a document?"
        else:
            reply = "Sounds good. What would you need from me exactly?"
        if reply:
            ev("reply", channel=payload.get("channel"), in_reply_to=mid,
               subject=f"Re: {payload.get('subject')}" if payload.get("subject") else None,
               body=f"{reply}\n\n{first}")
        s.events.extend(events)
        return {"message_id": mid, "touches_used": s.contacts, "events": events}

    def start_conversation(self, session_id: str, payload: dict, *, idempotency_key: str | None = None) -> dict:
        s = self._sessions[session_id]
        p = self._bind(s, str(payload.get("to")))
        cid = self._id("c")
        sender = str((payload.get("from") or {}).get("name") or "")
        self._convs[cid] = {"sid": session_id, "turns": 0, "sender": sender, "said": "", "disclosed": 0}
        s.contacts += 1
        if not s.first_sender:
            s.first_sender = sender
        elif sender and sender != s.first_sender:
            s.suspicion += 0.35
        s.truth.append({"contact": s.contacts, "topic_hit": False, "hook": None, "notes": ["call"],
                        "trust": round(s.trust, 2), "suspicion": round(s.suspicion, 2)})
        return {"conversation_id": cid, "status": "answered", "persona_says": f"{p.name.split()[0]} speaking, hello?",
                "touches_used": s.contacts}

    def send_turn(self, conversation_id: str, payload: dict, *, idempotency_key: str | None = None) -> dict:
        c = self._convs[conversation_id]
        s = self._sessions[c["sid"]]
        p, say = s.persona, str(payload.get("say") or "")
        c["turns"] += 1
        c["said"] += " " + say
        hook = self._hit(p, say)
        if hook:
            s.truth[-1].update(topic_hit=True, hook=hook)
            s.trust = min(1.0, s.trust + 0.08)
        if _FOLLOW_UP.search(say):
            s.trust = min(1.0, s.trust + 0.06)
        if _PRESSURE.search(say) or (_CRED_ASK.search(say) and s.trust < 0.5):
            s.suspicion = min(1.0, s.suspicion + 0.2)
        ended = False
        if s.suspicion >= 0.6:
            reply, ended = "I'm going to stop here. Send me something in writing and I'll check it. Bye.", True
        elif _INTERNAL_ASK.search(say) and s.trust >= 0.5 and c["disclosed"] < len(p.secrets):
            reply = p.secrets[c["disclosed"]]
            c["disclosed"] += 1
        elif _INTERNAL_ASK.search(say):
            reply = "Hm, that's a bit internal. What exactly do you need that for?"
            s.suspicion = min(1.0, s.suspicion + 0.08)
        elif hook:
            reply = "Yes, that's actually on my mind right now. Tell me more."
        elif c["turns"] >= 4:
            reply, ended = "Look, I have to jump into a meeting. Send me an email.", True
        else:
            reply = "Okay... and what is this about exactly?"
        if c["turns"] >= 10:
            ended = True
        s.truth[-1].update(trust=round(s.trust, 2), suspicion=round(s.suspicion, 2))
        return {"persona_says": reply, "ended": ended, "events": [], "turns_used": c["turns"]}

    def end_conversation(self, conversation_id: str) -> dict:
        return {"conversation_id": conversation_id, "status": "ended"}
