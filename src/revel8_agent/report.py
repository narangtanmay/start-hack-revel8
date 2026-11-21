"""Dashboard for agent runs: an overview page plus one page per run.

    python -m revel8_agent.cli report [--open]

Writes runs/index.html (overview) and runs/<run_id>.html (thread). Static files, no server, no
dependencies. Pages refresh themselves while a run is live. Light and dark themes follow the OS.
Series colours are the validated reference palette (blue / orange / violet, checked for colour-blind
separation in both modes); incidents use the reserved status green with an icon and a label.
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

from .engine import estimate_score

_CSS = """
:root{color-scheme:light;
--bg:#f6f6f4;--surface:#fcfcfb;--surface-2:#f0efec;--border:#e4e3df;--text:#0b0b0b;--text-2:#52514e;--muted:#8a8984;
--s1:#2a78d6;--s2:#eb6834;--s3:#6250d6;--good:#0ca30c;--good-bg:#e7f6e7;--good-text:#006300;--crit:#d03b3b;--crit-bg:#fbeaea;
--warn-bg:#fff4dc;--warn-text:#7a5300;--accent-bg:#eaf2fc;--radius:12px;--shadow:0 1px 2px rgba(16,16,15,.04),0 1px 1px rgba(16,16,15,.03)}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;
--bg:#111110;--surface:#1a1a19;--surface-2:#232321;--border:#2e2e2b;--text:#f0efec;--text-2:#c3c2b7;--muted:#8d8c85;
--s1:#3987e5;--s2:#d95926;--s3:#9085e9;--good:#0ca30c;--good-bg:#12301a;--good-text:#7fe09a;--crit:#d03b3b;--crit-bg:#3a1b1b;
--warn-bg:#3a2f12;--warn-text:#ffd27a;--accent-bg:#17263a;--shadow:none}}
*{box-sizing:border-box}html,body{margin:0}
body{font:14px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--text);
-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}a:hover{text-decoration:underline}
.nav{position:sticky;top:0;z-index:5;background:color-mix(in srgb,var(--surface) 88%,transparent);backdrop-filter:blur(8px);
border-bottom:1px solid var(--border)}
.nav-in{max-width:1240px;margin:0 auto;padding:14px 28px;display:flex;align-items:center;gap:14px}
.logo{width:26px;height:26px;border-radius:7px;background:var(--text);color:var(--surface);display:grid;place-items:center;font-weight:700;font-size:13px}
.brand{font-weight:650;letter-spacing:-.01em}.crumb{color:var(--muted)}.spacer{flex:1}
.live{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--text-2)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--s1);box-shadow:0 0 0 3px color-mix(in srgb,var(--s1) 25%,transparent)}
.page{max-width:1240px;margin:0 auto;padding:28px}
h1{font-size:24px;letter-spacing:-.02em;margin:0 0 4px;font-weight:650}
h2{font-size:13px;font-weight:600;margin:0 0 14px;color:var(--text-2)}
.sub{color:var(--text-2);margin:0 0 24px}
.grid{display:grid;gap:16px}.k4{grid-template-columns:repeat(4,1fr)}.split{grid-template-columns:minmax(0,1fr) 380px}
.side{grid-template-columns:340px minmax(0,1fr);align-items:start}
@media(max-width:960px){.k4{grid-template-columns:repeat(2,1fr)}.split,.side{grid-template-columns:1fr}}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:20px;box-shadow:var(--shadow)}
.tile .label{font-size:12px;color:var(--text-2);font-weight:500}
.tile .value{font-size:32px;font-weight:650;letter-spacing:-.02em;margin-top:6px;line-height:1.1}
.tile .value small{font-size:15px;color:var(--muted);font-weight:500}
.tile .foot{font-size:12px;color:var(--muted);margin-top:6px}
.badge{display:inline-flex;align-items:center;gap:5px;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600;white-space:nowrap;
background:var(--surface-2);color:var(--text-2)}
.b-good{background:var(--good-bg);color:var(--good-text)}.b-crit{background:var(--crit-bg);color:var(--crit)}
.b-live{background:var(--accent-bg);color:var(--s1)}.b-warn{background:var(--warn-bg);color:var(--warn-text)}
table{width:100%;border-collapse:collapse}
th{font-size:12px;font-weight:500;color:var(--muted);text-align:left;padding:0 12px 10px;border-bottom:1px solid var(--border)}
td{padding:12px;border-bottom:1px solid var(--border);vertical-align:middle}
tr:last-child td{border-bottom:0}tbody tr:hover{background:var(--surface-2)}
.num{text-align:right;font-variant-numeric:tabular-nums}
.strip{display:flex;gap:2px;align-items:center}
.cell{position:relative;width:14px;height:14px;border-radius:4px;border:1.5px solid var(--border);background:transparent}
.cell.c-reply{background:var(--s1);border-color:var(--s1)}.cell.c-event{background:var(--s2);border-color:var(--s2)}
.cell.c-call{background:var(--s3);border-color:var(--s3)}
.cell.c-hit{background:var(--good);border-color:var(--good);color:#fff;font-size:10px;line-height:11px;text-align:center;font-weight:800}
.cell.empty{border-style:dashed;opacity:.45}
[data-tip]:hover::after{content:attr(data-tip);position:absolute;left:50%;bottom:calc(100% + 8px);transform:translateX(-50%);
background:var(--text);color:var(--surface);padding:6px 9px;border-radius:7px;font-size:12px;font-weight:500;white-space:pre;z-index:9;
pointer-events:none;box-shadow:0 4px 14px rgba(0,0,0,.18)}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--text-2);margin-top:14px}
.legend span{display:inline-flex;align-items:center;gap:6px}
.legend .cell{width:12px;height:12px;display:inline-block}
.bars{display:flex;flex-direction:column;gap:14px}
.bar-row{display:grid;grid-template-columns:110px 1fr 54px;align-items:center;gap:12px}
.bar-name{font-size:13px;color:var(--text-2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.track{position:relative;height:22px}
.fill{position:absolute;left:0;top:3px;height:16px;border-radius:0 4px 4px 0;background:var(--s1);min-width:2px}
.track:hover .fill{filter:brightness(1.08)}
.bar-val{font-size:13px;font-variant-numeric:tabular-nums;text-align:right}
.axis{height:1px;background:var(--border);margin:4px 0 0 122px}
.kv{display:grid;grid-template-columns:96px 1fr;gap:8px 12px;font-size:13px}.kv dt{color:var(--muted)}.kv dd{margin:0}
.hooks{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px}
.hooks li{display:flex;gap:10px;align-items:flex-start;font-size:13px}
.hid{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;color:var(--muted);padding-top:2px;min-width:30px}
.hooks li.chosen{background:var(--accent-bg);margin:0 -10px;padding:6px 10px;border-radius:8px}
.facts{font-size:12.5px;color:var(--text-2);padding-left:18px;margin:8px 0 0}
details summary{cursor:pointer;font-size:13px;color:var(--text-2);list-style:none}details summary::before{content:"▸ ";color:var(--muted)}
details[open] summary::before{content:"▾ "}
.tl{position:relative;padding-left:44px}
.tl::before{content:"";position:absolute;left:15px;top:6px;bottom:6px;width:2px;background:var(--border);border-radius:2px}
.touch{position:relative;margin-bottom:22px}
.tn{position:absolute;left:-44px;top:0;width:32px;height:32px;border-radius:50%;background:var(--surface);border:2px solid var(--border);
display:grid;place-items:center;font-size:12px;font-weight:650;color:var(--text-2)}
.touch.hit .tn{background:var(--good);border-color:var(--good);color:#fff}
.touch.replied .tn{border-color:var(--s1);color:var(--s1)}
.thead{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:8px;min-height:32px}
.chan{font-weight:600}.why{font-size:13px;color:var(--text-2);background:var(--surface-2);border-radius:10px;padding:10px 12px;margin-bottom:10px}
.why b{color:var(--text);font-weight:600}
.msg{border:1px solid var(--border);border-radius:12px;overflow:hidden;background:var(--surface)}
.msg-h{padding:10px 14px;border-bottom:1px solid var(--border);font-size:12.5px;color:var(--text-2);display:flex;gap:6px;flex-wrap:wrap}
.msg-h b{color:var(--text);font-weight:600}
.msg-b{padding:14px;white-space:pre-wrap;word-wrap:break-word;font-size:13.5px}
.reply{margin:10px 0 0 28px;border:1px solid color-mix(in srgb,var(--s1) 35%,var(--border));background:var(--accent-bg);border-radius:12px;padding:12px 14px;
white-space:pre-wrap;font-size:13.5px}
.reply .who{font-size:12px;color:var(--s1);font-weight:600;margin-bottom:4px;white-space:normal}
.call{display:flex;flex-direction:column;gap:8px;padding:12px}
.line{max-width:82%;padding:9px 12px;border-radius:12px;font-size:13.5px}
.line.agent{align-self:flex-end;background:var(--surface-2)}.line.target{align-self:flex-start;background:var(--accent-bg)}
.line .who{font-size:11px;color:var(--muted);font-weight:600}
.evt{display:inline-flex;gap:6px;align-items:center;margin:10px 8px 0 28px;font-size:12px;padding:3px 10px;border-radius:999px;
background:color-mix(in srgb,var(--s2) 15%,transparent);color:var(--text)}
.evt::before{content:"";width:8px;height:8px;border-radius:2px;background:var(--s2)}
.silent{margin:8px 0 0 28px;font-size:12.5px;color:var(--muted)}
.incident{margin:10px 0 0 28px;display:flex;gap:10px;align-items:flex-start;background:var(--good-bg);color:var(--good-text);
border-radius:12px;padding:10px 14px;font-size:13px;font-weight:550}
.err{margin:10px 0 0 28px;background:var(--crit-bg);color:var(--crit);border-radius:12px;padding:10px 14px;font-size:13px}
.read{margin:8px 0 0 28px;font-size:12px;color:var(--muted)}
iframe{width:100%;border:0;display:block;background:#fff}
.frame{border-top:1px solid var(--border)}
.empty-state{padding:48px;text-align:center;color:var(--muted)}
.tabs{display:flex;gap:4px;margin-left:18px}.tabs a{padding:6px 10px;border-radius:8px;color:var(--text-2);font-size:13px}
.tabs a:hover{background:var(--surface-2);text-decoration:none}.tabs a.on{background:var(--surface-2);color:var(--text);font-weight:600}
.steps{margin:0;padding-left:20px;font-size:13.5px;display:flex;flex-direction:column;gap:6px}
.hook{border:1px solid var(--border);border-radius:10px;padding:12px 14px;margin-bottom:10px}
.hook-h{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.muted-p{color:var(--text-2);font-size:13px;margin:6px 0}
.evidence,.facts-list,.rejected,.hits{list-style:none;padding:0;margin:8px 0 0;display:flex;flex-direction:column;gap:10px;font-size:13px}
.facts-list li{display:flex;gap:10px}
blockquote{margin:6px 0 4px;padding:6px 10px;border-left:3px solid var(--s1);background:var(--surface-2);border-radius:0 8px 8px 0;
font-size:12.5px;color:var(--text-2)}
.q{border-top:1px solid var(--border);padding:10px 0}.q:first-of-type{border-top:0}.snip{font-size:12.5px;color:var(--text-2);margin-top:2px}
.hits a{font-weight:550}
.pipeline{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.loop{display:grid;grid-template-columns:repeat(7,1fr);gap:10px}
@media(max-width:1100px){.pipeline{grid-template-columns:1fr 1fr}.loop{grid-template-columns:1fr 1fr}}
.stage,.loop-step{position:relative;border:1px solid var(--border);border-radius:10px;padding:14px;font-size:13px;display:flex;gap:10px}
.loop-step{flex-direction:column;gap:4px}.stage p,.loop-step p{margin:4px 0;color:var(--text-2)}
.stage-n{flex:none;width:24px;height:24px;border-radius:50%;background:var(--accent-bg);color:var(--s1);display:grid;place-items:center;
font-weight:700;font-size:12px}
.det{margin:10px 0 0 28px;font-size:12.5px}.det summary{font-size:12.5px}
.det table td,.det table th{padding:6px 8px;font-size:12.5px}
.attempt{border-left:3px solid var(--crit);padding:4px 10px;margin:6px 0;background:var(--crit-bg);border-radius:0 8px 8px 0;color:var(--text)}
.attempt.ok{border-left-color:var(--good);background:var(--good-bg)}
.timing{display:inline-flex;gap:10px;margin-left:auto}
.toggle{display:inline-flex;align-items:center;gap:8px;font-size:12.5px;color:var(--text-2);cursor:pointer}
#why-toggle:not(:checked) ~ .tl .why,#why-toggle:not(:checked) ~ .tl .det{display:none}
.activity{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;line-height:1.6;white-space:pre-wrap;max-height:520px;
overflow:auto;background:var(--surface-2);border-radius:10px;padding:12px}
.activity .t{color:var(--muted)}
.wf{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px;font-size:13px}
.wf li{display:flex;gap:10px;align-items:flex-start}.wf .stage-n{width:20px;height:20px;font-size:11px}
.struck{text-decoration:line-through;opacity:.6}
.runid{white-space:nowrap}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;color:var(--muted)}
"""

_STATUS = {"done": ("b-good", "Done"), "error": ("b-crit", "Error"), "running": ("b-live", "Live"), "starting": ("b-live", "Starting")}


def _e(x: object) -> str:
    return escape("" if x is None else str(x))


_TARGETS: list[str] = []  # research pages that exist, for the nav


def _page(title: str, crumbs: str, body: str, live: bool, active: str = "") -> str:
    refresh = '<meta http-equiv="refresh" content="4">' if live else ""
    live_html = '<span class="live"><span class="dot"></span>Live · auto-refresh</span>' if live else ""
    tabs = [("index.html", "Overview"), ("score.html", "Score"), ("how.html", "How it works")] + [(f"research-{t}.html", f"Research · {t}") for t in _TARGETS]
    nav = "".join(f"<a href='{h}'{' class=on' if h == active else ''}>{_e(lbl)}</a>" for h, lbl in tabs)
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"{refresh}<title>{_e(title)}</title><style>{_CSS}</style></head><body>"
            f"<div class='nav'><div class='nav-in'><div class='logo'>r8</div><a class='brand' href='index.html'>revel8 agent</a>"
            f"<nav class='tabs'>{nav}</nav>{crumbs}<div class='spacer'></div>{live_html}</div></div><div class='page'>{body}</div></body></html>")


def _badge(status: str) -> str:
    cls, label = _STATUS.get(status, ("", status or "—"))
    return f"<span class='badge {cls}'>{_e(label)}</span>"


def _touch_outcomes(state: dict) -> list[tuple[str, str]]:
    """One (class, tooltip) per touch, used by the strip on both pages."""
    hits = {i["touch"] for i in state.get("incidents", [])}
    out = []
    for s in state.get("steps", []):
        a = s.get("action") or {}
        if a.get("decision") == "STOP":
            continue
        evs = s.get("events") or []
        n = s.get("touch")
        chan = a.get("channel", "")
        if n in hits:
            out.append(("c-hit", f"Touch {n} · {chan}\nIncident"))
        elif any(e.get("type") == "reply" for e in evs):
            out.append(("c-reply", f"Touch {n} · {chan}\nReplied"))
        elif a.get("kind") == "call" and s.get("transcript"):
            out.append(("c-call", f"Touch {n} · {chan}\nCall answered"))
        elif evs:
            out.append(("c-event", f"Touch {n} · {chan}\n" + ", ".join(sorted({e.get('type', '') for e in evs}))))
        elif s.get("error"):
            out.append(("", f"Touch {n} · {chan}\nAPI error"))
        else:
            out.append(("", f"Touch {n} · {chan}\nNo reaction"))
    return out


def _strip(state: dict, slots: int) -> str:
    cells = []
    for cls, tip in _touch_outcomes(state):
        mark = "✓" if cls == "c-hit" else ""
        cells.append(f"<span class='cell {cls}' data-tip='{_e(tip)}'>{mark}</span>")
    cells += ["<span class='cell empty'></span>"] * max(0, slots - len(cells))
    return f"<div class='strip' role='img' aria-label='touch outcomes'>{''.join(cells)}</div>"


_LEGEND = ("<div class='legend'><span><i class='cell c-reply'></i>Replied</span><span><i class='cell c-call'></i>Call answered</span>"
           "<span><i class='cell c-event'></i>Link / file / page event</span><span><i class='cell'></i>No reaction</span>"
           "<span><i class='cell c-hit'>✓</i>Incident</span></div>")


# --------------------------------------------------------------------------- run page


def _tile(label: str, value: str, foot: str = "") -> str:
    return f"<div class='card tile'><div class='label'>{label}</div><div class='value'>{value}</div><div class='foot'>{foot}</div></div>"


def _run_tiles(state: dict) -> str:
    sc = estimate_score(state)
    steps = [s for s in state.get("steps", []) if (s.get("action") or {}).get("decision") != "STOP"]
    replies = sum(1 for s in steps if any(e.get("type") == "reply" for e in s.get("events") or []))
    if sc["incident"]:
        outcome = (f"<span style='color:var(--good-text)'>✓ {_e(', '.join(sc['incident_types']))}</span>",
                   f"first at touch {sc['first_incident_touch']}" + ("" if sc["confirmed_by_api_event"] else " · judged"))
    elif state.get("status") in ("running", "starting"):
        outcome = ("<span style='color:var(--s1)'>Running</span>", "waiting for the target")
    else:
        outcome = ("<span style='color:var(--muted)'>None</span>", "no incident in this run")
    return ("<div class='grid k4' style='margin-bottom:20px'>"
            + _tile("Incident", outcome[0], outcome[1])
            + _tile("Est. results points", f"{sc['results_points']:g}<small> / 25</small>", "incident 20 + speed 5, this run only")
            + _tile("Touches", f"{state.get('touches_used', 0)}<small> / {_e(state.get('config', {}).get('max_touches'))}</small>",
                    f"{replies} with a reply")
            + _tile("LLM calls", _e(state.get("llm_calls", 0)), "planning, decisions, judging")
            + "</div>")


def _plan_card(state: dict) -> str:
    plan = state.get("plan") or {}
    if not plan:
        return "<div class='card'><h2>Campaign</h2><div class='mono'>planning…</div></div>"
    p = plan.get("persona") or {}
    return ("<div class='card'><h2>Campaign</h2><dl class='kv'>"
            f"<dt>Objective</dt><dd><span class='badge'>{_e(plan.get('objective'))}</span></dd>"
            f"<dt>Pretext</dt><dd>{_e(plan.get('pretext'))}</dd>"
            f"<dt>Persona</dt><dd><b>{_e(p.get('name'))}</b><br>{_e(p.get('role'))}<br>{_e(p.get('organisation'))}</dd>"
            f"<dt>Contact</dt><dd class='mono'>{_e(p.get('email'))}<br>{_e(p.get('phone'))}</dd>"
            f"<dt>Language</dt><dd>{_e(plan.get('language'))}</dd></dl>"
            f"<details style='margin-top:14px'><summary>Planned sequence & rationale</summary><ol style='font-size:13px;padding-left:18px'>"
            + "".join(f"<li>{_e(s.get('channel'))} — {_e(s.get('purpose'))}</li>" for s in plan.get("sequence") or [])
            + f"</ol><p style='font-size:13px;color:var(--text-2)'>{_e(plan.get('rationale'))}</p></details></div>")


def _research_card(state: dict) -> str:
    brief = state.get("brief") or {}
    if not brief:
        return ""
    chosen = (state.get("plan") or {}).get("hook_id")
    used = {(s.get("action") or {}).get("hook_id") for s in state.get("steps", [])}
    items = []
    for h in brief.get("hooks", []):
        tags = []
        if h.get("is_own_angle"):
            tags.append("<span class='badge b-warn'>own angle</span>")
        if str(h.get("timing", "")).startswith("PAST"):
            tags.append("<span class='badge'>past</span>")
        if h["id"] in used:
            tags.append("<span class='badge b-live'>used</span>")
        items.append(f"<li class='{'chosen' if h['id'] == chosen else ''}'><span class='hid'>{_e(h['id'])}</span>"
                     f"<span>{_e(h['topic'])}<br>{' '.join(tags)} <span class='mono'>{h.get('confidence', 0):.2f}</span></span></li>")
    facts = "".join(f"<li>{_e(f['fact'])} <span class='mono'>{_e(f.get('timing', ''))}</span></li>" for f in brief.get("facts", []))
    return (f"<div class='card'><h2>Research · hooks</h2><ul class='hooks'>{''.join(items)}</ul>"
            f"<details style='margin-top:14px'><summary>{len(brief.get('facts', []))} verified facts in the brief</summary>"
            f"<ul class='facts'>{facts}</ul></details></div>")


def _is_html(body: str) -> bool:
    b = body.lstrip().lower()
    return b.startswith("<!doctype") or b.startswith("<html")


_REDACT = False  # public snapshots: landing pages listed (URL + fields), never rendered
_FACTS: dict[str, dict[str, dict]] = {}  # target id -> fact id -> fact (from dossiers/), for cited-fact lookups


def _secs(x: object) -> str:
    return f"{x:g} s" if isinstance(x, (int, float)) else "—"


def _details(step: dict, a: dict, target_id: str, hooks: dict) -> str:
    """Everything behind one touch: full decision, cited evidence, gate attempts, judge, timings, API ids."""
    facts = _FACTS.get(target_id, {})
    rows = [("Decision", f"<span class='badge'>{_e(a.get('decision'))}</span> {_e(a.get('kind'))} via {_e(a.get('channel'))}"),
            ("Objective", _e(a.get("objective"))),
            ("Hook", f"<b>{_e(a.get('hook_id'))}</b> {_e((hooks.get(a.get('hook_id')) or {}).get('topic'))}")]
    if a.get("discarded"):
        rows.append(("Discarded", "<br>".join(_e(x) for x in a["discarded"])))
    if a.get("call_goal"):
        rows.append(("Call goal", _e(a["call_goal"])))
    if a.get("link"):
        lk = a["link"] if isinstance(a["link"], dict) else {"url": a["link"]}
        rows.append(("Link", f"<span class='mono'>{_e(lk.get('url'))}</span> · page type {_e(lk.get('page_type'))}"))
    if a.get("attachment_filename"):
        rows.append(("Attachment", _e(a["attachment_filename"])))
    if a.get("format"):
        rows.append(("Email format", _e(a["format"])))
    cited = []
    for fid in a.get("cited_fact_ids") or []:
        f = facts.get(fid)
        if f:
            cited.append(f"<div><b>[{_e(fid)}]</b> {_e(f['fact'])}<blockquote>“{_e(f['verbatim_quote'])}”</blockquote>"
                         f"<a class='mono' href='{_e(f['source_url'])}' target='_blank' rel='noopener noreferrer'>{_e(f['source_url'])}</a></div>")
        else:
            cited.append(f"<div class='mono'>[{_e(fid)}] (not in the current dossier)</div>")
    rows.append(("Facts used", "".join(cited) or "<span class='mono'>none cited</span>"))
    att = step.get("attempts") or []
    if att:
        items = []
        for x in att:
            ok = not x.get("errors")
            items.append(f"<div class='attempt {'ok' if ok else ''}'><b>Draft {x.get('try')}</b> · {_e(x.get('decision'))} "
                         f"{_e(x.get('kind'))} via {_e(x.get('channel'))}"
                         + (" — <b>passed the gate</b>" if ok else "<br>Rejected: " + _e("; ".join(x.get("errors") or [])))
                         + "</div>")
        rows.append(("Gate", "".join(items)))
    else:
        rows.append(("Gate", "<span class='mono'>passed (draft attempts were not recorded for runs before this dashboard)</span>"))
    j = step.get("judge") or {}
    if j:
        flags = []
        if "disclosure" in j:
            flags.append(f"disclosure: <b>{'yes' if j.get('disclosure') else 'no'}</b>")
        if "action" in j:
            flags.append(f"action: <b>{'yes' if j.get('action') else 'no'}</b>")
        ev = j.get("evidence")
        ev_html = (f"<blockquote>“{_e(ev)}”</blockquote><span class='mono'>evidence "
                   f"{'verified verbatim in their words' if j.get('evidence_verified') else 'NOT found verbatim, so ignored'}</span>"
                   if ev else "")
        rows.append(("Judge", f"read as <b>{_e(j.get('sentiment'))}</b>. {' · '.join(flags)}<br>{_e(j.get('reason'))}{ev_html}"))
    tm = step.get("timing") or {}
    if tm:
        rows.append(("Timing", f"decide {_secs(tm.get('decide_s'))} · send + target's reaction {_secs(tm.get('send_s'))} · "
                               f"judge {_secs(tm.get('judge_s'))}"))
    ids = " · ".join(x for x in (f"message {step.get('message_id')}" if step.get("message_id") else "",
                                 f"conversation {step.get('conversation_id')}" if step.get("conversation_id") else "",
                                 f"sent {str(step.get('at', ''))[11:19]} UTC") if x)
    rows.append(("API", f"<span class='mono'>{_e(ids)}</span>"))
    table = "".join(f"<tr><th style='width:120px;vertical-align:top'>{k}</th><td>{v}</td></tr>" for k, v in rows)
    return f"<details class='det'><summary>Full decision record · touch {_e(step.get('touch'))}</summary><table>{table}</table></details>"


def _touch(step: dict, incidents: list[dict], target_id: str = "", hooks: dict | None = None) -> str:
    a = step.get("action") or {}
    n = step.get("touch")
    hit = [i for i in incidents if i["touch"] == n and not i.get("superseded")]
    old = [i for i in incidents if i["touch"] == n and i.get("superseded")]
    evs = step.get("events") or []
    replied = any(e.get("type") == "reply" for e in evs)
    cls = "hit" if hit else ("replied" if replied else "")
    snd = a.get("sender") or {}
    out = [f"<div class='touch {cls}'><div class='tn'>{'✓' if hit else _e(n)}</div>"]
    if a.get("decision") == "STOP":
        out.append(f"<div class='thead'><span class='badge'>STOP</span></div><div class='why'>{_e(a.get('rationale'))}</div></div>")
        return "".join(out)
    icon = "📞" if a.get("kind") == "call" else ("✉️" if a.get("channel") == "email" else "💬")
    tm = step.get("timing") or {}
    total = sum(v for v in tm.values() if isinstance(v, (int, float)))
    tm_html = f"<span class='timing mono'>{_secs(round(total, 1))}</span>" if tm else ""
    out.append(f"<div class='thead'><span class='chan'>{icon} {_e(a.get('channel'))}</span><span class='badge'>{_e(a.get('decision'))}</span>"
               f"<span class='badge'>{_e(a.get('objective'))}</span><span class='mono'>hook {_e(a.get('hook_id'))}</span>{tm_html}</div>")
    out.append(f"<div class='why'><b>Read:</b> {_e(a.get('assessment'))}<br><b>Move:</b> {_e(a.get('rationale'))}</div>")
    if a.get("kind") == "call" and step.get("transcript") is not None:
        lines = "".join(f"<div class='line {'agent' if t['who'] == 'agent' else 'target'}'><div class='who'>"
                        f"{'Agent' if t['who'] == 'agent' else 'Target'}</div>{_e(t['text'])}</div>" for t in step["transcript"])
        out.append(f"<div class='msg'><div class='msg-h'>Call from <b>{_e(snd.get('name'))}</b> {_e(snd.get('address'))} · goal: "
                   f"{_e(a.get('call_goal'))}</div><div class='call'>{lines}</div></div>")
    else:
        payload = step.get("payload") or {}
        head = [f"From <b>{_e(snd.get('name'))}</b> &lt;{_e(snd.get('address'))}&gt;"]
        if payload.get("subject"):
            head.append(f"· <b>{_e(payload['subject'])}</b>")
        if a.get("attachment_filename"):
            head.append(f"· 📎 {_e(a['attachment_filename'])}")
        body = str(payload.get("body") or "")
        content = (f"<div class='frame'><iframe sandbox='' style='height:480px' srcdoc='{_e(body)}'></iframe></div>"
                   if _is_html(body) else f"<div class='msg-b'>{_e(body)}</div>")
        page = step.get("page")
        page_html = ""
        if page:
            page_html = (f"<details style='padding:10px 14px;border-top:1px solid var(--border)'><summary>Landing page "
                         f"<span class='mono'>{_e(page.get('url'))}</span></summary>")
            if _REDACT:
                page_html += (f"<div class='mono' style='margin-top:8px'>title: {_e(page.get('title'))} · fields: "
                              f"{_e(', '.join(page.get('fields') or []))} · not rendered in the public snapshot</div>")
            elif page.get("html"):
                page_html += f"<div class='frame' style='margin-top:10px'><iframe sandbox='' style='height:520px' srcdoc='{_e(page['html'])}'></iframe></div>"
            page_html += "</details>"
        out.append(f"<div class='msg'><div class='msg-h'>{' '.join(head)}</div>{content}{page_html}</div>")
    for e in evs:
        if e.get("type") == "reply":
            subj = f" · {_e(e.get('subject'))}" if e.get("subject") else ""
            out.append(f"<div class='reply'><div class='who'>Target replied via {_e(e.get('channel'))}{subj}</div>{_e(e.get('body'))}</div>")
        else:
            out.append(f"<span class='evt'>{_e(e.get('type'))} {_e(e.get('url') or e.get('filename') or e.get('fields') or '')}</span>")
    if not evs and not step.get("transcript") and not step.get("error"):
        out.append("<div class='silent'>No reaction (the target ignored it)</div>")
    if step.get("error"):
        out.append(f"<div class='err'>API error: {_e(step['error'])}</div>")
    j = step.get("judge")
    if j and j.get("sentiment") not in (None, "silent"):
        out.append(f"<div class='read'>Agent read this as <b>{_e(j.get('sentiment'))}</b> — {_e(j.get('reason'))}</div>")
    for i in hit:
        out.append(f"<div class='incident'>✓ Incident · {_e(i['type'])}<span style='font-weight:400'>{_e(i['detail'])} "
                   f"({_e(i['source'])})</span></div>")
    for i in old:
        out.append(f"<div class='err' style='background:var(--surface-2);color:var(--text-2)'><span class='struck'>Incident · {_e(i['type'])}: "
                   f"{_e(i['detail'])}</span><br>Withdrawn: {_e(i.get('superseded_reason', 're-judged with the stricter judge'))}</div>")
    out.append(_details(step, a, target_id, hooks or {}))
    out.append("</div>")
    return "".join(out)


def _workflow_card(state: dict) -> str:
    """What happened in this run, in order, before and during the touches."""
    t = state.get("target", {})
    brief = state.get("brief") or {}
    items = [f"<li><span class='stage-n'>1</span><div><b>Research loaded</b> — verified dossier for {_e(t.get('name'))} "
             f"(<a href='research-{_e(t.get('id'))}.html'>see how it was built</a>); a brief of "
             f"{len(brief.get('facts', []))} facts and {len(brief.get('hooks', []))} hooks goes to the planner.</div></li>"]
    for x in state.get("plan_attempts") or []:
        if x.get("rejected"):
            items.append(f"<li><span class='stage-n'>2</span><div><b>Plan rejected</b> — persona domain "
                         f"<span class='mono'>{_e(x.get('domain'))}</span>: {_e(x.get('rejected'))}</div></li>")
    plan = state.get("plan") or {}
    p = plan.get("persona") or {}
    if plan:
        items.append(f"<li><span class='stage-n'>2</span><div><b>Campaign planned</b> — hook {_e(plan.get('hook_id'))}, objective "
                     f"{_e(plan.get('objective'))}, persona {_e(p.get('name'))} ({_e(p.get('organisation'))}, "
                     f"<span class='mono'>{_e(p.get('website_domain'))}</span>, checked: not registered in DNS)</div></li>")
    if state.get("session_id"):
        items.append(f"<li><span class='stage-n'>3</span><div><b>Session opened</b> <span class='mono'>{_e(state['session_id'])}</span> — "
                     f"the target remembers every contact in it</div></li>")
    steps = [s for s in state.get("steps", []) if (s.get("action") or {}).get("decision") != "STOP"]
    if steps:
        replies = sum(1 for s in steps if any(e.get("type") == "reply" for e in s.get("events") or []))
        recorded = any(s.get("attempts") for s in steps)
        rejected = sum(1 for s in steps for x in s.get("attempts") or [] if x.get("errors"))
        calls = sum(1 for s in steps if (s.get("action") or {}).get("kind") == "call")
        gate = (f"{rejected} drafts rejected by the gate and rewritten" if recorded
                else "gate rejections not recorded for this older run")
        items.append(f"<li><span class='stage-n'>4</span><div><b>{len(steps)} touches</b> — {replies} replies, {calls} calls, "
                     f"{gate}</div></li>")
    live_inc = [i for i in state.get("incidents", []) if not i.get("superseded")]
    if live_inc:
        end = f"incident at touch {live_inc[0]['touch']} ({_e(live_inc[0]['type'])})"
    elif state.get("error"):
        end = "stopped by an error: " + _e(state.get("error"))
    else:
        end = "no incident; the touch budget was used or the agent stopped on its last touch"
    if state.get("status") in ("done", "error"):
        items.append(f"<li><span class='stage-n'>5</span><div><b>Run ended</b> — {end}</div></li>")
    return f"<div class='card'><h2>Workflow of this run</h2><ul class='wf'>{''.join(items)}</ul></div>"


def _activity_card(state: dict) -> str:
    act = state.get("activity") or []
    if not act:
        return ""
    lines = "\n".join(f"<span class='t'>{_e(str(x.get('at', ''))[11:19])}</span>  {_e(x.get('line'))}" for x in act)
    return (f"<div class='card' style='margin-top:20px'><details><summary><b>Full agent log</b> "
            f"<span class='mono'>· {len(act)} lines, exactly as printed while it ran</span></summary>"
            f"<div class='activity' style='margin-top:12px'>{lines}</div></details></div>")


def render_run(path: Path, out_dir: Path | None = None) -> Path:
    state = json.loads(path.read_text(encoding="utf-8"))
    t = state.get("target", {})
    live = state.get("status") in ("starting", "running")
    cfg = state.get("config", {})
    head = (f"<div style='display:flex;gap:12px;align-items:center;flex-wrap:wrap'><h1>{_e(t.get('name'))}</h1>{_badge(state.get('status', ''))}</div>"
            f"<p class='sub'>{_e(t.get('role'))} · scenario {_e(cfg.get('scenario_id'))} · session "
            f"<span class='mono'>{_e(state.get('session_id'))}</span> · started {_e(str(state.get('started_at', ''))[:16].replace('T', ' '))}</p>")
    error = f"<div class='card' style='border-color:var(--crit);margin-bottom:16px'><h2>Run error</h2>{_e(state['error'])}</div>" if state.get("error") else ""
    hooks = {h["id"]: h for h in (state.get("brief") or {}).get("hooks", [])}
    steps = "".join(_touch(s, state.get("incidents", []), t.get("id", ""), hooks) for s in state.get("steps", []))
    thread = (f"<div class='card'><div style='display:flex;align-items:center;gap:14px;margin-bottom:12px;flex-wrap:wrap'><h2 style='margin:0'>Thread</h2>"
              f"<div class='spacer' style='flex:1'></div>{_strip(state, int(cfg.get('max_touches') or 10))}</div>"
              "<input type='checkbox' id='why-toggle' checked hidden><label class='toggle' for='why-toggle'>"
              "<span class='badge'>⇄</span> Click to switch between the full record (agent reasoning + decision records) "
              "and the conversation only</label>"
              f"<div class='tl' style='margin-top:16px'>{steps or '<div class=empty-state>Planning the campaign…</div>'}</div>{_LEGEND}</div>")
    body = (head + error + _run_tiles(state)
            + f"<div class='grid side'><div class='grid'>{_workflow_card(state)}{_plan_card(state)}{_research_card(state)}</div>{thread}</div>"
            + _activity_card(state))
    out = (out_dir or path.parent) / path.with_suffix(".html").name
    crumbs = f"<span class='crumb'>/</span><span class='crumb'>{_e(state.get('run_id'))}</span>"
    out.write_text(_page(f"{t.get('name')} · revel8 agent", crumbs, body, live), encoding="utf-8")
    return out


# --------------------------------------------------------------------------- overview


def _load(runs_dir: Path) -> list[tuple[Path, dict]]:
    out = []
    for f in sorted(runs_dir.glob("*.json"), reverse=True):
        try:
            out.append((f, json.loads(f.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    return out


def _reply_bars(runs: list[dict]) -> str:
    per: dict[str, list[int]] = {}
    for st in runs:
        name = st.get("target", {}).get("name") or st.get("target", {}).get("id", "?")
        steps = [s for s in st.get("steps", []) if (s.get("action") or {}).get("decision") != "STOP" and not s.get("error")]
        r = sum(1 for s in steps if any(e.get("type") == "reply" for e in s.get("events") or []) or
                (s.get("action") or {}).get("kind") == "call" and len(s.get("transcript") or []) > 1)
        agg = per.setdefault(name, [0, 0])
        agg[0] += r
        agg[1] += len(steps)
    if not per:
        return "<div class='empty-state'>No runs yet</div>"
    rows = []
    for name, (r, n) in sorted(per.items(), key=lambda kv: -(kv[1][0] / kv[1][1] if kv[1][1] else 0)):
        pct = 100 * r / n if n else 0
        rows.append(f"<div class='bar-row'><div class='bar-name'>{_e(name)}</div><div class='track' data-tip='{_e(name)}\n{r} of {n} touches got a response'>"
                    f"<div class='fill' style='width:{pct:.1f}%'></div></div><div class='bar-val'>{pct:.0f}%</div></div>")
    return f"<div class='bars'>{''.join(rows)}</div><div class='axis'></div>"


def _bar(value: float, maximum: float) -> str:
    pct = 0 if maximum <= 0 else max(0.0, min(100.0, 100 * value / maximum))
    return (f"<div style='height:8px;border-radius:4px;background:var(--surface-2);overflow:hidden'>"
            f"<div style='width:{pct:.1f}%;height:100%;background:var(--s1)'></div></div>")


def render_score(states: list[dict], out_dir: Path) -> Path:
    """score.html: the rubric, with every part we can observe in practice projected and the rest marked."""
    from .scorecard import RUBRIC, compute

    sc = compute(states)
    a, c = sc["views"]["all"], sc["views"]["confirmed"]
    contacts = ", ".join("—" if x is None else str(x) for x in a["last3"]["contacts"]) or "—"
    tiles = ("<div class='grid k4' style='margin-bottom:20px'>"
             + _tile("Expected results", f"{a['expected']['total']:g}<small> / 25</small>",
                     f"any 3 runs like practice · API-confirmed only: {c['expected']['total']:g}")
             + _tile("Last 3 runs", f"{a['last3']['total']:g}<small> / 25</small>", f"contacts to first incident: {contacts}")
             + _tile("Runs with an incident", f"{a['incident_runs']}<small> / {sc['runs']}</small>",
                     f"{100 * a['incident_rate']:.0f}% · {c['incident_runs']} API-confirmed")
             + _tile("Median contacts to incident", _e(a["median_contacts_when_reached"] if a["median_contacts_when_reached"] is not None else "—"),
                     f"speed vs. a best team needing {sc['best_contacts']:g}")
             + "</div>")

    observed = {"results": (a["expected"]["total"], f"expected · incidents {a['expected']['incidents']:g} + speed {a['expected']['speed']:g}")}
    rows = []
    for key, label, pts, how in RUBRIC:
        if key in observed:
            val, note = observed[key]
            cell = f"<b>{val:g}</b><span class='mono'> / {pts}</span>"
            bar = _bar(val, pts)
        else:
            note = {"targeting": "Not visible in practice: the target notes topic hits privately; the eval reports them.",
                    "craft": "Not visible in practice: mails and pages are rendered and rated only in eval runs.",
                    }.get(key, "Judged by the jury after the pitches.")
            cell = f"<span class='mono'>— / {pts}</span>"
            bar = _bar(0, pts)
        rows.append(f"<tr><td><b>{_e(label)}</b><div class='mono'>{_e(how)}</div></td><td style='min-width:160px'>{bar}</td>"
                    f"<td class='num' style='white-space:nowrap'>{cell}</td><td style='font-size:13px;color:var(--text-2)'>{_e(note)}</td></tr>")
    rubric = ("<div class='card' style='margin-bottom:20px'><h2>Rubric · 100 points</h2><table><thead><tr><th>Part</th><th></th>"
              "<th class='num'>Points</th><th>Where it comes from</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")

    trows = []
    for tid, r in sc["per_target"].items():
        med = r["median_first_contact"]
        trows.append(f"<tr><td><b>{_e(r['name'])}</b><div class='mono'>{_e(tid)}</div></td><td class='num'>{r['runs']}</td>"
                     f"<td class='num'>{r['incident_runs']}<span class='mono'> ({r['confirmed_runs']} confirmed)</span></td>"
                     f"<td class='num'>{_e(med if med is not None else '—')}</td><td class='num'>{100 * r['reply_rate']:.0f}%</td></tr>")
    targets = ("<div class='card' style='margin-bottom:20px'><h2>Per target</h2>" + (
        "<table><thead><tr><th>Target</th><th class='num'>Runs</th><th class='num'>Runs with incident</th>"
        "<th class='num'>Median first contact</th><th class='num'>Reply rate</th></tr></thead><tbody>" + "".join(trows)
        + "</tbody></table>" if trows else "<div class='empty-state'>No finished runs yet.</div>") + "</div>")

    method = ("<div class='card'><h2>How this is computed</h2><p style='font-size:13px;color:var(--text-2);margin:0'>"
              f"Only finished practice runs with at least one touch count ({sc['runs']} of {sc['runs_total']}). "
              "The eval scores 3 runs: 20 × runs with an incident ÷ 3, plus 5 × best contacts ÷ your median contacts to the "
              "first incident, where a run without an incident counts as not reached. <b>Expected</b> averages that formula "
              "over every possible draw of 3 runs from practice (exact, closed form). <b>Last 3</b> applies it to the three "
              "most recent runs. An incident is a submitted landing page or an opened attachment (API-confirmed), or a "
              "disclosure/action judged from the target's own words (an estimate; withdrawn ones never count). "
              "Practice is not scored by revel8, so this is a projection, not a result.</p></div>")

    body = ("<h1>Score</h1><p class='sub'>What the 3 eval runs would likely score if they go like practice so far.</p>"
            + tiles + rubric + targets + method)
    out = out_dir / "score.html"
    out.write_text(_page("revel8 agent · score", "", body, False, active="score.html"), encoding="utf-8")
    return out


def render_index(runs_dir: Path = Path("runs"), out_dir: Path | None = None, public: bool = False,
                 dossiers_dir: Path = Path("dossiers")) -> Path:
    """Render the whole dashboard into runs_dir (default) or out_dir; public=True redacts landing pages."""
    from .report_pages import load_research, render_how, render_research

    global _REDACT
    _REDACT = public
    runs_dir.mkdir(parents=True, exist_ok=True)
    out_dir = out_dir or runs_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    loaded = _load(runs_dir)
    states = [st for _, st in loaded]

    _TARGETS.clear()
    _FACTS.clear()
    researched = []
    for dpath in sorted(dossiers_dir.glob("*.json")):
        if dpath.name.endswith(".stats.json"):
            continue
        research = load_research(dpath.stem, dossiers_dir)
        if research:
            _TARGETS.append(dpath.stem)
            _FACTS[dpath.stem] = {f["id"]: f for f in research["dossier"].get("facts", [])}
            researched.append((dpath.stem, research))
    for tid, research in researched:
        render_research(tid, out_dir, lambda *a, _t=tid: _page(*a, active=f"research-{_t}.html"), research)
    render_how(out_dir, lambda *a: _page(*a, active="how.html"), states, _TARGETS)
    render_score(states, out_dir)

    for f, _ in loaded:
        render_run(f, out_dir)
    scores = [estimate_score(st) for st in states]
    n = len(states)
    hits = sum(sc["incident"] for sc in scores)
    firsts = sorted(sc["first_incident_touch"] for sc in scores if sc["incident"])
    median = firsts[len(firsts) // 2] if firsts else None
    touches = sum(st.get("touches_used", 0) for st in states)
    replies = sum(1 for st in states for s in st.get("steps", []) for e in s.get("events") or [] if e.get("type") == "reply")
    live = any(st.get("status") in ("starting", "running") for st in states)
    withdrawn = sum(1 for st in states for i in st.get("incidents", []) if i.get("superseded"))

    tiles = ("<div class='grid k4' style='margin-bottom:20px'>"
             + _tile("Runs", str(n), f"{sum(st.get('status') == 'done' for st in states)} finished")
             + _tile("Runs with an incident", f"{hits}<small> / {n}</small>",
                     f"{(100 * hits / n if n else 0):.0f}% · est. {(20 * hits / n if n else 0):.1f} of 20 incident pts"
                     + (f" · {withdrawn} withdrawn" if withdrawn else ""))
             + _tile("Median touches to incident", _e(median if median is not None else "—"), "fewer is better (speed, 5 pts)")
             + _tile("Replies", str(replies), f"across {touches} touches")
             + "</div>")

    rows = []
    for (f, st), sc in zip(loaded, scores):
        plan = st.get("plan") or {}
        if sc["incident"]:
            inc = f"<span class='badge b-good'>✓ {_e(', '.join(sc['incident_types']))} @{sc['first_incident_touch']}</span>"
        elif any(i.get("superseded") for i in st.get("incidents", [])):
            inc = "<span class='badge'>withdrawn</span>"
        else:
            inc = "<span class='mono'>—</span>"
        rows.append(f"<tr><td><a href='{_e(f.with_suffix('.html').name)}'><b>{_e(st.get('target', {}).get('name'))}</b></a>"
                    f"<div class='mono runid'>{_e(st.get('run_id'))}</div></td>"
                    f"<td>{_badge(st.get('status', ''))}</td>"
                    f"<td>{_e((plan.get('persona') or {}).get('organisation'))}<div class='mono'>{_e(plan.get('objective'))}</div></td>"
                    f"<td>{_strip(st, int(st.get('config', {}).get('max_touches') or 10))}</td>"
                    f"<td>{inc}</td><td class='num'><b>{sc['results_points']:g}</b><span class='mono'> / 25</span></td></tr>")
    table = ("<div class='card'><h2>Runs · open one to replay every touch</h2>" + ("<table><thead><tr><th>Target</th><th>Status</th><th>Persona · objective</th>"
             "<th>Touches</th><th>Incident</th><th class='num'>Est. results</th></tr></thead><tbody>" + "".join(rows)
             + "</tbody></table>" + _LEGEND if rows else "<div class='empty-state'>No runs yet. Start one with "
             "<span class='mono'>python -m revel8_agent.cli run --target julius</span></div>") + "</div>")

    chart = ("<div class='card'><h2>Response rate by target</h2>" + _reply_bars(states)
             + "<p class='mono' style='margin:14px 0 0'>share of touches that got a reply or an answered call</p></div>")
    about = ("<div class='card'><h2>How the score is estimated</h2><p style='font-size:13px;color:var(--text-2);margin:0'>"
             "Measured locally: an incident is a submitted landing page, an opened attachment, or a disclosure/action judged "
             "from the target's own words (marked “judged”). Results = 20 if the run reached an incident + up to 5 for speed "
             "(vs. a team needing 2 contacts). Targeting, craft and the jury's 55 points are not visible here. "
             "<a href='score.html'>Full scorecard →</a> · <a href='how.html'>How the agent works →</a></p></div>")
    body = ("<h1>Overview</h1><p class='sub'>Practice runs against the revel8 targets. Start with "
            "<a href='how.html'><b>How it works</b></a>, look at the research per target, then open any run to replay every touch.</p>"
            + tiles + f"<div class='grid split' style='margin-bottom:20px'>{chart}{about}</div>" + table)
    out = out_dir / "index.html"
    out.write_text(_page("revel8 agent · overview", "", body, live and not public, active="index.html"), encoding="utf-8")
    _REDACT = False
    return out
