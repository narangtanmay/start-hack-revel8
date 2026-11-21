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
.runid{white-space:nowrap}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;color:var(--muted)}
.twins{margin:10px 0;background:var(--surface-2);border:1px solid var(--border);border-radius:10px;padding:10px 12px}
.twins-title{font-size:11.5px;font-weight:600;color:var(--text-2);margin-bottom:8px;text-transform:uppercase;letter-spacing:.03em}
.twin-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}
.twin-card{background:var(--surface);border:1px solid var(--border);border-radius:9px;padding:10px 12px;font-size:12.5px;display:flex;flex-direction:column;gap:6px}
.twin-card.selected{border-color:var(--good);background:color-mix(in srgb,var(--good-bg) 42%,var(--surface))}
.twin-head{display:flex;flex-wrap:wrap;align-items:center;gap:6px}
.twin-ev{margin-left:auto;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;font-weight:600;color:var(--text)}
.twin-summary{color:var(--text);font-weight:500}
.twin-metrics{display:flex;flex-wrap:wrap;gap:6px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;color:var(--text-2)}
.twin-metrics span{background:var(--surface-2);padding:1px 6px;border-radius:5px}
.twin-react{font-size:12px;color:var(--text-2)}
.twin-rat{font-size:11.5px;color:var(--muted)}
.ledger{margin:8px 0 0 28px;display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.ledger-lbl{font-size:11.5px;color:var(--muted);font-weight:600;margin-right:2px}
"""

_STATUS = {"done": ("b-good", "Done"), "error": ("b-crit", "Error"), "running": ("b-live", "Live"), "starting": ("b-live", "Starting")}


def _e(x: object) -> str:
    return escape("" if x is None else str(x))


def _page(title: str, crumbs: str, body: str, live: bool) -> str:
    refresh = '<meta http-equiv="refresh" content="4">' if live else ""
    live_html = '<span class="live"><span class="dot"></span>Live · auto-refresh</span>' if live else ""
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"{refresh}<title>{_e(title)}</title><style>{_CSS}</style></head><body>"
            f"<div class='nav'><div class='nav-in'><div class='logo'>r8</div><a class='brand' href='index.html'>revel8 agent</a>"
            f"{crumbs}<div class='spacer'></div>{live_html}</div></div><div class='page'>{body}</div></body></html>")


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


def _fmt_metric(value: object) -> str:
    if isinstance(value, bool) or value is None:
        return "—"
    if isinstance(value, (int, float)):
        return f"{value:.2f}"
    return _e(value)


def _shadow_twin_html(shadow_twin: object) -> str:
    if not isinstance(shadow_twin, dict):
        return ""
    candidates = shadow_twin.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    tier_cls = {"SAFE": "b-good", "BALANCED": "b-live", "BOLD": "b-warn"}
    cards: list[str] = []
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        tier = str(cand.get("risk_tier") or "").upper()
        selected = bool(cand.get("selected"))
        fc = cand.get("forecast") if isinstance(cand.get("forecast"), dict) else {}
        tcls = tier_cls.get(tier, "")
        sel_badge = "<span class='badge b-good'>SELECTED</span>" if selected else ""
        chan_kind = " · ".join(x for x in (str(cand.get("channel") or ""), str(cand.get("kind") or "")) if x)
        metrics = (
            f"<span>prog {_fmt_metric(fc.get('progress_prob'))}</span>"
            f"<span>susp {_fmt_metric(fc.get('suspicion_risk'))}</span>"
            f"<span>norm {_fmt_metric(fc.get('social_norm_violation'))}</span>"
        )
        react = fc.get("predicted_reaction")
        rat = fc.get("rationale")
        cards.append(
            f"<div class='twin-card{' selected' if selected else ''}'>"
            f"<div class='twin-head'>"
            f"<span class='badge {tcls}'>{_e(tier or 'BRANCH')}</span>"
            f"{sel_badge}"
            f"<span class='mono'>{_e(chan_kind)}</span>"
            f"<span class='twin-ev'>EV {_fmt_metric(cand.get('ev_score'))}</span>"
            f"</div>"
            + (f"<div class='twin-summary'>{_e(cand.get('summary'))}</div>" if cand.get("summary") else "")
            + f"<div class='twin-metrics'>{metrics}</div>"
            + (f"<div class='twin-react'><b>Predicted:</b> {_e(react)}</div>" if react else "")
            + (f"<div class='twin-rat'>{_e(rat)}</div>" if rat else "")
            + "</div>"
        )
    if not cards:
        return ""
    return (
        "<div class='twins'>"
        "<div class='twins-title'>Counterfactual Branch Comparison</div>"
        f"<div class='twin-grid'>{''.join(cards)}</div>"
        "</div>"
    )


def _ledger_badges_html(ledger: object) -> str:
    if not isinstance(ledger, dict) or not ledger:
        return ""
    pills: list[str] = []
    for key, val in ledger.items():
        if val is None or val is False or val == "" or val == 0 or val == []:
            continue
        label = str(key).replace("_", " ")
        if val is True:
            text = label
            cls = "b-warn" if "refused" in str(key) else "b-live"
        elif isinstance(val, list):
            text = f"{label}: {', '.join(str(x) for x in val)}"
            cls = "b-live"
        else:
            text = f"{label}: {val}"
            cls = "b-warn" if "stall" in str(key) else "b-live"
        pills.append(f"<span class='badge {cls}'>{_e(text)}</span>")
    if not pills:
        return ""
    return f"<div class='ledger'><span class='ledger-lbl'>Ledger:</span>{''.join(pills)}</div>"


_REDACT = False  # public snapshots: landing pages listed (URL + fields), never rendered


def _touch(step: dict, incidents: list[dict]) -> str:
    a = step.get("action") or {}
    n = step.get("touch")
    hit = [i for i in incidents if i["touch"] == n]
    evs = step.get("events") or []
    replied = any(e.get("type") == "reply" for e in evs)
    cls = "hit" if hit else ("replied" if replied else "")
    snd = a.get("sender") or {}
    out = [f"<div class='touch {cls}'><div class='tn'>{'✓' if hit else _e(n)}</div>"]
    if a.get("decision") == "STOP":
        out.append(f"<div class='thead'><span class='badge'>STOP</span></div><div class='why'>{_e(a.get('rationale'))}</div></div>")
        return "".join(out)
    icon = "📞" if a.get("kind") == "call" else ("✉️" if a.get("channel") == "email" else "💬")
    out.append(f"<div class='thead'><span class='chan'>{icon} {_e(a.get('channel'))}</span><span class='badge'>{_e(a.get('decision'))}</span>"
               f"<span class='badge'>{_e(a.get('objective'))}</span><span class='mono'>hook {_e(a.get('hook_id'))}</span></div>")
    out.append(f"<div class='why'><b>Read:</b> {_e(a.get('assessment'))}<br><b>Move:</b> {_e(a.get('rationale'))}</div>")
    twin_html = _shadow_twin_html(step.get("shadow_twin"))
    if twin_html:
        out.append(twin_html)
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
                page_html += (f"<div class='mono' style='margin-top:8px'>fields: {_e(', '.join(page.get('fields') or []))} · "
                              "not rendered in the public snapshot</div>")
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
        out.append("<div class='silent'>No reaction</div>")
    if step.get("error"):
        out.append(f"<div class='err'>API error: {_e(step['error'])}</div>")
    j = step.get("judge")
    if j and j.get("sentiment") not in (None, "silent"):
        out.append(f"<div class='read'>Agent read this as <b>{_e(j.get('sentiment'))}</b> — {_e(j.get('reason'))}</div>")
    ledger_html = _ledger_badges_html(step.get("ledger_after"))
    if ledger_html:
        out.append(ledger_html)
    for i in hit:
        out.append(f"<div class='incident'>✓ Incident · {_e(i['type'])}<span style='font-weight:400'>{_e(i['detail'])} "
                   f"({_e(i['source'])})</span></div>")
    out.append("</div>")
    return "".join(out)


def render_run(path: Path, out_dir: Path | None = None) -> Path:
    state = json.loads(path.read_text(encoding="utf-8"))
    t = state.get("target", {})
    live = state.get("status") in ("starting", "running")
    cfg = state.get("config", {})
    head = (f"<div style='display:flex;gap:12px;align-items:center;flex-wrap:wrap'><h1>{_e(t.get('name'))}</h1>{_badge(state.get('status', ''))}</div>"
            f"<p class='sub'>{_e(t.get('role'))} · scenario {_e(cfg.get('scenario_id'))} · session "
            f"<span class='mono'>{_e(state.get('session_id'))}</span> · started {_e(str(state.get('started_at', ''))[:16].replace('T', ' '))}</p>")
    error = f"<div class='card' style='border-color:var(--crit);margin-bottom:16px'><h2>Run error</h2>{_e(state['error'])}</div>" if state.get("error") else ""
    steps = "".join(_touch(s, state.get("incidents", [])) for s in state.get("steps", []))
    thread = (f"<div class='card'><div style='display:flex;align-items:center;gap:14px;margin-bottom:18px'><h2 style='margin:0'>Thread</h2>"
              f"<div class='spacer' style='flex:1'></div>{_strip(state, int(cfg.get('max_touches') or 10))}</div>"
              f"<div class='tl'>{steps or '<div class=empty-state>Planning the campaign…</div>'}</div>{_LEGEND}</div>")
    body = head + error + _run_tiles(state) + f"<div class='grid side'><div class='grid'>{_plan_card(state)}{_research_card(state)}</div>{thread}</div>"
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


def render_index(runs_dir: Path = Path("runs"), out_dir: Path | None = None, public: bool = False) -> Path:
    """Render the dashboard into runs_dir (default) or out_dir; public=True redacts landing pages."""
    global _REDACT
    _REDACT = public
    runs_dir.mkdir(parents=True, exist_ok=True)
    out_dir = out_dir or runs_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    loaded = _load(runs_dir)
    states = [st for _, st in loaded]
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

    tiles = ("<div class='grid k4' style='margin-bottom:20px'>"
             + _tile("Runs", str(n), f"{sum(st.get('status') == 'done' for st in states)} finished")
             + _tile("Runs with an incident", f"{hits}<small> / {n}</small>",
                     f"{(100 * hits / n if n else 0):.0f}% · est. {(20 * hits / n if n else 0):.1f} of 20 incident pts")
             + _tile("Median touches to incident", _e(median if median is not None else "—"), "fewer is better (speed, 5 pts)")
             + _tile("Replies", str(replies), f"across {touches} touches")
             + "</div>")

    rows = []
    for (f, st), sc in zip(loaded, scores):
        plan = st.get("plan") or {}
        inc = (f"<span class='badge b-good'>✓ {_e(', '.join(sc['incident_types']))} @{sc['first_incident_touch']}</span>"
               if sc["incident"] else "<span class='mono'>—</span>")
        rows.append(f"<tr><td><a href='{_e(f.with_suffix('.html').name)}'><b>{_e(st.get('target', {}).get('name'))}</b></a>"
                    f"<div class='mono runid'>{_e(st.get('run_id'))}</div></td>"
                    f"<td>{_badge(st.get('status', ''))}</td>"
                    f"<td>{_e((plan.get('persona') or {}).get('organisation'))}<div class='mono'>{_e(plan.get('objective'))}</div></td>"
                    f"<td>{_strip(st, int(st.get('config', {}).get('max_touches') or 10))}</td>"
                    f"<td>{inc}</td><td class='num'><b>{sc['results_points']:g}</b><span class='mono'> / 25</span></td></tr>")
    table = ("<div class='card'><h2>Runs</h2>" + ("<table><thead><tr><th>Target</th><th>Status</th><th>Persona · objective</th>"
             "<th>Touches</th><th>Incident</th><th class='num'>Est. results</th></tr></thead><tbody>" + "".join(rows)
             + "</tbody></table>" + _LEGEND if rows else "<div class='empty-state'>No runs yet. Start one with "
             "<span class='mono'>python -m revel8_agent.cli run --target julius</span></div>") + "</div>")

    chart = ("<div class='card'><h2>Response rate by target</h2>" + _reply_bars(states)
             + "<p class='mono' style='margin:14px 0 0'>share of touches that got a reply or an answered call</p></div>")
    about = ("<div class='card'><h2>How the score is estimated</h2><p style='font-size:13px;color:var(--text-2);margin:0'>"
             "Measured locally: an incident is a submitted landing page, an opened attachment, or a disclosure/action judged "
             "from the target's own words (marked “judged”). Results = 20 if the run reached an incident + up to 5 for speed "
             "(vs. a team needing 2 contacts). Targeting, craft and the jury's 55 points are not visible here.</p></div>")
    body = ("<h1>Overview</h1><p class='sub'>Practice runs against the revel8 targets. Open a run to replay its thread.</p>"
            + tiles + f"<div class='grid split' style='margin-bottom:20px'>{chart}{about}</div>" + table)
    out = out_dir / "index.html"
    out.write_text(_page("revel8 agent · overview", "", body, live and not public), encoding="utf-8")
    _REDACT = False
    return out
