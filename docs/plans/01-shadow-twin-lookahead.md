# Plan 01 — Risk-Calibrated Shadow-Twin Counterfactual Lookahead

**Feature Flag:** `RunConfig.use_shadow_twin: bool = True` (`--shadow-twin` / `--no-shadow-twin`)  
**Target Rubric Buckets:** Architecture & Persistence (**40 pts**), Results (**25 pts**), Pitch & Demo (**15 pts**)  
**Estimated Build Time:** ~2.0 hours  

## 1. Core Idea (Why It Is Not a Vanilla Orchestrator)
Instead of sending the first LLM draft directly to the Target API, the agent performs **inference-time counterfactual search**:
1. Proposes **3 distinct candidate moves** along a risk/appropriateness spectrum (`safe`, `balanced`, `bold`) — e.g., async email follow-up vs. channel pivot vs. 1-touch live call (`phone_call` / `teams_call`).
2. Rehearses all 3 candidates **in parallel** against a role-aware local **Shadow Twin** of the target (grounded strictly in `VerifiedDossier` + live session history).
3. Ranks the 3 forecasts with a **deterministic Python EV scorer**, dispatches ONLY the highest-EV move, and records **all 3 branches + predicted vs. actual reaction** in `step["shadow_twin"]` for the turn-by-turn jury replay.

Directly addresses the lead judge's feedback: *"an attacker prompt can't feel social appropriateness (e.g., WhatsApp-calling a C-level exec after 1 email) or when to take a calculated risk vs. play it safe."*

## 2. Exact Interfaces (`src/revel8_agent/shadow_twin.py`)
```python
class ShadowForecast(BaseModel):
    risk_tier: Literal["safe", "balanced", "bold"]
    predicted_reaction: Literal["engage", "question", "stall", "ignore", "suspicious", "incident"]
    progress_prob: float = Field(ge=0.0, le=1.0)
    suspicion_risk: float = Field(ge=0.0, le=1.0)
    social_norm_violation: float = Field(ge=0.0, le=1.0)
    verifiability_risk: float = Field(ge=0.0, le=1.0)
    predicted_questions: list[str] = Field(default_factory=list)
    rationale: str

def score_forecast(f: ShadowForecast, draft: dict, ledger: TargetLedger) -> float:
    return (
        f.progress_prob
        - 0.8 * f.suspicion_risk
        - 1.0 * f.social_norm_violation
        - 0.7 * f.verifiability_risk
    )
```

## 3. Latency & Rate-Limit Budget (AMD Token Factory)
- **1 LLM call** to generate 3 candidate drafts (`safe`, `balanced`, `bold`) in one JSON object (~10–12s on `DeepSeek-V4-Flash`).
- **3 parallel LLM calls** (`ThreadPoolExecutor(3)`) for Shadow-Twin rehearsal (~12s wall-clock).
- Total overhead: **~22–25s per touch** (~3.5 min per 10-touch run) — well within Sunday's eval window, and falls back cleanly to baseline `decide()` on any 429/timeout.

## 4. Replay & Verification
- `report.py` renders all 3 candidate cards (`Safe` / `Balanced` / `Bold`), EV scores, and **Predicted vs. Observed** reaction side-by-side.
- Unit tests (`tests/test_shadow_twin.py`): deterministic EV ranking, parallel execution, graceful fallback on LLM error, Brier calibration helper.
