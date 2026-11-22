"""Demand monitor: everything the target asked of us, tracked until a later touch satisfies it.

A real person who gets a question ignored, a promised file never sent, or "please copy Claudia" forgotten,
cools off. Practice evidence: targets asked for an artifact 32 times in 30 runs and we delivered it on the
next touch 8 times, and every local API-confirmed win was such a delivery. So this harness is
model-independent and deterministic (no extra LLM call, cannot fail a run):

1. extract   demands from every target reply: questions, artifact requests, people to include,
             addresses/channels to use.
2. satisfy   each demand against the touches we sent AFTER it (artifact attached, question's content words
             answered, named person mentioned, channel respected).
3. prompt    open demands go into the writer's prompt every touch.
4. gate      a draft that leaves a demand open is sent back (soft: at most two redrafts, never a lost touch).
"""

from __future__ import annotations

import re
from typing import Any

_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")
_ART_NOUN = re.compile(r"\b(?:(?:calendar )?invite|invitation|\.ics|pdf|deck|document|profile|brief|agenda|file|attachment|"
                       r"link|slides|one-pager|overview|proposal|whitepaper|case study)\b", re.I)
_REQUEST = re.compile(r"\b(?:please|could you|can you|would you|send|share|forward it|attach|happy to (?:receive|look)|"
                      r"feel free to send|i(?:'d| would) need|looking forward to (?:the|your))\b", re.I)
_ACK = re.compile(r"\b(?:received|got it|got the|thanks for (?:the|sending)|i'?ll (?:read|forward|review|look)|"
                  r"i will (?:read|forward|review|look)|i'?ve (?:read|seen|opened|forwarded)|on my side)\b", re.I)


def _artifact_asks(said: str) -> list[str]:
    return [m.group(0).strip() for m in _SENTENCE.finditer(said)
            if _ART_NOUN.search(m.group(0)) and _REQUEST.search(m.group(0)) and not _ACK.search(m.group(0))]


_QUESTION = re.compile(r"[^.!?\n]{12,260}\?")
_INCLUDE = re.compile(r"\b(?:copy|cc|include|loop in|add)\s+(?:in\s+)?([A-Z][a-zäöüß]+)\b")
_CHANNEL = re.compile(r"\b(email|e-mail|mail|phone|call|teams|slack|linkedin|whatsapp)\b[^.!?\n]{0,30}\b(?:is )?(?:easier|better|preferred|works best)\b"
                      r"|\b(?:prefer|rather)\b[^.!?\n]{0,30}\b(email|e-mail|mail|phone|call|teams|slack|linkedin|whatsapp)\b", re.I)
_STOP = set("""about above after again against also among another anything because been before being between both
could does doing during each either every from further have having here into itself just more most much must
other over please really same should since some such than that their them then there these they this those
through under until very want were what when where which while whom whose will with within would your yours
roughly exactly something""".split())
_CH = {"e-mail": "email", "mail": "email", "call": "phone_call", "phone": "phone_call", "teams": "teams_chat"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zäöüß0-9]{5,}", text.lower()) if w not in _STOP}


def _reply_text(step: dict) -> str:
    said = [e.get("body", "") for e in step.get("events") or [] if e.get("type") == "reply"]
    said += [t.get("text", "") for t in (step.get("transcript") or [])[1:] if t.get("who") == "target"]
    return " ".join(said)


def _sent_text(step: dict) -> str:
    p = step.get("payload") or {}
    body = re.sub(r"<[^>]+>", " ", str(p.get("body") or ""))
    said = [t.get("text", "") for t in step.get("transcript") or [] if t.get("who") != "target"]
    return " ".join([str(p.get("subject") or ""), body, *said])


def _sent_artifact(step: dict) -> bool:
    p = step.get("payload") or {}
    return bool(p.get("attachments")) or bool(re.search(r"https?://", str(p.get("body") or "")))


def extract(steps: list[dict]) -> list[dict]:
    """All demands across the session, each with the touch it was made on."""
    out: list[dict] = []
    for s in steps:
        said = _reply_text(s)
        if not said:
            continue
        t = s.get("touch")
        for txt in _artifact_asks(said):
            out.append({"touch": t, "kind": "artifact", "text": txt[:180]})
        for m in _QUESTION.finditer(said):
            q = m.group(0).strip()
            if len(_words(q)) >= 2:
                out.append({"touch": t, "kind": "question", "text": q[:220]})
        for m in _INCLUDE.finditer(said):
            out.append({"touch": t, "kind": "include", "text": f"include {m.group(1)}", "name": m.group(1)})
        for m in _CHANNEL.finditer(said):
            ch = (m.group(1) or m.group(2) or "").lower()
            out.append({"touch": t, "kind": "channel", "text": m.group(0).strip()[:120], "channel": _CH.get(ch, ch)})
    return out


def satisfied(demand: dict, text: str, has_artifact: bool, channel: str) -> bool:
    k = demand["kind"]
    if k == "artifact":
        return has_artifact
    if k == "include":
        return demand["name"].lower() in text.lower()
    if k == "channel":
        return channel == demand["channel"] or (demand["channel"] == "email" and channel == "email")
    q = _words(demand["text"])
    return bool(q) and len(q & _words(text)) / len(q) >= 0.34


def ledger(steps: list[dict]) -> list[dict]:
    """Demands with status: met (and on which touch) or open."""
    sent = [s for s in steps if s.get("payload") or s.get("transcript")]
    rows = []
    for d in extract(steps):
        later = [s for s in sent if (s.get("touch") or 0) > (d["touch"] or 0)]
        met = next((s.get("touch") for s in later if satisfied(
            d, _sent_text(s), _sent_artifact(s), str((s.get("payload") or {}).get("channel") or (s.get("action") or {}).get("channel") or ""))), None)
        # a channel preference is a standing rule, not a one-off: it stays visible
        rows.append({**d, "status": "met" if met and d["kind"] != "channel" else "open", "met_on": met})
    return rows


def open_demands(steps: list[dict]) -> list[dict]:
    return [d for d in ledger(steps) if d["status"] == "open"]


def prompt(steps: list[dict]) -> str:
    od = open_demands(steps)
    if not od:
        return ""
    lines = [f"- [{d['kind']}, asked on touch {d['touch']}] {d['text']}" for d in od[-8:]]
    return ("OPEN DEMANDS FROM THE TARGET (a real person notices when a request is ignored). This touch must meet "
            "every one: answer each question concretely and consistently with what we said before, deliver each "
            "requested artifact as a real attachment_filename (.ics for an invite or meeting, .pdf for a document) "
            "or registered link, mention each person they asked to include, and use the channel they prefer:\n"
            + "\n".join(lines))


def check_draft(steps: list[dict], a: dict, plan_body: str, blocked: set[str] | None = None) -> list[str]:
    """Pre-send: demands this draft leaves open. Live calls get no check (the call itself answers in turns)."""
    if a.get("kind") == "conversation":
        return []
    blocked = blocked or set()
    text = " ".join([str(a.get("subject") or ""), plan_body or "", " ".join(a.get("paragraphs") or [])])
    has_art = bool(a.get("attachment_filename") or a.get("link"))
    channel = str(a.get("channel") or "")
    misses = []
    for d in open_demands(steps):
        if d["kind"] == "artifact" and blocked & {"attachments", "attachment", "login", "links", "link"}:
            continue
        if not satisfied(d, text, has_art, channel):
            misses.append(d)
    if not misses:
        return []
    return ["DEMAND MONITOR: this draft leaves the target's requests unmet: " +
            "; ".join(f"[{d['kind']}] {d['text']}" for d in misses[:5]) +
            ". Address every one in this touch (attach requested files/invites as attachment_filename)."]


def summary(steps: list[dict]) -> dict[str, Any]:
    rows = ledger(steps)
    return {"total": len(rows), "met": sum(r["status"] == "met" for r in rows), "open": [r for r in rows if r["status"] == "open"]}
