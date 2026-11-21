# Plan 04 — Channel-Escalation Bandit + Unified Ablation Matrix

**Feature Flag:** `RunConfig.use_escalation_policy: bool = True` + `scripts/ablate.py`  
**Target Rubric Buckets:** Architecture & Persistence (**40 pts**), Results (**25 pts**), Pitch & Demo (**15 pts** — real before/after empirical table!)  
**Estimated Build Time:** ~1.5 hours  

## 1. Core Idea (Empirical Ablation + Live-Call Micro-Controller)
Rather than guessing which upgrades actually improve conversion on live practice runs, every strategy is an **independent boolean toggle** on `RunConfig`, plus a lightweight **Channel-Escalation Policy & 10-Turn Call Controller**:
1. **Multi-Target & Live-Call Escalation Policy:**
   - Inside a 10-touch session, if `ledger.open_to_call` is True or `ledger.stall_count >= 2` (and no live call was attempted yet), elevate `phone_call` / `teams_call` (1 touch = up to 10 turns!).
   - Inside a live call, run a clean 4-phase controller (`opening → agenda → verification → close`) that pauses the agenda whenever the target asks a verification question.
   - If the active target explicitly refuses (`sentiment == "refusing"` or `stall_count >= 3`), allow pivoting to the next-highest-dossier target in the scenario rather than burning remaining touches.
2. **Unified Ablation Matrix (`scripts/ablate.py`):**
   Runs controlled comparisons across the 3 practice targets (`julius`, `tom`, `robert`) toggling features ON/OFF cleanly:

| Variant | `ledger_gate` | `shadow_twin` | `playbook` | `escalation` | What It Measures |
|---|:---:|:---:|:---:|:---:|---|
| `V0_baseline` | OFF | OFF | OFF | OFF | Sriyash's current `engine.py` baseline (0 incidents in 12 runs) |
| `V1_ledger` | ON | OFF | OFF | OFF | Lift from fixing the 5 observed bugs (deterministic, 0 extra LLM calls) |
| `V2_shadow` | ON | ON | OFF | OFF | Lift from 3-branch Shadow-Twin counterfactual lookahead |
| `V3_full` | ON | ON | ON | ON | Full system (Ledger + Shadow-Twin + Cross-Session Playbook + Call Escalation) |

## 2. Metrics Logged Per Variant (Real Numbers for the Pitch!)
- `incident_rate` (`runs_with_incident / total_runs`)
- `median_touches_to_incident`
- `reply_rate` & `stall_turns`
- `gate_blocks_caught` (how many bad drafts were prevented pre-send)
- `shadow_twin_prediction_accuracy` (predicted vs. actual reaction match rate)
- `avg_wall_time_s` & `avg_llm_calls` (budget safety check for Sunday eval)

## 3. Pitch Value
Having a **real empirical ablation table** (`V0 → V1 → V2 → V3`) from Saturday practice runs directly answers Fabian's question (*"does a different architecture actually beat vanilla orchestrator + prompt engineering?"*) with hard data, not hand-waving.
