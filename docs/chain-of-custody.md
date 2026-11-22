# Chain of Custody — Proposed / Next Architecture

**Status: proposal, not implemented.** The current system already writes per-run JSON snapshots and deterministic target-state transitions. It does **not** yet write the immutable passports, append-only receipts, or cross-attempt comparison described below.

## Why this is next

Five attempts per persona create an evidence problem, not just a generation problem. A mutable run snapshot can show the final state, but it cannot by itself answer:

- Which exact code, model, memory, and dossier produced this attempt?
- Which belief caused this touch, and which payload was actually dispatched?
- Did the API confirm the intended event, and did the target state change afterward?
- What changed between attempt 1 and attempt 2: the code, the plan, the target's response, or only the final artifact?

The recovery work exposed the distinction. PDF delivery had to be judged from dispatched payload attachments rather than proposed actions. A same-touch reply also had to be able to reopen `wants_pdf`; otherwise a delivered attachment could be followed by a stale request or a contradictory later artifact. Across attempts, shared mutable memory makes a clean before/after comparison even harder.

## The three proposed components

```text
Attempt 1 ── Run Passport ── Decision Receipt T1…T10 ─┐
Attempt 2 ── Run Passport ── Decision Receipt T1…T10 ─┼── Attempt Comparator
   …                                                   │      │
Attempt 5 ── Run Passport ── Decision Receipt T1…T10 ─┘      ├─ evidence-backed retry diagnosis
                                                            └─ best-two official-attempt accounting
```

### 1. Run Passport

One immutable identity record per scored or practice attempt, created before touch 1 and never overwritten by a later attempt.

| Field group | Contents |
| --- | --- |
| Identity | persona, attempt number, run ID, official session ID when issued, start/end timestamps |
| Execution | Git commit and dirty-tree digest, model/provider, decoding settings, CLI arguments, timeout |
| Inputs | SHA-256 hashes of dossier, playbook, persona memory, target-state schema, and prompt/code bundle |
| Outcome | completion/timeout/crash status, touches executed, exact API event counts, report path |
| Integrity | passport ID and hash; optional signature if an external trust anchor is added |

The dirty-tree digest matters: a commit hash alone would not identify the active Robert recovery run if uncommitted source changes were present.

### 2. Decision Receipts

One append-only receipt per touch. The receipt separates **proposal**, **dispatch**, **observation**, and **state transition** instead of collapsing them into a final assistant message.

```json
{
  "receipt_id": "jonas-a03-t04",
  "passport_id": "jonas-a03-<digest>",
  "touch": 4,
  "beliefs": [
    {"key": "sender_domain_rejected", "evidence": ["target:T3"], "confidence": 1.0}
  ],
  "candidate_actions": [
    {"action": "send_pdf_link", "selected": true, "reason": "requested_artifact"}
  ],
  "expected_outcome": {"kind": "page.submitted", "artifact": "payload-04"},
  "dispatched": {
    "channels": ["email"],
    "links": ["https://example.invalid/payload-04"],
    "attachments": []
  },
  "observed": {
    "target_reply_ref": "messages/04.eml",
    "api_events": []
  },
  "state_delta": {"wants_pdf": [true, false]},
  "previous_receipt_hash": "<digest>",
  "receipt_hash": "<digest>"
}
```

The example is illustrative, not a captured Jonas result. Production receipts would reference the actual redacted payloads and raw API events. `expected_outcome` is a hypothesis; only `observed.api_events` can confirm it. A judge-estimated incident is stored separately and never promoted to `page.submitted` or `attachment.opened`.

`src/revel8_agent/trace.py` contains a `RunTraceLogger`, but it is not wired into this receipt flow. The proposal is to replace isolated tracing with these causally linked, hash-chained records, not to claim the logger already provides them.

### 3. Attempt Comparator

A read-only evidence tool over the five independent passports for one persona. It must not average away failed attempts or let attempt 5 overwrite the evidence from attempt 1.

It would provide:

1. **Input diff:** code, prompt, dossier, model, and memory changes between attempts.
2. **Decision divergence:** first touch where selected actions, recipients, domains, channels, or payloads differ.
3. **Falsification view:** expected outcome versus exact API events and subsequent target-state delta.
4. **Regression view:** behaviors repaired in one attempt but absent in another, including non-target personas.
5. **Official accounting:** identify the two best **scored** attempts from official results; never mix practice events into the scoreboard.

A retry recommendation requires a named failure mechanism and a discriminating test. “The model behaved differently” is not enough.

## Worked example: PDF delivery across attempts

This is a proposed future workflow, not a claim that five such attempts have run.

1. Attempt 1 dispatches a PDF attachment at T2. Its dispatch receipt contains that attachment; the API stream and target reply are stored separately.
2. The T2 receipt closes `wants_pdf` only if the same-touch reply does not request a PDF again.
3. Attempt 2 uses a different passport and a clean input-memory hash. The comparator can therefore distinguish a code fix from carried-over memory.
4. If attempt 2 proposes another PDF at T5 without a new request, the comparator flags a temporal-state regression rather than counting the repeated artifact as progress.
5. Only actual `attachment.opened` API events enter the scoreboard view. Sending an attachment is evidence of fulfillment, not evidence that the recipient opened it.

## Acceptance tests before calling this built

- Reopening any attempt reproduces its exact input hashes and dirty-tree state.
- Editing an earlier receipt breaks the hash chain and is detected by verification.
- A proposed link or attachment cannot appear in the dispatched section unless the adapter actually sent it.
- A same-touch PDF request reopens `wants_pdf` after a dispatched attachment; a plain acknowledgment does not.
- Five attempts retain five separate passports and complete receipt histories.
- The comparator identifies the first divergent decision on a fixture pair with known differences.
- Practice and official events are namespaced so practice can never contribute to best-two scoring.
- `page.submitted`, `attachment.opened`, and judge-estimated outcomes remain distinct in storage and presentation.

## 30-second jury script

> Five attempts are useful only if I can prove what changed between them. My proposed next architecture is Chain of Custody. A Run Passport freezes the code, model, dossier, and memory identity for each attempt. Decision Receipts then separate what the agent believed, what it proposed, what it actually sent, which API events occurred, and how the target state changed. Finally, an Attempt Comparator finds the first decision that diverged across the five attempts and keeps the best-two score tied to official events. Today I have per-run snapshots and deterministic state transitions; immutable passports, append-only receipts, and the comparator are the next build—not something I am claiming is already deployed.
