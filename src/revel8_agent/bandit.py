"""Thompson sampling over sender archetypes (and over targets) with a hierarchical empirical-Bayes prior.

Why a bandit here and nowhere else: sessions are the pulls. Inside one 10-touch session the incident reward is too
rare and too delayed to learn from, but across practice + eval sessions each run is one (archetype, target family)
pull with a binary API-confirmed outcome. Rewards are API-confirmed wins only, never replies.

Posterior per cell (archetype x target role family):
    Beta(s * p_arch + won_cell, s * (1 - p_arch) + lost_cell)
where p_arch is the archetype's smoothed global win rate (memory._rates) and s the shrinkage strength. A cell with
no own data falls back to the archetype; an archetype with no data falls back to the practice base rate.
Disable with REVEL8_BANDIT=0 (A/B).
"""
from __future__ import annotations

import os
import random

from .memory import _rates, role_family

STRENGTH = 5.0          # pseudo-runs the family cell borrows from its archetype
MIN_TOUCHES = 5         # same evidence floor as playbook_prompt


def enabled() -> bool:
    return os.environ.get("REVEL8_BANDIT", "1") != "0"


def _arms(pb: dict) -> dict:
    return {k: _rates(v) for k, v in (pb.get("archetypes") or {}).items() if v.get("touches", 0) >= MIN_TOUCHES}


def posterior(arm: dict, family: str) -> tuple[float, float]:
    p = arm["win_rate"]
    cell = (arm.get("families") or {}).get(family) or {}
    won, runs = cell.get("runs_won", 0), cell.get("runs", 0)
    return STRENGTH * p + won, STRENGTH * (1 - p) + max(0, runs - won)


def explore() -> bool:
    # Live evidence (22 Nov): exploration cast Tom as an event organiser (mean 0.07) and Robert as a recruiter
    # (0.05); both invented commitments and got "who invited me?". Three scored runs cannot pay for exploration,
    # so the default is greedy on the posterior mean. REVEL8_BANDIT_EXPLORE=1 for practice sweeps.
    return os.environ.get("REVEL8_BANDIT_EXPLORE", "0") == "1"


def sample_archetypes(pb: dict, target_role: str, rng: random.Random, sample: bool | None = None) -> list[dict]:
    """One Thompson draw per archetype for this target (or the posterior mean when not exploring); best first.
    'other' is a catch-all bucket, not a sender anyone can be cast as."""
    fam = role_family(target_role)
    sample = explore() if sample is None else sample
    out = []
    for name, arm in _arms(pb).items():
        if name == "other":
            continue
        a, b = posterior(arm, fam)
        mean = a / (a + b)
        out.append({"archetype": name, "draw": round(rng.betavariate(a, b) if sample else mean, 4),
                    "mean": round(mean, 4), "family": fam})
    return sorted(out, key=lambda d: d["draw"], reverse=True)


def rank_targets(pb: dict, targets: list[dict], rng: random.Random) -> list[dict]:
    """Hidden eval targets: score each by its best archetype draw; open on the top two, commit to who engages."""
    scored = []
    for t in targets:
        draws = sample_archetypes(pb, t.get("role", ""), rng)
        scored.append({**t, "draw": draws[0]["draw"] if draws else 0.0,
                       "archetype": draws[0]["archetype"] if draws else None})
    return sorted(scored, key=lambda t: t["draw"], reverse=True)


def pick_prompt(pick: dict | None) -> str:
    if not pick:
        return ""
    return (f"SENDER ARCHETYPE FOR THIS SESSION (Thompson sample over API-confirmed wins, {pick['family']} targets): "
            f"cast the sender as a {pick['archetype']}, unless the verified profile makes that implausible for this "
            "person. Keep the facts from this person's profile; only the sender type comes from here.")
