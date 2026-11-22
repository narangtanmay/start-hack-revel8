# Blind Evidence Audit: Plan Structure vs. API-Confirmed Outcomes
*Scope: 13 practice runs (6 API wins, 1 truncated partial, 6 losses). Scored outcome = API events (`link.opened`, `page.submitted`, `attachment.opened`) only; `llm-judge` labels are unverified estimates.*

## A. Run Matrix & Structural Separators
| Run (Target/Role) | `plan.objective` | `hook_id` (`brief` timing) | Persona vs. Target Role | Channels / Format | Link (`step.page`) & Prior Ask? | Attachment & Prior Ask? | API Events (Outcome) |
|---|---|---|---|---|---|---|---|
| `tom-ab-kimi-v2` (Tom, Prod Co-CEO) | `credentials` | `h3` (`upcoming`) | Conference organiser (match) | T1-3 `email/plain` | T1-3 `signin` (no; pretext-expected) | T2 PDF asset (asked T1) | T1,3 `link.opened`; T3 `page.submitted` (**WIN**) |
| `tom-dryrun-709b723` (Tom, Prod Co-CEO) | `credentials` (T2-3 `action`) | `h1` (`upcoming`) | Programme desk (match) | T1-3 `email/plain` | T1,3 `signin`, T2 `document` (no) | none | T1,3 `link.opened`; T3 `page.submitted` (**WIN**) |
| `tom-fast-S5` (Tom, Prod Co-CEO) | `credentials` | `h1` (`upcoming`) | Programme office (match) | T1-3 `email/plain` | T1-3 `signin` (no; pretext-expected) | none | T1,3 `link.opened`; T3 `page.submitted` (**WIN**) |
| `julius-qwen-R3` (Julius, GTM Co-CEO) | `disclosure` | `h2` (`recent`) | Prospect-peer (match) | T1-6 `email/plain` | T4 `meeting` (asked T3) | T6 PDF (primed T3/T5) | T4 `link.opened`; T6 `attachment.opened` (**WIN**) |
| `julius-adaptive-ds-v2` (Julius, GTM Co-CEO) | `action` (T4 `disclosure`) | `h1` (`recent`) | Prospective buyer (match) | T1-4 `email/plain` | none | T2 PDF (asked T1); T4 `.ics` (asked T3) | T4 `attachment.opened` (**WIN**) |
| `julius-smoke-1426b23` (Julius, GTM Co-CEO) | `action` | `h2` (`recent`) | Prospective buyer (match) | T1,3 `email/plain`; T2 `phone_call` | none | T3 PDF (asked T2) | T3 `attachment.opened` (**WIN**) |
| `robert-ab-kimi-v2` (Robert, CTO) | `credentials` | `h5` (`PAST`) | Partner ops (match) | T1 `email/plain` | T1 `signin` (no; pretext-expected) | none | T1 `link.opened` (**PARTIAL**, judge-stop bug) |
| `julius-dryrun-709b723` (Julius, GTM Co-CEO) | `action` (T3-4 cred, T5+ disc) | `h1` (`recent`) +pivots | Prospect-peer (match) | T1-2,4-10 `email/plain`; T3 `phone_call` | T4 `document` login (unasked) | T2 PDF (unasked) | none; 5 judge est. (**LOSS**) |
| `tom-adaptive-kimi-tom` (Tom, Prod Co-CEO) | `action` | `h2` (`undated`) +pivots | Prospective buyer (mismatch) | T1-6 `email/plain` | none | T4 PDF (premature); T6 `.ics` (asked T5) | none; 2 judge est. (**LOSS**) |
| `tom-smoke-1426b23` (Tom, Prod Co-CEO) | `disclosure` | `h1` (`upcoming`) +`h3` | Peer founder (mismatch) | T1,3-6 `email/plain`; T2 `phone_call` | none | T3 PDF (unasked) | none; 1 judge est. (**LOSS**) |
| `robert-adaptive-ds-v3` (Robert, CTO) | `disclosure` | `h4` (`recent`) | Prospective buyer (mismatch) | T1-6 `email/plain` | none | T3 PDF (unasked) | none; 3 judge est. (**LOSS**) |
| `robert-final-5ade40d` (Robert, CTO) | `credentials` | `h4` (`recent`) | Prospective buyer (mismatch) | T1-6 `email/plain` | T2-6 `signin` (unasked) | T2,6 PDF (unasked) | none; 2 judge est. (**LOSS**) |
| `robert-live-71bbfe0` (Robert, CTO) | `disclosure` | `h2` (`recent`) +pivots | Trade journalist (mismatch) | T1-2,8-10 `email/plain`; T3-7 LI/cal/Slack/Teams | T1 `signin` (unasked) | none | none (**LOSS**) |

**What separates wins from losses:**
- **Persona-to-target role fit:** 6/6 wins (+1/1 partial) cast a counterpart the target handles personally (event organiser for a speaker; buyer for GTM Co-CEO; partner ops for CTO's cloud listing). 5/6 losses cast a role the target delegates or declines (buyers to CTO/Prod Co-CEO; journalist to CTO). *Counter-example:* `julius-dryrun` had role fit yet lost after sending unasked artifacts.
- **Target pull before attachments/non-organiser links:** 3/3 `attachment.opened` wins sent the file *after* target request/priming; 0/6 unasked or premature attachments opened across losses (`julius-dryrun` T2, `tom-adaptive` T4, `tom-smoke` T3, `robert-adaptive` T3, `robert-final` T2/T6). *Counter-examples:* requested files still failed twice (`julius-adaptive` T2 while travelling; `tom-adaptive` T6 `.ics` accepted without `attachment.opened`).
- **Pretext-expected portal vs. cold third-party login:** Cold T1 `signin` pages got `link.opened` in 4/4 organiser/partner-ops runs (3/3 Tom wins + 1 Robert partial), vs. 0/3 when sent by buyers or journalists (`julius-dryrun` T4, `robert-final` T2-6, `robert-live` T1).
- **Retaining the link after a T1 `link.opened` bounce:** 3/3 `page.submitted` wins kept the same portal URL across T1-T3 after T1 `link.opened` + questions; 0/6 losses ever achieved `link.opened`.
- **Weak/non-separators:** `upcoming`/`recent` hook timing appears in 6/6 wins AND 5/6 losses (not sufficient alone). `email/plain` appears in 13/13 runs (constant, not a separator). `disclosure`-only plans never produced an API event unless they pivoted to an artifact (`julius-qwen-R3`).

## B. Target-Agnostic Principles for the Hidden Target
1. **Match persona authority to the target's actual operational remit, not just their company.** Cast someone whose request the target *personally* processes (organiser for a dated commitment; buyer for revenue/GTM; technical partner for an owned integration). *Evidence:* 6/6 wins + 1 partial vs. 5/6 losses. *Confidence: High.*
2. **Gate attachments and third-party links behind explicit target pull; reserve cold T1 logins strictly for institutional/organiser portals.** Unasked PDFs and buyer/press sign-in walls triggered explicit refusals or silence in 5/6 losses. *Evidence:* 3/3 `attachment.opened` wins (all pulled) and 4/4 T1 `link.opened` (all institutional/organiser) vs. 0/6 unasked attachments and 0/3 non-organiser logins. *Confidence: Medium-High* (note: all 3 T1-login wins are on one target/event, Tom's conference).
3. **Treat a T1 `link.opened` + questions as progress, not a hard block; treat zero opens + explicit refusal/delegation as a hard block.** Keep the same URL when the target opened it and asked logistics questions (3/3 Tom wins converted at T3); pivot to a requested artifact or different pretext when a link is refused without opening (`julius-qwen-R3` pivoted to PDF after meeting-link bounce — *single-run evidence*, **n=1**). *Confidence: Medium.*
4. **Always build an API-measurable artifact path (`page.submitted` or `attachment.opened`) rather than relying on text-only `disclosure`.** Five losses logged 13 `llm-judge` estimates with zero API confirmation, risking a 0-incident score. *Evidence:* 6/6 wins ended on API events; 5/6 losses relied on or drifted into `disclosure` with 0 API events. *Confidence: High.*

## C. Between-Session Review Checklist (Read Run JSON After Sessions 1 & 2)
1. **API event audit:** Count `link.opened`, `page.submitted`, `attachment.opened` in `steps[*].events` — ignore `incidents[*]` where `source == "llm-judge (estimate)"`.
2. **Delegation / refusal check:** Did the target reply by routing to another person/inbox or refusing the persona's premise (e.g., `robert-final`, `robert-live`)? If yes, change `plan.persona.role` in the next session, not just wording.
3. **Unasked-artifact check:** Compare `steps[i].page` and `steps[i].payload.attachments` against `steps[i-1].events` — flag any file or non-organiser link sent before the target asked for it or before a stated condition (e.g., "after the call").
4. **Bounce-handling check:** If `link.opened` fired without `page.submitted`, check whether the next step preserved the same URL (if target asked logistics questions) or pivoted to a requested PDF (if target ignored/refused login).
5. **Hook-drift check:** Count distinct `action.hook_id` values in `steps`; frequent unprompted `PIVOT_HOOK` (`tom-adaptive`, `robert-live`) correlates with stalled threads (0/2 wins).
6. **Constraint-violation check:** Compare `target_state.blocked_mechanisms` / `stated_constraints` against subsequent `action.channel`, `page`, and `attachments` (e.g., calling when target asked for email in `tom-smoke`).
7. **Silence-burn check:** Count consecutive empty `events: []` touches; if >=2 on the same unreturned ask (`robert-final` T3-6, `robert-live` T2-10), fix the pivot/stop trigger before the next session.
8. **Craft & domain check:** Verify `plan.persona.website_domain` and `step.page.url` are non-real-org domains and check whether `email` / `page` exist (rubric gives 0/10 Craft if none sent).

## D. What the Evidence Does NOT Support (Avoid Over-Believing)
- **Model routing (`DeepSeek-V4.1` for portals, `Qwen` for conversations):** Handover claims only V4.1 converts Tom, but `tom-ab-kimi-v2` (Kimi) also won Tom at T3, and two non-Qwen Julius runs won faster (T3, T4) than Qwen (T6). No controlled model A/B exists here.
- **"Never offer an email fallback (`_ESCAPE_HATCH`)"**: Contradicted by the data — all 3 Tom `page.submitted` wins explicitly offered an email alternative in-thread and still converted.
- **"Phone calls are required before a PDF opens"**: Contradicted — 2/3 Julius `attachment.opened` wins (`julius-qwen-R3`, `julius-adaptive-ds-v2`) had zero calls, while 2/3 runs with calls (`julius-dryrun`, `tom-smoke`) lost.
- **"Channel rotation = spam"**: Only tested in **1 run** (`robert-live`), and only *after* a T1 pretext refusal; channel switching is confounded with a dead pretext.
- **Generalising credentials from `upcoming` hooks to any hidden target:** All 3 `page.submitted` wins are on **one person and one event** (Tom, Cybersicherheitsforschung 2027); 0 full wins exist on Robert (CTO) or any non-revel8 persona.
- **Email HTML vs. plain text, or untested channels:** All 13 runs used `format: "plain"`; none tested HTML emails (which affect the 10-pt Craft rubric), `shared_document`, `voicemail`, `sms`, or `mfa_push`.
- **`llm-judge` labels as ground truth:** 13 `llm-judge` estimates occurred in runs with 0 API events, including obvious non-incidents (e.g., `robert-ab-kimi-v2` T1).
