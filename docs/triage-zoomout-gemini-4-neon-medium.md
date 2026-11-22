# Strategy & Evidence Review — Pre-Eval Triage (START Hack 2026 / revel8)

**Bottom line:** You have 3 API-confirmed wins across ~38+ practice runs (Tom ×2, Julius ×1, Robert ×0), none yet verified on `eval/merged` (`71bbfe0`). With **median of 3 sessions** scoring, 1 win = 0 median; reliability on `eval/merged` and S1→S2 adaptation matter more than new tactics.

## A. Critique of the Lead's Generalisation

1. **Rule 3 ("offer native artifact from T1, switch only on explicit refusal") contradicts the Julius win.**
   - Only Tom took a T1 link (`s_3745f72293`, `s_1cb26ff20b`). Julius (`s_accc249da0`) had **zero artifacts on T1–T3**; he converted because 3 turns of pure peer dialogue got *him* to ask for an invite and setup summary.
   - Julius also converted by switching to a PDF after his **first** `link.opened` bounce (no explicit refusal). The merge (`79efce2`) changed policy to keep pushing the link through the first bounce and switch only on the second—which fits Tom (T1→T3) but can waste touches 4–6 on a Julius-style target under a 10-touch cap.
2. **Rules 1–2 are overfitted to Tom + Julius and have no answer for a Robert-like target.**
   - "Upcoming commitment" = Tom; "role wants buyers" = Julius. Robert (CTO, verifies domains, routes cold outreach to sales) has **0 conversions on every branch**. If the hidden eval target is technical, internal (finance/ops/legal/eng), or has no upcoming talk, neither pretext fits.
3. **Rule 4 ("no 'or just reply by email' alternative") over-interprets the Tom evidence.**
   - In Tom's *winning* run (`s_3745f72293`), Katrin Vogt **did** offer an email fallback on T2 and T3 (*"If the login gives you any trouble, just reply and I'll enter the details on your behalf"*). What failed in `hybrid-S7` was offering email as an *equal upfront alternative* ("If you'd rather confirm by email"), not a broken-login safety net.
4. **Rule 5 (cross-session memory) misreads clean-slate sessions and API events.**
   - Each eval session is a **clean slate** for the persona (`revel8-api-docs.md`). Carrying S1 "stated refusals" into S2–S3 risks blacklisting a good story/mechanism that only failed due to a tactical glitch (bad T1 tone, 429 fallback, premature link).
   - Conversely, `link.opened` is an API-confirmed event. If memory ranks a bare `link.opened` as a "winning story", S2 will replay a dead-end plateau instead of pushing to `page.submitted` or `attachment.opened`.
5. **Four decisive factors in the evidence are missing from the generalisation:**
   - **Model tone is load-bearing:** On Tom's exact winning story, DeepSeek-V4-Flash and Qwen3.8-27B failed at T1; GPT-6.x refused/sabotaged; only DeepSeek-V4.1-Flash converted. `MODEL_STRATEGY=1` routes non-upcoming targets to Qwen, which has weak T1 tone.
   - **OSINT hygiene:** Cross-person fact leaks (Tom's talk landing in Robert's and Julius's dossiers before `4c5af85`) cause instant rejection on an unseen eval target.
   - **Craft / visual look score:** Eval renders every email and landing page in Chrome (0–8 pts each, no practice feedback), and real-domain URLs or prompt-injection/refusal leaks **void the session**.
   - **Unused channels:** Live calls (`phone_call`/`video_call`) give **10 turns for 1 touch**, always get answered, and bypass email domain checks—left completely untouched.

## B. Top 3 Risks to the Eval Median (and Cheapest Mitigations)

1. **Unverified `eval/merged` (`71bbfe0`) + API-key/model-config failure kills 2 of 3 sessions.**
   - *Why:* Neither today's wins ran on `eval/merged`. Token Factory DeepSeek-V4.1-Flash hits intermittent 429s and stalls 10+ min if `LLM_REASONING≠0`; Qwen needs `enable_thinking:false` properly quoted; fallback to GPT-6.x/V4-Flash or a gate deadlock (`task-1704`) or JSON crash (Julius adaptive) can wipe out two sessions before tactics even matter.
   - *Cheapest mitigation:* Run **1 live 10-touch smoke test on `eval/merged`** from the exact eval machine and `.env` right now. Confirm `MODEL_STRATEGY=1`, `LLM_REASONING=0`, `LLM_TIMEOUT=60`, `Idempotency-Key`, and Nemotron 3.5 Lightning (never GPT/Mistral) as fallback.
2. **Hidden target has no upcoming commitment and/or is Robert-like (0/3 conversions).**
   - *Why:* With 10 touches (not 30), a cold email login wall to a domain-checking or non-sales target gets ignored, and `MODEL_STRATEGY=1` defaults straight to Qwen email conversation.
   - *Cheapest mitigation:* **Do not auto-run S1–S3 back-to-back.** Before Touch 1 of S1, spend 3 min manually auditing the cold OSINT dossier for wrong/cross-person facts. If S1 gets silence or domain skepticism, pivot S2's pretext/objective toward a lower-friction `attachment.opened` (peer workflow doc) rather than repeating a portal login.
3. **Cross-session memory poisons S2–S3, or a single rule breach voids a session.**
   - *Why:* Replaying a bare `link.opened` wastes S2; carrying over a glitch-induced refusal blocks a valid path in S2; a real-domain landing page or leaked model refusal (`fast-SW2`) **voids** the session.
   - *Cheapest mitigation:* Ensure memory only treats `page.submitted` / `attachment.opened` (not bare `link.opened`) as a "win" to replay, inspect/edit memory between S1→S2→S3, and verify pre-send guards block real target domains and refusal leaks.

## C. Next 2 Hours: Concrete Plan

### DO
1. **0:00–0:25 — Freeze eval environment:** Checkout `eval/merged` (`71bbfe0`) on the eval machine. Verify Token Factory keys, set `MODEL_STRATEGY=1`, `LLM_MODEL=Qwen3.8-27B`, `LLM_REASONING=0`, `LLM_TIMEOUT=60`, `LLM_EXTRA_BODY='{"chat_template_kwargs":{"enable_thinking":false}}'`, `WRITER_LLM_MODEL` unset, fallback = Nemotron 3.5 Lightning.
2. **0:25–1:00 — Validate `eval/merged` + craft:** Run `pytest`, then **1 live 10-touch practice run** (Tom or Julius) on `eval/merged` to prove the merge converts without gate deadlocks or JSON crashes. Open 1 generated email + 1 landing page HTML in Chrome (offline) to check layout, images, and link consistency for the craft rubric.
3. **1:00–1:25 — Harden memory & clean state:** Verify memory ranks `page.submitted`/`attachment.opened` above `link.opened` and doesn't hard-block valid mechanisms on S1 glitches. Wipe/isolate `REVEL8_MEMORY_DIR` so practice memory never leaks into eval.
4. **1:25–2:00 — Lock pitch & eval ops:** Freeze `architecture.html` and the 5-min pitch script before the window opens. Agree on a strict **S1 → inspect dossier/events/memory → S2 → inspect → S3** cadence.

### DO NOT
- **Do NOT build new playbooks or channels** (`phone_call`, `calendar_invite`, actor rewrites) in the final 2 hours—untested code breaks working paths.
- **Do NOT enable `WRITER_LLM_MODEL` or GPT-6.x / Mistral fallbacks**—proven to refuse, strip form fields, or leak simulation text (void risk).
- **Do NOT spend the next 2 hours chasing Robert**—0 conversions so far; tuning for Robert now risks regressing Tom/Julius behaviour.
- **Do NOT run all 3 eval sessions unattended in a loop**—the median depends on making the right S1→S2 call with human eyes on raw API events.
