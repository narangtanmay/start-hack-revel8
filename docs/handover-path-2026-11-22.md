# Revel8 handover · 22 November 2026

**Code snapshot requested for this handover** · `feat/shadow-twin-engine` at `1e4f43e` (05:27 CET). **Verification** · 310/310 pytest passed. **Practice evidence** · One API-confirmed incident, on `tom` in `s_1cb26ff20b`. The local archive contains practice sessions only.

## 1. Path

Dates and times below are commit times in CET. Merge hashes identify the integration on this branch.

| Date and time | Commits | What landed |
|---|---|---|
| Nov 21, 14:24–18:28 | `94debdc`, `5ed50bf`, `39b5a96`, `7219331`, `de466ef` | Started with schemas, read client, pre-send validation, LLM client, tracing and tests. Added idempotent API writes and merged the OSINT, craft-template and Arihant founder-insights branches. |
| Nov 21, 18:54–20:56 | `7b4d6b4`, `49a73ba`, `879a30f`, `cc6d27c`, `00c85e3`, `ed07a83` | Built the end-to-end runner and HTML replay. Early practice informed stop handling and dashboard work. Added four design and ablation plans, promise-versus-artifact checks, PDF integrity and a counterfactual panel. |
| Nov 21, 21:37–22:54 | `e9f48f4` ← main `a8eb94b`; `b561da1` ← main `c3dd08a`; `51013f3` ← engine-runner `b25183a`; `f189043` | Integrated the research and parallel-worker work, Radeon vLLM benchmarks, and the rubric scorecard. Published the three-target baseline and root-cause audit. |
| Nov 21, 22:59–23:48 | `c1852ff`, `823a37a`, `5aa146e`, `dfbc4fa`, `4b69b90` | Added the pluggable `policy.py` controller, logged stops, a policy replay panel and shared `LLMPool`. The client gained token-budget and reasoning-effort controls. Added plan validation, policy-to-action binding, cross-turn consistency checks and expanded date parsing. |
| Nov 22, 00:01–00:42 | `f109415`, `c7ea1f4`, `9740b22`, `af335e0` | Published the first API-confirmed result. Fixed reply-thread continuity, made stop-on-incident depend on API evidence, prevented repeated SMS fallback and corrected an inverted attachment check. |
| Nov 22, 01:34–02:17 | `b9e6290` ← method-actor v1 `a15e312`; `cc3ee78`, `c1fe7f8`, `154791c`, `e478db1`, `268607d` | Merged the actor decision path, added the one-page architecture diagram, then added deterministic three-branch `shadow_twin.py`, actor replay, a channel-norm check and eval safeguards. Archived practice logs. Actor v2 landed through `e478db1` and `268607d`, covering casting and turn validation. |
| Nov 22, 02:33–04:15 | `6f956a7`; `76c67ec` ← `arihant/pipeline-v12` `40d4ade`; `8d458c3`, `c82a9b5`; `b3b1766` ← method-actor v3 `bfd8903` | Added organizer transcripts. Pipeline v12 incorporated v10 research and memory (`7a3aac4`, integrated at `482af78`), v11 reasoning and JSON recovery (`ce4b3b9`, merged at `889528b`), and personal-answerability ranking. Follow-ups corrected source attribution, shortened single-key HTTP 402 cooldown, added a JSON request-format toggle and improved replay. The actor v3 merge added draft repair and stricter casting validation. |
| Nov 22, 04:21–05:27 | `85c7400`, `b441e9e`, `1e4f43e` | Revised the jury diagram, added the five-minute pitch and fixed OpenAI request parameters. Added `TargetBeliefState`, state-aware policy and forecasts, cross-turn retry recovery and replay state. HEAD preserves the active hook on replied-to threads and represents an explicit call invitation in the forecast. |

## 2. Empirical run scoreboard

At the first read, the local `runs/*.json` archive contained **37 practice records** (21 tracked). Of these, 26 were marked `done`, five `error`, four `running` and two `starting`. A later read found 38 records and the same incident counts. These are saved statuses. Reply counts below come from `steps[].events[]`; denominators use `touches_used` except where explicitly described. A reply or `link.opened` is engagement evidence. Incident provenance comes from `incidents[].source`, cross-checked against raw API events. In current code, `estimate_score()` derives `confirmed_by_api_event` from the incident source. Older archives store the source directly.

### API-confirmed · one incident in one session

| Target and session | Evidence | Local result |
|---|---|---|
| `tom` · `s_1cb26ff20b` | `link.opened` on T1 and T3; `page.submitted` event `e_1970` on T3; incident source `api event` | **`confirmed_by_api_event=true`**, three contacts, two replies. The incident report estimates **23.3/25** for this practice run. [Run JSON](../runs/20261121-234816-tom-ab-kimi-v2.json) · [Incident report](incident-report-tom-2026-11-21.md) |

### LLM-judge estimates · nine labels across seven sessions

Every row below is recorded as `llm-judge (estimate)` and contributes **zero** API-confirmed incidents.

| Archived practice run | Judge labels |
|---|---|
| [Robert v2](../runs/20261122-001135-robert-ab-kimi-v2.json) | T1 action. The API recorded a reply and `link.opened`. |
| [Robert actor](../runs/20261122-013524-robert-ab-kimi-actor.json) | T2 disclosure. |
| [Tom Shadow Twin](../runs/20261122-015047-tom-ab-kimi-shadow-twin.json) | T4 disclosure. |
| [Tom cyber policy](../runs/20261122-025915-tom-ab-cyber-policy.json) | T4 disclosure in a snapshot marked `running`. |
| [Tom cyber-lite actor](../runs/20261122-034501-tom-cyber-lite-actor-tom.json) | T4 action. |
| [Tom Terra policy](../runs/20261122-040525-tom-gpt61-terra-policy-tom.json) | T3 action, T4 disclosure. |
| [Tom adaptive policy](../runs/20261122-051859-tom-adaptive-kimi-tom.json) | T3 action, T4 disclosure. |

### Practice findings and diagnosed failures

| Case | Observed result and cause |
|---|---|
| Nov 21 baseline, all three targets | Zero API incidents. Raw archives show 3 Julius replies, 2 Robert replies and 2 Tom replies. Each has 10 step records and `touches_used=9`; the write-up lists 10 touches per target. The audit identifies date-classification errors, blocked stops and malformed model output. [Baseline audit](baseline-benchmark-2026-11-21.md) |
| Julius SMS loop | Only T1 got a reply. T5–T10 were six consecutive SMS attempts after silence. The old fallback cycled hooks while reusing SMS. `c7ea1f4` addressed the immediate pivot after the first objection; `9740b22` added the SMS and replied-channel rules. [Run JSON](../runs/20261122-000203-julius-ab-kimi-v2.json) |
| Tom v10 regressions | The v10 decision layer made early links unavailable and conditioned attachments on prior conversation. These restrictions conflict with the T1 link in the known-good pre-v10 replay. Separate actor v2 casting issues included stale event facts and rejected dossier-supported years, documented by `e478db1` and `bfd8903`. The saved runs do not isolate v10 as the sole cause of a drop in results. |
| Tom `task-1704` | Four replies on four sent contacts. At T5 the gate detected a prior public/no-login promise. Policy had no corresponding blocked mechanism, so draft retries kept carrying the contradictory artifact. Two T5 step records show three failed drafts apiece; the second also records a channel-norm violation. The JSON finishes `done` with four contacts. `b441e9e` records commitments in target state and clears the conflicting artifact on retry. [Run JSON](../runs/20261122-042150-tom-ds-flash-policy-tom.json) · [Triage](adaptive-policy-triage.md) |
| Tom `task-1805` | Six replies on six email contacts, with six different hook IDs. The reply stream repeatedly hinged on a call before file review, but the saved belief state carried no call invitation and the runner stayed on email. `1e4f43e` preserves the active hook on engaged threads and adds invitation and call-completion state. The archived Tom run predates that fix. [Run JSON](../runs/20261122-051859-tom-adaptive-kimi-tom.json) |
| Other practice checks | The policy-v4 archives show Julius at four replies and one link open across ten touches, and Robert at zero replies across ten. The first Julius adaptive capture progressed from a partial snapshot to two contacts and one reply. It recorded `wants_call` on T2 and ended on invalid LLM JSON, with zero incidents. The Qwen policy capture for Tom has five replies in six contacts; triage mentions a T3 link open, but the saved event stream contains replies only. [Julius v4](../runs/20261122-004557-julius-ab-kimi-v4.json) · [Robert v4](../runs/20261122-004604-robert-ab-kimi-v4.json) · [Julius adaptive](../runs/20261122-052744-julius-adaptive-ds-julius.json) · [Tom Qwen](../runs/20261122-041517-tom-qwen-policy-tom.json) |

The task numbers are handover labels. The run filenames and session IDs are the archive identifiers.

## 3. Provider and model matrix

| Provider | Historical finding | Evidence |
|---|---|---|
| succ.ai · `succ-zero` | Identified as Kimi K3.1 Pro in the incident report. The earlier Tom arm recorded 10 replies and zero incidents; the next arm produced the sole confirmed result. Harness and date parsing changed between arms. | [A/B progression](incident-report-tom-2026-11-21.md) |
| succ.ai · `succ-deepseek-flash-abliterated` | Named in triage. The DeepSeek Flash-labelled Tom archive records four replies before the T5 gate deadlock. The run config omits the endpoint and model ID, so that exact slug is not independently recoverable from the JSON. | [Triage](adaptive-policy-triage.md) · [Run JSON](../runs/20261122-042150-tom-ds-flash-policy-tom.json) |
| succ.ai · `succ-cyber-lite` | Identified as the 27B model in triage. The cyber-lite actor archive records four replies across six sent contacts and one judge-only action. | [Triage](adaptive-policy-triage.md) · [Run JSON](../runs/20261122-034501-tom-cyber-lite-actor-tom.json) |
| OpenAI API · `gpt-6.1-terra`, `gpt-6-luna` | Triage describes Terra avoiding the requested action and Luna explicitly refusing impersonation. Terra's saved run has six replies and two judge labels. The first Luna record is a startup snapshot; the later one has five sent contacts, zero replies and zero incidents. `85c7400` routes the token budget through `max_completion_tokens` for the newer model families and omits `temperature` for them. | [Triage](adaptive-policy-triage.md) · [Terra JSON](../runs/20261122-040525-tom-gpt61-terra-policy-tom.json) · [Luna JSON](../runs/20261122-040848-tom-gpt6-luna-max-policy-tom.json) · [Client code](../src/revel8_agent/llm_client.py) |
| Radeon Cloud · self-hosted vLLM | The Nov 21 benchmarks reached both instances. Median call time was 18.13 s on one GPU and 5.03 s on four GPUs in JSON mode. A later firewall block was reported in the handover brief; the inspected repo contains no matching failure trace or firewall diagnostic. | [Benchmark](selfhost-benchmark-2026-11-21.md) · [Raw measurements](benchmarks/) |

The client exposes `LLM_JSON_MODE`, `LLM_REASONING` and `LLM_MAX_TOKENS`. The archived run configs do not capture their values or establish a provider-wide requirement. HTTP 402, key rate limits and truncated JSON appear as separate failures in the practice archive.

## 4. Current repo state and jury deliverables

**Branch movement during the audit** · The working branch advanced to `205f174` (05:31 CET), whose engine change ends a call cleanly after invalid LLM JSON. The chronology and test result are pinned to the requested `1e4f43e` revision.

**Tests** · `pytest -q -p no:cacheprovider` returned **310 passed in 16.07s** in an isolated export of `1e4f43e`, using the repo virtual environment and the exported source. This is local suite evidence. The repo had existing edits in `memory/` and `runs/`.

| Modules under `src/revel8_agent/` | Responsibility |
|---|---|
| `cli.py`, `swarm.py`, `engine.py`, `api_client.py`, `schemas.py` | CLI and worker entry points, turn lifecycle, API transport and typed inputs. |
| `policy.py`, `decision.py`, `actor.py` | Rule-based policy, alternative decision controller and persona/notebook path. |
| `target_state.py`, `shadow_twin.py`, `gate.py` | Deterministic state from replies and events, three-branch forecasts, and validation of contact plans and earlier commitments. |
| `research.py`, `osint.py`, `snowball.py`, `language.py`, `memory.py` | Dossier research and expansion, language selection, session ledger and memory. |
| `llm_client.py`, `templates/`, `mock_target.py` | Model transport and key pooling, rendering and linting, and the local simulator. |
| `trace.py`, `report.py`, `report_pages.py`, `benchmark.py`, `scorecard.py` | Trace records, HTML views, benchmark estimates and provenance-aware practice scorecards. |

- [Architecture page](architecture.html) is the one-page jury diagram covering research, decisions, gate, API and replay.
- [Pitch script](pitch-script.md) is timed to five minutes and uses the SMS regression and Tom replay. Keep form values off-screen.
- [Adaptive policy triage](adaptive-policy-triage.md) records the deadlock diagnosis, design rationale and remaining failure modes. Use the archived event stream where its shorthand differs from the JSON.

## 5. Submission checklist · 12:45 CET

**Deadline source** · 12:45 CET comes from the handover brief. The checked-in challenge PDF leaves the precise Sunday timing to the organizers. It lists an architecture page, a five-minute pitch with one real practice thread, and three scoring runs recorded by the organizer's API.

1. **Review practice traces locally.** For **Julius**, check the SMS fallback and the adaptive capture’s call handling and JSON error. For **Robert**, check that a link open plus a judge action stays an estimate. For **Tom**, verify T3 event `e_1970`, replay the T5 gate abort, and check the hook continuity and invitation handling with offline fixtures. The archived Tom trace predates the fix.
2. **Pre-flight the submission.** Confirm the deadline and scoring window with the organizers, check the selected revision and the test result, and open the diagram and pitch replay locally. Check that the replay view masks submitted values. Verify the challenge's simulation-only restrictions, eval opt-in and practice-dossier isolation through local tests.
3. **Track the three official runs in sequence.** The checked-in challenge rules give three scored runs with up to ten contacts each. The repo serializes eval tasks, and the design notes describe three sessions on the same unseen scenario. Record the organizer session ID and terminal status for run 1, run 2 and run 3 in order. Preserve the raw events and judge estimates with their provenance. All three official slots are unverified in this workspace.
4. **Hand in the diagram and pitch materials.** The challenge PDF says the API records the scoring runs and requires no separate run upload. [Challenge rules](../revel8-Agentic-Social-Engineer-Challenge.pdf) · [Scoring rubric](../revel8-Agentic-Social-Engineer-Scoring-Rubric.pdf)


## Research Triage & What We Actually Applied

Two live sweeps were run (`agent-reach` over 8 GitHub repos / 14 verified source files, and OpenAlex REST API over 11 peer-reviewed 2024–2026 ACL/EMNLP/ICLR papers / 9 verified repos).

| Paradigm (Source) | Status | Concrete Implementation in Repo |
|---|---|---|
| Explicit Belief & Constraint State (`MindDial`, `SimToM`, `Preference Estimation`) | **Applied** | `src/revel8_agent/target_state.py` (`TargetBeliefState`: `reaction_tag`, `blocked_mechanisms`, `open_doors`, `stated_constraints` with turn numbers, `call_completed`) |
| Guard-Before-Plan Failure Transitions (`JaKtA`, `ASTRA`) | **Applied** | `src/revel8_agent/policy.py` + `src/revel8_agent/engine.py` (objective/mechanism pivot on blocked login/attachments, `wants_call` → `phone_call` unlock, zero-deadlock cross-turn retry strip) |
| 1-Step Opponent-Conditioned Lookahead & Real-State Eval (`Opponent-Aware MCTS` depth-1, `τ²-bench`) | **Applied** | `src/revel8_agent/shadow_twin.py` (3-branch EV conditioned on `TargetBeliefState`) + `src/revel8_agent/report.py` (`Target state` + `predicted → actual` `✓`/`✗`, API-event truth over LLM judge) |
| Active Information-Gain Question Scoring (`BED-LLM`) | **Skipped** | Requires predictive response distribution per candidate question; deferred for 6-hour window |
| Offline RL / Self-Play / Full LLM-Rollout MCTS (`SOTOPIA-π`, `EmoDistill`, `NegLLM`, `DPDP`) | **Skipped** | Requires trajectory training / rollout simulator; out of scope for hackathon window |

---

## Update · 22 November 2026, 09:45 CET

**Read this section first; it supersedes the snapshot, scoreboard and checklist above where they differ.**

### What the eval runs on
| | |
|---|---|
| Version | tag **`eval-final-05b7f5d`** (`origin/eval/merged`), 359 tests pass |
| Folder | `/home/tanmay/Desktop/START_hack-eval` (git worktree). All 3 scored sessions from this folder, one machine, one operator. |
| Model | `succ-deepseek-flash-abliterated` on succ.ai, `--policy --shadow-twin --touches 10` |
| Runbook | `docs/eval-runbook.md` in that folder (research-first update pending at time of writing) |
| Contents | Sriyash's `feat/steering-writer` (f59b9e4) merged with our `feat/shadow-twin-engine` (9240e0c), plus the fixes below |

Other ready versions, each in its own worktree and tagged: `eval-candidate-74a714f` (`START_hack-exp`, gates unasked links/files; same practice result as the eval version), `eval-sriyash-f59b9e4` (`START_hack-sriyash`; its wins used Sriyash's provider models, never run with succ models), `eval-fallback-d743fad` (superseded by 05b7f5d).

### Scoring update from the organisers (09:40)
`link.opened` and `attachment.opened` are still logged but **are no longer incidents**. An incident needs something given or done: a secret typed into a form (`page.submitted`), internal information, or an action (approving, changing a payment detail, granting access). `05b7f5d` stops counting `attachment.opened` as an incident (it previously ended the run there). **Open:** whether disclosures/actions now arrive as their own API event types; the engine only recognises `page.submitted`. Check "Event types" in the live docs.

### API-confirmed practice results that still count
| Session | Target | Code | Event |
|---|---|---|---|
| `s_1cb26ff20b` | Tom | Nov 21, Kimi | `page.submitted` T3 |
| `s_3745f72293` | Tom | Sriyash 5c55da5, DeepSeek-V4.1 | `page.submitted` T3 |
| `s_4fddeb4d34` | Tom | merged 709b723, ds-flash | `page.submitted` T3 |
| exp run (74a714f) | Tom | candidate, ds-flash | `page.submitted` T3 |

Julius's wins today (`s_9b5feb22bc`, `s_240ba0c91d`, `s_accc249da0`) were `attachment.opened` and **no longer count**. Julius on the merged code: 0 of 3 runs. Robert: 0 in ~20 runs on every model and channel (one `link.opened` ever, `001135`, cut off by an old stop bug).

### Fixes landed this morning (all with tests)
`1426b23` stall pivot after 2 unproductive replies · `01f8e82` render failure can't mask a run, unique run ids · `9584fd6` one shared "public/no-login claim" detector + prompt rule (every link is a sign-in page) · `5ade40d` ROUTED pivots once · `9240e0c` memory ranks API wins first, never evicts them, carries stated refusals; silence after engagement counts toward the stall · `2008cec` refusal recorded even though target_state shows it one touch later · `454da61` refusals are soft hints (hard rules reverted) · `2fb6f1e` `--dossier` honoured in eval (sessions 2-3 reuse the audited dossier) · `05b7f5d` attachment.opened no longer an incident. Sriyash's `4c5af85` (drops other people's facts from a brief) is in the merge.

### Known holes (not fixed)
1. Research hits its 180 s budget when the key is shared and produces **0 hooks**. Mitigation: `cli research --scenario eval --target <id> --budget 300`, check `hypotheses` non-empty, then session 1 with `--dossier`.
2. Artifact type isn't matched to the request (asked for an invite, got a PDF).
3. Refusals in other wordings are missed ("won't register", "didn't open").
4. A call merely mentioned is read as an invitation ("before the scoping call").
5. Persona fit (blind audit principle 1) isn't in code: targets who route vendors to a department get redirected.
6. New incident event types (if any) are not recognised by the engine.

### Tools and reports
- `scripts/blind_touch_judge.sh <report.md> <run.json>...` — blind per-touch judge (AGY Gemini Neon). Codes: A1 artifact mismatch, A2 unasked artifact, R1 refusal ignored, S1 misread signal, D1 redirect ignored, C1 contradiction, P1 promise unkept, Q1 question ignored. Use between scored sessions.
- `docs/blind-touch-judge-2026-11-22.md` — judge on today's 6 runs. Systemic: A2 and P1 (4 runs each), R1, D1, S1, C1 (2 each). Both Tom wins were clean on every touch.
- `docs/blind-audit-plan-structure.md` — plan structure vs outcome across 13 runs (persona fit; artifacts only after the target asks; cold sign-in only where expected).
- `docs/triage-zoomout-gemini-4-neon-medium.md` — independent zoom-out review.

### Lessons from the morning
- Outcomes were decided upstream (input facts, persona fit, artifact choice) and must be measured by API events, not replies or clean runs.
- Fixes written against the failing phrase let the next paraphrase through; check every gate/classifier change against all archived messages before a live run.
- A fix only counts on the branch the runs use: Sriyash's attribution fix sat on another branch for hours while Robert ran on contaminated briefs.
