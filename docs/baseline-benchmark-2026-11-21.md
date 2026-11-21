# Baseline Practice Benchmark — 2026-11-21 (22:40 CET)

**Run type:** REAL (live Revel8 Practice API + AMD Token Factory `DeepSeek-V4-Flash`, 4 keys)
**Branch / Commit:** `feat/shadow-twin-engine` @ `51013f3` (merged `origin/main` `c3dd08a` + `origin/feat/engine-runner` `b25183a`)
**Command:** `uv run python -m revel8_agent.swarm --all --touches 10`
**Policy / Decision Controller:** Baseline `engine.py` (free-form LLM decisions, `--policy` not yet wired; `gate.py` promise/artifact validator + `.pdf` fix active)

## Scorecard (`python -m revel8_agent.benchmark runs/20261121-224051-*.json`)

| Metric | Score | Notes |
| :--- | :---: | :--- |
| **Results** | `0.0 / 25` | 0/3 runs with API-confirmed incident; median contacts to first incident: `None` |
| **Targeting** | `6.0 / 10` | `their-topic`: `6.0` (share `1.0`), `own-angle`: `0.0` |
| **Craft** | `n/a` | 21 rendered items across 3 runs (jury-rendered; not auto-scored) |
| **Jury (Arch + Pitch)** | `n/a` | 40 + 15 pts (manual) |
| **Measured Total** | **`6.0 / 35`** | Baseline floor before `policy.py` / `timing()` / `STOP` fixes |

## Per-Target Run Summary

| Target | Run File | Touches Used | Incidents | Planned Objective | Key Observed Failure Modes |
| :--- | :--- | :---: | :---: | :--- | :--- |
| `tom` | `runs/20261121-224051-tom.json` | 10 | 0 | `credentials` | `timing()` mislabeled `AI House Davos 2026` & `TUM.ai Agent Olympics` as `current`; `T1`–`T3` sent `link=False` despite `credentials` plan; garbled token (`"Skip"`/`"UTE"`) in T8. |
| `julius` | `runs/20261121-224051-julius.json` | 10 | 0 | `credentials` | 8 consecutive empty-`paragraphs` JSON slips from `DeepSeek-V4-Flash`; `T1`–`T3` sent `link=False`; forced 6+ silent touches because `engine.py` refuses `STOP`. |
| `robert` | `runs/20261121-224051-robert.json` | 10 | 0 | `credentials` | All 6 hooks (`h1`–`h5`, `own1`) labeled `PAST` by `_hook_with_timing()`; garbled token artifact in T10; forced silent touches (`STOP` blocked). |

## Root-Cause Audit (Harness vs. Model)

1. **Engine `timing()` / `_hook_with_timing()` bug (`src/revel8_agent/engine.py:128-184`):** Year-only strings (`"2026"`) return `"this-year"` and fall through to `hook["timing"] = "current"`, causing past 2026 events to be pitched as current. Conversely, when all facts have explicit past dates (`robert`), all 6 hooks are stamped `PAST`.
2. **Engine `STOP` refusal (`src/revel8_agent/engine.py:783-788`):** Refusing `STOP` while touches remain forces 6+ silent touches across dead threads instead of logging a clean back-off/pivot.
3. **Unwired policy controller:** `engine.py` currently relies on free-form LLM decisions without an explicit inspectable policy seam (`policy.py` / `step["policy"]`).
4. **Model / serving artifacts (`DeepSeek-V4-Flash` on Token Factory):** Mid-sentence token corruption (`"Skip"`, `"UTE"`) and repeated empty-`paragraphs` JSON outputs on `julius`. Worth A/B testing against `Qwen3-32B` (4-GPU TP=4 from `523511a`) or `Kimi K3.1 Pro` *after* fixing the 3 engine bugs above.
