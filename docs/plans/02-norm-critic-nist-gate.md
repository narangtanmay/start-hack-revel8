# Plan 02 — Dynamic Constraint Ledger + NIST SP 2276 Norm-Critic Gate

**Feature Flag:** `RunConfig.use_ledger_gate: bool = True` (`--ledger-gate` / `--no-ledger-gate`)  
**Target Rubric Buckets:** Architecture & Persistence (**40 pts**), Craft (**10 pts**), Targeting (`−5` wrong-facts protection), Results (**25 pts**)  
**Estimated Build Time:** ~1.5 hours  

## 1. Core Idea (Fixes All 5 Bugs Observed in the First 12 Live Runs)
Replaces prompt-praying with **deterministic Python state tracking + pre-send structural checks** grounded in **NIST SP 2276 (Premise Alignment vs. Observable Cues)**:
1. **Typed `TargetLedger` (`src/revel8_agent/ledger.py`):** Updated deterministically after every API response:
   - `refused_login: bool` — set when target explicitly refuses portals/sign-in; Python prunes `"credentials"` from eligible objectives automatically.
   - `requested_format: str | None` — captures explicit requests (`"pdf"`, `"plain_text"`).
   - `open_to_call: bool` — set when target offers or agrees to a call.
   - `stall_count: int` — increments on empty-event silence or repeated deferral phrases (`"next week"`, `"travelling"`, `"on the road"`).
   - `burned_channels: list[str]` — channels ignored ≥2 times.
   - `open_questions: list[str]` — unresolved verification questions from the target.
2. **Deterministic Gate Upgrades (`src/revel8_agent/gate.py` + `engine.py`):**
   - **Promise-vs-Artifact Check:** Hard-rejects any draft claiming `"public page"` / `"no login"` / `"without an account"` when `landing_page.fields` requests credentials.
   - **Attachment Format Integrity (`engine.py` L612):** Never silently renames `.pdf` → `.docx` when `_pdf_asset()` upload fails; preserves exact requested `.pdf` filename.
   - **Channel/Seniority Norm Check:** Flags inappropriate channel jumps (e.g., cold `whatsapp`/`sms` to C-level execs before establishing rapport) as a gate warning/penalty.

## 2. Exact Interfaces
```python
class TargetLedger(BaseModel):
    refused_login: bool = False
    requested_format: str | None = None
    open_to_call: bool = False
    stall_count: int = 0
    burned_channels: list[str] = Field(default_factory=list)
    channel_history: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)

def update_ledger(ledger: TargetLedger, step: dict) -> TargetLedger: ...
def allowed_objectives(ledger: TargetLedger) -> list[str]: ...
def recommended_action(ledger: TargetLedger) -> str | None: ...
```

## 3. Latency & Cost
- **Zero extra LLM calls** (~0 ms overhead, 100% deterministic Python).
- Works identically on any unseen Sunday holdout target — zero founder-specific hardcoding.

## 4. Verification
- `tests/test_ledger.py`: unit tests for refusal detection, `.pdf` detection, call openness, stall counting, channel burning, objective pruning.
- `tests/test_gate.py`: Promise-vs-Artifact rejection test + `.pdf` preservation test in `tests/test_engine.py`.
