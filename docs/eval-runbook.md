# Sunday Official Eval Runbook (`eval/merged`)

> **Scored-round rules**
> - **Code freeze:** Code is frozen at the go/no-go commit (**`2fb6f1e`** unless told otherwise). All 3 scored sessions run on that same commit.
> - **Session budget:** A scored session counts as used once one message is sent; the team has **3 in total**. Never stop a session halfway to fix something.
> - **Zero human-in-the-loop:** Never write, edit, or approve messages while a scored session runs (the rubric voids the run). Watching is fine.
> - **Between sessions:** Only two things are allowed: fixing an outright crash, and the dossier + events check (Section 4). **No behaviour tweaks.**

**Submission Deadline:** Sunday, 22 Nov 2026, **12:45 CET**  
**Eval Rules (`docs/revel8-api-docs.md`):**
- **3 scored sessions per team, median counts** (10 touches max per session).
- **Targets:** Hidden until the scoring window opens (check `cli status` right when it opens; confirm with revel8 organizers whether all 3 sessions target the same person or multiple revealed targets).
- **Concurrency:** `workers=1`, sequential only.

---

## 1. Single Machine & Folder Ownership ("Who Runs It")

- **Machine:** Tanmay's laptop (single operator — no teammate triggers `--scenario eval` from another machine).
- **Working directory:** `/home/tanmay/Desktop/START_hack-eval`
- **Branch:** `eval/merged` (frozen at **`2fb6f1e`**)
- **Why one folder:** All 3 scored sessions run from this same folder so `runs/` (for jury replay packaging) and `memory/targets/` (soft-hint memory carried across sessions) stay together.

---

## 2. Pre-Flight Checklist (Run Once Before Eval Session 1)

```bash
cd /home/tanmay/Desktop/START_hack-eval
git rev-parse --short HEAD                  # Must match frozen commit (2fb6f1e unless told otherwise)
git status --short -- src tests             # Must be clean (no uncommitted edits)
PYTHONPATH=$PWD/src ../START_hack/.venv/bin/python -c "import revel8_agent; print(revel8_agent.__file__)"
                                            # MUST print /home/tanmay/Desktop/START_hack-eval/src/revel8_agent/__init__.py
PYTHONPATH=$PWD/src ../START_hack/.venv/bin/pytest -q
                                            # Must be 100% green
```

1. **Balance check:** Verify `succ.ai` balance has comfortable headroom (and keep concurrency = 1, especially if falling back to `succ-zero`).
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

- **Primary model:** `succ-deepseek-flash-abliterated` with `LLM_JSON_MODE=0 LLM_REASONING=0 LLM_MAX_TOKENS=8192`
- **Fallback model:** `succ-zero` (with `LLM_MAX_TOKENS=8192 LLM_REASONING_EFFORT=low`, omit `LLM_JSON_MODE=0 LLM_REASONING=0`)

### Session 1 (Live Research — Target Hidden Until Window Opens)

```bash
cd /home/tanmay/Desktop/START_hack-eval
set -a; source ../START_hack/.env; set +a

PYTHONPATH=$PWD/src \
LLM_BASE_URL="https://api.succ.ai/v1" \
LLM_API_KEY="$KIMI_API_KEY" \
LLM_API_KEYS="" \
LLM_MODEL="succ-deepseek-flash-abliterated" \
LLM_JSON_MODE=0 \
LLM_REASONING=0 \
LLM_MAX_TOKENS=8192 \
../START_hack/.venv/bin/python -m revel8_agent.cli run \
  --scenario eval \
  --allow-eval \
  --target <TARGET_ID> \
  --policy \
  --shadow-twin \
  --touches 10 \
  --label eval-run-1
```

### Sessions 2 and 3 (Reuse Audited Dossier)

After auditing `dossiers/<TARGET_ID>.json` following Session 1, pass `--dossier dossiers/<TARGET_ID>.json` on Sessions 2 and 3 so they reuse the audited dossier instead of re-researching (honoured in eval since `2fb6f1e`). Run from this same folder so memory carries over.

```bash
cd /home/tanmay/Desktop/START_hack-eval
set -a; source ../START_hack/.env; set +a

# Replace N with 2, then 3:
PYTHONPATH=$PWD/src \
LLM_BASE_URL="https://api.succ.ai/v1" \
LLM_API_KEY="$KIMI_API_KEY" \
LLM_API_KEYS="" \
LLM_MODEL="succ-deepseek-flash-abliterated" \
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

## 4. Mandatory Between-Session Check (Before Session 2 and Before Session 3)

**Only two things are allowed between sessions:** fixing an outright crash, and this dossier + events check (no behaviour tweaks).

1. **Previous session API events & T1–T2 check:** Inspect `runs/*eval-run-N*.html` and `.json` — check the real API events (`link.opened` / `page.submitted` / `attachment.opened`) and what happened at **T1–T2**.
2. **Dossier audit (`dossiers/<TARGET_ID>.json`):** Verify that every fact the top hooks rely on is actually about **this person** (no facts from someone else's page / colleague bio).
3. **Memory note:** Cross-session refusals in `memory/targets/<slug>.json` act as **soft hints** in the planner prompt since `454da61` (they are not hard-blocked).
4. **Log the session:** Record `session_id`, `status`, and API events in the Session Log table below before starting the next session.

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
