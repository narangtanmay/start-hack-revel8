"""The landing page and the 3D score.

A run is drawn as a score: one staff per channel the agent used, one staff for the target's replies, and a note
block per touch standing on its staff. Reply blocks are as tall as the judge's read of the reply was warm; an
incident is an amber pillar (solid when the API confirmed it, outlined when it is our judge's estimate). It is
plain CSS 3D (perspective plus preserve-3d), so the page still opens from disk with no library, and the blocks
are already standing when motion is off.
"""

from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path
from typing import Any, Callable

_HEIGHT = {"engaged": 46, "questioning": 30, "hesitant": 24, "suspicious": 16, "refusing": 11}
_ORD = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth", "eleventh", "twelfth"]
_LANE_NAME = {"email": "Email", "phone_call": "Phone", "sms": "SMS", "whatsapp": "WhatsApp", "chat": "Chat", "linkedin": "LinkedIn"}


def _e(x: object) -> str:
    return escape("" if x is None else str(x))


def _json_for_script(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")


def _first(name: object) -> str:
    return str(name or "").split(" ")[0] or "the target"


def _steps(state: dict) -> list[dict]:
    return [s for s in state.get("steps", []) if (s.get("action") or {}).get("decision") != "STOP"]


def _live(state: dict) -> list[dict]:
    return [i for i in state.get("incidents", []) if not i.get("superseded")]


def _lane(step: dict) -> str:
    a = step.get("action") or {}
    return "phone_call" if a.get("kind") == "call" else str(a.get("channel") or "email")


def _touch_model(state: dict) -> list[dict]:
    """Everything the score and the conversation panel need about each touch, in order."""
    inc = _live(state)
    out = []
    for s in _steps(state):
        a, n = s.get("action") or {}, s.get("touch")
        evs = s.get("events") or []
        replies = [e for e in evs if e.get("type") == "reply"]
        p = s.get("payload") or {}
        if a.get("kind") == "call" and s.get("transcript"):
            body = "\n".join(t.get("text", "") for t in s["transcript"] if t.get("who") == "agent")
            reply = "\n".join(t.get("text", "") for t in s["transcript"] if t.get("who") != "agent")
        else:
            body = str(p.get("body") or "")
            if body.lstrip().lower().startswith(("<!doctype", "<html")):
                body = re.sub(r"<[^>]+>", " ", body)
                body = re.sub(r"\s+", " ", body).strip()
            reply = "\n\n".join(str(e.get("body") or "") for e in replies)
        hits = [i for i in inc if i.get("touch") == n]
        sent = (s.get("judge") or {}).get("sentiment")
        out.append({
            "n": n, "lane": _lane(s), "subject": p.get("subject") or a.get("subject") or "",
            "sender": (a.get("sender") or {}).get("name") or "",
            "body": body.strip(), "reply": reply.strip(), "sentiment": sent if reply else "",
            "events": [e.get("type") for e in evs if e.get("type") != "reply"],
            "hit": ("confirmed" if any(i.get("source") == "api event" for i in hits) else "estimated") if hits else "",
            "hit_types": sorted({i.get("type", "") for i in hits}),
            "error": bool(s.get("error")),
        })
    return out


# --------------------------------------------------------------------------- 3D score


def _block(cls: str, c: int, lane: int, h: int, tip: str = "", extra: str = "") -> str:
    tip_attr = f" data-tip='{_e(tip)}'" if tip else ""
    return (f"<i class='blk {cls}' style='--c:{c};--l:{lane};--h:{h}px'{tip_attr}>"
            f"<b class='t'></b><b class='f'></b><b class='sl'></b><b class='sr'></b>{extra}</i>")


def score3d(state: dict, slots: int | None = None, compact: bool = False, interactive: bool = False) -> str:
    touches = _touch_model(state)
    slots = max(slots or int((state.get("config") or {}).get("max_touches") or 10), len(touches), 1)
    persona = ((state.get("plan") or {}).get("persona") or {}).get("name") or "Agent"
    target = _first((state.get("target") or {}).get("name"))
    lanes = []
    for t in touches:
        if t["lane"] not in lanes:
            lanes.append(t["lane"])
    lanes = lanes or ["email"]
    rows = lanes + ["reply"]
    ridx = len(rows) - 1
    parts = []
    for i, name in enumerate(rows):
        lab = (f"{target} replies" if name == "reply" else _LANE_NAME.get(name, name.replace("_", " ").title())
               + ("" if compact else f" · {_first(persona)}"))
        parts.append(f"<div class='s3-staff{' rep' if name == 'reply' else ''}' style='--l:{i}'>"
                     + ("" if compact else f"<span class='s3-lab'><span>{_e(lab)}</span></span>") + "</div>")
    for c in range(slots):
        parts.append(f"<span class='s3-tick' style='--c:{c}'><span>{c + 1}</span></span>" if not compact else "")
    for c, t in enumerate(touches):
        lane = lanes.index(t["lane"])
        tip = f"Touch {t['n']} · {_LANE_NAME.get(t['lane'], t['lane'])}"
        parts.append(_block("agent" + (" err" if t["error"] else ""), c, lane, 6 if compact else 12, tip + "\nThe agent wrote this"))
        if t["reply"]:
            h = _HEIGHT.get(t["sentiment"] or "", 22)
            parts.append(_block("reply", c, ridx, round(h * (0.62 if compact else 1)),
                                tip + f"\n{target} replied" + (f" ({t['sentiment']})" if t["sentiment"] else "")))
        if t["hit"]:
            label = "Confirmed incident" if t["hit"] == "confirmed" else "Estimated incident"
            parts.append(_block(f"hit {'conf' if t['hit'] == 'confirmed' else 'est'}", c, ridx, 44 if compact else 88,
                                tip + f"\n{label}: {', '.join(t['hit_types'])}",
                                "" if compact else f"<span class='s3-flag'><span>{label}</span></span>"))
        elif t["events"]:
            parts.append(_block("evt", c, ridx, 14, tip + "\n" + ", ".join(t["events"])))
    head = ("<div class='s3-head' id='s3-head' style='--c:0'><span class='s3-flag blue'><span id='s3-flag'>Touch 1</span></span></div>"
            if interactive else "")
    cls = "s3" + (" s3-compact" if compact else "") + (" s3-live" if interactive else "")
    aria = (f"3D score of the run against {target}: {len(touches)} touches, "
            f"{sum(1 for t in touches if t['reply'])} replies"
            + (f", incident at touch {next(t['n'] for t in touches if t['hit'])}" if any(t["hit"] for t in touches) else ""))
    return (f"<div class='{cls}' style='--n:{slots};--lanes:{len(rows)}' role='img' aria-label='{_e(aria)}'>"
            f"<div class='s3-plane'>{''.join(parts)}{head}</div></div>")


def bars3d(rows: list[tuple[str, float, str]]) -> str:
    """A 3D bar per row: (label, value 0..1, tooltip). Bars stand on a tilted floor, value printed above each."""
    if not rows:
        return "<div class='empty-state'>No runs yet</div>"
    parts = []
    for c, (label, v, tip) in enumerate(rows):
        h = max(6, round(220 * v))
        parts.append(_block("bar", c, 0, h, tip, f"<span class='s3-val'><span>{round(100 * v)}%</span></span>"))
        parts.append(f"<span class='s3-tick name' style='--c:{c}'><span>{_e(label)}</span></span>")
    return (f"<div class='s3 s3-bars' style='--n:{len(rows)};--lanes:1' role='img' aria-label='Reply rate by target: "
            + _e(", ".join(f"{lbl} {round(100 * v)}%" for lbl, v, _ in rows)) + f"'><div class='s3-plane'>{''.join(parts)}</div></div>")


SCORE3D_CSS = """
@property --h{syntax:'<length>';inherits:true;initial-value:0px}
.s3{--tilt:58deg;--lane:64px;--depth:30px;position:relative;height:calc(var(--lanes) * var(--lane) * .62 + 150px);
perspective:1700px;perspective-origin:50% -40%;user-select:none}
.s3-plane{position:absolute;left:150px;right:0;top:50%;height:calc(var(--lanes) * var(--lane));margin-top:calc(var(--lanes) * var(--lane) / -2 + 16px);
transform-style:preserve-3d;transform:rotateX(var(--tilt)) rotateZ(var(--spin,0deg));transition:transform .9s var(--ease);
background:linear-gradient(#fbfbfd,#f5f5f7);border-radius:22px;box-shadow:0 40px 60px -40px rgba(0,0,0,.18)}
.s3-staff{position:absolute;left:0;right:0;top:calc(var(--l) * var(--lane) + var(--lane) / 2);height:1px;background:var(--hair);transform-style:preserve-3d}
.s3-staff.rep{background:var(--reply-2)}
.s3-lab{position:absolute;right:calc(100% + 22px);top:0;transform-origin:100% 0;transform:rotateX(calc(-1 * var(--tilt)));white-space:nowrap}
.s3-lab span{display:block;transform:translateY(-50%);font:600 14px var(--sans);color:var(--text-2);letter-spacing:-.01em}
.s3-tick{position:absolute;bottom:-4px;left:calc((var(--c) + .5) * 100% / var(--n));transform-origin:50% 0;transform:rotateX(calc(-1 * var(--tilt)))}
.s3-tick span{display:block;transform:translateX(-50%);font:600 12px var(--sans);color:var(--muted);font-variant-numeric:tabular-nums}
.blk{position:absolute;width:calc(100% / var(--n) * .58);height:var(--depth);left:calc((var(--c) + .21) * 100% / var(--n));
top:calc(var(--l) * var(--lane) + (var(--lane) - var(--depth)) / 2);transform-style:preserve-3d;border-radius:7px;
box-shadow:6px -10px 18px -6px rgba(0,0,0,.16);animation:s3rise 1.2s var(--ease) both;animation-delay:calc(var(--c) * 70ms + 150ms)}
@keyframes s3rise{from{--h:2px}}
.blk b{position:absolute;display:block}
.blk .t{inset:0;transform:translateZ(var(--h));border-radius:7px;background:var(--top)}
.blk .f{left:0;right:0;top:100%;height:var(--h);transform-origin:50% 0;transform:rotateX(90deg);background:var(--front);border-radius:0 0 3px 3px}
.blk .sr{left:100%;top:0;width:var(--h);height:100%;transform-origin:0 50%;transform:rotateY(-90deg);background:var(--side)}
.blk .sl{right:100%;top:0;width:var(--h);height:100%;transform-origin:100% 50%;transform:rotateY(90deg);background:var(--side)}
.blk.agent{--top:#3a3a3c;--front:#1d1d1f;--side:#2c2c2e}
.blk.agent.err{--top:#ffd5d5;--front:#ffb3b3;--side:#ffc4c4}
.blk.reply{--top:#d6e8fd;--front:#a9ccf5;--side:#bcd8f8}
.blk.evt{--top:#d9d8ff;--front:#b0aef7;--side:#c4c2fb}
.blk.bar{--top:#5aa9ff;--front:#0071e3;--side:#2b8af0}
.blk.hit{width:calc(100% / var(--n) * .36);left:calc((var(--c) + .32) * 100% / var(--n));height:calc(var(--depth) * .7);
top:calc(var(--l) * var(--lane) + (var(--lane) - var(--depth) * .7) / 2 - var(--lane) * .9)}
.blk.hit.conf{--top:#ffc061;--front:#ff9f0a;--side:#f08d00}
.blk.hit.est{--top:rgba(255,159,10,.16);--front:rgba(255,159,10,.2);--side:rgba(255,159,10,.14)}
.blk.hit.est b{border:1.5px dashed var(--amber)}
.s3-flag,.s3-val{position:absolute;left:50%;top:50%;transform-style:preserve-3d;transform:translateZ(calc(var(--h) + 8px)) rotateX(calc(-1 * var(--tilt)));
transform-origin:0 0}
.s3-flag span,.s3-val span{display:block;transform:translate(-50%,-100%);white-space:nowrap;font:650 12.5px var(--sans);padding:5px 10px;
border-radius:999px;background:var(--amber);color:#3d2000;box-shadow:0 6px 16px -6px rgba(0,0,0,.25)}
.blk.hit.est .s3-flag span{background:#fff;color:var(--amber-text);box-shadow:inset 0 0 0 1.5px var(--amber),0 6px 16px -6px rgba(0,0,0,.2)}
.s3-val span{background:none;box-shadow:none;color:var(--text);font:700 22px var(--display);letter-spacing:-.03em;padding:0 0 6px}
.s3-head{position:absolute;top:-10px;bottom:-10px;left:calc(var(--c) * 100% / var(--n));width:calc(100% / var(--n));border-radius:14px;
background:rgba(0,113,227,.07);box-shadow:inset 0 0 0 1.5px rgba(0,113,227,.6);transition:left .7s var(--ease);transform-style:preserve-3d;pointer-events:none}
.s3-head .s3-flag{top:0;transform:translateZ(6px) rotateX(calc(-1 * var(--tilt)))}
.s3-head .s3-flag span{background:var(--blue);color:#fff}
.s3-live .blk{cursor:pointer}
.s3-live.playing .blk.future{opacity:.22;transition:opacity .5s}
.s3[data-focus] .blk{opacity:.25;transition:opacity .3s}.s3[data-focus] .blk.on-focus{opacity:1}
.s3-compact{--tilt:62deg;--lane:34px;--depth:16px;height:calc(var(--lanes) * var(--lane) * .55 + 56px);perspective:1200px}
.s3-compact .s3-plane{left:0;border-radius:14px;margin-top:calc(var(--lanes) * var(--lane) / -2 + 6px)}
.s3-compact .blk{border-radius:4px}.s3-compact .blk .t{border-radius:4px}
.s3-compact .blk.hit{top:calc(var(--l) * var(--lane) + (var(--lane) - var(--depth) * .7) / 2 - var(--lane) * .7)}
.s3-bars{--tilt:62deg;--lane:120px;--depth:64px;height:400px;perspective:1500px}
.s3-bars .s3-plane{left:0;margin-top:30px}
.s3-bars .blk{width:calc(100% / var(--n) * .3);left:calc((var(--c) + .35) * 100% / var(--n));height:var(--depth)}
.s3-bars .s3-tick{bottom:-8px}.s3-bars .s3-tick span{font-size:14px;color:var(--text-2)}
@media(max-width:760px){.s3{--lane:48px;--depth:22px;height:calc(var(--lanes) * var(--lane) * .62 + 110px)}
.s3-plane{left:0;margin-top:calc(var(--lanes) * var(--lane) / -2 + 26px)}.s3-lab{right:auto;left:6px}
.s3-lab span{transform:translateY(-130%);font-size:12px}.s3-flag span{font-size:11px;padding:4px 8px}
.s3-compact{--lane:26px;--depth:12px}.s3-bars{--lane:90px;--depth:44px;height:320px}.s3-val span{font-size:17px}}
@media(prefers-reduced-motion:reduce){.blk{animation:none}.s3-plane,.s3-head{transition:none}}
"""

# --------------------------------------------------------------------------- landing page


def _featured(states: list[dict]) -> dict | None:
    with_steps = [st for st in states if _steps(st)]
    if not with_steps:
        return None
    def rank(st: dict) -> tuple:
        inc = _live(st)
        return (any(i.get("source") == "api event" for i in inc), bool(inc), st.get("status") == "done", st.get("run_id", ""))
    return max(with_steps, key=rank)


def _headline(st: dict, touches: list[dict]) -> str:
    first = _first((st.get("target") or {}).get("name"))
    hit = next((t for t in touches if t["hit"]), None)
    if hit:
        idx = touches.index(hit)
        word = "call" if hit["lane"] == "phone_call" else "message" if hit["lane"] != "email" else "email"
        types = set(hit["hit_types"])
        verb = ("submitted the page" if "submit" in types or "submission" in types else "opened the file" if "attachment" in types
                else "clicked" if "click" in types else "agreed" if "action" in types else "told the agent what it wanted")
        nth = _ORD[idx] if idx < len(_ORD) else f"{idx + 1}th"
        return f"On the {nth} {word}, {first} {verb}."
    replies = sum(1 for t in touches if t["reply"])
    tw = "touch" if len(touches) == 1 else "touches"
    rw = "reply" if replies == 1 else "replies"
    return f"{len(touches)} {tw}. {replies} {rw} from {first}. One persona, start to finish."


def _monologue(text: str, limit: int = 520) -> str:
    sents = re.split(r"(?<=[.!?])\s+", " ".join(str(text).split()))
    pick = sents[1:6] if len(sents) > 4 else sents
    out = " ".join(pick)
    out = out if len(out) <= limit else out[: limit - 1].rsplit(" ", 1)[0] + "…"
    return ("… " if pick is not sents and len(sents) > 4 else "") + out


def _demo_state() -> dict:
    """A self-contained, illustrative simulation for the landing demo.

    No practice run, no real target: the people and company are invented so the
    page can pitch the mechanism honestly without showing any live result.
    """
    def email(n, subject, body, reply, sentiment):
        return {"touch": n, "action": {"decision": "SEND", "channel": "email", "subject": subject,
                                        "sender": {"name": "Dana Reeve"}},
                "payload": {"subject": subject, "body": body},
                "events": [{"type": "reply", "body": reply}] if reply else [],
                "judge": {"sentiment": sentiment}}

    steps = [
        email(1, "Q1 payout: confirm your remittance details",
              "Hi Jordan, I'm Dana from Northwind Supply's vendor desk. We're migrating remittance "
              "records before the Q1 run and your profile is flagged for a quick confirmation. Could you "
              "verify the account on file through our vendor portal so your payouts aren't held? Takes a minute.",
              "Which portal? We usually handle this through AP, not the vendor directly.", "questioning"),
        email(2, "Re: Q1 payout: confirm your remittance details",
              "Totally fair. AP asked us to collect confirmations directly this cycle to cut the back-and-forth. "
              "Here's the secure link — it shows your current details and you just approve or correct them.",
              "Okay, I'll take a look in a bit.", "hesitant"),
        {"touch": 3, "action": {"decision": "SEND", "channel": "chat", "sender": {"name": "Dana Reeve"}},
         "payload": {"subject": "", "body": "Hi Jordan — Dana here. Just flagging that the confirmation closes "
                     "end of day so the Q1 payout isn't delayed. Happy to stay on while you check."},
         "events": [{"type": "reply", "body": "Give me 5 min, I'm in a meeting."}],
         "judge": {"sentiment": "engaged"}},
        {"touch": 4, "action": {"decision": "CALL", "kind": "call", "sender": {"name": "Dana Reeve"}},
         "payload": {"subject": "", "body": ""},
         "transcript": [
             {"who": "agent", "text": "Hi Jordan, it's Dana from Northwind — sorry to chase, I know you're slammed. "
              "I can walk you through the portal in about thirty seconds so this is off your plate."},
             {"who": "target", "text": "Sure, that's easier. What do I click?"}],
         "events": [], "judge": {"sentiment": "engaged"}},
        email(5, "Your remittance confirmation (expires today)",
              "As promised — the confirmation page is here. Sign in with your work account and approve the details. "
              "If anything looks off, correct it inline and it routes straight to AP.",
              "Done — approved it.", "engaged"),
    ]
    return {
        "run_id": "demo",
        "status": "done",
        "config": {"max_touches": 5},
        "target": {"name": "Jordan", "role": "Finance operations (illustrative target)"},
        "plan": {"persona": {"name": "Dana Reeve", "organisation": "Northwind Supply"}},
        "steps": steps,
        "incidents": [{"touch": 5, "source": "api event", "type": "sign-in submitted", "superseded": False}],
    }


_DEMO_MONOLOGUE = (
    "Jordan pushed back on the channel, not on the premise — the Q1 deadline is doing the work, so I won't "
    "over-explain. AP was named as the gatekeeper, so I'll borrow AP's authority rather than argue with it. "
    "The ask stays identical to touch 2; only the urgency moves. One link, one action, and a reason the page "
    "needs a sign-in. If this reply lands cold, I drop the deadline and offer to read the details back on a call instead.")

_DEMO_NOTES = [
    ("Before touch 1", "Target routes finance through AP, not vendors directly.", False),
    ("After touch 1", "Channel was doubted, premise was accepted — lean on the Q1 deadline, not on who I am.", False),
    ("After touch 3", "Prefers to be walked through; a call lowers the effort to act.", False),
    ("After touch 4", "ROUTE CLOSED: cold links alone. The warm hand-off on the call is what moved it.", True),
]


def render_home(states: list[dict], out_dir: Path, page: Callable[..., str], stats: dict,
                research_targets: list[str]) -> Path:
    """The pitch landing page: idea first, then a scripted live demo of the agent at work.

    Deliberately shows no practice results. The demo is a self-contained, illustrative
    simulation so judges see the mechanism live without any real target or score on screen.
    """
    from .report_style import CSS as BASE_CSS

    st = _demo_state()
    touches = _touch_model(st)
    data = [{k: x[k] for k in ("n", "lane", "subject", "sender", "body", "reply", "sentiment", "hit", "hit_types", "events")}
            for x in touches]

    nav = ("<header class='pz-nav' id='top'><div class='pz-nav-in'>"
           "<a class='pz-brand' href='#top'>revel8</a>"
           "<nav class='pz-links'><a href='#problem'>The problem</a><a href='#demo'>Watch it work</a>"
           "<a href='#how'>How it works</a></nav>"
           "<a class='pz-pill' href='#demo'>Watch the demo</a></div></header>")

    hero = ("<section class='pz-hero'>"
            "<div class='pz-hero-in reveal'>"
            "<span class='pz-eyebrow'>Autonomous social-engineering simulations</span>"
            "<h1 class='pz-h1'>The social-engineering<br>test that runs itself.</h1>"
            "<p class='pz-lede'>revel8 researches a target, casts a believable persona, and holds a real "
            "multi-touch conversation across email, chat and phone &mdash; adapting to every reply until the "
            "target acts. You only press start.</p>"
            "<div class='pz-cta'>"
            "<a class='btn pz-btn' href='#demo'><svg class='svgi' viewBox='0 0 24 24' aria-hidden='true'>"
            "<path d='M7 4.5v15l12-7.5z' fill='currentColor'/></svg>Watch it work</a>"
            "<a class='pz-ghost' href='#how'>How it works &rarr;</a></div></div>"
            "<div class='pz-scroll reveal' aria-hidden='true'><span></span>Scroll to watch a run</div></section>")

    problem = ("<section class='pz-sec' id='problem'>"
               "<div class='pz-sec-head reveal'><span class='pz-kicker'>The problem</span>"
               "<h2 class='pz-h2'>Attackers hold a conversation. Most tests send one email.</h2></div>"
               "<div class='pz-cols'>"
               "<p class='reveal'>Social engineering is how most breaches begin &mdash; not through a firewall, "
               "but through a person who was asked the right thing at the right moment.</p>"
               "<p class='reveal'>Yet teams still test it by hand: a template, sent once, graded later. It doesn't "
               "follow up, it doesn't adapt, and it looks nothing like a real adversary.</p>"
               "<p class='reveal'>A real attacker researches, picks a persona, and stays in character across days "
               "and channels. To defend against that, you have to be able to test against that.</p></div></section>")

    ctl = ("<div class='hm-ctl'><button type='button' id='hm-prev' aria-label='Previous touch'>"
           "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='m15 5-7 7 7 7' fill='none' stroke='currentColor' "
           "stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/></svg></button>"
           "<span id='hm-pos' class='hm-pos'>Touch 1 of {n}</span>".replace("{n}", str(len(touches)))
           + "<button type='button' id='hm-next' aria-label='Next touch'>"
           "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='m9 5 7 7-7 7' fill='none' stroke='currentColor' "
           "stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/></svg></button></div>")

    demo = ("<section class='pz-sec pz-demo' id='demo'>"
            "<div class='pz-sec-head reveal'><span class='pz-kicker'>Watch it work</span>"
            "<h2 class='pz-h2'>A full campaign, played in real time.</h2>"
            "<p class='pz-sub'>Press play. Every message is the agent's own. It researches, writes, reads "
            "the reply and decides the next move. This is a sample simulation; the person and company are "
            "illustrative.</p></div>"
            "<div class='pz-stage reveal glass'><div class='pz-stage-grid'>"
            f"<div class='pz-score'>{score3d(st, interactive=True)}{ctl}</div>"
            "<div class='pz-convo'><div class='hm-convo' id='hm-convo' aria-live='polite'></div></div>"
            "</div></div>"
            "<div class='pz-play-row reveal'>"
            "<button type='button' class='btn pz-btn' id='hm-play' aria-pressed='false'>"
            "<svg class='svgi' viewBox='0 0 24 24' aria-hidden='true'>"
            "<path id='hm-play-ic' d='M7 4.5v15l12-7.5z' fill='currentColor'/></svg>"
            "<span id='hm-play-l'>Play the conversation</span></button>"
            "<span class='pz-note'>Sample simulation &middot; illustrative scenario, not a real target</span></div>"
            f"<script type='application/json' id='hm-data'>{_json_for_script(data)}</script></section>")

    notes_html = "".join(
        f"<li class='{'closed' if c else ''}'><span class='hm-nt'>{_e(w)}</span>{_e(n)}</li>"
        for w, n, c in _DEMO_NOTES)
    mind = ("<section class='pz-sec' id='mind'>"
            "<div class='pz-sec-head reveal'><span class='pz-kicker'>Not a template</span>"
            "<h2 class='pz-h2'>It thinks before it writes.</h2>"
            "<p class='pz-sub'>The agent keeps a private notebook between touches and reasons about the next move. "
            "Nobody writes the copy and nobody edits it.</p></div>"
            "<div class='pz-mind reveal'>"
            f"<figure class='pz-quote glass'><blockquote>{_e(_DEMO_MONOLOGUE)}</blockquote>"
            "<figcaption>The agent's own reasoning, right before the final touch</figcaption></figure>"
            f"<div class='pz-notes glass'><h3>Its notebook</h3><ol>{notes_html}</ol></div></div></section>")

    stages = [("Research", "Public sources only. Every fact is checked against its source before the agent may use it."),
              ("Brief &amp; memory", "The verified facts become hooks, and what worked against this target before is remembered."),
              ("Casting", "The agent invents one believable person, with a role, a reason to write, and one small ask."),
              ("Session", "It writes, sends, reads the reply and decides the next move, touch after touch, in character.")]
    how = ("<section class='pz-sec' id='how'>"
           "<div class='pz-sec-head reveal'><span class='pz-kicker'>How it works</span>"
           "<h2 class='pz-h2'>Four stages. No script.</h2></div>"
           "<div class='pz-stages'>"
           + "".join(f"<div class='pz-stage glass reveal' style='--d:{i}'><span class='pz-stage-n'>0{i + 1}</span>"
                     f"<h3>{a}</h3><p>{b}</p></div>" for i, (a, b) in enumerate(stages))
           + "</div></section>")

    channels = ("<section class='pz-sec' id='channels'>"
                "<div class='pz-sec-head reveal'><h2 class='pz-h2'>One persona. Every channel.</h2>"
                "<p class='pz-sub'>The same character follows up over email, chat and a live phone call. "
                "Authorised simulations against consenting targets, with no human in the loop.</p></div>"
                "<div class='pz-chips reveal'>"
                + "".join(f"<span class='pz-chip'>{c}</span>" for c in ("Email", "Chat", "Phone / voice",
                                                                        "Multi-touch", "In character", "Authorised &amp; consenting"))
                + "</div></section>")

    close = ("<section class='pz-close reveal'><h2>No human in the loop.</h2>"
             "<p>The agent runs the whole campaign, from research to incident, on its own. "
             "You press start and watch.</p>"
             "<a class='btn pz-btn' href='#demo' id='hm-replay'>"
             "<svg class='svgi' viewBox='0 0 24 24' aria-hidden='true'><path d='M7 4.5v15l12-7.5z' fill='currentColor'/></svg>"
             "Watch the demo</a></section>"
             "<footer class='pz-foot'>revel8 &middot; START Hack &middot; authorised, consenting simulations only.</footer>")

    body = (nav + "<main class='pz-wrap'>" + hero + problem + demo + mind + how + channels + close + "</main>"
            + "<canvas id='pz-bg' aria-hidden='true'></canvas><div class='pz-veil' aria-hidden='true'></div>")

    three = "<script src='three.min.js' defer></script>"
    doc = (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
           f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>revel8 &middot; the agent that runs the conversation</title>"
           f"<style>{BASE_CSS}{SCORE3D_CSS}{PITCH_CSS}</style>{three}</head>"
           f"<body class='pz'>{body}<script>{PITCH_JS}</script></body></html>")

    out = out_dir / "index.html"
    out.write_text(doc, encoding="utf-8")
    return out


PITCH_CSS = """
.pz{background:#fbfbfd}
.pz-wrap{position:relative;z-index:1}
#pz-bg{position:fixed;inset:0;width:100%;height:100%;z-index:0;pointer-events:none;opacity:.9}
.pz-veil{position:fixed;inset:0;z-index:0;pointer-events:none;
background:radial-gradient(120% 80% at 70% -10%,transparent 0,rgba(251,251,253,.2) 42%,#fbfbfd 78%)}
.pz-nav{position:fixed;top:0;left:0;right:0;z-index:40;background:rgba(255,255,255,.62);
backdrop-filter:saturate(180%) blur(22px);-webkit-backdrop-filter:saturate(180%) blur(22px);border-bottom:1px solid rgba(0,0,0,.06)}
.pz-nav-in{max-width:1200px;margin:0 auto;padding:13px 32px;display:flex;align-items:center;gap:30px}
.pz-brand{font:800 21px var(--display);letter-spacing:-.03em;color:var(--text)}
.pz-brand:hover{text-decoration:none}
.pz-links{display:flex;gap:28px;margin-left:8px}
.pz-links a{font-size:14.5px;color:var(--text-2);font-weight:500}.pz-links a:hover{color:var(--text);text-decoration:none}
.pz-pill{margin-left:auto;font-size:14px;font-weight:600;color:var(--text);padding:8px 16px;border-radius:999px;
background:rgba(255,255,255,.6);border:1px solid rgba(0,0,0,.08);backdrop-filter:blur(8px)}
.pz-pill:hover{text-decoration:none;background:#fff}
.glass{background:rgba(255,255,255,.55);backdrop-filter:saturate(180%) blur(26px);-webkit-backdrop-filter:saturate(180%) blur(26px);
border:1px solid rgba(255,255,255,.8);box-shadow:0 1px 0 0 rgba(255,255,255,.7) inset,0 30px 60px -40px rgba(20,30,60,.35),
0 2px 14px -6px rgba(20,30,60,.12);border-radius:28px}
.pz-wrap>section,.pz-close{max-width:1200px;margin:0 auto;padding-left:32px;padding-right:32px}
.pz-hero{min-height:100svh;display:flex;flex-direction:column;justify-content:center;padding-top:92px;padding-bottom:40px}
.pz-hero-in{max-width:960px}
.pz-eyebrow{display:inline-block;font-size:13px;font-weight:650;letter-spacing:.02em;text-transform:uppercase;
color:var(--blue-text);margin-bottom:22px}
.pz-h1{font:800 clamp(44px,8vw,104px)/.96 var(--display);letter-spacing:-.045em;margin:0;color:var(--text);text-wrap:balance}
.pz-lede{font-size:clamp(19px,1.7vw,25px);line-height:1.42;color:var(--text-2);margin:28px 0 0;max-width:40ch;text-wrap:pretty}
.pz-cta{display:flex;align-items:center;gap:26px;margin-top:40px;flex-wrap:wrap}
.pz-btn{font-size:16px;padding:15px 28px}.pz-btn .svgi{width:17px;height:17px}
.pz-ghost{font-size:16px;font-weight:600;color:var(--text)}
.pz-scroll{margin-top:64px;display:flex;align-items:center;gap:12px;font-size:13px;color:var(--muted);letter-spacing:.01em}
.pz-scroll span{width:22px;height:34px;border:1.5px solid var(--hair);border-radius:12px;position:relative;flex:none}
.pz-scroll span::after{content:'';position:absolute;left:50%;top:7px;width:3px;height:6px;border-radius:2px;background:var(--muted);
transform:translateX(-50%);animation:pzdot 1.8s var(--ease) infinite}
@keyframes pzdot{0%{opacity:0;transform:translate(-50%,0)}30%{opacity:1}60%{opacity:1;transform:translate(-50%,10px)}100%{opacity:0;transform:translate(-50%,10px)}}
.pz-sec{padding-top:140px}
.pz-sec-head{max-width:760px;margin-bottom:56px}
.pz-kicker{display:inline-block;font-size:13px;font-weight:650;letter-spacing:.02em;text-transform:uppercase;color:var(--muted);margin-bottom:18px}
.pz-h2{font:800 clamp(34px,4.6vw,62px)/1.02 var(--display);letter-spacing:-.04em;margin:0;color:var(--text);text-wrap:balance}
.pz-sub{font-size:clamp(17px,1.5vw,21px);line-height:1.46;color:var(--text-2);margin:22px 0 0;max-width:52ch;text-wrap:pretty}
.pz-cols{display:grid;grid-template-columns:repeat(3,1fr);gap:40px}
.pz-cols p{margin:0;font-size:18px;line-height:1.55;color:var(--text-2);padding-top:22px;border-top:2px solid var(--text)}
.pz-stage{padding:40px}
.pz-stage-grid{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,.8fr);gap:48px;align-items:center}
.pz-score{position:relative}
.pz-convo{min-height:300px}
.hm-convo{display:flex;flex-direction:column;gap:12px}
.hm-meta{display:flex;align-items:center;gap:10px;font-size:13px;color:var(--muted);font-variant-numeric:tabular-nums;flex-wrap:wrap}
.hm-meta b{color:var(--text);font-weight:650}
.hm-bub{border-radius:20px;padding:15px 19px;font-size:15px;line-height:1.55;white-space:pre-wrap;overflow-wrap:anywhere;
display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:8;overflow:hidden;animation:hmIn .6s var(--ease) both}
.hm-bub .who{display:block;font-size:12.5px;font-weight:650;margin-bottom:4px;white-space:normal}
.hm-bub.out{background:#1d1d1f;color:#f5f5f7;border-bottom-right-radius:7px}.hm-bub.out .who{color:#a1a1a6}
.hm-bub.in{background:rgba(0,113,227,.09);color:var(--text);border-bottom-left-radius:7px;-webkit-line-clamp:6;animation-delay:.22s}
.hm-bub.in .who{color:var(--blue-text)}
.hm-silent{font-size:14px;color:var(--muted);padding:4px 2px}
.hm-inc{align-self:flex-start;font-size:13px;font-weight:650;padding:7px 14px;border-radius:999px;background:var(--amber);
color:#3d2000;animation:hmIn .6s var(--ease) .4s both}
@keyframes hmIn{from{opacity:0;transform:translateY(10px);filter:blur(4px)}}
.hm-ctl{display:flex;align-items:center;gap:14px;margin-top:18px;padding-left:150px}
.hm-ctl button{width:38px;height:38px;border-radius:50%;border:0;background:rgba(255,255,255,.7);color:var(--text);cursor:pointer;
display:grid;place-items:center;box-shadow:0 2px 8px -4px rgba(0,0,0,.25)}
.hm-ctl button:hover{background:#fff}.hm-ctl button svg{width:18px;height:18px}
.hm-pos{font-size:14px;font-weight:600;min-width:96px;text-align:center;font-variant-numeric:tabular-nums}
.pz-play-row{display:flex;align-items:center;gap:20px;margin-top:30px;flex-wrap:wrap}
.pz-note{font-size:13px;color:var(--muted)}
.pz-mind{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,.7fr);gap:28px;align-items:stretch}
.pz-quote{margin:0;padding:38px}
.pz-quote blockquote{margin:0;font:500 clamp(20px,1.9vw,27px)/1.42 var(--display);letter-spacing:-.02em;color:var(--text);text-wrap:pretty}
.pz-quote figcaption{margin-top:24px;font-size:13px;color:var(--muted)}
.pz-notes{padding:34px}
.pz-notes h3{font-size:15px;margin:0 0 20px;color:var(--text)}
.pz-notes ol{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:18px}
.pz-notes li{font-size:14.5px;line-height:1.5;color:var(--text-2);padding-top:14px;border-top:1px solid rgba(0,0,0,.1)}
.pz-notes li.closed{color:var(--crit-text)}
.hm-nt{display:block;font-size:12px;font-weight:650;color:var(--muted);margin-bottom:3px}
.pz-stages{display:grid;grid-template-columns:repeat(4,1fr);gap:22px}
.pz-stage{padding:30px;transition-delay:calc(var(--d,0) * 90ms)}
.pz-stage-n{font:700 14px var(--mono);color:var(--blue-text);letter-spacing:.04em}
.pz-stage h3{margin:14px 0 10px;font-size:20px;letter-spacing:-.02em}
.pz-stage p{margin:0;color:var(--text-2);font-size:15px;line-height:1.55}
.pz-chips{display:flex;flex-wrap:wrap;gap:12px}
.pz-chip{font-size:15px;font-weight:600;color:var(--text);padding:11px 20px;border-radius:999px;
background:rgba(255,255,255,.55);border:1px solid rgba(0,0,0,.08);backdrop-filter:blur(10px)}
.pz-close{text-align:center;padding:170px 32px 50px}
.pz-close h2{font:800 clamp(42px,6.4vw,88px)/1 var(--display);letter-spacing:-.045em;margin:0;color:var(--text)}
.pz-close p{font-size:21px;color:var(--text-2);margin:22px auto 36px;max-width:42ch}
.pz-foot{max-width:1200px;margin:60px auto 0;padding:28px 32px;border-top:1px solid var(--border);
font-size:13px;color:var(--muted);text-align:center}
.reveal{opacity:0;transform:translateY(30px) scale(.992);filter:blur(8px);
transition:opacity .9s var(--ease),transform .9s var(--ease),filter .9s var(--ease)}
.reveal.in{opacity:1;transform:none;filter:none}
@media(max-width:980px){.pz-stage-grid{grid-template-columns:minmax(0,1fr);gap:36px}
.pz-mind{grid-template-columns:minmax(0,1fr)}.pz-cols{grid-template-columns:minmax(0,1fr);gap:24px}
.pz-stages{grid-template-columns:1fr 1fr}.hm-ctl{padding-left:0}}
@media(max-width:760px){.pz-nav-in{padding:11px 18px;gap:16px}.pz-links{display:none}
.pz-wrap>section,.pz-close{padding-left:20px;padding-right:20px}.pz-sec{padding-top:96px}.pz-stage{padding:22px}
.pz-stages{grid-template-columns:1fr}.pz-quote,.pz-notes{padding:26px}.pz-close{padding-top:120px}}
@media(prefers-reduced-motion:reduce){.reveal{opacity:1;transform:none;filter:none;transition:none}
.hm-bub,.hm-inc{animation:none}.pz-scroll span::after{animation:none}}
"""

PITCH_JS = r"""
(function(){
  "use strict";
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // --- Apple-style scroll reveal ---
  var reveals = Array.prototype.slice.call(document.querySelectorAll(".reveal"));
  if ("IntersectionObserver" in window && !reduce){
    var io = new IntersectionObserver(function(es){
      es.forEach(function(e){ if(e.isIntersecting){ e.target.classList.add("in"); io.unobserve(e.target); } });
    }, {threshold:0.14, rootMargin:"0px 0px -8% 0px"});
    reveals.forEach(function(el){ io.observe(el); });
  } else { reveals.forEach(function(el){ el.classList.add("in"); }); }

  // --- the demo: playhead + conversation, driven by #hm-data ---
  var T = JSON.parse((document.getElementById("hm-data")||{}).textContent || "[]");
  var $ = function(id){ return document.getElementById(id); };
  var s3 = document.querySelector(".s3-live"), head = $("s3-head"), flag = $("s3-flag");
  var convo = $("hm-convo"), pos = $("hm-pos"), btn = $("hm-play"), lbl = $("hm-play-l"), ic = $("hm-play-ic");
  if (T.length && s3 && convo){
    var blocks = Array.prototype.slice.call(s3.querySelectorAll(".blk"));
    var LANE = {email:"Email", phone_call:"Phone call", sms:"SMS", whatsapp:"WhatsApp", chat:"Chat", linkedin:"LinkedIn"};
    var cur = 0, timer = null;
    function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c];}); }
    function show(i){
      cur = Math.max(0, Math.min(T.length-1, i));
      var t = T[cur];
      if(head) head.style.setProperty("--c", cur);
      if(flag) flag.textContent = "Touch " + t.n;
      if(pos) pos.textContent = "Touch " + t.n + " of " + T.length;
      blocks.forEach(function(b){ var c=+b.style.getPropertyValue("--c"); b.classList.toggle("future", c>cur); });
      var h = "<div class='hm-meta'><b>Touch " + t.n + "</b><span>" + esc(LANE[t.lane]||t.lane) + "</span>" +
              (t.subject ? "<span>&middot; " + esc(t.subject) + "</span>" : "") + "</div>";
      h += "<div class='hm-bub out'><span class='who'>" + esc(t.sender||"Agent") + "</span>" + esc(t.body) + "</div>";
      if (t.reply) h += "<div class='hm-bub in'><span class='who'>Reply</span>" + esc(t.reply) + "</div>";
      else h += "<div class='hm-silent'>" + (t.events.length ? esc(t.events.join(", ")) : "No reply yet.") + "</div>";
      if (t.hit) h += "<div class='hm-inc'>Incident reached &middot; " + esc(t.hit_types.join(", ")) + "</div>";
      convo.innerHTML = h;
    }
    function stop(){ clearInterval(timer); timer=null; if(s3) s3.classList.remove("playing");
      btn.setAttribute("aria-pressed","false"); if(lbl) lbl.textContent="Play the conversation";
      if(ic) ic.setAttribute("d","M7 4.5v15l12-7.5z"); }
    function play(){
      if (timer){ stop(); return; }
      if (cur >= T.length-1) show(0);
      if(s3) s3.classList.add("playing"); btn.setAttribute("aria-pressed","true");
      if(lbl) lbl.textContent="Pause"; if(ic) ic.setAttribute("d","M7 5h3.5v14H7zM13.5 5H17v14h-3.5z");
      show(cur);
      timer = setInterval(function(){ if (cur >= T.length-1){ stop(); return; } show(cur+1); }, reduce ? 5200 : 4200);
    }
    btn.addEventListener("click", play);
    $("hm-prev").addEventListener("click", function(){ stop(); show(cur-1); });
    $("hm-next").addEventListener("click", function(){ stop(); show(cur+1); });
    var again = $("hm-replay");
    if (again) again.addEventListener("click", function(){ stop(); show(0); setTimeout(play, reduce?0:650); });
    blocks.forEach(function(b){ b.addEventListener("click", function(){ stop(); show(+b.style.getPropertyValue("--c")); }); });
    document.addEventListener("keydown", function(e){
      if (e.target.closest && e.target.closest("input,select,textarea")) return;
      if (e.key==="ArrowRight"){ stop(); show(cur+1); } else if (e.key==="ArrowLeft"){ stop(); show(cur-1); }
    });
    if (!reduce && s3) s3.addEventListener("pointermove", function(e){
      var r=s3.getBoundingClientRect(), x=(e.clientX-r.left)/r.width-.5, y=(e.clientY-r.top)/r.height-.5;
      s3.style.setProperty("--spin",(x*-5).toFixed(2)+"deg"); s3.style.setProperty("--tilt",(58+y*6).toFixed(2)+"deg");
    });
    if (s3) s3.addEventListener("pointerleave", function(){ s3.style.removeProperty("--spin"); s3.style.removeProperty("--tilt"); });
    show(0);
    // auto-start once the demo scrolls into view
    if ("IntersectionObserver" in window && !reduce){
      var once=false, demoEl=document.getElementById("demo");
      if (demoEl){ var io2=new IntersectionObserver(function(es){ es.forEach(function(e){
        if(e.isIntersecting && !once){ once=true; setTimeout(play,600); io2.disconnect(); } }); },{threshold:0.4});
        io2.observe(demoEl); }
    }
  }

  // --- three.js ambient hero backdrop (graceful fallback to CSS if it can't load) ---
  function startBG(){
    var canvas = document.getElementById("pz-bg");
    if (!canvas || !window.THREE || reduce) return;
    try{
      var THREE = window.THREE;
      var renderer = new THREE.WebGLRenderer({canvas:canvas, antialias:true, alpha:true});
      renderer.setPixelRatio(Math.min(window.devicePixelRatio||1, 2));
      var scene = new THREE.Scene();
      var camera = new THREE.PerspectiveCamera(60, 1, 0.1, 100);
      camera.position.z = 15;
      // a slow, faint wireframe icosahedron
      var ico = new THREE.Mesh(
        new THREE.IcosahedronGeometry(6.2, 1),
        new THREE.MeshBasicMaterial({color:0x0071e3, wireframe:true, transparent:true, opacity:0.12}));
      scene.add(ico);
      // drifting point field
      var N = 520, pos = new Float32Array(N*3);
      for (var i=0;i<N;i++){ pos[i*3]=(Math.random()-.5)*34; pos[i*3+1]=(Math.random()-.5)*22; pos[i*3+2]=(Math.random()-.5)*20; }
      var geo = new THREE.BufferGeometry(); geo.setAttribute("position", new THREE.BufferAttribute(pos,3));
      var pts = new THREE.Points(geo, new THREE.PointsMaterial({color:0x5e5ce6, size:0.06, transparent:true, opacity:0.5}));
      scene.add(pts);
      var mx=0, my=0;
      window.addEventListener("pointermove", function(e){ mx=(e.clientX/window.innerWidth-.5); my=(e.clientY/window.innerHeight-.5); }, {passive:true});
      function resize(){ var w=window.innerWidth, h=window.innerHeight; renderer.setSize(w,h,false); camera.aspect=w/h; camera.updateProjectionMatrix(); }
      resize(); window.addEventListener("resize", resize);
      var t0=performance.now();
      (function loop(now){
        var t=(now-t0)/1000;
        ico.rotation.y = t*0.12; ico.rotation.x = t*0.05;
        pts.rotation.y = t*0.04;
        camera.position.x += (mx*3 - camera.position.x)*0.04;
        camera.position.y += (-my*2 - camera.position.y)*0.04;
        camera.lookAt(0,0,0);
        renderer.render(scene, camera);
        requestAnimationFrame(loop);
      })(t0);
    } catch(err){ /* fallback: the CSS gradient background stays */ }
  }
  if (document.readyState === "complete") startBG();
  else window.addEventListener("load", startBG);
})();
"""
