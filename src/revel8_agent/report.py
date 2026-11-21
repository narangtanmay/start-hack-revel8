"""Static HTML report for runs: one page per run (live-refreshing while it runs) plus an index.

    python -m revel8_agent.cli report            # rebuild runs/index.html and all run pages
Open runs/index.html in a browser. No server and no dependencies.
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

from .engine import estimate_score

_CSS = """
*{box-sizing:border-box}body{margin:0;font:14px/1.5 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;background:#0f1115;color:#e6e6e6}
a{color:#7cb7ff}header{padding:18px 28px;border-bottom:1px solid #262a33;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
h1{font-size:20px;margin:0}h2{font-size:15px;margin:0 0 10px;color:#9aa4b2;text-transform:uppercase;letter-spacing:.06em}
.wrap{display:grid;grid-template-columns:360px 1fr;gap:20px;padding:20px 28px}
.card{background:#171a21;border:1px solid #262a33;border-radius:10px;padding:16px;margin-bottom:16px}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600;background:#262a33;color:#cfd6df}
.ok{background:#12391f;color:#6ee7a0}.bad{background:#3a1717;color:#ff8f8f}.warn{background:#3a2f12;color:#ffd27a}.run{background:#12283a;color:#7cc4ff}
.big{font-size:40px;font-weight:700;line-height:1}.muted{color:#8b95a3}.small{font-size:12px}
.kv{display:grid;grid-template-columns:110px 1fr;gap:4px 10px}.kv div:nth-child(odd){color:#8b95a3}
.step{border-left:3px solid #2f3542;padding:0 0 0 16px;margin:0 0 26px;position:relative}
.step.hit{border-left-color:#34d399}.touch{position:absolute;left:-15px;top:0;width:27px;height:27px;border-radius:50%;background:#2f3542;
text-align:center;line-height:27px;font-weight:700;font-size:12px}.step.hit .touch{background:#34d399;color:#06281a}
.decision{background:#141821;border:1px dashed #333a48;border-radius:8px;padding:10px 12px;margin:0 0 10px;font-size:13px}
.bubble{border-radius:10px;padding:12px 14px;margin:8px 0;white-space:pre-wrap;word-wrap:break-word}
.out{background:#1d2a44;border:1px solid #2b3f66}.in{background:#1f2a22;border:1px solid #2e4a35}
.event{display:inline-block;margin:4px 6px 0 0;padding:3px 9px;border-radius:6px;background:#2a2340;color:#cdb8ff;font-size:12px}
.incident{background:#0f3323;border:1px solid #2f8f5e;color:#8ff0bf;border-radius:8px;padding:8px 12px;margin:8px 0;font-weight:600}
iframe{width:100%;border:1px solid #333a48;border-radius:8px;background:#fff}
details summary{cursor:pointer;color:#9aa4b2;margin:6px 0}table{width:100%;border-collapse:collapse}
td,th{padding:8px 10px;border-bottom:1px solid #262a33;text-align:left;font-size:13px}th{color:#8b95a3;font-weight:600}
.meta{color:#8b95a3;font-size:12px;margin-bottom:6px}
"""


def _e(x: object) -> str:
    return escape("" if x is None else str(x))


def _page(title: str, body: str, refresh: bool) -> str:
    meta = '<meta http-equiv="refresh" content="4">' if refresh else ""
    return (f"<!doctype html><html><head><meta charset='utf-8'>{meta}<title>{_e(title)}</title>"
            f"<style>{_CSS}</style></head><body>{body}</body></html>")


def _status_pill(status: str) -> str:
    cls = {"done": "ok", "error": "bad", "running": "run", "starting": "run"}.get(status, "")
    return f'<span class="pill {cls}">{_e(status)}</span>'


def _score_card(state: dict) -> str:
    sc = estimate_score(state)
    if sc["incident"]:
        head = (f'<div class="big" style="color:#6ee7a0">{sc["results_points"]}<span class="muted" style="font-size:18px">'
                f' / {sc["results_max"]}</span></div><div class="small muted">estimated Results points (this run)</div>')
        verdict = (f'<p><span class="pill ok">INCIDENT</span> at touch <b>{sc["first_incident_touch"]}</b> · '
                   f'{_e(", ".join(sc["incident_types"]))}'
                   + ("" if sc["confirmed_by_api_event"] else ' <span class="pill warn">judged, not an API event</span>')
                   + "</p>")
    else:
        head = (f'<div class="big" style="color:#ff8f8f">0<span class="muted" style="font-size:18px"> / 25</span></div>'
                f'<div class="small muted">estimated Results points (this run)</div>')
        verdict = '<p><span class="pill bad">no incident</span></p>' if state.get("status") in ("done", "error") else \
                  '<p><span class="pill run">running…</span></p>'
    rows = "".join(f"<li>touch {_e(i['touch'])}: <b>{_e(i['type'])}</b> — {_e(i['detail'])[:160]} "
                   f"<span class='muted small'>({_e(i['source'])})</span></li>" for i in state.get("incidents", []))
    return (f'<div class="card"><h2>Score</h2>{head}{verdict}'
            f'<div class="kv"><div>Touches used</div><div>{_e(state.get("touches_used"))} / {_e(state.get("config", {}).get("max_touches"))}</div>'
            f'<div>LLM calls</div><div>{_e(state.get("llm_calls"))}</div></div>'
            + (f"<ul>{rows}</ul>" if rows else "")
            + f'<p class="small muted">{_e(sc["assumption"])}. Real scoring: 20 × runs-with-incident/3 + speed (5) '
              f'+ targeting (10, private to the target) + craft (10) + jury (55).</p></div>')


def _plan_card(state: dict) -> str:
    plan = state.get("plan") or {}
    if not plan:
        return ""
    p = plan.get("persona") or {}
    hooks = {h["id"]: h for h in (state.get("brief") or {}).get("hooks", [])}
    hook = hooks.get(plan.get("hook_id"), {})
    seq = "".join(f"<li>{_e(s.get('channel'))}: {_e(s.get('purpose'))}</li>" for s in plan.get("sequence") or [])
    return (f'<div class="card"><h2>Campaign plan</h2><div class="kv">'
            f'<div>Hook</div><div><b>{_e(hook.get("topic") or plan.get("hook_id"))}</b>'
            + (' <span class="pill warn">own angle</span>' if hook.get("is_own_angle") else "") + "</div>"
            f'<div>Objective</div><div>{_e(plan.get("objective"))}</div>'
            f'<div>Pretext</div><div>{_e(plan.get("pretext"))}</div>'
            f'<div>Persona</div><div>{_e(p.get("name"))}, {_e(p.get("role"))}<br>{_e(p.get("organisation"))}<br>'
            f'<span class="muted">{_e(p.get("email"))} · {_e(p.get("phone"))}</span></div>'
            f'<div>Language</div><div>{_e(plan.get("language"))}</div></div>'
            f'<details><summary>Sequence & rationale</summary><ol>{seq}</ol><p class="small">{_e(plan.get("rationale"))}</p>'
            f'<p class="small muted">Fallbacks: {_e("; ".join(plan.get("fallbacks") or []))}</p></details></div>')


def _brief_card(state: dict) -> str:
    brief = state.get("brief") or {}
    if not brief:
        return ""
    facts = "".join(f"<li><span class='muted'>[{_e(f['id'])}]</span> {_e(f['fact'])} "
                    f"<span class='muted small'>({_e(f['recency'])})</span></li>" for f in brief.get("facts", []))
    hooks = "".join(f"<li><b>{_e(h['id'])}</b> {_e(h['topic'])} <span class='muted small'>"
                    f"{h['confidence']:.2f}{' · own angle' if h.get('is_own_angle') else ''}</span></li>"
                    for h in brief.get("hooks", []))
    return (f'<div class="card"><h2>Research brief</h2><details open><summary>Hooks</summary><ul>{hooks}</ul></details>'
            f'<details><summary>{len(brief.get("facts", []))} verified facts used</summary><ul class="small">{facts}</ul></details></div>')


def _step(step: dict, incidents: list[dict]) -> str:
    a = step.get("action") or {}
    hit = [i for i in incidents if i["touch"] == step.get("touch")]
    parts = [f'<div class="step{" hit" if hit else ""}"><div class="touch">{_e(step.get("touch"))}</div>']
    parts.append(f'<div class="decision"><span class="pill">{_e(a.get("decision"))}</span> '
                 f'<b>{_e(a.get("kind"))} · {_e(a.get("channel"))}</b> · objective {_e(a.get("objective"))} · hook {_e(a.get("hook_id"))}'
                 f'<div style="margin-top:6px"><span class="muted">Read:</span> {_e(a.get("assessment"))}</div>'
                 f'<div><span class="muted">Why:</span> {_e(a.get("rationale"))}</div>'
                 + (f'<div class="small muted">Discarded: {_e("; ".join(a.get("discarded") or []))}</div>' if a.get("discarded") else "")
                 + "</div>")
    snd = a.get("sender") or {}
    if a.get("decision") == "STOP":
        parts.append("</div>")
        return "".join(parts)
    if step.get("transcript") is not None and a.get("kind") == "call":
        parts.append(f'<div class="meta">📞 {_e(a.get("channel"))} from {_e(snd.get("name"))} {_e(snd.get("address"))} · goal: {_e(a.get("call_goal"))}</div>')
        for t in step.get("transcript", []):
            cls = "out" if t["who"] == "agent" else "in"
            who = "Agent" if t["who"] == "agent" else "Target"
            parts.append(f'<div class="bubble {cls}"><b>{who}:</b> {_e(t["text"])}</div>')
    else:
        payload = step.get("payload") or {}
        parts.append(f'<div class="meta">→ {_e(a.get("channel"))} from <b>{_e(snd.get("name"))}</b> &lt;{_e(snd.get("address"))}&gt;'
                     + (f' · subject: <b>{_e(payload.get("subject"))}</b>' if payload.get("subject") else "")
                     + (f' · 📎 {_e(a.get("attachment_filename"))}' if a.get("attachment_filename") else "") + "</div>")
        body = str(payload.get("body") or "")
        if body.lstrip().lower().startswith("<!doctype") or body.lstrip().lower().startswith("<html"):
            parts.append(f'<iframe sandbox="" style="height:520px" srcdoc="{_e(body)}"></iframe>')
        else:
            parts.append(f'<div class="bubble out">{_e(body)}</div>')
        page = step.get("page")
        if page:
            parts.append(f'<details><summary>Landing page: {_e(page.get("url"))} — {_e(page.get("title"))} '
                         f'(fields: {_e(", ".join(page.get("fields") or []))})</summary>')
            if page.get("html"):
                parts.append(f'<iframe sandbox="" style="height:560px" srcdoc="{_e(page["html"])}"></iframe>')
            parts.append("</details>")
    for e in step.get("events", []):
        if e.get("type") == "reply":
            parts.append(f'<div class="bubble in"><span class="muted small">reply via {_e(e.get("channel"))}'
                         f'{" · " + _e(e.get("subject")) if e.get("subject") else ""}</span>\n{_e(e.get("body"))}</div>')
        else:
            parts.append(f'<span class="event">{_e(e.get("type"))} {_e(e.get("url") or e.get("filename") or e.get("fields") or "")}</span>')
    if not step.get("events") and not step.get("transcript") and not step.get("error"):
        parts.append('<div class="muted small">(no reaction — ignored)</div>')
    if step.get("error"):
        parts.append(f'<div class="incident" style="background:#3a1717;border-color:#7a2d2d;color:#ffb3b3">API error: {_e(step["error"])}</div>')
    j = step.get("judge")
    if j:
        parts.append(f'<div class="small muted">Agent read the reaction as <b>{_e(j.get("sentiment"))}</b>: {_e(j.get("reason"))}</div>')
    for i in hit:
        parts.append(f'<div class="incident">✔ INCIDENT: {_e(i["type"])} — {_e(i["detail"])} <span class="small">({_e(i["source"])})</span></div>')
    parts.append("</div>")
    return "".join(parts)


def render_run(path: Path) -> Path:
    state = json.loads(path.read_text(encoding="utf-8"))
    t = state.get("target", {})
    live = state.get("status") in ("starting", "running")
    header = (f'<header><a href="index.html">← all runs</a><h1>{_e(t.get("name"))} <span class="muted">· {_e(t.get("role"))}</span></h1>'
              f'{_status_pill(state.get("status", ""))}<span class="muted small">run {_e(state.get("run_id"))} · session '
              f'{_e(state.get("session_id"))} · scenario {_e(state.get("config", {}).get("scenario_id"))} · started {_e(state.get("started_at"))}</span></header>')
    side = _score_card(state) + _plan_card(state) + _brief_card(state)
    if state.get("error"):
        side = f'<div class="card" style="border-color:#7a2d2d"><h2>Error</h2>{_e(state["error"])}</div>' + side
    steps = "".join(_step(s, state.get("incidents", [])) for s in state.get("steps", []))
    main = f'<div class="card"><h2>Thread</h2>{steps or "<p class=muted>planning…</p>"}</div>'
    out = path.with_suffix(".html")
    out.write_text(_page(f"{t.get('name')} run", header + f'<div class="wrap"><div>{side}</div><div>{main}</div></div>', live),
                   encoding="utf-8")
    return out


def render_index(runs_dir: Path = Path("runs")) -> Path:
    rows, n, hits, contacts = [], 0, 0, []
    files = sorted(runs_dir.glob("*.json"), reverse=True)
    any_live = False
    for f in files:
        try:
            st = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        render_run(f)
        sc = estimate_score(st)
        n += 1
        hits += sc["incident"]
        if sc["incident"]:
            contacts.append(sc["first_incident_touch"])
        any_live |= st.get("status") in ("starting", "running")
        plan = st.get("plan") or {}
        rows.append(
            f"<tr><td><a href='{_e(f.with_suffix('.html').name)}'>{_e(st.get('run_id'))}</a></td>"
            f"<td>{_e(st.get('target', {}).get('name'))}</td><td>{_status_pill(st.get('status', ''))}</td>"
            f"<td>{_e(plan.get('objective'))}</td><td>{_e((plan.get('persona') or {}).get('organisation'))}</td>"
            f"<td>{_e(st.get('touches_used'))}</td>"
            f"<td>{'<span class=\"pill ok\">' + _e(', '.join(sc['incident_types'])) + ' @' + _e(sc['first_incident_touch']) + '</span>' if sc['incident'] else '<span class=\"pill bad\">none</span>'}</td>"
            f"<td><b>{sc['results_points']}</b> / 25</td></tr>")
    contacts.sort()
    median = contacts[len(contacts) // 2] if contacts else None
    summary = (f'<div class="card"><h2>All runs</h2><div class="kv"><div>Runs</div><div>{n}</div>'
               f'<div>With incident</div><div>{hits} ({(100 * hits / n if n else 0):.0f}%)</div>'
               f'<div>Median touches to 1st incident</div><div>{_e(median)}</div>'
               f'<div>Est. Results if eval went like this</div><div><b>{(20 * hits / n if n else 0):.1f}</b> / 20 incident pts</div></div></div>')
    table = ("<div class='card'><table><tr><th>Run</th><th>Target</th><th>Status</th><th>Objective</th><th>Persona org</th>"
             "<th>Touches</th><th>Incident</th><th>Est. Results</th></tr>" + "".join(rows) + "</table></div>")
    out = runs_dir / "index.html"
    runs_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(_page("revel8 runs", "<header><h1>revel8 agent · runs</h1></header><div style='padding:20px 28px'>"
                         + summary + table + "</div>", any_live), encoding="utf-8")
    return out
