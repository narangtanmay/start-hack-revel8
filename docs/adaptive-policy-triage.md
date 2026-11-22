# Adaptive Policy Triage: Deterministic Rails + On-Your-Feet Pivoting

**Date:** 2026-11-22  
**Goal:** Combine `--policy` (deterministic state machine + `shadow_twin.py` EV scoring) with live, reply-aware pivoting (`TargetBeliefState`) so the agent adapts to what a target actually says without drifting into polite zero-score chatter or deadlocking on gates.

---

## 1. Empirical Diagnosis: Why Previous Modes Stalled

| Mode & Run | What Worked | Why It Failed (Root Cause) |
|---|---|---|
| `--policy` + `succ-zero` on `tom` (`s_1cb26ff20b`) | **API-confirmed `page.submitted` at T3.** Stayed in-thread, strong speaker-coordinator persona, `link.opened` T1/T3. | Only worked when initial route matched target's workflow cleanly. |
| `--policy` + `ds-flash` on `tom` (`task-1704`) | **4/4 replies (100% engagement)**, sharp live lookups. | **Self-abort deadlock at T5:** earlier text tripped `gate.py` `_NO_LOGIN_CLAIMS`, but `policy.py` didn't track `login_wall` as blocked and `engine.py` kept attaching a credential page across 6 retries until hard abort. |
| `--policy` + `qwen-27b` on `tom` (`task-1675`) | **5/6 replies + `link.opened` T3.** | Low-stakes peer persona → Tom bounced at login wall (*"won't sign in for a one-pager"*), then refused weekend file. Policy had no structured constraint memory. |
| `--actor` v2/v3 + `qwen-27b` on `tom` (`task-1538`, `task-1674`) | Natural in-character tone (4/6 replies on v2). | Drifted into plain-text confirmation loop (0 API events) after T2 login pushback, or cast weak consultant persona + tried 4× SMS jumps. |
| OpenAI `gpt-6.1-terra` / `gpt-6-luna` (`task-1638`, `task-1645`) | Fast, clean JSON. | Safety blocks: `terra` soft-dodged into linkless `action`; `luna` hard-refused impersonation. |

---

## 2. Why This Hybrid Will Work Where Others Failed

1. **Closes the Blind Spot Between `policy.py` and the Target's Actual Words:**  
   `TargetBeliefState` (`target_state.py`) deterministically extracts **explicit constraints** (`login_wall`, `attachments`, `weekend_files`, `phone_switch`), **bounce signals** (`link.opened` without `page.submitted`), and **open doors / pull requests** (`wants_pdf`, `wants_email_body`, `wants_weekday_followup`) from every API event and reply.
2. **Eliminates Self-Abort Deadlocks:**  
   Prior-turn commitments (`_NO_LOGIN_CLAIMS`, `_NO_ATTACHMENT_CLAIMS`) update `blocked_mechanisms` *before* the next move is chosen, and `engine.py` strips any contradicting artifact on gate retry instead of looping 6× into an abort.
3. **Preserves Objective Discipline While Pivoting on Your Feet:**  
   Unlike pure `--actor` (which drifts into pleasant plain text after a pushback), `RuleBasedPolicy` + `shadow_twin.py` keep a concrete measurable objective active while switching *mechanism* (`credentials` → `.pdf` attachment → `disclosure`) based on the target's stated constraints.
4. **Directly Strengthens the 40-Pt Architecture & Persistence Rubric:**  
   Every touch logs `target_state` (`reaction_tag`, `stated_constraints`, `blocked_mechanisms`, `open_doors`) + 3-branch `shadow_twin` EV + `predicted → actual` `✓`/`✗` in `report.py`.

---

## 3. Why It Could Still Fail (Honest Pre-Mortem)

1. **Weak Initial Persona / Thin OSINT (Sparse Eval Targets like `julius`):**  
   Even perfect mid-thread pivoting cannot rescue a T1 hook that gets ignored (0 replies) or a low-obligation peer persona that the target won't authenticate for.
2. **Double-Block (Weekend / Strict Policy):**  
   If a target refuses *both* login links and outside files (e.g., `task-1675` T3+T4), API-confirmed incidents (`page.submitted` / `attachment.opened`) are blocked on that thread unless the agent pivots to a different angle or timing.
3. **Regex Coverage Gaps:**  
   Novel phrasing in German or English for refusals/pulls could miss deterministic cue patterns (mitigated by keeping cues broad, bilingual DE/EN, and unit-tested against all real practice transcripts).
4. **Model Floor:**  
   A 27B model (`succ-cyber-lite`) still produces weaker casting than frontier uncensored models (`succ-zero` / `succ-deepseek-flash-abliterated`).

---

## 4. Concrete Implementation & Verification Plan

1. **Add `src/revel8_agent/target_state.py`:** Typed `TargetBeliefState` extractor (`extract_target_state(steps)`) covering reaction classification, bilingual DE/EN constraint & pull cues, `link.opened` bounce detection, and prior-turn commitment detection.
2. **Wire into `policy.py` (`RuleBasedPolicy`):** Respect `blocked_mechanisms` (`login_wall`, `attachments`, `weekend_files`), pivot objective cleanly when blocked, surface `open_doors` + `stated_constraints` + `forbidden_artifacts` in `policy_move`, and attach `target_state`.
3. **Wire into `shadow_twin.py` (`select_shadow_twin_move`):** Condition 3-branch EV (`safe`/`balanced`/`bold`) on `TargetBeliefState` (`login_wall` penalty on `credentials`, `wants_pdf` boost on `action`, `weekend_files` penalty on `action`, `LINK_OPENED_BOUNCE` handling).
4. **Fix `engine.py` Deadlock + Locale Defaults:** On `Cross-turn contradiction` gate error, strip the conflicting `link` or `attachment_filename` on retry; fix hardcoded `"Dokument"` fallback to `"Dokument" if lang == "de" else "Document"`; persist `step["target_state"]`.
5. **Render in `report.py`:** Show `Target belief state` row (`reaction_tag`, `engagement_stage`, `blocked_mechanisms`, `open_doors`, `stated_constraints`) per touch.
6. **Verify:**
   - Unit tests for `target_state.py`, `policy.py`, `shadow_twin.py`, `engine.py` deadlock recovery, and `report.py` (`uv run pytest -q` 100% green).
   - Live practice tests on **`julius`** (sparse target) and **`tom`** with `succ-deepseek-flash-abliterated` + `--policy --shadow-twin` to verify zero deadlocks, live state transitions, and real API behavior.
