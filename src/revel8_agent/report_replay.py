"""Replay: step through a run one touch at a time and see what the agent saw, thought and did.

    python -m revel8_agent.cli report        # writes runs/replay.html with the rest of the dashboard

The jury asked for a UI that shows "what your agents decided to do, when and how and why", the options they
discarded and when a channel was burned (kickoff Q&A 04:20, 11:00-11:40), plus an internal renderer to check how
the mails and pages look (04:00). This page is that view, built from the run JSONs alone:

* summary header: outcome, chosen angle, persona and the touch timeline (channel lanes), readable in seconds;
* step 0 is the casting (chosen hook up front, the other hooks and rejected casts folded away);
* left: the attacker's mind (decision, inner monologue, drafts the guardrails bounced, options dropped, notes);
* centre: what the target sees, rendered per channel (mail client, phone chat, call, landing page in a browser),
  then their reaction or their silence and how the agent read it;
* right: one persona profile, the route board, and the mood and notebook as activity feeds.

One static file, no server, no dependencies; it works from file://. Landing pages run in sandboxed iframes with
scripts disabled. Public snapshots (report --public) drop the landing-page HTML, like the run pages do.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

_PAGE_HTML_MAX = 250_000  # a landing page bigger than this is listed, not rendered


def _s(x: Any) -> str:
    return "" if x is None else str(x)


def _sender(a: dict, payload: dict) -> dict:
    snd = a.get("sender") if isinstance(a.get("sender"), dict) else {}
    frm = payload.get("from") if isinstance(payload.get("from"), dict) else {}
    return {"name": _s(snd.get("name") or frm.get("name")), "address": _s(frm.get("address") or snd.get("address"))}


def _step(step: dict, redact: bool) -> dict:
    a = step.get("action") or {}
    payload = step.get("payload") or {}
    page = step.get("page") if isinstance(step.get("page"), dict) else None
    if page:
        html = _s(page.get("html"))
        page = {"url": _s(page.get("url")), "title": _s(page.get("title")), "fields": list(page.get("fields") or []),
                "html": "" if redact or len(html) > _PAGE_HTML_MAX else html}
    link = a.get("link")
    if isinstance(link, str):
        link = {"url": link}
    elif not (isinstance(link, dict) and link.get("url")):
        link = None
    actor = step.get("actor") if isinstance(step.get("actor"), dict) else {}
    mind = _s(a.get("inner_monologue") or actor.get("inner_monologue") or a.get("assessment"))
    rationale = _s(a.get("rationale"))
    return {
        "n": step.get("touch"),
        "at": _s(step.get("at")),
        "decision": _s(a.get("decision") or step.get("decision")),
        "kind": _s(a.get("kind") or "message"),
        "channel": _s(a.get("channel") or payload.get("channel")),
        "objective": _s(a.get("objective")),
        "hook": _s(a.get("hook_id")),
        "sender": _sender(a, payload),
        "subject": _s(payload.get("subject") or a.get("subject")),
        "body": _s(payload.get("body")) or "\n\n".join(_s(p) for p in a.get("paragraphs") or []),
        "headline": _s(a.get("headline")),
        "cta": _s(a.get("cta_label")),
        "link": link,
        "attachment": _s(a.get("attachment_filename")),
        "page": page,
        "call_goal": _s(a.get("call_goal")),
        "transcript": [{"who": _s(t.get("who")), "text": _s(t.get("text"))}
                       for t in step.get("transcript") or [] if isinstance(t, dict)],
        "call_notes": step.get("call_notes") or [],
        "mind": mind,
        "rationale": rationale if rationale and rationale != mind else "",
        "notes": [_s(n) for n in a.get("note_to_self") or []],
        "discarded": [_s(d) for d in a.get("discarded") or []],
        "attempts": [{"try": x.get("try"), "decision": _s(x.get("decision")), "kind": _s(x.get("kind")),
                      "channel": _s(x.get("channel")), "errors": [_s(e) for e in x.get("errors") or []]}
                     for x in step.get("attempts") or [] if isinstance(x, dict)],
        "cited": [_s(c) for c in a.get("cited_fact_ids") or []],
        "lookups": [{"query": _s(x.get("query")), "found": [_s(f) for f in (x.get("found") or [])[:3]]}
                    for x in step.get("live_lookup") or [] if isinstance(x, dict)],
        "events": [{k: e.get(k) for k in ("type", "channel", "subject", "body", "url", "filename", "fields") if e.get(k)}
                   for e in step.get("events") or [] if isinstance(e, dict)],
        "judge": {k: (step.get("judge") or {}).get(k) for k in
                  ("sentiment", "reason", "disclosure", "action", "evidence", "evidence_verified")},
        "policy": step.get("policy") if isinstance(step.get("policy"), dict) else None,
        "twin": step.get("shadow_twin") if isinstance(step.get("shadow_twin"), dict) else None,
        "ledger": step.get("ledger_after") if isinstance(step.get("ledger_after"), dict) else None,
        "timing": step.get("timing") if isinstance(step.get("timing"), dict) else {},
        "error": _s(step.get("error")),
    }


def compact_run(state: dict, redact: bool = False) -> dict:
    """The fields the replay needs from one run JSON, nothing else (keeps the page small)."""
    brief = state.get("brief") or {}
    plan = state.get("plan") or {}
    persona = plan.get("persona") or {}
    character = plan.get("character") or {}
    cfg = state.get("config") or {}
    return {
        "id": _s(state.get("run_id")),
        "status": _s(state.get("status")),
        "label": _s(cfg.get("label")),
        "policy": _s(cfg.get("policy") or plan.get("architecture")),
        "max_touches": int(cfg.get("max_touches") or 10),
        "started": _s(state.get("started_at")),
        "target": state.get("target") or {},
        "facts": [{k: f.get(k) for k in ("id", "fact", "category", "timing", "recency")}
                  for f in brief.get("facts") or [] if isinstance(f, dict)],
        "hooks": [{k: h.get(k) for k in ("id", "topic", "rationale", "confidence", "timing", "is_own_angle")}
                  for h in brief.get("hooks") or [] if isinstance(h, dict)],
        "plan": {"hook_id": _s(plan.get("hook_id")), "objective": _s(plan.get("objective")),
                 "language": _s(plan.get("language")), "rationale": _s(plan.get("rationale")),
                 "pretext": _s(plan.get("pretext"))},
        "persona": {k: _s(persona.get(k)) for k in ("name", "organisation", "role", "email", "website_domain",
                                                     "brand_color", "story")},
        "character": {k: character.get(k) for k in ("who", "why_them", "need", "artifact", "first_small_yes",
                                                     "deadline", "deadline_reason", "voice", "would_never",
                                                     "unblocks_me")},
        "plan_attempts": [{k: x.get(k) for k in ("attempt", "domain", "persona", "organisation", "hook_id", "rejected")}
                          for x in state.get("plan_attempts") or [] if isinstance(x, dict)],
        "notebook": [{"touch": n.get("touch", 0), "note": _s(n.get("note"))}
                     for n in plan.get("notebook") or [] if isinstance(n, dict)],
        "steps": [_step(s, redact) for s in state.get("steps") or []],
        "incidents": [{k: i.get(k) for k in ("touch", "type", "detail", "source", "superseded", "superseded_reason")}
                      for i in state.get("incidents") or [] if isinstance(i, dict)],
        "error": _s(state.get("error")),
        "touches_used": state.get("touches_used"),
        "llm_calls": state.get("llm_calls"),
    }


def _json_for_script(data: Any) -> str:
    # inside <script type="application/json">: "</" would close the tag early; "\/" is a valid JSON escape
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")


def render_replay(states: list[dict], out_dir: Path, page: Callable[..., str], redact: bool = False) -> Path:
    from .report import ICON_PATHS

    runs = [compact_run(st, redact) for st in states if st.get("run_id")]
    body = (f"<style>{_CSS}</style>"
            f"<script type='application/json' id='rp-data'>{_json_for_script(runs)}</script>"
            f"{_SHELL}<script>{_JS.replace('__ICON_PATHS__', _json_for_script(ICON_PATHS))}</script>")
    out = out_dir / "replay.html"
    out.write_text(page("Replay · revel8 agent", "", body, False), encoding="utf-8")
    return out


_SHELL = """
<div class="rp" id="rp">
  <header class="rp-hero" aria-label="Run summary">
    <div class="rp-bar">
      <label class="rp-pick"><span class="rp-lbl">Run</span><select id="rp-run"></select></label>
      <nav class="seg" aria-label="How to view this run"><a id="rp-read" href="index.html">Read</a><a id="rp-self" aria-current="page" href="#">Replay</a></nav>
      <div class="rp-ctl">
        <button type="button" id="rp-prev" title="Previous touch (←)" aria-label="Previous touch">‹</button>
        <button type="button" id="rp-play" title="Play / pause (space)" aria-label="Play">▶</button>
        <button type="button" id="rp-next" title="Next touch (→)" aria-label="Next touch">›</button>
        <span class="rp-stepname" id="rp-stepname"></span>
      </div>
      <div class="seg" role="group" aria-label="What to show" id="rp-view">
        <button type="button" data-view="full" aria-pressed="true">Full record</button>
        <button type="button" data-view="convo" aria-pressed="false">Conversation only</button>
      </div>
    </div>
    <div class="rp-summary" id="rp-summary"></div>
    <div class="rp-timeline">
      <div class="rp-timeline-h"><span class="rp-lbl">Touch timeline</span><div class="rp-legend" id="rp-legend"></div></div>
      <div id="rp-lanes" class="rp-lanes"></div>
    </div>
  </header>
  <div class="rp-cols" id="rp-cols">
    <section class="rp-col rp-mind" aria-label="The attacker's mind"><div class="rp-colh">Attacker's reasoning</div><div id="rp-mind"></div></section>
    <section class="rp-col rp-stage" aria-label="What the target sees"><div class="rp-colh" id="rp-stage-h">What the target sees</div><div id="rp-stage"></div></section>
    <section class="rp-col rp-state" aria-label="Campaign"><div class="rp-colh">Campaign</div><div id="rp-state"></div></section>
  </div>
  <div id="rp-tip" class="rp-tip" role="tooltip" hidden></div>
</div>
"""

_CSS = """
/* fixed top navigation: never floats over content */
.nav{position:fixed;top:0;left:0;right:0;z-index:30;background:#0b1720;backdrop-filter:none;border-bottom:1px solid #ffffff14}
.nav-in{max-width:1560px;flex-wrap:nowrap;padding:10px 28px;gap:16px}
.tabs{flex:1;min-width:0;overflow-x:auto;scrollbar-width:none;margin-left:8px}.tabs::-webkit-scrollbar{display:none}
.tabs a{white-space:nowrap}.nav .spacer,.nav .crumb{display:none}
body{padding-top:56px}
.page{max-width:1560px;padding:24px 28px 48px}
:root{--rp-line:color-mix(in srgb,var(--border) 65%,transparent)}
:root[data-theme=dark]{--muted:var(--n40,#9ba1a6);--text-2:var(--n20)}
.rp-hero{border-color:transparent}
.rp{--gap:20px;font-size:14.5px;line-height:1.6;min-width:0}
.rp-lbl{font-size:12.5px;font-weight:500;color:var(--text-2)}
/* --- summary header --- */
.rp-hero{background:var(--surface);border:1px solid var(--rp-line);border-radius:16px;padding:18px 24px 14px;margin-bottom:var(--gap)}
.rp-bar{display:flex;flex-wrap:wrap;align-items:center;gap:12px 20px;padding-bottom:14px;border-bottom:1px solid var(--rp-line)}
.rp-pick{display:flex;align-items:center;gap:10px;min-width:0}
.rp select{font:inherit;font-size:13.5px;background:var(--surface-2);color:var(--text);border:1px solid var(--rp-line);border-radius:8px;
padding:6px 10px;max-width:min(440px,70vw);min-width:0}
.rp-ctl{display:flex;gap:6px;align-items:center;margin-left:auto}
.rp-ctl button{font:inherit;font-size:16px;line-height:1;width:34px;height:34px;border-radius:9px;border:1px solid var(--rp-line);
background:var(--surface-2);color:var(--text);cursor:pointer}
.rp-ctl button:hover:not(:disabled){border-color:var(--text-2)}.rp-ctl button:disabled{opacity:.35;cursor:default}
.rp-ctl button:focus-visible,.rp select:focus-visible,.rp summary:focus-visible,.rp-feed button:focus-visible{outline:2px solid var(--s1);outline-offset:2px}
.rp-stepname{font-size:13px;color:var(--text-2);min-width:120px;margin-left:6px;font-variant-numeric:tabular-nums}
.rp-stepname b{color:var(--text)}
.rp-switch{display:inline-flex;gap:8px;align-items:center;font-size:13px;color:var(--text-2);cursor:pointer}
.rp-summary{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1.2fr) minmax(0,1fr);gap:24px;padding:18px 0}
.rp-sum h1{font-size:24px;margin:2px 0 2px;letter-spacing:-.02em;line-height:1.2}
.rp-sum .rp-subt{color:var(--text-2);font-size:13.5px}
.rp-sum .val{font-size:16px;font-weight:600;color:var(--text);margin-top:4px;line-height:1.35}
.rp-sum .meta{color:var(--text-2);font-size:13px;margin-top:4px}
.rp-status{display:inline-flex;align-items:center;gap:8px;margin-top:10px;font-size:14px;font-weight:650;padding:5px 12px;border-radius:999px;
background:var(--surface-2);color:var(--text)}
.rp-status.hit{background:var(--good-bg);color:var(--good-text)}.rp-status.err{background:var(--crit-bg);color:var(--crit)}
.rp-status.live{background:var(--accent-bg);color:var(--accent-text)}
.rp-stats{display:flex;flex-wrap:wrap;gap:6px 16px;margin-top:10px;font-size:13px;color:var(--text-2)}
.rp-stats b{color:var(--text);font-variant-numeric:tabular-nums}
.rp-who{display:flex;gap:12px;align-items:center;margin-top:6px}
.rp-timeline{border-top:1px solid var(--rp-line);padding-top:12px}
.rp-timeline-h{display:flex;flex-wrap:wrap;gap:6px 18px;align-items:center}
.rp-legend{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12px;color:var(--text-2)}
.rp-legend span{display:inline-flex;gap:5px;align-items:center}
.rp-lanes{overflow-x:auto;margin-top:4px}
.rp-lanes svg{display:block;font-family:inherit}
.rp-lanes .lane-lbl{font-size:12px;fill:var(--text-2)}
.rp-lanes .tick{font-size:11px;fill:var(--text-2);font-variant-numeric:tabular-nums}
.rp-lanes .grid{stroke:var(--rp-line);stroke-width:1}
.rp-lanes .path{fill:none;stroke:var(--muted);stroke-width:2;opacity:.5}
.rp-lanes .col-hit{fill:transparent;cursor:pointer}
.rp-lanes .col-cur{fill:var(--accent-bg)}
.rp-lanes .mk{stroke:var(--surface);stroke-width:2}
.rp-lanes .mk-silent{fill:var(--surface);stroke:var(--muted);stroke-width:2}
.rp-lanes .mk-reply{fill:var(--s1)}.rp-lanes .mk-event{fill:var(--s2)}.rp-lanes .mk-call{fill:var(--s3)}.rp-lanes .mk-hit{fill:var(--good)}
.rp-lanes .mk-x{stroke:var(--crit);stroke-width:2.2;stroke-linecap:round}
.rp-lanes .hitglyph{font-size:10px;font-weight:800;fill:#fff;pointer-events:none}
.rp-lanes .mk-est{fill:var(--warn-text)}
.rp-lanes .estglyph{font-size:11px;font-weight:800;fill:var(--surface);pointer-events:none}
.rp-status.est{background:var(--warn-bg);color:var(--warn-text)}.rp-status.stop{background:var(--warn-bg);color:var(--warn-text)}
.rp-incident.est{background:var(--warn-bg);color:var(--warn-text)}
.rp-stop{background:var(--warn-bg);color:var(--text);border-radius:12px;padding:10px 14px;font-size:13.5px;width:100%;box-sizing:border-box}
.rp-stop b{color:var(--warn-text)}.rp-stop pre{white-space:pre-wrap;word-break:break-word;font-size:12px;margin:8px 0 0}
.rp-lanes .rej{font-size:10.5px;fill:var(--crit);font-weight:700}
/* --- columns --- */
.rp-cols{display:grid;grid-template-columns:minmax(0,.95fr) minmax(0,1.35fr) minmax(0,.9fr);gap:var(--gap);align-items:start}
.rp.convo .rp-cols{grid-template-columns:minmax(0,1.4fr) minmax(0,.8fr)}.rp.convo .rp-mind{display:none}
.rp-col{min-width:0;display:flex;flex-direction:column;gap:12px}
.rp-col>div:last-child{display:flex;flex-direction:column;gap:var(--gap)}
.rp-colh{font-size:14px;font-weight:600;color:var(--text);padding:0 4px}
.rp-sec{background:var(--surface);border:1px solid var(--rp-line);border-radius:14px;padding:20px 22px;min-width:0}
.rp-sec>h3{font-size:13px;font-weight:650;color:var(--text);margin:0 0 12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.rp-sec p{margin:0 0 10px}.rp-sec p:last-child{margin-bottom:0}
.rp-chip{display:inline-flex;align-items:center;gap:5px;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600;white-space:nowrap;
background:var(--surface-2);color:var(--text)}
.rp-chip.good{background:var(--good-bg);color:var(--good-text)}.rp-chip.crit{background:var(--crit-bg);color:var(--crit)}
.rp-chip.id{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:500;color:var(--text-2)}
.rp-dim{color:var(--text-2);font-size:13px}
.rp-mono{font-family:"Geist Mono",ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;color:var(--text-2)}
.rp-quote{font-size:14px;line-height:1.65;color:var(--text);background:var(--paper);border-radius:var(--radius-s);padding:12px 14px;margin:0}
.rp-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:10px;font-size:13.5px}
.rp-list li{display:flex;gap:10px;align-items:flex-start}
.rp-list .ic{flex:none;width:16px;text-align:center;color:var(--text-2)}
.rp-closed,.rp-list .ic.crit{color:var(--crit)}
.rp details{border-top:1px solid var(--rp-line);margin-top:14px;padding-top:12px}
.rp details.bare{border:0;margin:0;padding:0}
.rp summary{cursor:pointer;list-style:none;font-size:13.5px;font-weight:600;color:var(--text);display:flex;gap:8px;align-items:center}
.rp summary::-webkit-details-marker{display:none}
.rp summary::before{content:"";width:7px;height:7px;border-right:2px solid var(--text-2);border-bottom:2px solid var(--text-2);
transform:rotate(-45deg);transition:transform .15s;flex:none;margin-right:2px}
.rp details[open]>summary::before{transform:rotate(45deg)}
.rp details>div{margin-top:12px}
.rp-rej{background:var(--crit-bg);border-radius:var(--radius-s);padding:8px 12px;font-size:13px}
.rp-rej b{color:var(--crit)}.rp-rej ul{margin:4px 0 0;padding-left:18px;color:var(--text)}
.rp-sent{display:flex;gap:8px;align-items:center;font-size:13.5px}
.rp-alt{background:var(--paper);border:1px solid var(--rp-line);border-radius:var(--radius-s);padding:8px 12px;font-size:13px;color:var(--text)}
.rp-alt.sel{border-left-color:var(--good)}
.rp-hook{padding:12px 0;border-top:1px solid var(--rp-line)}.rp-hook:first-child{border-top:0;padding-top:0}
.rp-hook .t{font-weight:600;font-size:13.5px}.rp-hook .r{color:var(--text-2);font-size:13px;margin-top:3px}
.rp-chosen{border-radius:12px;padding:18px 20px;background:color-mix(in srgb,var(--good-bg) 55%,var(--surface));
border:1px solid color-mix(in srgb,var(--good) 35%,transparent)}
.rp-chosen h2{font-size:19px;line-height:1.3;color:var(--text);margin:8px 0 6px;font-weight:650}
.rp-chosen .r{color:var(--text);font-size:14px;margin:0}
.rp-meter{display:inline-flex;gap:8px;align-items:center;font-size:12.5px;color:var(--text-2)}
.rp-meter i{display:inline-block;width:70px;height:6px;border-radius:3px;background:var(--surface-2);overflow:hidden;position:relative}
.rp-meter i::after{content:"";position:absolute;inset:0 auto 0 0;width:var(--v);background:var(--good);border-radius:3px}
.rp-funnel{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:13px;color:var(--text-2);margin-bottom:14px}
.rp-funnel b{color:var(--text);font-size:15px}
/* --- channel renders --- */
.rp-step-h{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:14px}
.rp-step-h .big{font-size:18px;font-weight:650;letter-spacing:-.01em}
.rp-win{border:1px solid #e5e7eb;border-radius:12px;overflow:hidden;background:#fff;color:#111827;box-shadow:0 8px 28px rgba(0,0,0,.14)}
.rp-win-bar{display:flex;align-items:center;gap:6px;padding:8px 12px;background:#f3f4f6;border-bottom:1px solid #e5e7eb;font-size:12px;color:#6b7280}
.rp-win-bar i{width:10px;height:10px;border-radius:50%;background:#d1d5db;display:inline-block}
.rp-win-bar .ttl{margin-left:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rp-mail-h{padding:16px 20px 12px;border-bottom:1px solid #eef0f3}
.rp-mail-subj{font-size:17px;font-weight:650;margin:0 0 12px;color:#111827}
.rp-mail-from{display:flex;gap:10px;align-items:center;font-size:13px}
.rp-ava{flex:none;width:36px;height:36px;border-radius:50%;display:grid;place-items:center;color:#fff;font-weight:650;font-size:13px;background:#475569}
.rp-ava.lg{width:46px;height:46px;font-size:16px}
.rp-mail-from .who{display:flex;flex-direction:column;min-width:0}
.rp-mail-from .addr{color:#6b7280;font-size:12px;overflow-wrap:anywhere}
.rp-mail-from .when{margin-left:auto;color:#6b7280;font-size:12px;white-space:nowrap}
.rp-mail-b{padding:18px 20px 20px;font:14px/1.65 "Segoe UI",Helvetica,Arial,sans-serif;white-space:pre-wrap;overflow-wrap:anywhere;color:#111827}
.rp-cta{display:inline-block;margin:0 20px 16px;background:#1d4ed8;color:#fff;border-radius:6px;padding:9px 16px;font-size:13.5px;font-weight:600;
font-family:"Segoe UI",Helvetica,Arial,sans-serif}
.rp-urlpeek{margin:-8px 20px 16px;font-size:11.5px;color:#6b7280;font-family:ui-monospace,Menlo,monospace;overflow-wrap:anywhere}
.rp-att{display:inline-flex;align-items:center;gap:8px;margin:0 20px 18px;border:1px solid #e5e7eb;border-radius:8px;padding:8px 12px;font-size:13px;background:#f9fafb}
.rp-frame{display:block;width:100%;height:460px;border:0;background:#fff}
.rp-browser .rp-url{flex:1;display:flex;gap:6px;align-items:center;background:#fff;border:1px solid #e5e7eb;border-radius:999px;padding:4px 12px;
font-family:ui-monospace,Menlo,monospace;font-size:12px;color:#374151;min-width:0}
.rp-browser .rp-url span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.rp-browser .rp-url b{color:#111827}
.rp-fields{padding:8px 12px;border-top:1px solid #e5e7eb;font-size:12px;color:#4b5563;background:#f9fafb}
.rp-phone{max-width:420px;margin:0 auto;border-radius:26px;border:8px solid #111827;background:#e5ddd5;overflow:hidden}
.rp-phone.sms{background:#fff}
.rp-phone-h{display:flex;gap:10px;align-items:center;padding:10px 12px;background:#075e54;color:#fff;font-size:13px}
.rp-phone.sms .rp-phone-h{background:#f3f4f6;color:#111827;border-bottom:1px solid #e5e7eb}
.rp-phone-h small{display:block;opacity:.85;font-size:11px}
.rp-bubbles{display:flex;flex-direction:column;gap:6px;padding:12px;min-height:220px;max-height:560px;overflow:auto}
.rp-bub{max-width:82%;padding:7px 10px;border-radius:10px;font:13.5px/1.45 "Segoe UI",Helvetica,Arial,sans-serif;white-space:pre-wrap;
overflow-wrap:anywhere;box-shadow:0 1px 1px rgba(0,0,0,.08);color:#111827}
.rp-bub.out{align-self:flex-end;background:#dcf8c6}.rp-bub.in{align-self:flex-start;background:#fff}
.rp-phone.sms .rp-bub.out{background:#2563eb;color:#fff}.rp-phone.sms .rp-bub.in{background:#e5e7eb}
.rp-bub.old{opacity:.55}.rp-bub .meta{display:block;font-size:10.5px;color:#6b7280;margin-top:2px;text-align:right}
.rp-phone.sms .rp-bub.out .meta{color:#dbeafe}
.rp-call{border:1px solid var(--rp-line);border-radius:12px;overflow:hidden}
.rp-call-h{display:flex;gap:12px;align-items:center;padding:14px 16px;background:color-mix(in srgb,var(--s3) 14%,var(--surface))}
.rp-call-h .rp-ava{background:var(--s3)}
.rp-call-b{display:flex;flex-direction:column;gap:8px;padding:16px}
.rp-line{max-width:84%;padding:9px 13px;border-radius:12px;font-size:14px;white-space:pre-wrap}
.rp-line.agent{align-self:flex-end;background:var(--surface-2)}.rp-line.target{align-self:flex-start;background:var(--accent-bg)}
.rp-line .who{display:block;font-size:11.5px;font-weight:650;color:var(--text-2)}
.rp-react-in{border:1px solid color-mix(in srgb,var(--s1) 35%,transparent);background:var(--accent-bg);border-radius:var(--radius);padding:12px 16px;
white-space:pre-wrap;font-size:14px;overflow-wrap:anywhere;width:100%;box-sizing:border-box}
.rp-react-in .who{display:block;font-size:12.5px;font-weight:650;color:var(--accent-text);margin-bottom:4px;white-space:normal}
.rp-evt{display:inline-flex;gap:8px;align-items:center;font-size:13px;padding:4px 10px;border-radius:999px;background:color-mix(in srgb,var(--s2) 16%,transparent)}
.rp-evt::before{content:"";width:9px;height:9px;border-radius:2px;background:var(--s2)}
.rp-silence{border:1px dashed var(--rp-line);border-radius:12px;padding:16px;color:var(--text-2);font-size:13.5px;text-align:center;width:100%;box-sizing:border-box}
.rp-read{font-size:13.5px;color:var(--text)}
.rp-incident{display:flex;gap:10px;align-items:flex-start;background:var(--good-bg);color:var(--good-text);border-radius:12px;padding:12px 16px;
font-size:13.5px;font-weight:550;width:100%;box-sizing:border-box}
.rp-withdrawn{background:var(--surface-2);color:var(--text-2);border-radius:12px;padding:10px 14px;font-size:13px}
.rp-err{background:var(--crit-bg);color:var(--crit);border-radius:12px;padding:10px 14px;font-size:13.5px;width:100%;box-sizing:border-box}
/* --- persona profile --- */
.rp-profile-h{display:flex;gap:14px;align-items:center;margin-bottom:16px}
.rp-profile-h .n{font-size:16px;font-weight:650}
.rp-kv{display:grid;grid-template-columns:92px minmax(0,1fr);gap:10px 14px;font-size:13.5px;margin:0}
.rp-kv dt{color:var(--text-2);font-size:12.5px;padding-top:1px}.rp-kv dd{margin:0;overflow-wrap:anywhere;color:var(--text)}
.rp-routes{display:flex;flex-direction:column;gap:8px;font-size:13.5px}
.rp-route{display:flex;gap:10px;align-items:center}
.rp-route .sw{flex:none;width:10px;height:10px;border-radius:3px}
.rp-route .cnt{margin-left:auto;color:var(--text-2);font-variant-numeric:tabular-nums;font-size:12.5px;white-space:nowrap}
/* --- activity feeds (mood, notebook) --- */
.rp-feed{list-style:none;margin:0;padding:0;position:relative}
.rp-feed::before{content:"";position:absolute;left:15px;top:8px;bottom:8px;width:1px;background:var(--rp-line)}
.rp-feed>li{position:relative;padding:0 0 14px 40px}.rp-feed>li:last-child{padding-bottom:0}
.rp-feed .dot{position:absolute;left:4px;top:1px;width:23px;height:23px;border-radius:50%;display:grid;place-items:center;font-size:11px;
font-weight:700;background:var(--surface-2);color:var(--text-2);border:2px solid var(--surface);font-variant-numeric:tabular-nums}
.rp-feed li.cur .dot{background:var(--text);color:var(--surface)}
.rp-feed li.fut{opacity:.4}
.rp-feed button{all:unset;cursor:pointer;display:block;width:100%;border-radius:8px}
.rp-feed button:hover .lbl{text-decoration:underline}
.rp-feed .lbl{font-size:13.5px;font-weight:600;color:var(--text);display:flex;gap:6px;align-items:center}
.rp-feed .lbl .ic{width:14px;text-align:center}
.rp-feed .rsn{font-size:12.5px;color:var(--text-2);margin-top:2px;line-height:1.5}
.rp-feed .notes{list-style:none;margin:4px 0 0;padding:0;display:flex;flex-direction:column;gap:6px}
.rp-feed .notes li{font-size:13px;color:var(--text);line-height:1.5}
.rp-feed .notes li.closed{color:var(--crit);font-weight:600}
.rp-new{font-size:10.5px;font-weight:700;color:var(--accent-text);background:var(--accent-bg);border-radius:5px;padding:0 6px}
.ic-good{color:var(--good-text)}.ic-crit{color:var(--crit)}.ic-warn{color:var(--warn-text)}
.rp-scroll{max-height:420px;overflow:auto;padding-right:4px}
.rp-tip{position:fixed;z-index:50;pointer-events:none;background:var(--text);color:var(--surface);padding:7px 10px;border-radius:8px;font-size:12px;
max-width:320px;white-space:pre-line;box-shadow:0 4px 14px rgba(0,0,0,.2)}
.rp-empty{padding:48px;text-align:center;color:var(--text-2)}
@media(max-width:1180px){.rp-cols,.rp.convo .rp-cols{grid-template-columns:minmax(0,1fr)}.rp-stage{order:-1}
.rp-summary{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}.rp-summary>:first-child{grid-column:1/-1}}
@media(max-width:640px){.page{padding:16px 16px 40px}.nav-in{padding:10px 16px}.nav .brand{display:none}.tabs{margin-left:0}
.rp-hero{padding:14px 16px 10px}.rp-summary{grid-template-columns:minmax(0,1fr);gap:16px}.rp-ctl{margin-left:0}
.rp-sec{padding:16px}.rp-kv{grid-template-columns:1fr;gap:2px 0}.rp-kv dd{margin-bottom:8px}.rp-mail-from .when{display:none}
.rp-mail-h,.rp-mail-b{padding-left:14px;padding-right:14px}.rp-pick{flex:1 1 100%}.rp select{flex:1;max-width:100%;min-width:160px}}
"""

_JS = r"""
(function () {
  "use strict";
  var RUNS = JSON.parse(document.getElementById("rp-data").textContent || "[]");
  var $ = function (id) { return document.getElementById(id); };
  var ICON_PATHS = __ICON_PATHS__;  // the dashboard's one drawn icon family (report.ICON_PATHS), not emoji
  function icon(name) {
    return "<svg class='svgi' viewBox='0 0 24 24' width='14' height='14' fill='none' stroke='currentColor' stroke-width='1.8' " +
      "stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'>" + ICON_PATHS[name] + "</svg>";
  }
  var root = $("rp");
  var esc = function (x) {
    return String(x == null ? "" : x).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  var CHAT = { whatsapp: "WhatsApp", sms: "SMS", signal: "Signal", telegram: "Telegram", imessage: "iMessage", slack: "Slack",
    teams: "Teams", discord: "Discord", linkedin: "LinkedIn", x: "X", instagram: "Instagram", messenger: "Messenger",
    live_chat: "Live chat" };
  var LIVE = { phone_call: "Phone call", video_call: "Video call", teams_call: "Teams call", live_chat: "Live chat", voicemail: "Voicemail" };
  var DECISION = { STAY: "Stay on the channel", PIVOT_CHANNEL: "Pivot to another channel", ESCALATE_CALL: "Escalate to a call",
    STOP: "Stop", BACK_OFF: "Back off", WAIT: "Wait" };
  var MOOD = { engaged: ["▲", "good"], warm: ["▲", "good"], positive: ["▲", "good"], complying: ["✓", "good"],
    questioning: ["?", "warn"], neutral: ["–", ""], cautious: ["!", "warn"], suspicious: ["!", "crit"],
    refusing: ["✕", "crit"], hostile: ["✕", "crit"], silent: ["·", ""], reacted: ["•", ""] };

  if (!RUNS.length) {
    root.innerHTML = "<div class='rp-hero rp-empty'>No runs yet. Run the agent, then rebuild the dashboard with <span class='rp-mono'>report</span>.</div>";
    return;
  }

  var run = null, cur = 0, timer = null;

  function chanLabel(c) { return LIVE[c] || CHAT[c] || (c === "email" ? "Email" : (c || "—").replace(/_/g, " ")); }
  function initials(name) {
    var p = String(name || "?").trim().split(/\s+/);
    return ((p[0] || "?")[0] + (p.length > 1 ? p[p.length - 1][0] : "")).toUpperCase();
  }
  function hostOf(url) { try { return new URL(url).host; } catch (e) { return ""; } }
  function when(at) {
    if (!at) return "";
    var d = new Date(at);
    return isNaN(d) ? at : d.toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  }
  function cap(s) { s = String(s || ""); return s.charAt(0).toUpperCase() + s.slice(1); }
  function shortTiming(t) { return String(t || "").split(" (")[0]; }
  function firstSentence(t, n) {
    t = String(t || ""); var m = /^(.{20,}?[.!?])\s/.exec(t); var s = m ? m[1] : t;
    return s.length > (n || 140) ? s.slice(0, (n || 140) - 1) + "…" : s;
  }
  function liveIncidents(r) { return r.incidents.filter(function (i) { return !i.superseded; }); }
  // API-confirmed (page.submitted / attachment.opened) vs our judge's estimate: shown the same way on every page
  function isConfirmed(i) { return i.source === "api event"; }
  function rejectedCount(s) { return s.attempts.filter(function (a) { return a.errors.length; }).length; }
  function outcome(r, s) {
    var here = liveIncidents(r).filter(function (i) { return i.touch === s.n; });
    if (here.length) return here.some(isConfirmed) ? "hit" : "est";
    if (s.events.some(function (e) { return e.type === "reply"; })) return "reply";
    if (s.events.length) return "event";
    if (s.kind === "call" && s.transcript.length) return "call";
    return "silent";
  }
  var OUT_LABEL = { hit: "incident, confirmed by the API", est: "incident, our estimate", reply: "reply", event: "link / file event",
    call: "call answered", silent: "no reaction" };
  function plainError(e) {
    e = String(e || "");
    if (/valid draft/i.test(e)) return "The agent could not write a message that passed its own checks in three tries, so it stopped instead of sending something broken.";
    if (/Revel8APIError|HTTP|\b429\b|\b5\d\d\b/.test(e)) return "The target API kept returning errors.";
    if (/LLM|timed? ?out/i.test(e)) return "The language model stopped responding.";
    return "An unexpected error stopped the run.";
  }
  function chosenHook(r) { return r.hooks.filter(function (h) { return h.id === r.plan.hook_id; })[0] || null; }
  function avatar(name, color, lg) {
    return "<span class='rp-ava" + (lg ? " lg" : "") + "' style='background:" + esc(/^#[0-9a-f]{3,8}$/i.test(color || "") ? color : "#475569") + "'>" + esc(initials(name)) + "</span>";
  }
  function sec(title, html) { return "<div class='rp-sec'>" + (title ? "<h3>" + title + "</h3>" : "") + html + "</div>"; }
  function fold(summary, html, open) { return "<details" + (open ? " open" : "") + "><summary>" + summary + "</summary><div>" + html + "</div></details>"; }

  // routes the target closed: notebook / notes "ROUTE CLOSED: ..."
  function closedUpTo(r, n) {
    var seen = {}, out = [];
    var add = function (touch, note) {
      var m = /ROUTE CLOSED:\s*(.+)/i.exec(note || "");
      if (!m || touch > n) return;
      var k = m[1].trim().toLowerCase();
      if (!seen[k]) { seen[k] = 1; out.push({ touch: touch, route: m[1].trim() }); }
    };
    r.notebook.forEach(function (x) { add(x.touch, x.note); });
    r.steps.forEach(function (s) { s.notes.forEach(function (note) { add(s.n, note); }); });
    return out.sort(function (a, b) { return a.touch - b.touch; });
  }

  // ---- run picker
  var sel = $("rp-run");
  RUNS.forEach(function (r) {
    var o = document.createElement("option");
    o.value = r.id;
    var li = liveIncidents(r);
    o.textContent = (li.some(isConfirmed) ? "✓ " : li.length ? "≈ " : "") + (r.target.name || r.target.id || "?") + " · " + (r.label || r.policy || "") + " · " + r.id.slice(0, 15);
    sel.appendChild(o);
  });
  sel.addEventListener("change", function () { load(sel.value, 0); });

  // ---- controls
  function maxStep() { return run.steps.length; }
  function go(n) { cur = Math.max(0, Math.min(maxStep(), n)); syncHash(); draw(); }
  $("rp-prev").onclick = function () { stop(); go(cur - 1); };
  $("rp-next").onclick = function () { stop(); go(cur + 1); };
  $("rp-play").onclick = function () { timer ? stop() : play(); };
  function play() {
    if (cur >= maxStep()) go(0);
    $("rp-play").textContent = "❚❚"; $("rp-play").setAttribute("aria-label", "Pause");
    timer = setInterval(function () { if (cur >= maxStep()) { stop(); } else { go(cur + 1); } }, 4000);
  }
  function stop() {
    if (timer) clearInterval(timer);
    timer = null; $("rp-play").textContent = "▶"; $("rp-play").setAttribute("aria-label", "Play");
  }
  // "Full record | Conversation only": the same control and the same remembered choice as the run pages
  var viewBar = $("rp-view");
  function setView(v, save) {
    root.classList.toggle("convo", v === "convo");
    viewBar.querySelectorAll("button[data-view]").forEach(function (b) { b.setAttribute("aria-pressed", String(b.getAttribute("data-view") === v)); });
    if (save) { try { localStorage.setItem("r8-view", v); } catch (err) { /* private mode: keep it for this page only */ } }
  }
  viewBar.addEventListener("click", function (e) { var b = e.target.closest("button[data-view]"); if (b) setView(b.getAttribute("data-view"), true); });
  (function () { var v = "full"; try { v = localStorage.getItem("r8-view") || "full"; } catch (err) { /* ignore */ } setView(v, false); })();
  document.addEventListener("keydown", function (e) {
    if (e.target && /^(input|select|textarea)$/i.test(e.target.tagName)) return;
    // space and enter on a focused button or link must press it, not toggle playback
    if ((e.key === " " || e.key === "Enter") && e.target && /^(button|a|summary)$/i.test(e.target.tagName)) return;
    if (e.key === "ArrowRight") { stop(); go(cur + 1); e.preventDefault(); }
    else if (e.key === "ArrowLeft") { stop(); go(cur - 1); e.preventDefault(); }
    else if (e.key === " ") { timer ? stop() : play(); e.preventDefault(); }
    else if (e.key === "Home") { stop(); go(0); } else if (e.key === "End") { stop(); go(maxStep()); }
  });
  function syncHash() {
    var h = "#run=" + encodeURIComponent(run.id) + "&t=" + cur;
    if (location.hash !== h) history.replaceState(null, "", h);
    $("rp-read").href = encodeURIComponent(run.id) + ".html" + (cur ? "#touch-" + cur : "");
    $("rp-self").href = h;
  }
  function load(id, n) {
    stop();
    run = RUNS.filter(function (r) { return r.id === id; })[0] || RUNS[0];
    sel.value = run.id;
    cur = Math.max(0, Math.min(run.steps.length, n || 0));
    syncHash(); draw();
  }

  // ---- tooltip
  var tip = $("rp-tip");
  function showTip(ev, text) {
    tip.textContent = text; tip.hidden = false;
    var x = Math.min(ev.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
    var y = ev.clientY + 16 + tip.offsetHeight > window.innerHeight ? ev.clientY - tip.offsetHeight - 10 : ev.clientY + 16;
    tip.style.left = x + "px"; tip.style.top = y + "px";
  }
  function hideTip() { tip.hidden = true; }

  // ---- summary header: outcome · angle · persona, readable in seconds
  function drawSummary() {
    var t = run.target, inc = liveIncidents(run), p = run.persona, h = chosenHook(run);
    var types = inc.map(function (i) { return i.type; }).filter(function (v, i, a) { return a.indexOf(v) === i; });
    var status = inc.some(isConfirmed) ? "<span class='rp-status hit' title='Confirmed by an API event'>✓ Incident · " + esc(types.join(" + ")) + " at touch " + esc(inc[0].touch) + "</span>"
      : inc.length ? "<span class='rp-status est' title=\"Our judge's read of the reply; the API has not confirmed it\">≈ Estimated incident · " + esc(types.join(" + ")) + " at touch " + esc(inc[0].touch) + "</span>"
      : run.status === "error" ? "<span class='rp-status stop' title='" + esc(plainError(run.error)) + "'>Stopped early</span>"
      : (run.status === "running" || run.status === "starting") ? "<span class='rp-status live'>● Live</span>"
      : "<span class='rp-status'>No incident</span>";
    var replies = run.steps.filter(function (s) { return s.events.some(function (e) { return e.type === "reply"; }) || (s.kind === "call" && s.transcript.length); }).length;
    var rej = run.steps.reduce(function (n, s) { return n + rejectedCount(s); }, 0);
    var closed = closedUpTo(run, Infinity).length;
    var stats = "<div class='rp-stats'><span><b>" + run.steps.length + "</b> / " + run.max_touches + " touches</span><span><b>" + replies + "</b> answered</span>" +
      (rej ? "<span><b>" + rej + "</b> drafts rejected</span>" : "") + (closed ? "<span><b>" + closed + "</b> route" + (closed > 1 ? "s" : "") + " closed</span>" : "") + "</div>";
    $("rp-summary").innerHTML =
      "<div class='rp-sum'><h1>" + esc(t.name || t.id) + "</h1><div class='rp-subt'>" + esc(t.role || "") + "</div>" + status + stats + "</div>" +
      "<div class='rp-sum'><span class='rp-lbl'>Angle</span><div class='val'>" + esc(h ? h.topic : run.plan.hook_id || "—") + "</div>" +
      "<div class='meta'>" + (h ? "<span class='rp-chip id'>" + esc(h.id) + "</span> " : "") + (h && h.timing ? esc(cap(shortTiming(h.timing))) + " · " : "") +
      "goal: <b>" + esc(run.plan.objective || "—") + "</b> · " + run.hooks.length + " hooks evaluated</div></div>" +
      "<div class='rp-sum'><span class='rp-lbl'>Persona</span><div class='rp-who'>" + avatar(p.name, p.brand_color) + "<div><div class='val' style='margin:0'>" +
      esc(p.name || "—") + "</div><div class='meta' style='margin:0'>" + esc([p.role, p.organisation].filter(Boolean).join(" · ")) + "</div>" +
      (p.website_domain ? "<div class='rp-mono'>" + esc(p.website_domain) + "</div>" : "") + "</div></div></div>";
    $("rp-stepname").innerHTML = cur === 0 ? "<b>Casting</b> · before touch 1" : "<b>Touch " + cur + "</b> of " + run.steps.length;
  }

  // ---- compact timeline: a lane per channel, a column per touch
  function drawLanes() {
    var steps = run.steps, slots = Math.max(run.max_touches || 10, steps.length);
    var chans = [];
    steps.forEach(function (s) { if (chans.indexOf(s.channel) < 0) chans.push(s.channel); });
    if (!chans.length) chans = ["email"];
    var closed = closedUpTo(run, Infinity);
    var box = $("rp-lanes"), avail = box.clientWidth || 900;
    var L = avail < 560 ? 82 : 104, R = 10, T = 18, rowH = 24;
    var colW = Math.max(30, Math.min(110, (avail - L - R) / slots));
    var W = Math.ceil(L + slots * colW + R), H = T + chans.length * rowH + (closed.length ? 22 : 4);
    var cx = function (n) { return L + (n - 0.5) * colW; };
    var cy = function (c) { return T + chans.indexOf(c) * rowH + rowH / 2; };
    var svg = ["<svg width='" + W + "' height='" + H + "' viewBox='0 0 " + W + " " + H + "' role='img' aria-label='Channel used at each touch, with replies, calls, incidents and closed routes'>"];
    if (cur > 0) svg.push("<rect class='col-cur' x='" + (L + (cur - 1) * colW + 2) + "' y='2' width='" + (colW - 4) + "' height='" + (H - 4) + "' rx='6'/>");
    for (var n = 1; n <= slots; n++) svg.push("<text class='tick' x='" + cx(n) + "' y='11' text-anchor='middle'>" + n + "</text>");
    chans.forEach(function (c) {
      svg.push("<line class='grid' x1='" + L + "' x2='" + (W - R) + "' y1='" + cy(c) + "' y2='" + cy(c) + "'/>");
      svg.push("<text class='lane-lbl' x='" + (L - 10) + "' y='" + (cy(c) + 4) + "' text-anchor='end'>" + esc(chanLabel(c)) + "</text>");
    });
    if (steps.length > 1) svg.push("<polyline class='path' points='" + steps.map(function (s) { return cx(s.n) + "," + cy(s.channel); }).join(" ") + "'/>");
    steps.forEach(function (s) {
      var o = outcome(run, s), x = cx(s.n), y = cy(s.channel);
      if (o === "silent") svg.push("<circle class='mk-silent' cx='" + x + "' cy='" + y + "' r='5.5'/>");
      else svg.push("<circle class='mk mk-" + o + "' cx='" + x + "' cy='" + y + "' r='" + (o === "hit" || o === "est" ? 8.5 : 6.5) + "'/>");
      if (o === "est") svg.push("<text class='estglyph' x='" + x + "' y='" + (y + 4) + "' text-anchor='middle'>≈</text>");
      if (o === "hit") svg.push("<text class='hitglyph' x='" + x + "' y='" + (y + 3.5) + "' text-anchor='middle'>✓</text>");
      var rej = rejectedCount(s);
      if (rej) svg.push("<text class='rej' x='" + (x + 10) + "' y='" + (y - 5) + "'>" + rej + "✕</text>");
    });
    if (closed.length) {
      var yc = T + chans.length * rowH + 11;
      svg.push("<text class='lane-lbl' x='" + (L - 10) + "' y='" + (yc + 4) + "' text-anchor='end'>Routes closed</text>");
      closed.forEach(function (c) {
        var x = cx(c.touch);
        svg.push("<path class='mk-x' d='M" + (x - 4.5) + " " + (yc - 4.5) + "l9 9M" + (x + 4.5) + " " + (yc - 4.5) + "l-9 9'/>");
      });
    }
    for (var k = 1; k <= steps.length; k++) svg.push("<rect class='col-hit' data-n='" + k + "' x='" + (L + (k - 1) * colW) + "' y='0' width='" + colW + "' height='" + H + "'/>");
    svg.push("</svg>");
    box.innerHTML = svg.join("");
    box.querySelectorAll(".col-hit").forEach(function (el) {
      var n = +el.getAttribute("data-n"), s = steps[n - 1], rej = rejectedCount(s);
      var cl = closed.filter(function (c) { return c.touch === n; }).map(function (c) { return "Route closed: " + c.route; });
      var text = "Touch " + n + " · " + chanLabel(s.channel) + "\n" + (DECISION[s.decision] || s.decision || "") +
        "\nReaction: " + OUT_LABEL[outcome(run, s)] + (s.judge.sentiment ? " (" + s.judge.sentiment + ")" : "") +
        (rej ? "\n" + rej + " draft(s) rejected before sending" : "") + (cl.length ? "\n" + cl.join("\n") : "");
      el.addEventListener("mousemove", function (ev) { showTip(ev, text); });
      el.addEventListener("mouseleave", hideTip);
      el.addEventListener("click", function () { stop(); go(n); });
    });
    var dot = function (fill, label, hollow) {
      return "<span><svg width='10' height='10' aria-hidden='true'><circle cx='5' cy='5' r='" + (hollow ? 3.8 : 4.5) + "' fill='" + (hollow ? "none" : fill) + "'" +
        (hollow ? " stroke='var(--muted)' stroke-width='1.6'" : "") + "/></svg>" + label + "</span>";
    };
    $("rp-legend").innerHTML = dot("var(--s1)", "Reply") + dot("var(--s2)", "Link / file") + dot("var(--s3)", "Call") + dot("var(--good)", "✓ Incident (API)") +
      dot("var(--warn-text)", "≈ Incident (our estimate)") +
      dot("", "No reaction", true) + "<span style='color:var(--crit)'>n✕ drafts rejected</span>" + (closed.length ? "<span style='color:var(--crit)'>✕ route closed</span>" : "");
  }

  function timing(s) {
    var tm = s.timing || {};
    var parts = [["decide", tm.decide_s], ["send + reaction", tm.send_s], ["judge", tm.judge_s]].filter(function (x) { return typeof x[1] === "number"; });
    return parts.length ? "<div class='rp-mono' style='margin-top:14px'>" + icon("clock") + " " + parts.map(function (x) { return x[0] + " " + x[1] + " s"; }).join(" · ") + "</div>" : "";
  }
  function factText(id) { var f = run.facts.filter(function (x) { return x.id === id; })[0]; return f ? f.fact : ""; }

  // ---- left: the attacker's reasoning
  function drawMind() {
    var out = [];
    if (cur === 0) {
      out.push(sec("Why this angle", run.plan.rationale ? "<p class='rp-quote'>" + esc(run.plan.rationale) + "</p>" : "<p class='rp-dim'>No rationale recorded.</p>"));
      var rejected = run.plan_attempts.filter(function (x) { return x.rejected; });
      var c = run.character || {};
      var folds = "";
      if (rejected.length) {
        folds += fold("Casts the checks rejected <span class='rp-chip crit'>" + rejected.length + "</span>",
          "<div class='rp-list'>" + rejected.map(function (x) {
            return "<div class='rp-rej'><b>✕ " + esc(x.persona || "") + "</b> · " + esc(x.organisation || "") + " <span class='rp-mono'>" + esc(x.domain || "") +
              "</span><br><span class='rp-dim'>" + esc(x.rejected) + "</span></div>";
          }).join("") + "</div>");
      }
      if (c.would_never && c.would_never.length) {
        folds += fold("The character would never <span class='rp-chip'>" + c.would_never.length + "</span>",
          "<ul class='rp-list'>" + c.would_never.map(function (w) { return "<li><span class='ic'>✕</span>" + esc(w) + "</li>"; }).join("") + "</ul>");
      }
      if (folds) out.push(sec("", folds.replace("<details", "<details class='bare'")));
      $("rp-mind").innerHTML = out.join("");
      return;
    }
    var s = run.steps[cur - 1];
    out.push(sec(esc(DECISION[s.decision] || s.decision || "Decision") + " <span class='rp-chip'>" + (s.kind === "call" ? icon("phone") + " " : "") + esc(chanLabel(s.channel)) + "</span>" +
      (s.hook ? "<span class='rp-chip id'>" + esc(s.hook) + "</span>" : ""),
      (s.mind ? "<p class='rp-quote'>" + esc(s.mind) + "</p>" : "<p class='rp-dim'>No reasoning recorded.</p>") +
      (s.rationale ? "<p style='margin-top:12px;font-size:13.5px'><b>Move:</b> " + esc(s.rationale) + "</p>" : "") + timing(s)));

    var rej = s.attempts.filter(function (a) { return a.errors.length; });
    if (s.attempts.length) {
      var sent = "<div class='rp-sent'><span class='ic-good'>✓</span> Draft " + esc(s.attempts.length) + " passed the guardrails and was sent</div>";
      if (rej.length) {
        out.push(sec("Guardrails <span class='rp-chip crit'>" + rej.length + " rejected</span>", sent +
          "<details><summary>Why " + (rej.length > 1 ? "the earlier drafts were" : "the first draft was") + " rejected</summary><div class='rp-list'>" +
          rej.map(function (a) {
            return "<div class='rp-rej'><b>✕ Draft " + esc(a.try) + "</b> · " + esc(a.kind) + " via " + esc(chanLabel(a.channel)) +
              "<ul>" + a.errors.map(function (e) { return "<li>" + esc(e) + "</li>"; }).join("") + "</ul></div>";
          }).join("") + "</div></details>"));
      } else {
        out.push(sec("Guardrails <span class='rp-chip good'>first draft passed</span>", sent));
      }
    }

    var alts = [];
    s.discarded.forEach(function (d) { alts.push("<div class='rp-alt'>" + esc(d) + "</div>"); });
    if (s.policy && s.policy.alternatives_considered) {
      s.policy.alternatives_considered.forEach(function (a) {
        if (!a || typeof a !== "object") return;
        var meta = [a.move_type, a.channel && chanLabel(a.channel), a.hook_id && "hook " + a.hook_id].filter(Boolean).join(" · ");
        alts.push("<div class='rp-alt'><b>" + esc(meta) + "</b> " + esc(a.reason || "") + "</div>");
      });
    }
    if (s.twin && s.twin.candidates) {
      s.twin.candidates.forEach(function (c) {
        if (!c || typeof c !== "object") return;
        var fc = c.forecast || {}, num = function (v) { return typeof v === "number" ? v.toFixed(2) : "—"; };
        alts.push("<div class='rp-alt" + (c.selected ? " sel" : "") + "'><b>" + esc(c.risk_tier || "branch") + (c.selected ? " ✓ chosen" : "") + "</b> · " +
          esc(chanLabel(c.channel)) + " · EV " + num(c.ev_score) + "<br>" + esc(c.summary || "") +
          (fc.predicted_reaction ? "<br><i>Predicted: " + esc(fc.predicted_reaction) + "</i>" : "") + "</div>");
      });
    }

    var more = "";
    if (s.notes.length) {
      more += fold("Notes to self <span class='rp-chip'>" + s.notes.length + "</span>", "<ul class='rp-list'>" + s.notes.map(function (n) {
        var closed = /ROUTE CLOSED/i.test(n);
        return "<li><span class='ic" + (closed ? " crit" : "") + "'>" + (closed ? "✕" : "✎") + "</span><span" + (closed ? " class='rp-closed'" : "") + ">" + esc(n) + "</span></li>";
      }).join("") + "</ul>", true);
    }
    if (alts.length) more += fold("Considered, not chosen <span class='rp-chip'>" + alts.length + "</span>", "<div class='rp-list'>" + alts.join("") + "</div>");
    if (s.lookups.length) {
      more += fold("Looked up while replying <span class='rp-chip'>" + s.lookups.length + "</span>", s.lookups.map(function (l) {
        return "<p><b>" + icon("search") + " " + esc(l.query) + "</b></p><ul class='rp-list' style='margin-bottom:10px'>" + l.found.map(function (f) {
          return "<li class='rp-dim'><span class='ic'>·</span>" + esc(f.length > 220 ? f.slice(0, 220) + "…" : f) + "</li>";
        }).join("") + "</ul>";
      }).join(""));
    }
    if (s.cited.length) {
      more += fold("Public facts it relied on <span class='rp-chip'>" + s.cited.length + "</span>", "<ul class='rp-list'>" + s.cited.map(function (id) {
        return "<li><span class='rp-chip id'>" + esc(id) + "</span><span>" + esc(factText(id) || "(not in this run's brief)") + "</span></li>";
      }).join("") + "</ul>");
    }
    if (more) out.push(sec("", more.replace("<details", "<details class='bare'")));
    $("rp-mind").innerHTML = out.join("");
  }

  // ---- centre: what the target sees, then the reaction
  function renderEmail(s) {
    var p = run.persona, h = [];
    h.push("<div class='rp-win'><div class='rp-win-bar'><i></i><i></i><i></i><span class='ttl'>Inbox · " + esc(run.target.name) + "</span></div>");
    h.push("<div class='rp-mail-h'><p class='rp-mail-subj'>" + esc(s.subject || "(no subject)") + "</p><div class='rp-mail-from'>" +
      avatar(s.sender.name, p.brand_color) + "<span class='who'><b>" + esc(s.sender.name) + "</b><span class='addr'>&lt;" + esc(s.sender.address) +
      "&gt; to " + esc(run.target.name) + "</span></span><span class='when'>" + esc(when(s.at)) + "</span></div></div>");
    if (/^\s*(<!doctype|<html|<body|<table|<div|<p[ >])/i.test(s.body)) {
      h.push("<iframe class='rp-frame' sandbox='' title='Email body as rendered' srcdoc='" + esc(s.body) + "'></iframe>");
    } else {
      h.push("<div class='rp-mail-b'>" + esc(s.body) + "</div>");
      if (s.link) h.push("<span class='rp-cta'>" + esc(s.cta || "Open") + "</span><div class='rp-urlpeek'>→ " + esc(s.link.url) + "</div>");
    }
    if (s.attachment) h.push("<span class='rp-att'>" + icon("clip") + " " + esc(s.attachment) + "</span>");
    h.push("</div>");
    return h.join("");
  }
  function chatHistory(s) {
    var out = [];
    run.steps.slice(0, s.n - 1).forEach(function (o) {
      if (o.channel !== s.channel || o.kind === "call") return;
      out.push({ dir: "out", text: o.body, at: o.at, old: true });
      o.events.forEach(function (e) { if (e.type === "reply") out.push({ dir: "in", text: e.body, at: "", old: true }); });
    });
    return out;
  }
  function renderChat(s) {
    var sms = /sms|imessage/.test(s.channel);
    var msgs = chatHistory(s).concat([{ dir: "out", text: s.body + (s.link && s.body.indexOf(s.link.url) < 0 ? "\n" + s.link.url : ""), at: s.at }]);
    s.events.forEach(function (e) { if (e.type === "reply" && (e.channel || s.channel) === s.channel) msgs.push({ dir: "in", text: e.body, at: "" }); });
    return "<div class='rp-phone" + (sms ? " sms" : "") + "'><div class='rp-phone-h'>" + avatar(s.sender.name, run.persona.brand_color) +
      "<div><b>" + esc(s.sender.name || s.sender.address) + "</b><small>" + esc(chanLabel(s.channel)) + " · " + esc(s.sender.address) + "</small></div></div>" +
      "<div class='rp-bubbles'>" + msgs.map(function (m) {
        return "<div class='rp-bub " + m.dir + (m.old ? " old" : "") + "'>" + esc(m.text) + (m.at ? "<span class='meta'>" + esc(when(m.at)) + "</span>" : "") + "</div>";
      }).join("") + (s.attachment ? "<div class='rp-bub out'>" + icon("clip") + " " + esc(s.attachment) + "</div>" : "") + "</div></div>";
  }
  function renderCall(s) {
    var lines = s.transcript.length ? s.transcript.map(function (t) {
      var agent = t.who === "agent";
      return "<div class='rp-line " + (agent ? "agent" : "target") + "'><span class='who'>" + esc(agent ? s.sender.name || "Caller" : run.target.name) + "</span>" + esc(t.text) + "</div>";
    }).join("") : "<div class='rp-silence'>Nobody picked up.</div>";
    return "<div class='rp-call'><div class='rp-call-h'>" + avatar(s.sender.name) + "<div><b>" + icon("phone") + " " + esc(chanLabel(s.channel)) + " · " + esc(s.sender.name) +
      " → " + esc(run.target.name) + "</b><div class='rp-dim'>" + esc(s.sender.address) + (s.call_goal ? " · goal: " + esc(s.call_goal) : "") +
      "</div></div></div><div class='rp-call-b'>" + lines + "</div></div>";
  }
  function renderPage(pg) {
    var host = hostOf(pg.url), rest = pg.url.replace(/^https?:\/\//, "").slice(host.length);
    var body = pg.html ? "<iframe class='rp-frame' sandbox='' title='Landing page as the target sees it' srcdoc='" + esc(pg.html) + "'></iframe>"
      : "<div class='rp-silence' style='margin:12px;width:auto'>Page not rendered in this snapshot.</div>";
    return "<div class='rp-win rp-browser'><div class='rp-win-bar'><i></i><i></i><i></i><span class='rp-url'>" + icon("lock") + " <span><b>" + esc(host) + "</b>" +
      esc(rest) + "</span></span></div>" + body + (pg.fields && pg.fields.length ? "<div class='rp-fields'>Form fields: " + esc(pg.fields.join(", ")) + "</div>" : "") + "</div>";
  }
  function drawStage() {
    var first = esc((run.target.name || "the target").split(" ")[0]);
    if (cur === 0) {
      $("rp-stage-h").textContent = "Casting · before touch 1";
      var h = chosenHook(run), others = run.hooks.filter(function (x) { return !h || x.id !== h.id; });
      var conf = h && typeof h.confidence === "number" ? Math.round(h.confidence * 100) : null;
      var chosen = h ? "<div class='rp-chosen'><div style='display:flex;gap:8px;flex-wrap:wrap;align-items:center'><span class='rp-chip good'>✓ Chosen angle</span>" +
        "<span class='rp-chip id'>" + esc(h.id) + "</span>" + (h.timing ? "<span class='rp-chip'>" + esc(cap(shortTiming(h.timing))) + "</span>" : "") +
        (h.is_own_angle ? "<span class='rp-chip'>own angle</span>" : "") + "</div><h2>" + esc(h.topic) + "</h2><p class='r'>" + esc(h.rationale || "") + "</p>" +
        (conf != null ? "<div class='rp-meter' style='margin-top:12px'>confidence <i style='--v:" + conf + "%'></i> " + conf + "%</div>" : "") + "</div>"
        : "<p class='rp-dim'>No hook recorded for this run.</p>";
      var rest = others.length ? fold("View " + others.length + " other evaluated hook" + (others.length > 1 ? "s" : ""),
        others.map(function (x) {
          return "<div class='rp-hook'><div class='t'><span class='rp-chip id'>" + esc(x.id) + "</span> " + esc(x.topic) +
            (x.is_own_angle ? " <span class='rp-chip'>own angle</span>" : "") + "</div><div class='r'>" + (x.timing ? "<b>" + esc(cap(shortTiming(x.timing))) + ".</b> " : "") +
            esc(x.rationale || "") + "</div></div>";
        }).join("")) : "";
      $("rp-stage").innerHTML = sec("", "<div class='rp-funnel'><span><b>" + run.facts.length + "</b> verified facts</span><span>→</span><span><b>" + run.hooks.length +
        "</b> hooks</span><span>→</span><span><b>1</b> angle + a sender with a real reason to write</span></div>" + chosen + rest);
      return;
    }
    var s = run.steps[cur - 1], out = [];
    $("rp-stage-h").innerHTML = "What " + first + " sees";
    var view = s.kind === "call" || LIVE[s.channel] ? renderCall(s) : s.channel === "email" || !s.channel ? renderEmail(s) : renderChat(s);
    out.push(sec("", "<div class='rp-step-h'><span class='big'>Touch " + s.n + "</span><span class='rp-chip'>" + esc(chanLabel(s.channel)) +
      "</span><span class='rp-dim'>" + esc(when(s.at)) + "</span></div>" + view));
    if (s.page) out.push(sec("Behind the link · landing page", renderPage(s.page)));

    var react = [];
    s.events.forEach(function (e) {
      if (e.type === "reply") {
        if (s.kind !== "call" && !(CHAT[s.channel] && (e.channel || s.channel) === s.channel)) {
          react.push("<div class='rp-react-in'><span class='who'>↩ " + esc(run.target.name) + " replied via " + esc(chanLabel(e.channel || s.channel)) +
            (e.subject ? " · " + esc(e.subject) : "") + "</span>" + esc(e.body) + "</div>");
        } else if (CHAT[s.channel]) react.push("<div class='rp-read'>↩ Replied in the chat above.</div>");
      } else {
        var detail = e.url || e.filename || (Array.isArray(e.fields) ? e.fields.join(", ") : e.fields) || "";
        react.push("<span class='rp-evt'>" + esc(String(e.type).replace(/_/g, " ")) + (detail ? " · " + esc(detail) : "") + "</span>");
      }
    });
    if (s.kind === "call" && s.transcript.length && !s.events.length) react.push("<div class='rp-read rp-dim'>The conversation is the reaction: see the call above.</div>");
    if (!react.length && !s.error) react.push("<div class='rp-silence'>Silence. No reply, no click, no open.<br><span style='font-size:12.5px'>Silence is an answer too: the next move has to account for it.</span></div>");
    if (s.error) react.push("<div class='rp-err'>API error: " + esc(s.error) + "</div>");
    var j = s.judge || {};
    if (j.sentiment) {
      var m = MOOD[j.sentiment] || ["", ""];
      react.push("<div class='rp-read'><b>Agent's read:</b> <span class='rp-chip'><span class='ic-" + m[1] + "'>" + esc(m[0]) + "</span> " + esc(cap(j.sentiment)) +
        "</span> <span class='rp-dim'>" + esc(j.reason || "") + "</span></div>");
    }
    var groups = [];  // one card per piece of evidence: the same reply can count as disclosure and action
    liveIncidents(run).filter(function (i) { return i.touch === s.n; }).forEach(function (i) {
      var g = groups.filter(function (x) { return x.detail === i.detail; })[0];
      if (g) { if (g.types.indexOf(i.type) < 0) g.types.push(i.type); } else groups.push({ detail: i.detail, source: i.source, types: [i.type] });
    });
    groups.forEach(function (g) {
      var ok = g.source === "api event";
      react.push("<div class='rp-incident" + (ok ? "" : " est") + "'>" + (ok ? "✓" : "≈") + " <div><b>" + (ok ? "Incident · " : "Estimated incident · ") +
        esc(g.types.join(" + ")) + "</b><br><span style='font-weight:400'>" + esc(g.detail) + "</span><br><span class='rp-mono'>" +
        (ok ? "confirmed by an API event" : "our judge's read of their reply; the API has not confirmed it") + "</span></div></div>");
    });
    run.incidents.filter(function (i) { return i.superseded && i.touch === s.n; }).forEach(function (i) {
      react.push("<div class='rp-withdrawn'><s>Incident · " + esc(i.type) + "</s> withdrawn: " + esc(i.superseded_reason || "re-judged") + "</div>");
    });
    if (cur === run.steps.length && run.error) react.push("<div class='rp-stop'><b>The run stopped early here.</b> " + esc(plainError(run.error)) +
      "<details class='bare'><summary>Technical details</summary><pre class='rp-mono'>" + esc(run.error) + "</pre></details></div>");
    out.push(sec("Their reaction", "<div style='display:flex;flex-direction:column;gap:12px;align-items:flex-start'>" + react.join("") + "</div>"));
    $("rp-stage").innerHTML = out.join("");
  }

  // ---- right: one persona profile, routes, and the mood + notebook feeds
  function drawState() {
    var out = [], p = run.persona, c = run.character || {};
    var core = "<dl class='rp-kv'>" +
      (c.unblocks_me ? "<dt>Wants</dt><dd>" + esc(c.unblocks_me) + "</dd>" : "") +
      (c.first_small_yes ? "<dt>Small yes</dt><dd>" + esc(c.first_small_yes) + "</dd>" : "") +
      (c.deadline ? "<dt>Deadline</dt><dd><b>" + esc(c.deadline) + "</b>" + (c.deadline_reason ? "<br><span class='rp-dim'>" + esc(c.deadline_reason) + "</span>" : "") + "</dd>" : "") +
      (run.plan.objective ? "<dt>Objective</dt><dd><span class='rp-chip'>" + esc(run.plan.objective) + "</span></dd>" : "") + "</dl>";
    var back = "<dl class='rp-kv'>" + (c.why_them ? "<dt>Why them</dt><dd>" + esc(c.why_them) + "</dd>" : "") +
      (c.need ? "<dt>Their need</dt><dd>" + esc(c.need) + "</dd>" : "") + (c.voice ? "<dt>Voice</dt><dd>" + esc(c.voice) + "</dd>" : "") +
      (run.plan.pretext ? "<dt>Pretext</dt><dd>" + esc(run.plan.pretext) + "</dd>" : "") + "</dl>";
    var hasBack = c.why_them || c.need || c.voice || run.plan.pretext;
    out.push(sec("Persona profile", "<div class='rp-profile-h'>" + avatar(p.name, p.brand_color, true) + "<div><div class='n'>" + esc(p.name || "—") + "</div><div class='rp-dim'>" +
      esc([p.role, p.organisation].filter(Boolean).join(" · ")) + "</div>" + (p.website_domain ? "<div class='rp-mono'>" + esc(p.website_domain) + "</div>" : "") +
      "</div></div>" + core + (hasBack ? fold("Backstory and voice", back, cur === 0) : "")));

    var used = {};
    run.steps.slice(0, cur).forEach(function (s) {
      var u = used[s.channel] || (used[s.channel] = { n: 0, replies: 0 });
      u.n++; if (s.events.some(function (e) { return e.type === "reply"; }) || (s.kind === "call" && s.transcript.length)) u.replies++;
    });
    var routes = Object.keys(used).map(function (ch) {
      var u = used[ch];
      return "<div class='rp-route'><span class='sw' style='background:" + (u.replies ? "var(--s1)" : "var(--muted)") + "'></span>" + esc(chanLabel(ch)) +
        "<span class='cnt'>" + u.n + " sent · " + u.replies + " answered</span></div>";
    }).join("") || "<span class='rp-dim'>No contact yet.</span>";
    routes += closedUpTo(run, cur).map(function (x) {
      return "<div class='rp-route rp-closed'><span class='ic-crit'>✕</span>" + esc(cap(x.route)) + "<span class='cnt'>closed at touch " + x.touch + "</span></div>";
    }).join("");
    out.push(sec("Routes", "<div class='rp-routes'>" + routes + "</div>"));

    if (run.steps.length) {
      out.push(sec("Their mood", "<ul class='rp-feed rp-scroll'>" + run.steps.map(function (s) {
        // the campaign column is the state AT this touch: later moods are not known yet (and would spoil the replay)
        if (s.n > cur) return "<li class='fut'><span class='dot'>" + s.n + "</span><button type='button' data-n='" + s.n + "' title='Go to touch " + s.n + "'>" +
          "<span class='lbl rp-dim' style='font-weight:500'>Not reached yet</span></button></li>";
        var mood = (s.judge && s.judge.sentiment) || (s.events.length ? "reacted" : "silent"), m = MOOD[mood] || ["", ""];
        var cls = s.n === cur ? "cur" : s.n > cur ? "fut" : "";
        var why = s.judge && s.judge.reason ? firstSentence(s.judge.reason, 120) : "";
        return "<li class='" + cls + "'><span class='dot'>" + s.n + "</span><button type='button' data-n='" + s.n + "' title='Go to touch " + s.n + "'>" +
          "<span class='lbl'><span class='ic ic-" + m[1] + "'>" + esc(m[0]) + "</span>" + esc(cap(mood)) + " <span class='rp-dim' style='font-weight:400'>· " +
          esc(chanLabel(s.channel)) + "</span></span>" + (why && s.n <= cur ? "<div class='rsn'>" + esc(why) + "</div>" : "") + "</button></li>";
      }).join("") + "</ul>"));
    }

    var notes = run.notebook.filter(function (n) { return n.touch <= cur; }), byTouch = {}, order = [];
    notes.forEach(function (n) { if (!byTouch[n.touch]) { byTouch[n.touch] = []; order.push(n.touch); } byTouch[n.touch].push(n.note); });
    order.sort(function (a, b) { return b - a; });
    out.push(sec("Notebook · the story so far <span class='rp-chip'>" + notes.length + "</span>", order.length ? "<ul class='rp-feed rp-scroll'>" + order.map(function (t) {
      var fresh = t === cur && cur > 0;
      return "<li" + (fresh ? " class='cur'" : "") + "><span class='dot'>" + (t ? t : "0") + "</span><div class='lbl'>" + (t ? "Touch " + t : "Casting") +
        (fresh ? " <span class='rp-new'>new</span>" : "") + "</div><ul class='notes'>" + byTouch[t].map(function (n) {
          var closed = /ROUTE CLOSED/i.test(n);
          return "<li" + (closed ? " class='closed'" : "") + ">" + (closed ? "✕ " : "") + esc(n) + "</li>";
        }).join("") + "</ul></li>";
    }).join("") + "</ul>" : "<span class='rp-dim'>Empty.</span>"));
    $("rp-state").innerHTML = out.join("");
    $("rp-state").querySelectorAll(".rp-feed button").forEach(function (b) {
      b.addEventListener("click", function () { stop(); go(+b.getAttribute("data-n")); });
    });
  }

  function draw() {
    drawSummary(); drawLanes(); drawMind(); drawStage(); drawState();
    $("rp-prev").disabled = cur === 0; $("rp-next").disabled = cur >= maxStep();
  }

  function fromHash() {
    var m = /run=([^&]+)/.exec(location.hash), t = /[&#]t=(\d+)/.exec(location.hash);
    return { id: m ? decodeURIComponent(m[1]) : RUNS[0].id, t: t ? +t[1] : 0 };
  }
  window.addEventListener("hashchange", function () {
    var h = fromHash();
    if (!run || h.id !== run.id || h.t !== cur) load(h.id, h.t);
  });
  var rz = null;
  window.addEventListener("resize", function () { clearTimeout(rz); rz = setTimeout(function () { if (run) drawLanes(); }, 120); });
  var h0 = fromHash();
  load(h0.id, h0.t);
})();
"""
