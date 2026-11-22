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
    return f"{len(touches)} touches. {replies} replies from {first}. One persona, start to finish."


def _monologue(text: str, limit: int = 520) -> str:
    sents = re.split(r"(?<=[.!?])\s+", " ".join(str(text).split()))
    pick = sents[1:6] if len(sents) > 4 else sents
    out = " ".join(pick)
    out = out if len(out) <= limit else out[: limit - 1].rsplit(" ", 1)[0] + "…"
    return ("… " if pick is not sents and len(sents) > 4 else "") + out


def render_home(states: list[dict], out_dir: Path, page: Callable[..., str], stats: dict, research_targets: list[str]) -> Path:
    st = _featured(states)
    if st is None:
        body = ("<section class='hm-hero'><h1 class='hm-h'>The agent that holds the conversation.</h1>"
                "<p class='hm-lede'>No runs yet. Start one with <span class='mono'>python -m revel8_agent.cli run --target julius</span>.</p></section>")
        out = out_dir / "index.html"
        out.write_text(page("revel8 agent", "", f"<style>{SCORE3D_CSS}{HOME_CSS}</style>{body}", False), encoding="utf-8")
        return out
    touches = _touch_model(st)
    t = st.get("target") or {}
    plan = st.get("plan") or {}
    persona = plan.get("persona") or {}
    rid = _e(st.get("run_id"))
    first = _first(t.get("name"))
    hit = next((x for x in touches if x["hit"]), None)
    when = str(st.get("started_at") or st.get("run_id", ""))[:10]
    if hit and hit["hit"] == "confirmed":
        proof = f"Incident confirmed by the revel8 API at touch {hit['n']}."
    elif hit:
        proof = (f"Incident at touch {hit['n']} is our judge's estimate from {first}'s own reply; the revel8 API has not "
                 "confirmed it.")
    else:
        proof = "No incident in this run."
    if st.get("status") == "error":
        proof += f" The run stopped early after touch {st.get('touches_used', len(touches))}."
    lede = (f"The agent researched {_e(t.get('name'))}, cast itself as {_e(persona.get('name') or 'a persona')} of "
            f"{_e(persona.get('organisation') or 'an invented organisation')}, and wrote every message by itself.")
    data = [{k: x[k] for k in ("n", "lane", "subject", "sender", "body", "reply", "sentiment", "hit", "hit_types", "events")} for x in touches]
    hero = (
        "<section class='hm-hero' id='play'>"
        "<div class='hm-top'><div class='hm-copy'>"
        f"<h1 class='hm-h'>{_e(_headline(st, touches))}</h1>"
        f"<p class='hm-lede'>{lede}</p>"
        "<div class='hm-cta'><button type='button' class='btn' id='hm-play' aria-pressed='false'>"
        "<svg class='svgi' viewBox='0 0 24 24' aria-hidden='true'><path id='hm-play-ic' d='M7 4.5v15l12-7.5z' fill='currentColor'/></svg>"
        "<span id='hm-play-l'>Play the conversation</span></button>"
        "<a class='more' href='runs.html'>See all runs</a></div>"
        f"<p class='hm-proof'>{_e(t.get('name'))}, {_e(t.get('role'))} · practice run {_e(when)} · {_e(proof)}</p></div>"
        "<div class='hm-convo' id='hm-convo' aria-live='polite'></div></div>"
        f"<div class='hm-score'>{score3d(st, interactive=True)}"
        "<div class='hm-ctl'><button type='button' id='hm-prev' aria-label='Previous touch'>"
        "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='m15 5-7 7 7 7' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/></svg></button>"
        "<span id='hm-pos' class='hm-pos'>Touch 1 of {n}</span>".replace("{n}", str(len(touches)))
        + "<button type='button' id='hm-next' aria-label='Next touch'>"
        "<svg viewBox='0 0 24 24' aria-hidden='true'><path d='m9 5 7 7-7 7' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/></svg></button>"
        f"<a class='more' href='replay.html#run={rid}&amp;t=0'>Open in Replay</a>"
        f"<a class='more' href='{rid}.html'>Read the full record</a></div></div>"
        f"<script type='application/json' id='hm-data'>{_json_for_script(data)}</script></section>")

    # 2. The agent's own reasoning on the decisive touch, next to its notebook.
    focus_n = hit["n"] if hit else touches[-1]["n"]
    step = next((s for s in _steps(st) if s.get("touch") == focus_n), {})
    mono = str((step.get("action") or {}).get("inner_monologue") or (step.get("action") or {}).get("rationale") or "")
    notes = [x for x in plan.get("notebook") or [] if int(x.get("touch") or 0) <= int(focus_n or 0)]
    notes_html = "".join(
        f"<li class='{'closed' if 'ROUTE CLOSED' in str(x.get('note')) else ''}'><span class='hm-nt'>"
        f"{'Before touch 1' if not x.get('touch') else 'After touch ' + str(x.get('touch'))}</span>{_e(x.get('note'))}</li>"
        for x in notes[-6:])
    mind = ("<section class='hm-sec'><h2 class='hm-h2'>It thinks before it writes.</h2>"
            f"<p class='hm-intro'>What the agent was thinking right before touch {_e(focus_n)}, and the notebook it keeps "
            "between touches. Nobody edited either.</p><div class='hm-mind'>"
            f"<figure class='hm-quote'><blockquote>{_e(_monologue(mono))}</blockquote>"
            f"<figcaption>Inner monologue, touch {_e(focus_n)} · excerpt</figcaption></figure>"
            f"<div class='hm-notes'><h3>Its notebook</h3><ol>{notes_html}</ol></div></div></section>") if mono else ""

    # 3. Every run, as identical scores, read in one sweep.
    rows = []
    for x in states:
        if not _steps(x):
            continue
        inc = _live(x)
        tx = x.get("target") or {}
        px = ((x.get("plan") or {}).get("persona") or {})
        if inc:
            conf = any(i.get("source") == "api event" for i in inc)
            first_n = min(i["touch"] for i in inc)
            outcome = (f"<span class='badge {'b-good' if conf else 'b-est'}'>{'Confirmed' if conf else 'Estimated'} incident · touch {first_n}</span>")
        else:
            outcome = "<span class='badge'>No incident</span>"
        if x.get("status") == "error":
            outcome += " <span class='badge b-warn'>Stopped early</span>"
        xid = _e(x.get("run_id"))
        rows.append(f"<a class='hm-run' href='{xid}.html'><div class='hm-run-meta'><h3>{_e(tx.get('name'))}</h3>"
                    f"<p>as {_e(px.get('name'))} · {_e(px.get('organisation'))}</p><div class='hm-run-out'>{outcome}</div>"
                    f"<span class='mono'>{xid}</span></div><div class='hm-run-score'>{score3d(x, compact=True)}</div></a>")
    runs = ("<section class='hm-sec'><h2 class='hm-h2'>Every run, side by side.</h2>"
            "<p class='hm-intro'>Each practice run as the same score: the agent's touches on top, the target's replies "
            "below, taller where the reply was warmer. Amber marks an incident.</p>"
            f"<div class='hm-runs'>{''.join(rows)}</div><p class='hm-after'><a class='more' href='runs.html'>All runs, in detail</a></p></section>")

    # 4. Honest numbers.
    bars = bars3d(stats["bars"])
    numbers = ("<section class='hm-sec'><h2 class='hm-h2'>Honest numbers.</h2><div class='hm-num'>"
               f"<div class='hm-facts'>{stats['sentences']}<p><a class='more' href='score.html'>The full scorecard</a></p></div>"
               f"<figure class='hm-bars'>{bars}<figcaption>Share of touches that got a reply or an answered call, per target.</figcaption></figure>"
               "</div></section>")

    # 5. How it works, then the close.
    stages = [("Research", "Public sources only. Every fact is checked against its source before the agent may use it."),
              ("Brief and memory", "The verified facts become hooks, and what worked against this target before is remembered."),
              ("Casting", "The agent invents one believable person, with a role, a deadline and one small ask."),
              ("Session", "It writes, sends, reads the reply and decides the next move, touch after touch, in character.")]
    how = ("<section class='hm-sec'><h2 class='hm-h2'>Four stages. No script.</h2><div class='hm-stages'>"
           + "".join(f"<div class='hm-stage'><h3>{_e(a)}</h3><p>{_e(b)}</p></div>" for a, b in stages)
           + "</div><p class='hm-after'><a class='more' href='how.html'>How the agent works</a>"
           + "".join(f" <a class='more' href='research-{_e(r)}.html'>Research on {_e(r.title())}</a>" for r in research_targets[:3])
           + "</p></section>")
    close = ("<section class='hm-close'><h2>No human in the loop.</h2><p>Every message on this page was written, sent and judged "
             "by the agent. We only pressed start.</p><a class='btn' href='#play' id='hm-replay'>Play it again</a></section>")
    body = f"<style>{SCORE3D_CSS}{HOME_CSS}</style>" + hero + mind + runs + numbers + how + close + f"<script>{HOME_JS}</script>"
    out = out_dir / "index.html"
    out.write_text(page("revel8 agent", "", body, False), encoding="utf-8")
    return out


HOME_CSS = """
.page{max-width:1240px;padding-top:72px}
.hm-hero{min-height:calc(100vh - 52px - 72px);display:flex;flex-direction:column;justify-content:space-between;gap:36px;margin-bottom:120px}
.hm-top{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,.85fr);gap:64px;align-items:start}
.hm-h{font:750 clamp(46px,6.4vw,92px)/.98 var(--display);letter-spacing:-.045em;margin:0;text-wrap:balance;max-width:12ch}
.hm-lede{font-size:clamp(19px,1.6vw,23px);line-height:1.4;color:var(--muted);margin:26px 0 0;max-width:40ch;text-wrap:pretty}
.hm-cta{display:flex;align-items:center;gap:28px;margin-top:34px;flex-wrap:wrap}
.hm-proof{font-size:13px;color:var(--muted);margin:26px 0 0;max-width:62ch;line-height:1.5}
.hm-convo{display:flex;flex-direction:column;gap:12px;min-height:420px;padding-top:8px}
.hm-meta{display:flex;align-items:center;gap:10px;font-size:13px;color:var(--muted);font-variant-numeric:tabular-nums}
.hm-meta b{color:var(--text);font-weight:650}
.hm-bub{border-radius:22px;padding:16px 20px;font-size:15px;line-height:1.55;white-space:pre-wrap;overflow-wrap:anywhere;
display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:9;overflow:hidden;animation:hmIn .6s var(--ease) both}
.hm-bub .who{display:block;font-size:12.5px;font-weight:650;margin-bottom:4px;white-space:normal}
.hm-bub.out{background:#1d1d1f;color:#f5f5f7;border-bottom-right-radius:8px;margin-left:36px}.hm-bub.out .who{color:#a1a1a6}
.hm-bub.in{background:var(--blue-bg);color:var(--text);border-bottom-left-radius:8px;margin-right:36px;-webkit-line-clamp:6;animation-delay:.25s}
.hm-bub.in .who{color:var(--blue-text)}
.hm-silent{font-size:14px;color:var(--muted);padding:6px 4px}
.hm-inc{align-self:flex-start;font-size:13px;font-weight:650;padding:6px 12px;border-radius:999px;background:var(--amber);color:#3d2000;animation:hmIn .6s var(--ease) .45s both}
.hm-inc.est{background:#fff;color:var(--amber-text);box-shadow:inset 0 0 0 1.5px var(--amber)}
@keyframes hmIn{from{opacity:0;transform:translateY(10px);filter:blur(4px)}}
.hm-score{position:relative}
.hm-ctl{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-top:6px;padding-left:150px}
.hm-ctl button{width:36px;height:36px;border-radius:50%;border:0;background:var(--surface-2);color:var(--text);cursor:pointer;display:grid;place-items:center}
.hm-ctl button:hover{background:#e8e8ed}.hm-ctl button svg{width:18px;height:18px}
.hm-ctl .more{font-size:14px;margin-left:14px}
.hm-pos{font-size:14px;font-weight:600;min-width:96px;text-align:center;font-variant-numeric:tabular-nums}
.hm-sec{padding:120px 0 0;border-top:1px solid var(--border);margin-top:0}
.hm-sec+.hm-sec{margin-top:120px}
.hm-h2{font:750 clamp(36px,4.4vw,60px)/1.02 var(--display);letter-spacing:-.04em;margin:0;max-width:16ch;text-wrap:balance}
.hm-intro{font-size:21px;line-height:1.42;color:var(--muted);margin:20px 0 64px;max-width:46ch}
.hm-after{margin:48px 0 0;display:flex;gap:28px;flex-wrap:wrap}
.hm-mind{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,.7fr);gap:80px;align-items:start}
.hm-quote{margin:0}.hm-quote blockquote{margin:0;padding:0;background:none;border:0;font:500 clamp(22px,2.2vw,30px)/1.38 var(--display);
letter-spacing:-.02em;color:var(--text);text-wrap:pretty}
.hm-quote figcaption{margin-top:22px;font-size:13px;color:var(--muted)}
.hm-notes h3{font-size:15px;margin:0 0 18px;color:var(--text)}
.hm-notes ol{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:18px}
.hm-notes li{font-size:14.5px;line-height:1.5;color:var(--text-2);padding-top:14px;border-top:1px solid var(--border)}
.hm-notes li.closed{color:var(--crit-text)}
.hm-nt{display:block;font-size:12px;font-weight:650;color:var(--muted);margin-bottom:3px}
.hm-runs{display:flex;flex-direction:column}
.hm-run{display:grid;grid-template-columns:minmax(0,280px) minmax(0,1fr);gap:48px;align-items:center;padding:30px 0;border-top:1px solid var(--border);
color:inherit;transition:background .3s}
.hm-run:hover{text-decoration:none}.hm-run:hover h3{color:var(--blue-text)}
.hm-run h3{margin:0;font-size:22px;letter-spacing:-.02em}.hm-run p{margin:4px 0 10px;color:var(--muted);font-size:14px}
.hm-run-out{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}
.hm-num{display:grid;grid-template-columns:minmax(0,.9fr) minmax(0,1.1fr);gap:72px;align-items:center}
.hm-facts p{font:600 clamp(22px,2.3vw,30px)/1.3 var(--display);letter-spacing:-.022em;margin:0 0 22px;color:var(--text)}
.hm-facts p span{color:var(--muted)}.hm-facts p:last-child{font:inherit;margin-top:36px}
.hm-bars{margin:0}.hm-bars figcaption{font-size:13px;color:var(--muted);text-align:center;margin-top:8px}
.hm-stages{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:40px}
.hm-stage{border-top:2px solid var(--text);padding-top:20px}
.hm-stage h3{margin:0 0 10px;font-size:21px}.hm-stage p{margin:0;color:var(--text-2);font-size:15px;line-height:1.55}
.hm-close{text-align:center;padding:180px 0 40px}
.hm-close h2{font:750 clamp(44px,6vw,84px)/1 var(--display);letter-spacing:-.045em;margin:0}
.hm-close p{font-size:21px;color:var(--muted);margin:22px auto 36px;max-width:40ch}
@media(max-width:980px){.hm-top,.hm-mind,.hm-num{grid-template-columns:minmax(0,1fr);gap:48px}.hm-stages{grid-template-columns:1fr 1fr}
.hm-hero{min-height:0}.hm-convo{min-height:0}}
@media(max-width:760px){.page{padding-top:40px}.hm-h{font-size:44px}.hm-ctl{padding-left:0}.hm-ctl .more{margin-left:0}
.hm-run{grid-template-columns:minmax(0,1fr);gap:8px}.hm-stages{grid-template-columns:minmax(0,1fr)}.hm-sec{padding-top:80px}
.hm-sec+.hm-sec{margin-top:80px}.hm-intro{font-size:18px;margin-bottom:40px}.hm-close{padding-top:120px}.hm-bub.out{margin-left:0}.hm-bub.in{margin-right:0}}
@media(prefers-reduced-motion:reduce){.hm-bub,.hm-inc{animation:none}}
"""

HOME_JS = r"""
(function(){
  "use strict";
  var T = JSON.parse(document.getElementById("hm-data").textContent || "[]");
  if (!T.length) return;
  var $ = function(id){ return document.getElementById(id); };
  var s3 = document.querySelector(".s3-live"), head = $("s3-head"), flag = $("s3-flag");
  var convo = $("hm-convo"), pos = $("hm-pos"), btn = $("hm-play"), lbl = $("hm-play-l"), ic = $("hm-play-ic");
  var blocks = Array.prototype.slice.call(s3.querySelectorAll(".blk"));
  var LANE = {email:"Email", phone_call:"Phone call", sms:"SMS", whatsapp:"WhatsApp", chat:"Chat", linkedin:"LinkedIn"};
  var cur = 0, timer = null;
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  function esc(s){ return String(s == null ? "" : s).replace(/[&<>"']/g, function(c){ return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]; }); }
  function show(i){
    cur = Math.max(0, Math.min(T.length - 1, i));
    var t = T[cur];
    head.style.setProperty("--c", cur);
    flag.textContent = "Touch " + t.n;
    pos.textContent = "Touch " + t.n + " of " + T.length;
    blocks.forEach(function(b){ var c = +b.style.getPropertyValue("--c"); b.classList.toggle("future", c > cur); });
    var h = "<div class='hm-meta'><b>Touch " + t.n + "</b><span>" + esc(LANE[t.lane] || t.lane) + "</span>" +
            (t.subject ? "<span>· " + esc(t.subject) + "</span>" : "") + "</div>";
    h += "<div class='hm-bub out'><span class='who'>" + esc(t.sender || "Agent") + "</span>" + esc(t.body) + "</div>";
    if (t.reply) h += "<div class='hm-bub in'><span class='who'>Reply</span>" + esc(t.reply) + "</div>";
    else h += "<div class='hm-silent'>" + (t.events.length ? esc(t.events.join(", ")) : "No reply.") + "</div>";
    if (t.hit) h += "<div class='hm-inc" + (t.hit === "estimated" ? " est" : "") + "'>" +
            (t.hit === "estimated" ? "Estimated incident · " : "Confirmed incident · ") + esc(t.hit_types.join(", ")) + "</div>";
    convo.innerHTML = h;
  }
  function stop(){ clearInterval(timer); timer = null; s3.classList.remove("playing"); btn.setAttribute("aria-pressed","false");
    lbl.textContent = "Play the conversation"; ic.setAttribute("d","M7 4.5v15l12-7.5z"); }
  function play(){
    if (timer) { stop(); return; }
    if (cur >= T.length - 1) show(0);
    s3.classList.add("playing"); btn.setAttribute("aria-pressed","true");
    lbl.textContent = "Pause"; ic.setAttribute("d","M7 5h3.5v14H7zM13.5 5H17v14h-3.5z");
    show(cur);
    timer = setInterval(function(){ if (cur >= T.length - 1) { stop(); return; } show(cur + 1); }, reduce ? 5200 : 4200);
  }
  btn.addEventListener("click", play);
  $("hm-prev").addEventListener("click", function(){ stop(); show(cur - 1); });
  $("hm-next").addEventListener("click", function(){ stop(); show(cur + 1); });
  var again = $("hm-replay");
  if (again) again.addEventListener("click", function(){ stop(); show(0); setTimeout(play, reduce ? 0 : 700); });
  blocks.forEach(function(b){ b.addEventListener("click", function(){ stop(); show(+b.style.getPropertyValue("--c")); }); });
  document.addEventListener("keydown", function(e){
    if (e.target.closest && e.target.closest("input,select,textarea")) return;
    if (e.key === "ArrowRight") { stop(); show(cur + 1); }
    else if (e.key === "ArrowLeft") { stop(); show(cur - 1); }
  });
  // the score turns a little with the pointer, like an object on a table
  if (!reduce) s3.addEventListener("pointermove", function(e){
    var r = s3.getBoundingClientRect(), x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5;
    s3.style.setProperty("--spin", (x * -5).toFixed(2) + "deg"); s3.style.setProperty("--tilt", (58 + y * 6).toFixed(2) + "deg");
  });
  s3.addEventListener("pointerleave", function(){ s3.style.removeProperty("--spin"); s3.style.removeProperty("--tilt"); });
  show(0);
})();
"""
