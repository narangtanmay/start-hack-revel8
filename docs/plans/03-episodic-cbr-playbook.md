# Plan 03 — Episodic Case-Based Reasoning & Cross-Session Causal Playbook

**Feature Flag:** `RunConfig.use_playbook: bool = True` (`--playbook` / `--no-playbook`)  
**Target Rubric Buckets:** Architecture & Persistence (**40 pts**), Results (**25 pts** — median across 3 eval runs), Speed (**5 pts**)  
**Estimated Build Time:** ~1.5 hours  

## 1. Core Idea (Exploiting Cross-Session Memory Across Runs 1 → 2 → 3)
`docs/revel8-api-docs.md` (line 100) explicitly states: *"A new session is a clean slate... Your agent may remember whatever it likes across sessions."*
Because Sunday eval runs **3 sessions sequentially against the same unseen scenario**, a stateless agent wastes Run 2 and Run 3 repeating Run 1's mistakes. Instead:
1. **Episodic Memory Store (`runs/episodes_<scenario_id>.jsonl`):** Logs compact `(target_role, channel, hook_category, move_summary, observed_outcome)` tuples from every turn.
2. **Causal Playbook Compiler (`src/revel8_agent/playbook.py`):** At the end of each run, compiles up to **3 structured, falsifiable rules**:
   - `PlaybookRule(id, trigger, decision_change, expected_outcome, evidence_refs, status)`
   - Separates **scenario-general rules** (e.g., *"when target defers async by >2 turns, 1-touch live call breaks the stall"*) from **target-specific discoveries** learned in Run 1 (e.g., *"Hook H2 got immediate engagement; Hook H1 was ignored"*).
3. **Run 1 → Run 2 → Run 3 Progression:**
   - **Run 1 (Explore):** Probes top hypothesis, records what stalled vs. engaged.
   - **Run 2 (Exploit):** Loads Run 1's compiled playbook to hit the engaged hook/channel in 2–4 touches.
   - **Run 3 (Verify or Own-Angle):** Either locks 3/3 reliability or tests an `own_angle` (+4 pts bonus) with Run 1/2's fallback ready.

## 2. Exact Interfaces
```python
class PlaybookRule(BaseModel):
    id: str
    trigger: str
    decision_change: str
    expected_outcome: str
    evidence_run_id: str
    status: Literal["active", "confirmed", "discarded"] = "active"

def load_playbook(scenario_id: str, runs_dir: Path = Path("runs")) -> list[PlaybookRule]: ...
def compile_playbook_update(state: dict, llm: LocalLLMClient, runs_dir: Path = Path("runs")) -> list[PlaybookRule]: ...
```

## 3. Risks & Mitigations
- **False causality risk (flagged by The Fool):** With only 3 live runs, simulator variance can look like a causal rule. Mitigation: tag every rule with `evidence_run_id`, limit to 1–3 high-signal rules, and never override hard `TargetLedger` constraints.
- **Overhead:** Only **1 extra LLM call per finished session** (~10s between runs).

## 4. Verification
- `tests/test_playbook.py`: JSON persistence round-trip, rule cap enforcement, clean separation of `practice` vs. `eval` playbooks (so practice founder rules never leak into Sunday's unseen `eval` scenario!).
