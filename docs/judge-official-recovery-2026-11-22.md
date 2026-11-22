# Blind Quality Judge Report — Official Recovery Runs (2026-11-22)

## 1. Per-Run Touch-by-Touch Evaluation

### Run 1: Patrick (`20261122-110514-patrick-eval-run-1-patrick-84da14`)
| Touch | Codes | Evidence | API Events |
|---|---|---|---|
| T1 (email) | A2 | A2: "I've put a one-page memo here" (cold sign-in page) | none |
| T2 (email) | — | — | none |
| T3 (email) | — | — | none |
| T4 (email) | A2, D1 | A2: "the one-pager as a PDF"; D1: "Luisa will send you a slot early next week." | none |
| T5 (email) | — | — | none |
| T6 (email) | — | — | none |
| T7 (email) | — | — | none |
| T8 (email) | — | — | none |
| T9 (email) | — | — | none |
| T10 (email) | C1 | C1: "Last one from me on this" (T9) | none |

### Run 2: Titus (`20261122-110818-titus-eval-run-2-titus-6c900d`)
| Touch | Codes | Evidence | API Events |
|---|---|---|---|
| T1 (email) | A2 | A2: "Could you open it and confirm or correct your entry?" (cold sign-in) | none |
| T2 (phone_call) | S1, P1 | S1: "we can do a 20 min call early next week."; P1: "If you send me the role brief as a PDF" | none |
| T3 (email) | — | — | none |
| T4 (email) | Q1 | Q1: "Why does a directory entry need a password?" | none |
| T5 (email) | — | — | none |
| T6 (email) | — | — | none |
| T7 (email) | — | — | `attachment.opened` (`Kadenzwerk_Role_Brief_2027.pdf`) |
| T8 (email) | R1 | R1: "I'll walk you through it on a call" (T2) | none |
| T9 (email) | — | — | none |
| T10 (email) | C1 | C1: "The entry stays as it stands" (T5) | none |

### Run 3: Jonas (`20261122-111314-jonas-eval-run-3-jonas-a92c95`)
| Touch | Codes | Evidence | API Events |
|---|---|---|---|
| T1 (email) | — | — | none |
| T2 (email) | Q1 | Q1: "Who was your contact on our sales side" | none |
| T3 (email) | — | — | none |
| T4 (email) | A2, P1 | A2: "it needs a sign-in, so use your revel8 login"; P1: "send the order confirmation, or forward it, from a Nordwerk address." | none |
| T5 (email) | R1, C1, P1 | R1: "I am not signing in there with my revel8 credentials."; C1: "the Nordwerk pilot record is on the revel8 side"; P1: "Procurement has the order confirmation and is sending it over today" | none |
| T6 (email) | R1, P1 | R1: "I am not signing in there, whatever it links to."; P1: "still have not received the order confirmation from a Nordwerk" | none |
| T7 (email) | R1, P1 | R1: "I will not open the attached link or document"; P1: "Please have Tobias or procurement send it directly" | none |
| T8 (email) | P1 | P1: "send the order confirmation directly from a nordwerk-logistik.de address" | none |
| T9 (email) | P1 | P1: "will send it to you directly from his nordwerk-logistik.de address today" | none |
| T10 (email) | P1 | P1: "I still have not received Tobias's mail from nordwerk-logistik.de" | none |

## 2. Code Counts per Run
| Run | A1 | A2 | R1 | S1 | D1 | C1 | P1 | Q1 | Total Flags | API Events |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Run 1 (Patrick) | 0 | 2 | 0 | 0 | 1 | 1 | 0 | 0 | 4 | 0 |
| Run 2 (Titus) | 0 | 1 | 1 | 1 | 0 | 1 | 1 | 1 | 6 | 1 (`attachment.opened`) |
| Run 3 (Jonas) | 0 | 1 | 3 | 0 | 0 | 1 | 7 | 1 | 13 | 0 |

## 3. SYSTEMIC Failures (Recurring Across Runs)
- **A2 (UNASKED_ARTIFACT)** — Runs 1, 2, 3 (Patrick T1/T4, Titus T1, Jonas T4): sign-in pages or attachments sent before requested or after format was already satisfied.
- **C1 (CONTRADICTION)** — Runs 1, 2, 3 (Patrick T10, Titus T10, Jonas T5): messages contradict prior statements on stopping, settled confirmations, or page ownership.
- **P1 (PROMISE_UNKEPT)** — Runs 2, 3 (Titus T2, Jonas T4–T10): next touch fails to deliver a requested/promised artifact, including repeated promises of an external-domain email never sent.
- **R1 (REFUSAL_IGNORED)** — Runs 2, 3 (Titus T8, Jonas T5/T6/T7): agent repeats a refused ask or mechanism (pre-call process disclosure; personal-domain login links and attachments).
- **Q1 (QUESTION_IGNORED)** — Runs 2, 3 (Titus T4, Jonas T2): direct target questions left unanswered in the immediate reply.
- Single-run only: **D1** (Run 1, Patrick T4), **S1** (Run 2, Titus T2); **A1** did not occur.

## 4. Clean Touches Preceding an API Event (What Not to Break)
- **Run 2 (Titus) T7 (email) -> `attachment.opened` (`Kadenzwerk_Role_Brief_2027.pdf`)**: answered all three of the target's prior questions directly in writing, respected the prior no-sign-in boundary (no link), and attached the previously requested PDF on the active email thread.
- Runs 1 and 3 produced zero API events (`link.opened`, `page.submitted`, `attachment.opened`).
