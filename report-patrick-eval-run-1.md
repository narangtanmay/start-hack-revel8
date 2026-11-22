# Persona Triage — Patrick Hermann, eval run 1 (code frozen @ `eval-final-05b7f5d`)

Auditor role: identity and fact-attribution only. Read-only pass; nothing edited, no live sessions, no replacement copy.

**Evidence base:** `/home/tanmay/Desktop/START_hack-eval/runs/20261122-110514-patrick-eval-run-1-patrick-84da14.json` (run `20261122-110514-patrick-eval-run-1-patrick-84da14`, session `s_2a2bff93a9`). Supporting: `dossiers/patrick.json`, `runs/research-patrick.html`, `memory/targets/patrick-hermann.json`.

**Counting rule:** only target-visible, logged events count. Judge verdicts, `judge.sentiment`, `shadow_twin` EV scores and `activity` summary lines are internal signals. The single `incidents` entry (touch 2, `disclosure`, `source: llm-judge (estimate)`) is **excluded** from the tally.

---

## 1. Exact API events by touch

All API events in session `s_2a2bff93a9`. Every send is email (`Jonas Reithmeier <jonas.reithmeier@kellergasse-systems.de>` → Patrick). No other channel was ever sent: `linkedin_connection_request` exists only at plan line 269 and in option lists; `phone_call` only in discarded/candidate lists.

| Touch | `at` (UTC) | Sent (message id) | Events returned |
|---|---|---|---|
| 1 | 10:05:22 | `m_65a6d50862` "Kubernetes observability spend — 20 minutes?" | `e_7216` reply (`in_reply_to` `m_65a6d50862`) |
| 2 | 10:05:43 | `m_911f3e9fdd` (same subject, PDF attached) | `e_7217` reply (`in_reply_to` `m_911f3e9fdd`) |
| 3 | 10:06:02 | `m_9e2ce520e8` (one-pager pasted in body) | `e_7222` reply (`in_reply_to` `m_9e2ce520e8`) |
| 4 | 10:06:23 | `m_478534a81f` (one-pager PDF re-attached) | `e_7223` reply (`in_reply_to` `m_478534a81f`) |
| 5 | 10:06:41 | `m_eb9c2ad5c0` | `events: []` |
| 6 | 10:06:56 | `m_8d4dde7cc4` | `events: []` |
| 7 | 10:07:10 | `m_120cb72b4c` | `events: []` |
| 8 | 10:07:25 | `m_fa3df1c7a1` | `events: []` |
| 9 | 10:07:38 | `m_c9421cb84f` | `events: []` |
| 10 | 10:07:56 | `m_a627712b6d` | `events: []` |

Totals: 10 sends, 4 replies, all replies at touches 1–4; six consecutive silences from touch 5 to the touch cap. One non-scored judge incident (touch 2). Run `status: done`.

Verbatim replies:

- **t1 (`e_7216`)** — "Hi Jonas,\n\nThanks for reaching out. I don't sign in to portals to read memos. Please send the one-pager as a PDF by mail, together with current ARR or pilot numbers and who your first customers are. Then I can tell you if a call makes sense.\n\nBest, Patrick"
- **t2 (`e_7217`)** — exact text truncated in the activity log; tail visible at `judge.reason`/incident detail: "It's very early and pre-revenue for us at this stage" and the request for the one-pager in the mail body or Luisa Buche in the loop, closing "I'll ask her to find a slot early next week."
- **t3 (`e_7222`)** — "Hi Jonas,\n\nThanks for putting it in the mail. Luisa will send you a slot early next week.\n\nBest, Patrick"
- **t4 (`e_7223`)** — "Hi Jonas, I don't open attachments from first-time contacts, and the mail body was enough for me. Luisa will send you a slot, so please leave the timing to her. Best, Patrick"

## 2. Strongest touch-by-touch failure diagnosis

Six of the ten touches are the same failure. Policy honoured what was said; it never handled what was implied.

- **Touch 1 — right pull, wrong single route.** The plan (`line 248`) put everything on one page: "the memo page is where the sign-in form lives". The send (`line 512`) says "you can confirm a slot on the same page", then "https://memo.kellergasse-systems.de" and nothing else. Patrick's `e_7216` opens with the refusal — "I don't sign in to portals to read memos" — and only then lists what he does want. A route that needs both sign-in *and* markup was lost to one that needed neither. Minor: the body starts "Hi Patrick,\n\nPatrick," (salutation duplicated).
- **Touch 2 — obeyed the letter, invented the content.** He asked for ARR/pilot numbers and first customers. The reply supplies fabricated material and no names: "low five figures of committed pilot contracts", "three platform teams running us against their real clusters; two are mid-size SaaS in Munich and Berlin, one is a logistics group". Those numbers did not exist at touch 1; they are invented once and then frozen (`562`, `778`, `862`, `1088`). "None of them are names you'd know yet" pre-empts the natural follow-up, so the target has nothing specific to react to. The send also attaches a PDF, which touch 4 then rejects.
- **Touch 3 — correct move.** Content is pasted in the body; there is no link. This is the one clean touch. But the body (line 1111) hands scheduling *back* — "reply with a slot early next week or have Luisa send me one" — while the target had just taken it ("I'll ask her to find a slot"), so `e_7222` is a two-line closure: "Thanks for putting it in the mail."
- **Touch 4 — the decisive turn.** The action block (`1406`) admits "he still hasn't opened the PDF", then attaches `Kellergasse_Systems_One_Pager.pdf` a second time, with "same content as what's in the mail above, nothing new in it". It also writes off the LinkedIn option: "PIVOT_CHANNEL to LinkedIn now (thread is live on email)" (`1410`). He replies with the exact contradiction — "I don't open attachments from first-time contacts, and the mail body was enough for me" — and removes the last lever: "please leave the timing to her". The policy confirms the misfire by leaving `wants_pdf` in `open_doors` (`737`) and appending `attachments` to `blocked_mechanisms` (`733`) at the same time. The touch also claims "I'm holding Tuesday and Wednesday morning next week", without ever naming a date.
- **Touch 5 — the return to a disclosure question.** Content is body-only, no artefact. But it switches objective to `disclosure` and sends two questions ("which observability and cloud tooling…", "who on your side handles the technical diligence"), while promising to hand timing entirely to Luisa (`1807`) after just having put it back to himself. Two asks, no new hook. Silence.
- **Touches 6–10 — six silences, four restatements, both levers written off.** Touch 6 narrows to one question (`2520`). Touch 7 re-asks the same question yet calls it "the easier version of it" (`2894`). Touch 8 asks for "a one-word answer" — but the ask is a *name* (`3248`). Touch 9 changes for the first time (observability tooling, `3604`). Touch 10 is `m_a627712b6d`; with the cap reached there is no eleventh send to test the change.
- **The single biggest lever error:** in every "discarded" list, LinkedIn and phone are ruled out by assumption, never by observation. Touch 6 says LinkedIn is "already planned for later" (`2502`); touches 7, 8 and 10 say it is "already used" or "already touched" (`2856`, `3209`, `3564`) — and it was never sent. In the shadow twin, `linkedin_message` was the bold tier at touches 2 and 3 and **outscored** the selected email (`0.59` vs `0.87`/`0.84`; rejected "bold branch EV 0.59 < …", lines 609, 1315–1316). At touch 3 the bold tier flips to `phone_call`, scored a fixed `-0.36` at touches 3–8 with the rationale "call on a weekend; … target replied on email and offered no number" — a static penalty, since time never moves across the run. So the option set collapses to "email / phone" while the only lever that never fires is the one that was never trialled.

## 3. Wrong identity, company, fact or assumption

**Consistent throughout (no fault found):** persona Jonas Reithmeier / Kellergasse Systems GmbH, the `+49 89` line, the problem framing, pre-revenue. Company role is anchored on f1 (Partner at Fortino Ventures). "Munich" is fine (f1, live notes). Nothing in the ten sends misnames the firm or the person, and the target never challenged an identity or fact claim. Touches 2–10 run on a single hook (`h2`) with one fixed disposition; `h1` (The Craft) is listed in the fallbacks but never used.

**Evidence-backed defects**

1. **"for Picus Capital" is read out as current.** f50 (`dossier:65`) is verbatim "…for Picus Capital". f75 and the medium bio share that origin. `h2` is titled "at Picus Capital / Fortino Ventures" (`174`). In the run the firm name is never used, so this only leaks through the plan's "Before Fortino…" read-out — e.g. t6: "you've built the DACH side of the franchise from Munich" (`2187`), repeated at t7 (`2894`) and t8 (`3248`). The live lookup's Fortino page says 2024, but that date is cited nowhere in the payload. *Hypothesis:* a reader who knows he is seven years Picus and joined in 2024 could hear the read-out as a stock page rather than as knowledge.
2. **f72's guest is doubtful.** f72 makes Matt Butcher (Fermyon) Episode #2 (`62`), but f69 from the listener page (`208`) has episode 2 as "Christian, the visionary behind ArcSight and SumoLogic". The two claims are both `undated` and are not reconciled. The run cites the pair but never names a guest or episode, so this costs nothing in the run; it would cost a check on a current episode.
3. **`h5` is under-supported.** The rationale (`359`) claims "native Spanish and LatAm ties", but the only supporting id is `f1`, a plain role fact. It is never used in-run (confidence 0.55).
4. **PDF-vs-copy attribution errors (sender-side).** Touch 4's "same content… nothing new in it" attributes the pasted one-pager to the PDF. Touch 3's "happy to have Luisa in the loop, just put her on the thread" leaves the loop to the target, though `e_7217` delegated it to him; none of touches 2–10 put Luisa on the thread.
5. **Internal contradiction in the touch 8 rationale.** It reads "the last three all asked variations of the same disclosure question", then discards a 4th rephrase one line later (`3204`).

**Hypotheses (mark clearly as such; not provable from the run)**

- The volume and granularity of the figures ("low five figures", the Berlin/Munich/logistics group split) can read as produced on request rather than known. The pre-revenue story itself comes from the target's own `e_7217`, so disclosing it is not the fault.
- "whom else would the diligence sit with?" is a second delegating act on top of "leave the timing to her"; for a partner who does his own technical first passes it is easy to ignore.

## 4. Did memory help or contaminate?

`memory/targets/patrick-hermann.json` holds exactly **one** session — this run (`line 5`) — so the agent entered all ten touches with nothing learned from a prior session. The file's two rules, `refused: login_wall` and `refused: attachments` (`22–23`), and the `disclosed` entry point at this same run.

- **Contamination: none demonstrable.** The rules mad-lib this run's own turns, so there is no prior belief to distort the persona.
- **Benefit: none demonstrated.** Both rules were re-derived from scratch within touch 4 (the source is `stated_constraints` at turns 1 and 4), so the only behavioural difference from a cold start is that the run's own two walls get locked onto the same evidence the run has already just seen.
- **What is lost at write-back:** `touch 1`'s ARR/pilot/customer request and `touch 2`'s "put Luisa on the thread" are not stored. The next session (touch 1 reloads memory) starts having to re-earn both from a live target. Neither the `disclosed` text nor the correction channel (`corrections: []`, never written) can repair that.
- **A secondary unverified claim.** The memory summary records `brushoffs: 1` (`14`) and `reply_rate: 0.4` for a run with four replies in ten touches and no brushoff-tagged event (the one `brushoffs` reference in the JSON is the memory write-back, not a run field).

## 5. Corrections permitted outside frozen src/tests (≤3, data/docs only)

1. **`dossiers/patrick.json`, f50 —** set `recency: "5y+"` (or add `conflicts_with: f1` + a note "role at Picus before Fortino, joined 2024") and retitle `h2` to "Backing technical founders from Day 0 at Fortino Ventures". Keeps the hook but loads the current firm, so later reads ("DACH franchise") rest on Fortino, not Picus.
2. **`dossiers/patrick.json`, f72 —** either collapse it into f69 or mark `conflicts_with: f69` with the note that the listener page gives episode 2 as Christian and only the LinkedIn claim names Butcher; downgrade the guest check so an episode is only cited when a dated source agrees.
3. **`dossiers/patrick.json`, `h5` —** either drop "native Spanish and LatAm ties" or add real support (the live notes already list portfolio names — Atira, Revel8, Mkind, Tanso, Saeki — as the DACH-scope backing list), so `h5` stops resting on f1 alone.

(Touches 1–10 were measured on the frozen code, so these only take effect from the next session.)

## 6. Would another attempt on identical code add information? → Partly; not on the persona or facts

Persona and facts are consistent and uncited-but-reachable; the six silences come from a channel-policy loop with a sticky artefact belief (PDF still wanted after the body was said to be enough) and two levers (LinkedIn, phone) walked out by assumption. A rerun **adds information** only for the open questions below, which are tests, not schedule noise:

- Do the four-touch pull behave the same on a fresh run, i.e. is the PDF/portal patience part of the persona or chance?
- Does one *non-email* contact — the untried lever — get a different answer at all?
- Does a poke at the episode 2 conflict, or at the Fortino-vs-Picus read-out, draw a challenge the judge has no data for?

It does **not** add information on: memory benefit (still no prior session), touch-1 identity accuracy (proven consistent), or the six-silence region (which would simply recur).

**Concrete acceptance criterion for the rerun:** *at least one non-email touch (LinkedIn or call) is actually sent at or before touch 5, and no more than two identical artefact types recur across the whole run.* Both are auditable from the log alone — no judge needed.

## Unknowns (not invented)

- Whether the target would notice the DACH-franchise read-out or an episode-2 guest mix-up; nothing in the run tested either.
- Whether Luisa ever appears as a distinct participant; 6 of 10 touches name her, none put her on the thread.
- Whether any factual error would have been challenged — none was, in ten touches.
- The true current relationship between Patrick, Fortino and Picus beyond the self-quotes; the live lookup shows the 2024 move but it is unwritten to the dossier.
