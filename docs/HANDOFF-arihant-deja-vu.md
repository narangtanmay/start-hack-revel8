# Handoff: branch `arihant/deja-vu` (2026-11-22)

Context for a new Claude session continuing this work. Branched from Tanmay's `feat/shadow-twin-engine` @ `76472bd`.

## Rules that matter (read first)
- **Scoring update (2026-11-22):** `link.opened` / `attachment.opened` still give some points but are **NOT incidents**.
  A win needs something given or done: a secret typed into a form (`page.submitted`), internal information
  (disclosure), or the person doing something for us (approve, change payment details, grant access).
- **Eval:** 3 sessions per team, median counts, **10 touches per session across all hidden targets**.
  Practice: 30 touches per session, named targets julius / tom / robert.
- Voids: prompt injection / addressing the twin as an AI, real org domains, human in the loop.
- **Paid models:** succ.ai Kimi (`KIMI_*` in `.env`) costs the user real money. Never use it without explicit
  permission per run. Token Factory DeepSeek / Qwen (rc- keys) are free. The self-hosted Radeon instance burns points.

## What this branch adds (all model-independent, deterministic, tested: 340 pass)
| Module | What | Why it should hold on held-out twins |
|---|---|---|
| `memory.py` Déjà-vu | Stores every thread per target; next session replays the best earlier thread compressed (pre-answer their questions) | Twins forget across sessions, we do not |
| `memory.py` playbook v2 | Archetype win-rates with empirical-Bayes prior (0.7, 10); API-confirmed mechanisms by role family; "reuse mechanism, never facts" | Transfers by role, not by name |
| `memory.py` `is_win` / `is_confirmed_win` | New win definition. Only `page.submitted` stops a run / triggers the chain (judged wins can be false positives) | Scoring update |
| `demands.py` | Demand monitor: questions, artifact asks, people to include, channel; open demands go into the prompt and the draft is sent back if unmet (max 2 redrafts) | Targets asked for artifacts 32x in 30 runs, we delivered next touch 8x |
| `ladder.py` (NEW, not yet live-tested) | Commitment ladder rung 0-3 from events; every draft from rung 1 must carry an elicitation (tool/process/approver), an approval ask or a registered link. Flag `REVEL8_LADDER=0` disables (A/B) | Twins reply a lot but give nothing; a reply with one internal fact is the cheapest win |
| engine "THEY ENGAGED" hint | After an open with no win: convert to sign-in page / approval / one internal fact | Opens no longer score |
| `cli.py` chaining | `--then all --max-chain 2`: after a confirmed win, leftover touches go to the next target in the same session | Coverage within 10 touches |
| `_llm_json` | 429/5xx backoff up to 6x | Token Factory 429s crashed runs |
| `templates/mail.py` | Real signature block, plausible phone | Craft 10 pts |

## Evidence so far
- Old-rule wins (now only engagement): Julius attachment.opened, Qwen T6 and Kimi T4 (clean round, 09:10).
- Only API-confirmed win under the new rule in all history: Tom `page.submitted` T3 (kimi-v2, `s_1cb26ff20b`).
- Clean round 09:10 (6 sessions, Qwen + Kimi): **0 wins under the new rule**. Replies plentiful (Kimi Tom 9/9).
- Kimi vs others on old rule: 1/16 vs 2/73, Fisher p=0.45, so the model is not the bottleneck.
- A Qwen round under the new rule (no ladder; started before ladder.py) was launched ~09:40:
  `runs/*-clean-qwen-*.json` with the latest timestamps. Check its results.

## How to run
```bash
cd wt-shadow   # worktree on arihant/deja-vu; .env is gitignored (keys from the team)
uv run pytest -q
scripts/clean_round.sh qwen julius tom robert      # free; one session per target, chaining on
REVEL8_LADDER=0 scripts/clean_round.sh qwen ...    # A/B without ladder
scripts/run_matrix.sh <ds|qwen|kimi|self> <targets>
```
Profiles: `ds` = DeepSeek-V4.1-Flash, `LLM_REASONING=0` (it stalls otherwise). `qwen` = Qwen3.8-27B with
`enable_thinking:false`. `kimi` = PAID, needs `LLM_JSON_MODE=0 LLM_REASONING=0`. Verify the live model with
`ps -wwE -p <pid> | tr ' ' '\n' | grep LLM_MODEL` (macOS bash 3.2 once silently ran the wrong profile).

## Next steps
1. Run the ladder A/B on Qwen: 3 sessions with the ladder vs the results of the no-ladder round. Metric: judged
   disclosure/action plus `page.submitted`, not replies.
2. First-target ordering for eval (targets hidden): rank by role-family win-rate (new definition) plus OSINT
   signals that the person publicly asks for things. Open on the top 2 and commit to whoever engages.
3. Fill the trial table in `docs/architecture-v2.html` (published privately as a Claude artifact) with real numbers.
