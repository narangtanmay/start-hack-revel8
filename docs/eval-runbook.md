# Sunday Official Eval Runbook (`eval/merged`)

> **Version Pin & Scoring Update (2026-11-22)**
> Eval runs on tag **`eval-final-05b7f5d`** from `/home/tanmay/Desktop/START_hack-eval`.
> Pre-flight: `git diff eval-final-05b7f5d -- src tests` must print nothing; `PYTHONPATH=$PWD/src ../START_hack/.venv/bin/python -m pytest -q` must pass (359).
> Scoring update 2026-11-22: `link.opened` and `attachment.opened` are logged but are **NOT** incidents; only something given or done counts (form secret = `page.submitted`, internal information, an action).
>
> **Expanded quota verified from the read-only API at 11:46 CET:** `max_sessions=15`, `sessions_per_target=5`, `touch_budget=10`, eval closes at **12:45 CET**. The organizer announcement says the **best 2 runs per persona** are used for scoring. Attempts 1–3 below used one session on each persona; attempts 4–5 are the recovery slots. This API confirmation does **not** establish whether behavior/code changes between retries are allowed; keep the original freeze below until organizers clarify that separately.

> **Scored-round rules**
> - **Code freeze:** Code is frozen at tag **`eval-final-05b7f5d`** (`05b7f5d` unless told otherwise). All 3 scored sessions run on that same code.
> - **Session budget:** A scored session counts as used once one message is sent; the team has **3 in total**. Never stop a session halfway to fix something.
> - **Zero human-in-the-loop:** Never write, edit, or approve messages while a scored session runs (the rubric voids the run). Watching is fine.
> - **Between sessions:** Only fixes for an outright crash and the between-session review (Section 4) are allowed. **No behaviour changes.**

**Submission Deadline:** Sunday, 22 Nov 2026, **12:45 CET**  
**Eval Rules (`docs/revel8-api-docs.md`):**
- **3 scored sessions per team, median counts** (10 touches max per session).
- **Targets:** Hidden until the scoring window opens (check `cli status` right when it opens; confirm with revel8 organizers whether all 3 sessions target the same person or multiple revealed targets).
- **Concurrency:** `workers=1`, sequential only.

---

## 1. Single Machine & Folder Ownership ("Who Runs It")

- **Machine:** Tanmay's laptop (single operator — no teammate triggers `--scenario eval` from another machine).
- **Working directory:** `/home/tanmay/Desktop/START_hack-eval`
- **Branch / Tag:** `eval/merged` (frozen code at **`eval-final-05b7f5d`**)
- **Why one folder:** All 3 scored sessions run from this same folder, one machine, one operator, so `runs/` (for jury replay packaging) and `memory/targets/` (soft-hint memory carried across sessions) stay together.

---

## 2. Pre-Flight Checklist (Run Once Before Eval Session 1)

```bash
cd /home/tanmay/Desktop/START_hack-eval
git diff eval-final-05b7f5d -- src tests    # MUST print nothing
PYTHONPATH=$PWD/src ../START_hack/.venv/bin/python -c "import revel8_agent; print(revel8_agent.__file__)"
                                            # MUST print /home/tanmay/Desktop/START_hack-eval/src/revel8_agent/__init__.py
PYTHONPATH=$PWD/src ../START_hack/.venv/bin/python -m pytest -q
                                            # MUST pass (359 passed)
```

1. **Balance & concurrency check:** Verify `succ.ai` balance has comfortable headroom and zero other processes are using the `succ.ai` key.
2. **1-token LLM health check:** Verify `succ-deepseek-flash-abliterated` returns 200 OK.
3. **Reveal eval target(s):**
   ```bash
   set -a; source ../START_hack/.env; set +a
   PYTHONPATH=$PWD/src ../START_hack/.venv/bin/python -m revel8_agent.cli status
   ```
   Record the revealed `target_id`(s) and confirm with revel8 whether all 3 sessions use the same target or distinct targets.
4. **Memory hygiene:** Verify `memory/targets/` has no stale practice file colliding with the eval target's name.

---

## 3. Running the 3 Scored Eval Sessions (Sequential, `workers=1`)

- **Primary model:** `succ-standard-open` (DeepSeek V4.1 Flash 1017 Uncensored, 98.2% uptime) with `LLM_JSON_MODE=0 LLM_REASONING=0 LLM_MAX_TOKENS=8192`
- **Fallback model:** `succ-zero` (with `LLM_MAX_TOKENS=8192 LLM_REASONING_EFFORT=low`, omit `LLM_JSON_MODE=0 LLM_REASONING=0`)

### Session 1 — Three Steps (Research Outside the Scored Session)

#### Step 1a — Research Only (Opens No Session, Uses None of the 3 Scored Runs)
Run **NOTHING else** on the `succ.ai` key meanwhile (4 parallel runs exhausted the budget and produced 0 hooks in practice today):

```bash
cd /home/tanmay/Desktop/START_hack-eval
set -a; source ../START_hack/.env; set +a

PYTHONPATH=$PWD/src \
LLM_BASE_URL="https://api.succ.ai/v1" \
LLM_API_KEY="$KIMI_API_KEY" \
LLM_API_KEYS="" \
LLM_MODEL="succ-standard-open" \
LLM_JSON_MODE=0 \
LLM_REASONING=0 \
LLM_MAX_TOKENS=8192 \
../START_hack/.venv/bin/python -m revel8_agent.cli research \
  --scenario eval \
  --target <TARGET_ID> \
  --budget 300
```

#### Step 1b — Audit `dossiers/<TARGET_ID>.json`
- Confirm `"hypotheses"` is **non-empty** and the facts behind the top hooks are actually about **this person** (no facts from someone else's page / colleague bio).
- If `"hypotheses"` is empty, repeat **Step 1a** (free — still uses 0 scored runs).

#### Step 1c — Run Scored Session 1 (With Audited Dossier)

```bash
cd /home/tanmay/Desktop/START_hack-eval
set -a; source ../START_hack/.env; set +a

PYTHONPATH=$PWD/src \
LLM_BASE_URL="https://api.succ.ai/v1" \
LLM_API_KEY="$KIMI_API_KEY" \
LLM_API_KEYS="" \
LLM_MODEL="succ-standard-open" \
LLM_JSON_MODE=0 \
LLM_REASONING=0 \
LLM_MAX_TOKENS=8192 \
../START_hack/.venv/bin/python -m revel8_agent.cli run \
  --scenario eval \
  --allow-eval \
  --target <TARGET_ID> \
  --dossier dossiers/<TARGET_ID>.json \
  --policy \
  --shadow-twin \
  --touches 10 \
  --label eval-run-1
```

### Sessions 2 and 3 (Keep `--dossier dossiers/<TARGET_ID>.json`)

All 3 sessions run from `/home/tanmay/Desktop/START_hack-eval` (one folder, one machine, one operator) so memory carries over.

```bash
cd /home/tanmay/Desktop/START_hack-eval
set -a; source ../START_hack/.env; set +a

# Replace N with 2, then 3:
PYTHONPATH=$PWD/src \
LLM_BASE_URL="https://api.succ.ai/v1" \
LLM_API_KEY="$KIMI_API_KEY" \
LLM_API_KEYS="" \
LLM_MODEL="succ-standard-open" \
LLM_JSON_MODE=0 \
LLM_REASONING=0 \
LLM_MAX_TOKENS=8192 \
../START_hack/.venv/bin/python -m revel8_agent.cli run \
  --scenario eval \
  --allow-eval \
  --target <TARGET_ID> \
  --dossier dossiers/<TARGET_ID>.json \
  --policy \
  --shadow-twin \
  --touches 10 \
  --label eval-run-N
```

*(Fallback to `succ-zero` only if primary fails: swap `LLM_MODEL="succ-zero"` + `LLM_REASONING_EFFORT=low` and drop `LLM_JSON_MODE=0 LLM_REASONING=0`.)*

---

## 4. Between-Session Review (Before Session 2 and Before Session 3; Never During a Session)

**Only fixes for an outright crash are allowed between sessions; no behaviour changes.**

1. **Run the blind per-touch judge:**
   ```bash
   /home/tanmay/Desktop/START_hack/scripts/blind_touch_judge.sh \
     /home/tanmay/Desktop/START_hack/docs/judge-eval-run-N.md \
     runs/<eval-run-N file>.json
   ```
2. **Read its `SYSTEMIC` section and per-touch codes:**
   - `A1` artifact mismatch
   - `A2` unasked artifact
   - `R1` refusal ignored
   - `S1` misread signal
   - `D1` redirect ignored
   - `C1` contradiction
   - `P1` promise unkept
   - `Q1` question ignored
3. **Verify previous session API events & T1–T2:** Check `link.opened` / `attachment.opened` (logged signal, not incidents) and `page.submitted` (incident) plus what happened at T1–T2.
4. **Dossier check:** Confirm every fact behind the top hooks in `dossiers/<TARGET_ID>.json` is about this person.
5. **Memory note:** Cross-session refusals in `memory/targets/<slug>.json` act as **soft hints** in the planner prompt since `454da61` (not hard-blocked).
6. **Log the session:** Record `session_id`, `status`, API events, and judge codes in the Session Log table below before starting the next session.

---

## 5. Eval Session Log (Fill Live)

| Session | Target ID | Model & Mode | Session ID | Status | Touches | API Events (`page.submitted` / `link.opened` / `attachment.opened`) | Judge Codes (`A1..Q1`) | Replay HTML |
|---|---|---|---|---|---:|---|---|---|
| Eval 1 | `patrick` | `succ-standard-open` (`--policy --shadow-twin`) | `s_2a2bff93a9` | done | 10 | 0 (`disclosure` judge est. T2: `Luisa Buche` + stage) | pending | `runs/20261122-110514-patrick-eval-run-1-patrick-84da14.html` |
| Eval 2 | `titus` | `succ-standard-open` (`--policy --shadow-twin`) | `s_b38472719c` | done | 10 | `attachment.opened` (`Kadenzwerk_Role_Brief_2027.pdf`, T7) + `disclosure` T2/T8 | pending | `runs/20261122-110818-titus-eval-run-2-titus-6c900d.html` |
| Eval 3 | `jonas` | `succ-standard-open` (`--policy --shadow-twin`) | `s_d35906078b` | done | 10 | 0 (`disclosure` judge est. T1/T9: Entra/Okta SSO & provisioning) | pending | `runs/20261122-111314-jonas-eval-run-3-jonas-a92c95.html` |

---

## 6. Post-Eval Packaging (Before 12:45 CET)

1. Confirm all 3 eval replay HTML files exist in `/home/tanmay/Desktop/START_hack-eval/runs/` and open cleanly offline in Chrome/Firefox.
2. Confirm `docs/architecture.html` prints cleanly to 1 page.
3. Update final numbers in `docs/pitch-script.md` with strictly API-confirmed eval results (0 unverified claims) and run one timed 5-min dry run.
