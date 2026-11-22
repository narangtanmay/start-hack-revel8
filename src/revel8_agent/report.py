"""Dashboard for agent runs: an overview page plus one page per run.

    python -m revel8_agent.cli report [--open]

Writes runs/index.html (overview) and runs/<run_id>.html (thread). Static files, no server, no
dependencies. Pages refresh themselves while a run is live. Light and dark themes follow the OS.
Series colours are the validated reference palette (blue / orange / violet, checked for colour-blind
separation in both modes); incidents use the reserved status green with an icon and a label.
"""

from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path

from .engine import estimate_score

from .report_style import CSS as _CSS  # noqa: E402  (the one visual world, shared by every page)

_STATUS = {"done": ("b-good", "Done"), "error": ("b-warn", "Stopped early"), "running": ("b-live", "Live"),
           "starting": ("b-live", "Starting")}


def _e(x: object) -> str:
    return escape("" if x is None else str(x))


def plain_error(error: object) -> str:
    """What stopped a run, in words a reader understands; the raw exception goes under 'Technical details'."""
    e = str(error or "")
    if re.search(r"valid draft", e, re.I):
        return ("The agent could not write a message that passed its own checks in three tries, so it stopped "
                "instead of sending something broken")
    if re.search(r"Revel8APIError|HTTP|\b429\b|\b5\d\d\b", e):
        return "The target API kept returning errors"
    if re.search(r"LLM|timed? ?out", e, re.I):
        return "The language model stopped responding"
    return "An unexpected error stopped the run"


def _flag(value: object) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")  # run JSONs store config booleans as strings


def decision_path(state: dict) -> str:
    """Which decision path made the moves in this run (the A/B story the overview compares)."""
    plan, cfg = state.get("plan") or {}, state.get("config") or {}
    if plan.get("architecture") == "method-actor" or cfg.get("policy") == "actor":
        return "Method actor"
    if _flag(cfg.get("use_shadow_twin")):
        return "Shadow twin"
    if _flag(cfg.get("use_policy")):
        return "Rule policy"
    if cfg.get("policy") == "controller":
        return "Escalation controller"
    return "LLM planner"


def _live_incidents(state: dict) -> list[dict]:
    return [i for i in state.get("incidents", []) if not i.get("superseded")]


def _confirmed(i: dict) -> bool:
    return i.get("source") == "api event"


def _uncounted_note(states: list[dict]) -> str:
    """Incidents in runs the counting rule leaves out (stopped early, live), so a ≈/✓ badge in the runs table never
    contradicts a 0 in the tiles without an explanation."""
    n = sum(1 for st in states if _live_incidents(st)
            and not (st.get("status") == "done" and int(st.get("touches_used") or 0) > 0))
    return f" · {n} more in a run that is not counted" if n == 1 else f" · {n} more in runs that are not counted" if n else ""


def _incident_badge(sc: dict) -> str:
    types, n = ", ".join(sc["incident_types"]), sc["first_incident_touch"]
    if sc["confirmed_by_api_event"]:
        return f"<span class='badge b-good' title='Confirmed by an API event'>✓ {_e(types)} @{_e(n)}</span>"
    return (f"<span class='badge b-est' title=\"Our judge's read of the target's reply; the API has not confirmed it\">"
            f"≈ {_e(types)} @{_e(n)} · estimate</span>")


_TARGETS: list[str] = []  # research pages that exist, for the nav


def _page(title: str, crumbs: str, body: str, live: bool, active: str = "") -> str:
    refresh = '<meta http-equiv="refresh" content="4">' if live else ""
    live_html = '<span class="live"><span class="dot"></span>Live · auto-refresh</span>' if live else ""
    tabs = [("index.html", "Overview"), ("runs.html", "Runs"), ("replay.html", "Replay"), ("score.html", "Score"),
            ("how.html", "How it works")] + [(f"research-{t}.html", f"Research · {t}") for t in _TARGETS]
    nav = "".join(f"<a href='{h}'{' class=on' if h == active else ''}>{_e(lbl)}</a>" for h, lbl in tabs)
    # Fonts are self-hosted (report_style.FONT_FACES points at fonts/ next to the page; render_index copies them).
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"{refresh}<title>{_e(title)}</title>"
            f"<style>{_CSS}</style></head><body>"
            f"<div class='nav'><div class='nav-in'><div class='logo'>r8</div><a class='brand' href='index.html'>revel8 agent</a>"
            f"<nav class='tabs'>{nav}</nav>{crumbs}<div class='spacer'></div>{live_html}</div></div><div class='page'>{body}</div></body></html>")


def _badge(status: str) -> str:
    cls, label = _STATUS.get(status, ("", status or "—"))
    return f"<span class='badge {cls}'>{_e(label)}</span>"


def _touch_outcomes(state: dict) -> list[tuple[str, str]]:
    """One (class, tooltip) per touch, used by the strip on both pages."""
    live = _live_incidents(state)  # withdrawn incidents are not hits
    confirmed = {i["touch"] for i in live if _confirmed(i)}
    estimated = {i["touch"] for i in live} - confirmed
    out = []
    for s in state.get("steps", []):
        a = s.get("action") or {}
        if a.get("decision") == "STOP":
            continue
        evs = s.get("events") or []
        n = s.get("touch")
        chan = a.get("channel", "")
        if n in confirmed:
            out.append(("c-hit", f"Touch {n} · {chan}\nIncident, confirmed by the API"))
        elif n in estimated:
            out.append(("c-est", f"Touch {n} · {chan}\nIncident, our judge's estimate (not an API event)"))
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
        mark = {"c-hit": "✓", "c-est": "≈"}.get(cls, "")
        cells.append(f"<span class='cell {cls}' data-tip='{_e(tip)}'>{mark}</span>")
    cells += ["<span class='cell empty'></span>"] * max(0, slots - len(cells))
    return f"<div class='strip' role='img' aria-label='touch outcomes'>{''.join(cells)}</div>"


_LEGEND = ("<div class='legend'><span><i class='cell c-reply'></i>Replied</span><span><i class='cell c-call'></i>Call answered</span>"
           "<span><i class='cell c-event'></i>Link / file / page event</span><span><i class='cell'></i>No reaction</span>"
           "<span><i class='cell c-hit'>✓</i>Incident, confirmed by the API</span>"
           "<span><i class='cell c-est'>≈</i>Incident, our estimate</span></div>")


# --------------------------------------------------------------------------- run page


def _tile(label: str, value: str, foot: str = "") -> str:
    return f"<div class='card tile'><div class='label'>{label}</div><div class='value'>{value}</div><div class='foot'>{foot}</div></div>"


def _run_tiles(state: dict) -> str:
    sc = estimate_score(state)
    steps = [s for s in state.get("steps", []) if (s.get("action") or {}).get("decision") != "STOP"]
    replies = sum(1 for s in steps if any(e.get("type") == "reply" for e in s.get("events") or []))
    if sc["incident"] and sc["confirmed_by_api_event"]:
        outcome = (f"<span style='color:var(--good-text)'>✓ {_e(', '.join(sc['incident_types']))}</span>",
                   f"first at touch {sc['first_incident_touch']} · confirmed by the API")
    elif sc["incident"]:
        outcome = (f"<span style='color:var(--warn-text)'>≈ {_e(', '.join(sc['incident_types']))}</span>",
                   f"touch {sc['first_incident_touch']} · our judge's estimate, not an API event")
    elif state.get("status") in ("running", "starting"):
        outcome = ("<span style='color:var(--accent-text)'>Running</span>", "waiting for the target")
    else:
        outcome = ("<span style='color:var(--muted)'>None</span>", "no incident in this run")
    counted = state.get("status") == "done" and int(state.get("touches_used") or 0) > 0  # scorecard.finished()
    pts_foot = "incident 20 + speed 5, this run only"
    if sc["incident"] and not sc["confirmed_by_api_event"]:
        pts_foot = "only if the API confirms the incident"
    if not counted and state.get("status") not in ("running", "starting"):
        pts_foot += " · not counted on Score (stopped early)"
    return ("<div class='grid k4' style='margin-bottom:20px'>"
            + _tile("Incident", outcome[0], outcome[1])
            + _tile("Est. results points", f"{sc['results_points']:g}<small> / 25</small>", pts_foot)
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


_REACTIONS = {
    "engaged": "engage", "questioning": "question", "hesitant": "stall",
    "silent": "ignore", "suspicious": "suspicious", "refusing": "refuse",
}
_COMPARABLE_REACTIONS = frozenset(_REACTIONS.values()) | {"incident"}


def _actual_reaction(step: dict, incidents: list[dict]) -> str:
    if incidents:
        return "incident"
    if step.get("error"):
        return ""
    sentiment = (step.get("judge") or {}).get("sentiment")
    if sentiment in _REACTIONS:
        return _REACTIONS[sentiment]
    if any(e.get("type") == "reply" for e in step.get("events") or []) or any(
        t.get("who") == "target" for t in step.get("transcript") or []
    ):
        return "response recorded"
    if step.get("events"):
        return "event recorded"
    return "ignore" if "events" in step or "transcript" in step else ""


def _prediction_html(predicted: str, actual: str, *, comparable: bool = True) -> str:
    comparison = f"{_e(predicted)} → {_e(actual)}"
    if comparable:
        match = predicted.strip().casefold() == actual.strip().casefold()
        comparison += " <span class='badge b-good' title='Match'>✓</span>" if match else (
            " <span class='badge b-warn' title='Mismatch'>✗</span>"
        )
    return comparison


def _shadow_twin_html(shadow_twin: object, actual: str = "") -> str:
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
        prediction = _e(react)
        if react and selected and actual:
            comparable = react in _COMPARABLE_REACTIONS and actual in _COMPARABLE_REACTIONS
            prediction = _prediction_html(react, actual, comparable=comparable)
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
            + (f"<div class='twin-react'><b>Predicted:</b> {prediction}</div>" if react else "")
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


def _policy_html(policy: object, actual_move: str = "") -> str:
    if not isinstance(policy, dict) or not policy:
        return ""
    move_type = str(policy.get("move_type") or "")
    badge_cls = "b-warn" if move_type == "STOP" else ("b-good" if move_type == "STAY" else "b-live")
    head_parts = [
        "<span class='policy-title'>Policy Move</span>",
        f"<span class='badge {badge_cls}'>{_e(move_type)}</span>",
    ]
    if policy.get("channel"):
        head_parts.append(f"<span class='badge'>{_e(policy.get('channel'))}</span>")
    if policy.get("objective"):
        head_parts.append(f"<span class='badge'>{_e(policy.get('objective'))}</span>")
    if policy.get("hook_id"):
        head_parts.append(f"<span class='mono'>hook {_e(policy.get('hook_id'))}</span>")

    rows: list[str] = []
    if move_type and actual_move:
        rows.append(f"<dt>Predicted → actual</dt><dd>{_prediction_html(move_type, actual_move)}</dd>")
    if policy.get("ask"):
        rows.append(f"<dt>Ask</dt><dd>{_e(policy.get('ask'))}</dd>")
    if policy.get("rationale"):
        rows.append(f"<dt>Rationale</dt><dd>{_e(policy.get('rationale'))}</dd>")
    cited = [str(x) for x in (policy.get("cited_fact_ids") or []) if str(x).strip()]
    if cited:
        chips = " ".join(f"<span class='badge mono'>{_e(fid)}</span>" for fid in cited)
        rows.append(f"<dt>Cited facts</dt><dd>{chips}</dd>")
    promises = [str(x) for x in (policy.get("promises") or []) if str(x).strip()]
    if promises:
        p_items = "".join(f"<li>{_e(p)}</li>" for p in promises)
        rows.append(f"<dt>Promises</dt><dd><ul class='policy-alts'>{p_items}</ul></dd>")
    alts = [a for a in (policy.get("alternatives_considered") or []) if isinstance(a, dict)]
    if alts:
        alt_items: list[str] = []
        for alt in alts:
            m = _e(alt.get("move_type") or "")
            ch = _e(alt.get("channel") or "")
            hk = _e(alt.get("hook_id") or "")
            rsn = _e(alt.get("reason") or "")
            meta = " · ".join(x for x in (m, ch, f"hook {hk}" if hk else "") if x)
            alt_items.append(f"<li><b>{meta}</b>: {rsn}</li>" if meta else f"<li>{rsn}</li>")
        rows.append(f"<dt>Alternatives</dt><dd><ul class='policy-alts'>{''.join(alt_items)}</ul></dd>")

    return (
        "<div class='policy'>"
        f"<div class='policy-head'>{''.join(head_parts)}</div>"
        f"<dl class='policy-grid'>{''.join(rows)}</dl>"
        "</div>"
    )


def _actor_html(actor: object, attempts: object = None) -> str:
    """Method-actor view: the character's reasoning, notebook additions and gate rejections for one touch."""
    if not isinstance(actor, dict) or not actor:
        return ""
    rows: list[str] = []
    if actor.get("inner_monologue"):
        rows.append(f"<dt>Reasoning</dt><dd>{_e(actor['inner_monologue'])}</dd>")
    notes = [str(x) for x in (actor.get("notebook_added") or []) if str(x).strip()]
    if notes:
        rows.append(f"<dt>Notebook</dt><dd><ul class='policy-alts'>{''.join(f'<li>{_e(n)}</li>' for n in notes)}</ul></dd>")
    rejected = [str(e) for at in (attempts or []) if isinstance(at, dict) for e in (at.get("errors") or []) if str(e).strip()]
    rejected += [str(x) for x in (actor.get("gate_notes") or []) if str(x).strip()]
    if rejected:
        rows.append(f"<dt>Gate</dt><dd><ul class='policy-alts'>{''.join(f'<li>{_e(r)}</li>' for r in rejected)}</ul></dd>")
    head = "<span class='policy-title'>Character</span>"
    if actor.get("decision_read_off"):
        head += f"<span class='badge b-live'>{_e(actor['decision_read_off'])}</span>"
    return f"<div class='policy'><div class='policy-head'>{head}</div><dl class='policy-grid'>{''.join(rows)}</dl></div>"


def _casting_html(casting: object) -> str:
    if not isinstance(casting, dict) or not casting:
        return ""
    ch = casting.get("character") if isinstance(casting.get("character"), dict) else {}
    pe = casting.get("persona") if isinstance(casting.get("persona"), dict) else {}
    rows = []
    for label, val in (("Cast", f"{pe.get('name', '')} · {pe.get('role', '')} · {pe.get('organisation', '')}".strip(" ·")),
                       ("Need", ch.get("need")), ("Unblocks", ch.get("unblocks_me")),
                       ("Deadline", ch.get("deadline")), ("Pretext", casting.get("pretext"))):
        if val:
            rows.append(f"<dt>{label}</dt><dd>{_e(val)}</dd>")
    if not rows:
        return ""
    return (f"<div class='card' style='margin-bottom:16px'><h2>Casting</h2>"
            f"<dl class='policy-grid'>{''.join(rows)}</dl></div>")


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
    lookups = [
        f"<li><b>{_e(note.get('query'))}</b><ul>"
        + "".join(f"<li>{_e(result)}</li>" for result in note.get("found") or [])
        + "</ul></li>"
        for note in step.get("live_lookup") or [] if isinstance(note, dict)
    ]
    if lookups:
        rows.append(("Live lookup", f"<ul class='policy-alts'>{''.join(lookups)}</ul>"))
    tstate = step.get("target_state") or (step.get("policy") or {}).get("target_state")
    if isinstance(tstate, dict) and tstate.get("reaction_tag"):
        ts_bits = [
            f"<span class='tag'>{_e(tstate.get('reaction_tag'))}</span>",
            f"stage: <b>{_e(tstate.get('engagement_stage'))}</b>",
        ]
        if tstate.get("blocked_mechanisms"):
            ts_bits.append(f"blocked: <span class='mono'>{_e(', '.join(tstate['blocked_mechanisms']))}</span>")
        if tstate.get("open_doors"):
            ts_bits.append(f"open doors: <span class='mono'>{_e(', '.join(tstate['open_doors']))}</span>")
        rows.append(("Target state", " · ".join(ts_bits)))
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


# One drawn icon family (24px grid, 1.8 stroke, currentColor) instead of emoji; replay.py uses the same paths.
ICON_PATHS = {
    "mail": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
    "phone": '<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/>',
    "chat": '<path d="M21 12a8 8 0 0 1-11.8 7L4 20l1.1-4.2A8 8 0 1 1 21 12z"/>',
    "clip": '<path d="m21 11-8.6 8.6a5 5 0 0 1-7-7l8.6-8.6a3.3 3.3 0 0 1 4.7 4.7l-8.6 8.6a1.7 1.7 0 0 1-2.4-2.4l7.9-7.9"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "lock": '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
}


def icon(name: str, size: int = 14) -> str:
    return (f"<svg class='svgi' viewBox='0 0 24 24' width='{size}' height='{size}' fill='none' stroke='currentColor' "
            f"stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'>{ICON_PATHS[name]}</svg>")


def _sentence(text: str, limit: int = 170) -> str:
    m = re.match(r"(.{20,}?[.!?])\s", text)
    s = m.group(1) if m else text
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def _why(a: dict) -> str:
    """The reasoning behind one touch, once. Actor runs store the same monologue as 'assessment' and 'rationale';
    printing both doubled every touch. Long reasoning folds to its first sentence."""
    read, move = str(a.get("assessment") or "").strip(), str(a.get("rationale") or "").strip()
    if not read or not move or " ".join(read.split()) == " ".join(move.split()):
        parts = [("Reasoning", read or move)]
    else:
        parts = [("Read", read), ("Move", move)]
    parts = [(k, v) for k, v in parts if v]
    if not parts:
        return ""
    if len(parts) == 1:
        full = _e(parts[0][1])
    else:
        full = "<br>".join(f"<b>{k}:</b> {_e(v)}" for k, v in parts)
    lead = _sentence(parts[0][1])
    if sum(len(v) for _, v in parts) <= len(lead) + 40:
        return f"<div class='why'><b>{parts[0][0]}:</b> {_e(parts[0][1])}" + (
            f"<br><b>{parts[1][0]}:</b> {_e(parts[1][1])}" if len(parts) > 1 else "") + "</div>"
    label = "Reasoning" if len(parts) == 1 else "Read and move"
    return (f"<details class='why'><summary><b>{label}</b><span class='lead'> · {_e(lead)}</span></summary>"
            f"<div class='full'>{full}</div></details>")


def _touch(step: dict, incidents: list[dict], target_id: str = "", hooks: dict | None = None) -> str:
    a = step.get("action") or {}
    n = step.get("touch")
    hit = [i for i in incidents if i["touch"] == n and not i.get("superseded")]
    old = [i for i in incidents if i["touch"] == n and i.get("superseded")]
    evs = step.get("events") or []
    replied = any(e.get("type") == "reply" for e in evs)
    confirmed_hit = any(_confirmed(i) for i in hit)
    cls = "hit" if confirmed_hit else ("est" if hit else ("replied" if replied else ""))
    snd = a.get("sender") or {}
    out = [f"<div class='touch {cls}' id='touch-{_e(n)}'><div class='tn'>{'✓' if confirmed_hit else '≈' if hit else _e(n)}</div>"]
    if a.get("decision") == "STOP" or step.get("decision") == "STOP":
        pol_html = _policy_html(step.get("policy"), "STOP")
        out.append(f"<div class='thead'><span class='badge'>STOP</span></div><div class='why'>{_e(a.get('rationale'))}</div>{pol_html}</div>")
        return "".join(out)
    chan_icon = icon("phone" if a.get("kind") == "call" else "mail" if a.get("channel") == "email" else "chat")
    tm = step.get("timing") or {}
    total = sum(v for v in tm.values() if isinstance(v, (int, float)))
    tm_html = f"<span class='timing mono'>{_secs(round(total, 1))}</span>" if tm else ""
    out.append(f"<div class='thead'><span class='chan'>{chan_icon} {_e(a.get('channel'))}</span><span class='badge'>{_e(a.get('decision'))}</span>"
               f"<span class='badge'>{_e(a.get('objective'))}</span><span class='mono'>hook {_e(a.get('hook_id'))}</span>{tm_html}</div>")
    actor = step.get("actor")
    monologue = str(actor.get("inner_monologue") or "").strip() if isinstance(actor, dict) else ""
    # actor runs store the monologue as assessment/rationale too; the actor panel already shows it
    if not monologue or {str(a.get("assessment") or "").strip(), str(a.get("rationale") or "").strip()} - {monologue, ""}:
        out.append(_why(a))
    pol_html = _policy_html(step.get("policy"), a.get("decision") or "")
    if pol_html:
        out.append(pol_html)
    out.append(_actor_html(actor, step.get("attempts")))
    twin_html = _shadow_twin_html(step.get("shadow_twin"), _actual_reaction(step, hit))
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
            head.append(f"· {icon('clip')} {_e(a['attachment_filename'])}")
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
    ledger_html = _ledger_badges_html(step.get("ledger_after"))
    if ledger_html:
        out.append(ledger_html)
    for i in hit:
        if _confirmed(i):
            out.append(f"<div class='incident'>✓ Incident · {_e(i['type'])}<span style='font-weight:400'>{_e(i['detail'])} "
                       f"(confirmed by an API event)</span></div>")
        else:
            out.append(f"<div class='incident est'>≈ Estimated incident · {_e(i['type'])}<span style='font-weight:400'>"
                       f"{_e(i['detail'])} (our judge's read of their reply; the API has not confirmed it)</span></div>")
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
    live_inc = _live_incidents(state)
    parts = []
    if live_inc:
        first = min(live_inc, key=lambda i: i["touch"])
        how = "confirmed by the API" if any(_confirmed(i) for i in live_inc) else "our estimate"
        parts.append(f"incident at touch {_e(first['touch'])} ({_e(first['type'])}, {how})")
    if state.get("error"):
        why = plain_error(state.get("error"))
        parts.append(("then stopped early: " if parts else "stopped early: ") + _e(why[:1].lower() + why[1:]))
    end = "; ".join(parts) or "no incident; the touch budget was used or the agent stopped on its last touch"
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


# "Full record | Conversation only": real buttons with a visible pressed state, remembered across pages and the live
# auto-refresh (the same key as the replay). Without JavaScript the control stays hidden and the full record shows.
_VIEW_JS = """<script>(function(){var bar=document.getElementById('viewbar'),card=document.getElementById('thread');
if(!bar||!card)return;bar.hidden=false;
function set(v,save){card.classList.toggle('convo-only',v==='convo');
bar.querySelectorAll('button[data-view]').forEach(function(b){b.setAttribute('aria-pressed',String(b.getAttribute('data-view')===v));});
if(save){try{localStorage.setItem('r8-view',v);}catch(e){}}}
var v='full';try{v=localStorage.getItem('r8-view')||'full';}catch(e){}set(v,false);
bar.addEventListener('click',function(e){var b=e.target.closest('button[data-view]');if(b)set(b.getAttribute('data-view'),true);});})();</script>"""


def render_run(path: Path, out_dir: Path | None = None) -> Path:
    state = json.loads(path.read_text(encoding="utf-8"))
    t = state.get("target", {})
    live = state.get("status") in ("starting", "running")
    cfg = state.get("config", {})
    rid = _e(state.get("run_id"))
    modes = (f"<nav class='seg' aria-label='How to view this run'><a aria-current='page' href='{_e(path.with_suffix('.html').name)}'>Read</a>"
             f"<a href='replay.html#run={rid}&amp;t=0' title='Step through the run one touch at a time'>Replay</a></nav>")
    head = (f"<div class='head' style='display:flex;gap:12px;align-items:center;flex-wrap:wrap'><h1>{_e(t.get('name'))}</h1>{_badge(state.get('status', ''))}"
            f"<span class='path'>{_e(decision_path(state))}</span><div class='spacer'></div>{modes}</div>"
            f"<p class='sub'>{_e(t.get('role'))} · scenario {_e(cfg.get('scenario_id'))} · session "
            f"<span class='mono'>{_e(state.get('session_id'))}</span> · started {_e(str(state.get('started_at', ''))[:16].replace('T', ' '))}</p>")
    error = ""
    if state.get("error"):
        raw = str(state.get("error") or "") + ("\n\n" + str(state["error_trace"]) if state.get("error_trace") else "")
        error = (f"<div class='card notice'><b>Stopped early after touch {_e(state.get('touches_used', 0))}.</b> "
                 f"{_e(plain_error(state['error']))}. Everything up to that point is below."
                 f"<details><summary>Technical details</summary><pre class='mono'>{_e(raw)}</pre></details></div>")
    hooks = {h["id"]: h for h in (state.get("brief") or {}).get("hooks", [])}
    steps = "".join(_touch(s, state.get("incidents", []), t.get("id", ""), hooks) for s in state.get("steps", []))
    view = ("<div class='viewbar' id='viewbar' hidden><span>Show</span><div class='seg' role='group' aria-label='What to show'>"
            "<button type='button' data-view='full' aria-pressed='true'>Full record</button>"
            "<button type='button' data-view='convo' aria-pressed='false'>Conversation only</button></div></div>")
    thread = (f"<div class='card' id='thread'><div style='display:flex;align-items:center;gap:14px;margin-bottom:12px;flex-wrap:wrap'><h2 style='margin:0'>Touches</h2>"
              f"<div class='spacer' style='flex:1'></div>{_strip(state, int(cfg.get('max_touches') or 10))}</div>{view}"
              f"<div class='tl' style='margin-top:16px'>{steps or '<div class=empty-state>Planning the campaign…</div>'}</div>{_LEGEND}</div>"
              + _VIEW_JS)
    body = (head + _run_tiles(state) + error + _casting_html(state.get("casting"))
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
    last3 = a["last3"]["contacts"]
    contacts = ("none reached an incident" if not any(x is not None for x in last3)
                else ", ".join("not reached" if x is None else str(x) for x in last3)) if last3 else "no runs yet"
    tiles = ("<div class='grid k4' style='margin-bottom:20px'>"
             + _tile("Expected results", f"{a['expected']['total']:g}<small> / 25</small>",
                     f"any 3 runs like practice · API-confirmed only: {c['expected']['total']:g}")
             + _tile("Last 3 runs", f"{a['last3']['total']:g}<small> / 25</small>", f"contacts to first incident: {contacts}")
             + _tile("Runs with an incident", f"{a['incident_runs']}<small> / {sc['runs']}</small>",
                     f"{c['incident_runs']} confirmed by the API · {a['incident_runs'] - c['incident_runs']} estimated · "
                     f"{sc['runs']} of {sc['runs_total']} runs counted" + _uncounted_note(states))
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


_FONTS = Path(__file__).parent / "assets" / "fonts"


def _copy_fonts(out_dir: Path) -> None:
    """The stylesheet loads fonts/<file>.woff2 relative to the page, so pages open from disk with no network."""
    import shutil

    dst = out_dir / "fonts"
    dst.mkdir(parents=True, exist_ok=True)
    for f in _FONTS.glob("*.woff2"):
        shutil.copyfile(f, dst / f.name)
    # three.js is self-hosted so the landing page's 3D backdrop works offline and from file://.
    three = _FONTS.parent / "three.min.js"
    if three.exists():
        shutil.copyfile(three, out_dir / "three.min.js")


def _home_stats(states: list[dict], card: dict) -> dict:
    """The landing page's "Honest numbers" section: reply-rate bars per target and a few plain sentences. Same
    counting rule as every page (scorecard.compute); confirmed and estimated incidents stay apart."""
    a, c = card["views"]["all"], card["views"]["confirmed"]
    counted = card["runs"]
    bars = sorted(((str(r["name"]).split(" ")[0], r["reply_rate"],
                    f"{r['name']}: {r['replies']} replies across {r['touches']} touches")
                   for r in card["per_target"].values()), key=lambda b: -b[1])
    inc, conf = a["incident_runs"], c["incident_runs"]
    est = inc - conf
    median = a["median_contacts_when_reached"]
    touches = sum(int(st.get("touches_used") or 0) for st in states)
    replies = sum(1 for st in states for s in st.get("steps", []) for e in s.get("events") or [] if e.get("type") == "reply")
    out = []
    if counted:
        out.append(f"<p>{inc} of {counted} finished runs reached an incident.<span> Runs that stopped early are not counted.</span></p>")
    if conf and est:
        out.append(f"<p>{conf} confirmed by the revel8 API.<span> {est} more are our judge's estimate from the target's own words.</span></p>")
    elif conf:
        out.append(f"<p>{'Both' if conf == 2 else 'All ' + str(conf)} confirmed by the revel8 API.</p>")
    elif inc:
        out.append("<p>None confirmed by the API yet.<span> Each is our judge's estimate from the target's own reply.</span></p>")
    if median is not None:
        out.append(f"<p>{median:g} touches to the first incident<span>, the median when one was reached.</span></p>")
    if touches:
        out.append(f"<p>{replies} replies<span> across {touches} touches, every one answered in character.</span></p>")
    return {"bars": bars, "sentences": "".join(out)}


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
    from .report_replay import render_replay
    render_replay(states, out_dir, lambda *a: _page(*a, active="replay.html"), redact=public)

    for f, _ in loaded:
        render_run(f, out_dir)
    from .scorecard import compute as scorecard_compute

    scores = [estimate_score(st) for st in states]
    n = len(states)
    # One counting rule on every page: the scorecard's (finished runs with at least one touch). Runs that stopped early
    # or are still live are listed below but not counted, and the tiles say so.
    card = scorecard_compute(states)
    a_view, c_view = card["views"]["all"], card["views"]["confirmed"]
    counted = card["runs"]
    stopped = sum(st.get("status") == "error" for st in states)
    running = sum(st.get("status") in ("starting", "running") for st in states)
    median = a_view["median_contacts_when_reached"]
    touches = sum(st.get("touches_used", 0) for st in states)
    replies = sum(1 for st in states for s in st.get("steps", []) for e in s.get("events") or [] if e.get("type") == "reply")
    live = running > 0
    withdrawn = sum(1 for st in states for i in st.get("incidents", []) if i.get("superseded"))
    estimated_runs = a_view["incident_runs"] - c_view["incident_runs"]

    runs_foot = " · ".join(x for x in (f"{counted} counted", f"{stopped} stopped early" if stopped else "",
                                       f"{running} live" if running else "") if x)
    inc_foot = (f"{c_view['incident_runs']} confirmed by the API"
                + (f" · {estimated_runs} estimated" if estimated_runs else "")
                + _uncounted_note(states)
                + (f" · {withdrawn} withdrawn" if withdrawn else ""))
    tiles = ("<div class='grid k4' style='margin-bottom:20px'>"
             + _tile("Runs", str(n), runs_foot)
             + _tile("Runs with an incident", f"{a_view['incident_runs']}<small> / {counted}</small>", inc_foot)
             + _tile("Median touches to incident", _e(median if median is not None else "—"), "counted runs · fewer is better (speed, 5 pts)")
             + _tile("Replies", str(replies), f"across {touches} touches")
             + "</div>")

    rows = []
    for (f, st), sc in zip(loaded, scores):
        plan = st.get("plan") or {}
        if sc["incident"]:
            inc = _incident_badge(sc)
        elif any(i.get("superseded") for i in st.get("incidents", [])):
            inc = "<span class='badge'>withdrawn</span>"
        else:
            inc = "<span class='mono'>—</span>"
        is_counted = st.get("status") == "done" and int(st.get("touches_used") or 0) > 0
        pts = (f"<b>{sc['results_points']:g}</b><span class='mono'> / 25</span>" if is_counted or st.get("status") in ("running", "starting")
               else f"<span style='color:var(--muted)'>{sc['results_points']:g}</span><span class='mono'> / 25</span>"
                    "<div class='note' title='Only finished runs count, on this page and on Score'>not counted</div>")
        status_tip = f" title='{_e(plain_error(st.get('error')))}'" if st.get("status") == "error" else ""
        rid = _e(st.get("run_id"))
        rows.append(f"<tr><td><a href='{_e(f.with_suffix('.html').name)}'><b>{_e(st.get('target', {}).get('name'))}</b></a>"
                    f"<div class='mono runid'>{rid} · <a href='replay.html#run={rid}&amp;t=0'>replay</a></div></td>"
                    f"<td><span{status_tip}>{_badge(st.get('status', ''))}</span><div class='path' style='margin-top:4px'>"
                    f"{_e(decision_path(st))}</div></td>"
                    f"<td>{_e((plan.get('persona') or {}).get('organisation'))}<div class='note'>{_e(plan.get('objective'))}</div></td>"
                    f"<td>{_strip(st, int(st.get('config', {}).get('max_touches') or 10))}</td>"
                    f"<td>{inc}</td><td class='num' style='white-space:nowrap'>{pts}</td></tr>")
    table = ("<div class='card'><h2>Runs · open one to read it, or replay it touch by touch</h2>" + ("<table><thead><tr><th>Target</th>"
             "<th>Status · decision path</th><th>Persona · objective</th>"
             "<th>Touches</th><th>Incident</th><th class='num'>Est. results</th></tr></thead><tbody>" + "".join(rows)
             + "</tbody></table>" + _LEGEND if rows else "<div class='empty-state'>No runs yet. Start one with "
             "<span class='mono'>python -m revel8_agent.cli run --target julius</span></div>") + "</div>")

    chart = ("<div class='card'><h2>Response rate by target</h2>" + _reply_bars(states)
             + "<p class='note' style='margin:14px 0 0'>Share of touches that got a reply or an answered call.</p></div>")
    about = ("<div class='card'><h2>How the score is estimated</h2><p style='font-size:13px;color:var(--text-2);margin:0'>"
             "Measured locally. <b>✓ Confirmed</b>: the API reported a submitted landing page or an opened attachment. "
             "<b>≈ Estimate</b>: our judge read a disclosure or action in the target's own words; the API has not confirmed it. "
             "Counted runs are finished runs with at least one touch, the same rule as the Score page; runs that stopped "
             "early are listed but not counted. Results = 20 if the run reached an incident + up to 5 for speed "
             "(vs. a team needing 2 contacts). Targeting, craft and the jury's 55 points are not visible here. "
             "<a href='score.html'>Full scorecard →</a> · <a href='how.html'>How the agent works →</a></p></div>")
    body = ("<h1>All runs</h1><p class='sub'>Practice runs against the revel8 targets. Start with "
            "<a href='how.html'><b>How it works</b></a>, look at the research per target, then open any run to replay every touch.</p>"
            + tiles + f"<div class='grid split' style='margin-bottom:20px'>{chart}{about}</div>" + table)
    (out_dir / "runs.html").write_text(
        _page("revel8 agent · all runs", "", body, live and not public, active="runs.html"), encoding="utf-8")

    # The landing page is index.html: the featured run as a playable 3D score, the rest read in one sweep.
    from .report_home import render_home

    stats = _home_stats(states, card)
    out = render_home(states, out_dir, lambda *a: _page(*a, active="index.html"), stats, _TARGETS)
    _copy_fonts(out_dir)
    _REDACT = False
    return out
