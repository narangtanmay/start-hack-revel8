# Sunday Official Eval Runbook (`eval/merged`)

**Submission Deadline:** Sunday, 22 Nov 2026, **12:45 CET**  
**Eval Rules (`docs/revel8-api-docs.md`):**
- **3 scored sessions per team, median counts** (10 touches max per session).
- **Targets:** Hidden until the scoring window opens (check `cli status` right when it opens; confirm with revel8 organizers whether all 3 sessions target the same person or multiple revealed targets).
- **Quota rule:** An eval session only counts once you use a touch in it. Never open/run in parallel (`workers=1`, sequential only).

---

## 1. Single Machine & Folder Ownership ("Who Runs It")

- **Machine:** Tanmay's laptop (single operator — no teammate triggers `--scenario eval` from another machine).
- **Working directory:** `/home/tanmay/Desktop/START_hack-eval`
- **Branch:** `eval/merged`
- **Why one folder:** All 3 eval sessions share `runs/` (for jury replay packaging) and `memory/targets/` (so target-stated refusals carry forward cleanly as hard rules if multiple sessions hit the same target).

---

## 2. Pre-Flight Checklist (Run Once Before Eval Session 1)

```bash
cd /home/tanmay/Desktop/START_hack-eval
git rev-parse --short HEAD                  # Confirm exact frozen eval/merged commit
git status --short -- src tests             # Must be clean (no uncommitted edits)
PYTHONPATH=$PWD/src ../START_hack/.venv/bin/python -c "import revel8_agent; print(revel8_agent.__file__)"
                                            # MUST print /home/tanmay/Desktop/START_hack-eval/src/revel8_agent/__init__.py
PYTHONPATH=$PWD/src ../START_hack/.venv/bin/pytest -q
                                            # Must be 100% green (356+ passed)
```

1. **Balance check:** Verify `succ.ai` balance is **≥ $3.50** (and keep concurrency = 1 so `succ-zero` never hits a 402 hold).
2. **1-token LLM health check:** Verify `succ-zero` (or `succ-deepseek-flash-abliterated`) returns 200 OK.
3. **Reveal eval target(s):**
   ```bash
   set -a; source ../START_hack/.env; set +a
   PYTHONPATH=$PWD/src ../START_hack/.venv/bin/python -m revel8_agent.cli status
   ```
   Record the revealed `target_id`(s) and confirm with revel8 whether all 3 sessions use the same target or distinct targets.
4. **Memory hygiene:** Verify `memory/targets/` has no stale practice file colliding with the eval target's name.

---

## 3. Running the 3 Scored Eval Sessions (Sequential, `workers=1`)

```bash
cd /home/tanmay/Desktop/START_hack-eval
set -a; source ../START_hack/.env; set +a

# Replace <TARGET_ID> and N (1, 2, 3).
# Primary model: succ-zero (Kimi K3.1 Pro, 64% Cyber Index, 0% safety blocks)
# Fallback model: succ-deepseek-flash-abliterated (57% Cyber Index, LLM_JSON_MODE=0 LLM_REASONING=0)
PYTHONPATH=$PWD/src \
LLM_BASE_URL="https://api.succ.ai/v1" \
LLM_API_KEY="$KIMI_API_KEY" \
LLM_API_KEYS="" \
LLM_MODEL="succ-zero" \
LLM_MAX_TOKENS=8192 \
LLM_REASONING_EFFORT=low \
../START_hack/.venv/bin/python -m revel8_agent.cli run \
  --scenario eval \
  --allow-eval \
  --target <TARGET_ID> \
  --policy \
  --shadow-twin \
  --touches 10 \
  --label eval-run-N
```

---

## 4. Mandatory Between-Session Review Gate (Session 1 → 2 and 2 → 3)

**Do NOT fire Session N+1 blindly.** Spend 2 minutes checking 4 concrete items after Session N finishes:

1. **Session accounting:** Record `session_id`, `status`, `touches_used`, and real API events (`link.opened`, `page.submitted`, `attachment.opened`) in the log table below.
2. **Dossier sanity (for targeting −5 wrong-fact guard):** Inspect `dossiers/<TARGET_ID>.json` — confirm top hooks (`h1`, `h2`) and facts are actually about THIS person (no colleague bio bleed, no past event pitched as upcoming).
3. **T1–T2 mechanics check:** Open `runs/*eval-run-N*.html` — check whether there were crashes, draft-rejection loops, or unintended channel jumps (`sms`/`linkedin_connection_request`).
4. **Cross-session memory check:** Inspect `memory/targets/<slug>.json`:
   - Confirm `rules` contains ONLY explicit target-stated refusals (`refused: login_wall`, `refused: attachments`, etc.) and zero accidental self-blocks.
   - Note: on Session N+1, `engine.py` automatically loads `tmemory.refused_mechanisms()` into `prior_blocked` / `forbidden_artifacts` as hard rules from Touch 1.
5. **Go / No-Go:** Only start Session N+1 once items 1–4 are green.

---

## 5. Eval Session Log (Fill Live)

| Session | Target ID | Model & Mode | Session ID | Status | Touches | API Events (`link.opened` / `page.submitted` / `attachment.opened`) | Replay HTML |
|---|---|---|---|---|---:|---|---|
| Eval 1 | | | | | | | |
| Eval 2 | | | | | | | |
| Eval 3 | | | | | | | |

---

## 6. Post-Eval Packaging (Before 12:45 CET)

1. Confirm all 3 eval replay HTML files exist in `/home/tanmay/Desktop/START_hack-eval/runs/` and open cleanly offline in Chrome/Firefox.
2. Confirm `docs/architecture.html` prints cleanly to 1 page.
3. Update final numbers in `docs/pitch-script.md` with strictly API-confirmed eval results (0 unverified claims) and run one timed 5-min dry run.
