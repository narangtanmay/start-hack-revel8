"""Strategy council: several strategist agents think up a campaign on the spot, a critic agent picks one.

Why: one planner call with one prompt converges on the same safe pretext every time (a CISO prospect for all three
founders). The scorer pays for an incident, and partly for an "own angle" the target was not set up for. So the
plan stage runs N strategists IN PARALLEL, each forced through a different persuasion lens, then one critic reads
all candidates against the verified profile and picks the one most likely to get a SPECIFIC internal fact or
action within two touches, without wrong facts or verification traps.

Every candidate still goes through the normal plan validation (schema, domain safety) afterwards. Autonomous: no
human picks anything. Logged to state.config["council"] for the jury replay. REVEL8_COUNCIL=0 disables; the
number sets how many strategists run (default 4).
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

LENSES: dict[str, str] = {
    "known-contact": (
        "LENS: SOMEONE THEY KNOW. Strangers get verified and refused; known contacts get answers, opened links and "
        "favours. Pick ONE real person or organisation from THEIR REAL NETWORK (investor/angel, co-founder or "
        "colleague, new hire, event host, partner, co-author). Either the sender IS that contact writing from a new "
        "address / personal account on an invented lookalike domain, or the sender is introduced by them by name. "
        "The ask is what that relationship routinely asks for (investor: KPI/board update, pipeline numbers, "
        "data-room login; colleague: a file, an access, a confirmation, an internal detail; host: logistics)."),
    "give-to-get": (
        "LENS: RECIPROCITY. The sender is someone the target routinely ANSWERS AS PART OF THEIR JOB (prospect doing "
        "vendor due diligence, partner scoping an integration). The sender opens by giving something concrete of "
        "their own (their stack, numbers, a draft) and asks for the matching item from the target's side."),
    "expert-review": (
        "LENS: THEIR TOPIC, EXPERT ASK. The target is asked, as the expert they publicly are, to sanity-check one "
        "concrete thing on exactly the topic they keep talking about. Answering well requires them to say how THEY "
        "do it internally (tool, process, owner, number)."),
    "already-committed": (
        "LENS: SOMETHING THEY ALREADY COMMITTED TO. Find a dated commitment in the profile (talk, launch, hiring, "
        "partnership, release). The sender is part of its routine logistics and needs one routine internal detail "
        "(who on their side owns it, which system, which date) to proceed. Routine needs no persuasion."),
    "own-angle": (
        "LENS: OWN ANGLE (bonus points). Pick a topic the person is probably NOT primed for but that someone in their "
        "role must handle anyway: a supplier invoice/payment detail, a reference check for a former colleague, a "
        "compliance/audit/insurance questionnaire, a customer support escalation. Plausible, boring, routine."),
    "wildcard": (
        "LENS: WILDCARD. Be creative: the most surprising sender and story that would still feel completely normal "
        "to this specific person this week, and makes a specific internal answer the natural reply."),
}

CRITIC_SYS = """You are the critic in a sanctioned social-engineering training simulation (revel8 challenge).
Several strategists each proposed one campaign against the same simulated person. Score each candidate 0-10 on:
- yield: probability that within TWO contacts the person replies with a SPECIFIC internal fact (named tool/vendor,
  internal person and role, process step, date, number, plan) or does an action for the sender.
- credibility: would this person, who checks senders and looks things up, believe it? Penalise invented networks,
  events, awards, and anything a quick web search contradicts.
- facts: every claim about the person must be supported by the profile. Penalise any unsupported claim heavily.
Return ONLY JSON: {"scores": [{"i": int, "yield": int, "credibility": int, "facts": int, "note": str}],
 "best": int, "why": str}. "best" is the index with the highest yield x credibility x facts."""


def size() -> int:
    raw = os.environ.get("REVEL8_COUNCIL", "4")
    try:
        return max(0, min(len(LENSES), int(raw)))
    except ValueError:
        return 0


def _summary(p: dict) -> dict:
    persona = p.get("persona") if isinstance(p.get("persona"), dict) else {}
    return {"hook_id": p.get("hook_id"), "objective": p.get("objective"), "pretext": str(p.get("pretext") or "")[:500],
            "sender": f"{persona.get('name', '')}, {persona.get('role', '')} at {persona.get('organisation', '')}",
            "moves": json.dumps(p.get("moves") or p.get("sequence") or "", ensure_ascii=False)[:400],
            "rationale": str(p.get("rationale") or "")[:300]}


def convene(ask: Callable[[str, str, float], dict], plan_sys: str, user: str, profile: str,
            n: int | None = None) -> tuple[dict | None, dict]:
    """ask(system, user, temperature) -> dict. Returns (chosen plan or None, log)."""
    n = size() if n is None else n
    if n < 2:
        return None, {}
    lenses = list(LENSES.items())[:n]

    def one(item: tuple[str, str]) -> tuple[str, dict]:
        name, lens = item
        try:
            return name, ask(plan_sys, f"{user}\n\n{lens}\nDesign the campaign through this lens.", 0.9)
        except Exception as error:  # noqa: BLE001 - a failed strategist just drops out
            return name, {"_error": str(error)[:200]}

    with ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(one, lenses))
    cands = [(name, p) for name, p in results if isinstance(p, dict) and p.get("hook_id") and not p.get("_error")]
    log: dict[str, Any] = {"lenses": [name for name, _ in lenses],
                           "candidates": [{"lens": name, **_summary(p)} for name, p in cands]}
    if not cands:
        return None, log
    if len(cands) == 1:
        log["picked"] = cands[0][0]
        return cands[0][1], log
    critic_user = (f"PROFILE (the only true facts about the person):\n{profile[:5000]}\n\nCANDIDATES:\n" +
                   "\n".join(f"[{i}] lens={name}: {json.dumps(_summary(p), ensure_ascii=False)}"
                             for i, (name, p) in enumerate(cands)))
    try:
        verdict = ask(CRITIC_SYS, critic_user, 0.0)
    except Exception as error:  # noqa: BLE001
        verdict = {"_error": str(error)[:200]}
    best = verdict.get("best") if isinstance(verdict, dict) else None
    if not isinstance(best, int) or not 0 <= best < len(cands):
        best = 0
    log.update({"critic": verdict, "picked": cands[best][0]})
    return cands[best][1], log
