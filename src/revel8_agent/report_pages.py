"""Extra dashboard pages: per-target research (search -> sources -> facts -> hooks) and "How it works".

Rendered by report.render_index(); they share its CSS and page shell.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from .engine import timing
from .osint import Target, build_queries


def _e(x: object) -> str:
    from html import escape

    return escape("" if x is None else str(x))


def _host(url: str) -> str:
    from urllib.parse import urlsplit

    return (urlsplit(url).hostname or url).removeprefix("www.")


def load_research(target_id: str, dossiers_dir: Path = Path("dossiers"),
                  cache_dir: Path = Path(".cache/search")) -> dict | None:
    """Dossier + stats, with the search step rebuilt from the search cache for older dossiers."""
    dpath = dossiers_dir / f"{target_id}.json"
    if not dpath.exists():
        return None
    dossier = json.loads(dpath.read_text(encoding="utf-8"))
    spath = dossiers_dir / f"{target_id}.stats.json"
    stats = json.loads(spath.read_text(encoding="utf-8")) if spath.exists() else {}
    if not stats.get("search"):
        t = Target(dossier["target_id"], dossier["target_name"], dossier["role"], dossier["company"])
        search = []
        for q in build_queries(t):
            hits = []
            for provider in ("brave", "tavily", "duckduckgo"):
                f = cache_dir / f"{provider}_{hashlib.sha1(q.encode()).hexdigest()[:16]}.json"
                if f.exists():
                    try:
                        hits = json.loads(f.read_text(encoding="utf-8"))
                    except ValueError:
                        hits = []
                    break
            from .osint import mentions_target

            search.append({"query": q, "hits": [{"url": h["url"], "title": h["title"], "snippet": h["snippet"][:300],
                                                 "about_target": mentions_target(f"{h['title']} {h['snippet']} {h['url']}", t)}
                                                for h in hits]})
        stats["search"] = search
        stats["search_reconstructed"] = True
    if not stats.get("sources"):
        sources: dict[str, dict] = {}
        for f in dossier.get("facts", []):
            s = sources.setdefault(f["source_url"], {"title": "", "kind": "page", "status": "about target",
                                                    "proposed": 0, "verified": 0, "rejected": 0})
            s["verified"] += 1
            s["proposed"] += 1
        for r in stats.get("rejected", []):
            s = sources.setdefault(r["url"], {"title": "", "kind": "page", "status": "about target",
                                              "proposed": 0, "verified": 0, "rejected": 0})
            s["rejected"] += 1
            s["proposed"] += 1
        stats["sources"] = sources
        stats["sources_reconstructed"] = True
    return {"dossier": dossier, "stats": stats}


# --------------------------------------------------------------------------- research page


def _funnel(stats: dict, dossier: dict) -> str:
    hits = sum(len(q["hits"]) for q in stats.get("search", []))
    about = sum(1 for s in stats.get("sources", {}).values() if str(s.get("status", "")).startswith("about"))
    stages = [
        ("Search queries", stats.get("queries") or len(stats.get("search", []))),
        ("Search results", stats.get("hits") or hits),
        ("Sources about the target", about),
        ("Facts proposed by the LLM", stats.get("facts_proposed", 0)),
        ("Facts verified (quote found on page)", stats.get("facts_verified_raw", stats.get("facts_verified", len(dossier.get("facts", []))))),
        ("Unique after merging duplicates", len(dossier.get("facts", []))),
        ("Themes", len(dossier.get("themes", []))),
        ("Hooks ranked", len(dossier.get("hypotheses", []))),
    ]
    top = max((v or 0) for _, v in stages) or 1
    rows = "".join(
        f"<div class='bar-row'><div class='bar-name' style='white-space:normal'>{_e(name)}</div>"
        f"<div class='track' data-tip='{_e(name)}: {v}'><div class='fill' style='width:{100 * (v or 0) / top:.1f}%'></div></div>"
        f"<div class='bar-val'>{_e(v)}</div></div>" for name, v in stages)
    return f"<div class='bars funnel'>{rows}</div><div class='axis'></div>"


def render_research(target_id: str, out_dir: Path, page, research: dict) -> Path:
    d, st = research["dossier"], research["stats"]
    facts = {f["id"]: f for f in d.get("facts", [])}

    steps = (
        "<ol class='steps'>"
        f"<li><b>Targeted web search.</b> {len(st.get('search', []))} queries built from the name, role and company "
        f"(Brave Search API, cached 12 h).</li>"
        "<li><b>Fetch and clean.</b> Result pages are downloaded and reduced to visible text; login walls (LinkedIn, X, "
        "Crunchbase) are not fetched, their search snippet is used instead.</li>"
        "<li><b>Relevance filter.</b> A source is kept only if it names <i>both</i> the surname and the company "
        "(umlaut-aware), which separates this person from namesakes.</li>"
        "<li><b>LLM extraction.</b> DeepSeek-V4-Flash proposes facts from each source, each with a verbatim quote.</li>"
        "<li><b>Deterministic verification.</b> Plain code checks the quote really occurs on that source page "
        "(≥ 4 words, no ellipsis). Anything else is rejected and listed below.</li>"
        "<li><b>Hook ranking.</b> The LLM ranks 3–5 topics that matter to the person right now plus one own angle; "
        "a hook without a verified supporting fact is dropped. Dates are labelled past/upcoming in code.</li></ol>")
    if st.get("version") == 2:
        steps = (
            "<ol class='steps'>"
            f"<li><b>Parallel lanes, one Token Factory key each.</b> {len(st.get('search', []))} searches across web, news, "
            "video, image (used only to find the pages a photo appears on), social (LinkedIn posts/articles, X, YouTube, "
            "podcasts, Medium/Substack, event and speaker sites) and academic/code (OpenAlex, GitHub).</li>"
            "<li><b>Identity check, not just a name match.</b> A source counts only if it has the full name plus an identity "
            "anchor (company, earlier employer, university, co-founder …) or the surname plus the company. Namesakes and posts "
            "that merely mention the person drop out here.</li>"
            "<li><b>LLM extraction, person first:</b> what they said, talks, posts, past jobs, studies, interests — each with "
            "a verbatim quote and the source's publish date.</li>"
            "<li><b>Deterministic verification</b> of every quote on its page.</li>"
            "<li><b>Round 2.</b> From the verified facts the LLM proposes new identity anchors (kept only if they appear in a "
            "verified quote) and follow-up searches about the person.</li>"
            "<li><b>Consolidation.</b> Duplicates merged (the strongest source kept, the rest counted as corroboration); "
            "contradicting facts flagged and kept out of the planner; themes counted; hooks ranked from themes and "
            "upcoming facts.</li></ol>")
    reconstructed = ("<p class='note'>Search results rebuilt from the local search cache; this dossier was built before "
                     "per-step logging existed.</p>" if st.get("search_reconstructed") else "")

    # hooks with their evidence
    hook_html = []
    for h in d.get("hypotheses", []):
        ev = []
        for fid in h.get("supporting_fact_ids", []):
            f = facts.get(fid)
            if f:
                tm = timing(f.get("recency", ""))
                ev.append(f"<li><b>[{_e(fid)}]</b> {_e(f['fact'])} <span class='badge'>{_e(tm)}</span>"
                          f"<blockquote>“{_e(f['verbatim_quote'])}”</blockquote>"
                          f"<a class='mono' href='{_e(f['source_url'])}' target='_blank' rel='noopener noreferrer'>{_e(_host(f['source_url']))}</a></li>")
        tag = " <span class='badge b-warn'>own angle</span>" if h.get("is_own_angle") else ""
        hook_html.append(f"<div class='hook'><div class='hook-h'><span class='hid'>{_e(h['id'])}</span><b>{_e(h['topic'])}</b>{tag}"
                         f"<span class='spacer'></span><span class='mono'>confidence {h.get('confidence', 0):.2f}</span></div>"
                         f"<p class='muted-p'>{_e(h.get('rationale'))}</p><ul class='evidence'>{''.join(ev)}</ul></div>")

    # search queries and hits
    q_html = []
    for q in st.get("search", []):
        hits = "".join(
            f"<li><span class='badge {'b-live' if h.get('about_target') else ''}'>{'about target' if h.get('about_target') else 'other'}</span> "
            f"<a href='{_e(h['url'])}' target='_blank' rel='noopener noreferrer'>{_e(h['title'] or h['url'])}</a>"
            f"<div class='mono'>{_e(_host(h['url']))}</div><div class='snip'>{_e(h.get('snippet'))}</div></li>"
            for h in q.get("hits", []))
        lane = f"<span class='badge b-live'>{_e(q['lane'])}{' · ' + _e(q['vertical']) if q.get('vertical') not in (None, 'web') else ''}</span> " if q.get("lane") else ""
        q_html.append(f"<details class='q'><summary>{lane}<span class='mono'>query</span> <b>{_e(q['query'])}</b> "
                      f"<span class='mono'>· {len(q.get('hits', []))} results</span></summary><ul class='hits'>{hits or '<li class=mono>no results</li>'}</ul></details>")

    # sources
    src_rows = []
    for url, s in sorted(st.get("sources", {}).items(), key=lambda kv: -(kv[1].get("verified") or 0)):
        src_rows.append(f"<tr><td><a href='{_e(url)}' target='_blank' rel='noopener noreferrer'>{_e(s.get('title') or _host(url))}</a>"
                        f"<div class='mono'>{_e(_host(url))}</div></td><td>{_e(s.get('kind'))}</td><td>{_e(s.get('status'))}</td>"
                        f"<td class='num'>{_e(s.get('proposed', '—'))}</td><td class='num'><b>{_e(s.get('verified', '—'))}</b></td>"
                        f"<td class='num'>{_e(s.get('rejected', '—'))}</td></tr>")

    # facts grouped by source
    by_src: dict[str, list[dict]] = defaultdict(list)
    for f in d.get("facts", []):
        by_src[f["source_url"]].append(f)
    fact_groups = []
    def fact_badges(f: dict) -> str:
        b = [f"<span class='badge'>{_e(f['category'])}</span>", f"<span class='badge'>{_e(timing(f.get('recency', '')))}</span>"]
        if f.get("lane"):
            b.append(f"<span class='badge b-live'>{_e(f['lane'])}</span>")
        if f.get("corroborated_by"):
            b.append(f"<span class='badge b-good' data-tip='{_e(chr(10).join(f['corroborated_by']))}'>"
                     f"✓ {len(f['corroborated_by']) + 1} sources</span>")
        if f.get("conflicts_with"):
            b.append(f"<span class='badge b-crit'>conflict with {_e(', '.join(f['conflicts_with']))}</span>")
        return " ".join(b)

    for url, fs in sorted(by_src.items(), key=lambda kv: -len(kv[1])):
        items = "".join(f"<li><span class='hid'>{_e(f['id'])}</span><div><div>{_e(f['fact'])} {fact_badges(f)} "
                        f"<span class='mono'>{_e(f.get('recency'))}</span></div>"
                        + (f"<div class='mono' style='color:var(--crit)'>{_e(f['conflict_note'])}</div>" if f.get("conflict_note") else "")
                        + f"<blockquote>“{_e(f['verbatim_quote'])}”</blockquote></div></li>" for f in fs)
        fact_groups.append(f"<details class='q'><summary><b>{_e(_host(url))}</b> <span class='mono'>· {len(fs)} facts</span></summary>"
                           f"<a class='mono' href='{_e(url)}' target='_blank' rel='noopener noreferrer'>{_e(url)}</a><ul class='facts-list'>{items}</ul></details>")

    rejected = "".join(f"<li><div>{_e(r.get('fact'))}</div><blockquote>“{_e(r.get('quote'))}”</blockquote>"
                       f"<span class='mono'>{_e(_host(r.get('url', '')))} · quote not found verbatim on the page</span></li>"
                       for r in st.get("rejected", []))

    # v2: themes, lanes, anchors, conflicts
    v2 = ""
    if d.get("themes"):
        th_rows = "".join(
            f"<div class='bar-row'><div class='bar-name' style='white-space:normal'>{_e(th['topic'])}</div>"
            f"<div class='track' data-tip='{_e(th['topic'])}: {th['count']} verified mentions, latest {_e(th.get('latest') or 'unknown')}'>"
            f"<div class='fill' style='width:{100 * th['count'] / max(x['count'] for x in d['themes']):.1f}%'></div></div>"
            f"<div class='bar-val'>{th['count']}</div></div>" for th in d["themes"])
        v2 += (f"<div class='card'><h2>Themes · what they keep coming back to</h2><div class='bars'>{th_rows}</div>"
               "<div class='axis'></div><p class='note' style='margin:12px 0 0'>count of verified facts per theme, across "
               "their posts, talks, interviews and articles</p></div>")
    if st.get("lanes"):
        lane_rows = "".join(f"<tr><td><b>{_e(k)}</b></td><td class='num'>{v['queries']}</td><td class='num'>{v['results']}</td>"
                            f"<td class='num'><b>{v['facts']}</b></td></tr>" for k, v in st["lanes"].items())
        anchors = ", ".join(_e(a) for a in d.get("anchors", []))
        added = ", ".join(_e(a) for a in st.get("anchors_added", [])) or "none"
        exp = "".join(f"<li class='mono'>{_e(q)}</li>" for q in st.get("expansion_queries", []))
        v2 += ("<div class='card'><h2>Research lanes · one Token Factory key each</h2><table><thead><tr><th>Lane</th>"
               "<th class='num'>Queries</th><th class='num'>Results</th><th class='num'>Facts kept</th></tr></thead>"
               f"<tbody>{lane_rows}</tbody></table><p style='font-size:13px;margin:12px 0 4px'><b>Identity anchors:</b> {anchors}"
               f"<br><b>Learned in round 2:</b> {added} · <b>duplicates merged:</b> {_e(st.get('duplicates_merged', 0))} · "
               f"<b>conflicts found:</b> {_e(st.get('conflicts', 0))} · <b>keys used:</b> {_e(st.get('keys', 1))}</p>"
               f"<details><summary>Round-2 follow-up queries</summary><ul>{exp or '<li class=mono>none</li>'}</ul></details></div>")
    v2_html = f"<div class='grid split' style='margin-bottom:20px'>{v2}</div>" if v2 else ""

    body = (f"<h1>Research · {_e(d['target_name'])}</h1><p class='sub'>{_e(d['role'])} · {_e(d['company'])} · "
            f"built in {_e(st.get('elapsed_s', '—'))} s" + (" · research v2" if st.get("version") == 2 else "") + "</p>"
            "<div class='grid split' style='margin-bottom:20px'>"
            f"<div class='card'><h2>Research funnel</h2>{_funnel(st, d)}</div>"
            f"<div class='card'><h2>What happens, step by step</h2>{steps}{reconstructed}</div></div>"
            + v2_html +
            f"<div class='card' style='margin-bottom:20px'><h2>Hooks · what matters to them right now, with evidence</h2>{''.join(hook_html) or '<p class=mono>no hooks</p>'}</div>"
            f"<div class='card' style='margin-bottom:20px'><h2>1 · Search queries and results</h2>{''.join(q_html)}</div>"
            "<div class='card' style='margin-bottom:20px'><h2>2 · Sources and what each one yielded</h2>"
            "<table><thead><tr><th>Source</th><th>Kind</th><th>Status</th><th class='num'>Proposed</th><th class='num'>Verified</th>"
            f"<th class='num'>Rejected</th></tr></thead><tbody>{''.join(src_rows)}</tbody></table></div>"
            f"<div class='card' style='margin-bottom:20px'><h2>3 · All {len(d.get('facts', []))} verified facts, by source</h2>{''.join(fact_groups)}</div>"
            f"<div class='card'><h2>4 · Rejected by the verifier ({len(st.get('rejected', []))})</h2>"
            f"<ul class='rejected'>{rejected or '<li class=mono>none</li>'}</ul></div>")
    out = out_dir / f"research-{target_id}.html"
    out.write_text(page(f"Research · {d['target_name']}", f"<span class='crumb'>/</span><span class='crumb'>research · {_e(target_id)}</span>",
                        body, False), encoding="utf-8")
    return out


# --------------------------------------------------------------------------- how it works


def render_how(out_dir: Path, page, states: list[dict], targets: list[str]) -> Path:
    n_runs = len(states)
    touches = sum(s.get("touches_used", 0) for s in states)
    llm = sum(s.get("llm_calls", 0) for s in states)
    from .report import decision_path

    pipeline = [
        ("Research", "Parallel search lanes (web, news, media, social, academic) → keep only sources that are about this "
                     "person → the LLM proposes facts, each with a verbatim quote → code checks every quote really is on its "
                     "page → contradictions are flagged → hooks are proposed and ranked by openness, recency and how "
                     "personal they are.",
         "research.py · snowball.py", "research-" + targets[0] + ".html" if targets else ""),
        ("Brief and memory", "A bounded brief: hook evidence first, each fact labelled past or upcoming from its date. Plus what "
                             "earlier sessions taught us about this person (what they corrected, rules they stated, what got "
                             "replies) and a playbook across targets.",
         "engine.make_brief · memory.py", ""),
        ("Casting", "Instead of a campaign planner, the agent casts ONE ordinary person: a job, a deadline and one small "
                    "need only the target can resolve (confirm in a portal, open a document, answer an internal "
                    "question). The need decides the objective. Code recasts if the domain resolves in DNS, belongs to "
                    "the target, or the need has the target sending something.",
         "ActorRunner.plan", ""),
        ("Session", "One API session = one run. The target twin remembers every contact in it, across all channels.",
         "api_client.create_session", ""),
    ]
    loop = [
        ("Act", "The character reads her conversation and her notebook and does what she would do now: answer, follow "
                "up, send the link, call, or make her ask smaller. No planner picks moves; the move label on each touch "
                "is read off what she did."),
        ("Build", "Email → craft templates (plain personal note, branded notice or shared-doc); landing pages from "
                  "templates; greetings and sign-offs de-duplicated; PDFs uploaded as assets."),
        ("Check", "Code wraps her without steering her: no AI-directed wording, lookalike domains only, no contradiction "
                  "with earlier turns, no year the target never used, no invented named people, a first link only with "
                  "a question, and every message asks for something. A failing draft goes back to her with the reason "
                  "(up to 3 tries)."),
        ("Send", "Register the landing page, then send the message, or run a live call turn by turn. Every request "
                 "carries an Idempotency-Key, so a retry never spends a second touch."),
        ("Read", "Events come back: reply, link.opened, page.submitted, attachment.opened. Silence is an answer too. "
                 "Things they mention are looked up on the web before the next touch."),
        ("Judge", "✓ Confirmed by the API only when something was given: a secret typed into a form (credentials) or an "
                  "internal-info field in a form (disclosure). A basic-details form, an opened link or an opened file is "
                  "a step. ≈ Estimate: a disclosure or action our judge reads in their reply or typed values; the "
                  "evidence must be a verbatim quote."),
        ("Remember", "Everything she commits to goes into her notebook and is read back every turn. After the run, what "
                     "worked and what they corrected is saved for the next session with the same person."),
    ]
    paths: dict[str, int] = {}
    for s in states:
        paths[decision_path(s)] = paths.get(decision_path(s), 0) + 1
    path_counts = " · ".join(f"{_e(p)}: {n}" for p, n in sorted(paths.items(), key=lambda kv: -kv[1])) or "no runs yet"
    alternatives = (
        "<div class='card' style='margin-bottom:20px'><h2>Other decision paths, for comparison</h2><ul class='steps'>"
        "<li><b>Method actor</b> (above, <span class='mono'>--actor</span>): a cast character decides every touch.</li>"
        "<li><b>Escalation controller</b> (<span class='mono'>decision.py</span>): an explicit belief state about the "
        "target and a priority-ordered rule picks hold / escalate / pivot / back off; the LLM only writes the text.</li>"
        "<li><b>Rule policy</b> (<span class='mono'>policy.py</span>, <span class='mono'>--policy</span>): a deterministic "
        "state machine over hooks and channels.</li>"
        "<li><b>Shadow twin</b> (<span class='mono'>shadow_twin.py</span>, <span class='mono'>--shadow-twin</span>): drafts "
        "a safe, a balanced and a bold move, rehearses each against a model of the target and sends the best.</li></ul>"
        f"<p class='note' style='margin:12px 0 0'>Runs on this dashboard by path: {path_counts}. The Overview's "
        "Decision path column shows which path each run used.</p></div>")
    pipe = "".join(f"<div class='stage'><div class='stage-n'>{i + 1}</div><div><b>{_e(t)}</b><p>{_e(x)}</p>"
                   f"<span class='mono'>{_e(code)}</span>{f' · <a class=mono href={_e(link)}>see example</a>' if link else ''}</div></div>"
                   for i, (t, x, code, link) in enumerate(pipeline))
    loop_html = "".join(f"<div class='loop-step'><div class='stage-n'>{chr(65 + i)}</div><b>{_e(t)}</b><p>{_e(x)}</p></div>"
                        for i, (t, x) in enumerate(loop))
    research_links = " · ".join(f"<a href='research-{_e(t)}.html'>{_e(t)}</a>" for t in targets)
    body = ("<h1>How the agent works</h1><p class='sub'>From a name to an incident: every stage, what it does, and "
            "where it lives in the code.</p>"
            "<div class='grid k4' style='margin-bottom:20px'>"
            f"<div class='card tile'><div class='label'>Runs recorded</div><div class='value'>{n_runs}</div></div>"
            f"<div class='card tile'><div class='label'>Touches spent</div><div class='value'>{touches}</div></div>"
            f"<div class='card tile'><div class='label'>LLM calls</div><div class='value'>{llm}</div></div>"
            f"<div class='card tile'><div class='label'>Research pages</div><div class='value' style='font-size:16px'>{research_links or '—'}</div></div></div>"
            f"<div class='card' style='margin-bottom:20px'><h2>Before the first contact</h2><div class='pipeline'>{pipe}</div></div>"
            f"<div class='card' style='margin-bottom:20px'><h2>Every touch: the loop</h2><div class='loop'>{loop_html}</div>"
            "<p class='note' style='margin-top:14px'>Each run page shows this loop per touch: her reasoning, every rejected "
            "draft, what was sent, the full reaction, the judge's read, and the time each part took. Replay steps through "
            "the same run one touch at a time.</p></div>"
            + alternatives +
            "<div class='card'><h2>Rules the agent cannot break</h2><ul class='steps'>"
            "<li>Talk to the person, never to the AI: drafts with AI-directed or instruction-override wording are blocked.</li>"
            "<li>Only invented / lookalike domains: the persona domain must not resolve in DNS and must not be the target's.</li>"
            "<li>One persona per session, consistent story; facts about the target only from the verified brief; no exact figures.</li>"
            "<li>No real malware: attachments are file names, PDFs are one-page placeholders.</li>"
            "<li>No human in the loop: the agent writes, sends and decides on its own.</li>"
            "<li>Eval sessions refused unless explicitly allowed (--allow-eval).</li></ul></div>")
    out = out_dir / "how.html"
    out.write_text(page("How it works · revel8 agent", "<span class='crumb'>/</span><span class='crumb'>how it works</span>", body, False),
                   encoding="utf-8")
    return out
