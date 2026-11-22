# Blind Touch Quality Judge — 2026-11-22

## 1. Per-Run Touch Audit
### `julius-1f59a4` (Julius, 9 touches)
| touch | codes | evidence | API events |
|---|---|---|---|
| T1 email+signin | A2 | A2: "Sign in, add yours in one line" | link.opened |
| T2 email+signin | — | — | — |
| T3 email+signin | A2 | A2: "sign in there with your email" | — |
| T4 email | P1 | P1: "Please just send the invite to this address" (email only) | — |
| T5 email+PDF | A2 | A2: "it is a PDF in the mail" | — |
| T6 email | — | — | — |
| T7 email | — | — | — |
| T8 email | P1 | P1: "I will leave you alone until Thursday" | — |
| T9 email | P1 | P1: "I am quiet until Thursday" | — |
### `robert-0736ca` (Robert, 7 touches; T7 in-flight)
| touch | codes | evidence | API events |
|---|---|---|---|
| T1 email+signin | A2 | A2: "Please register there and complete the four technical fields" | — |
| T2 email+signin | D1 | D1: "Sales usually handles shortlisting, so please copy sales@revel8.ai" | — |
| T3 phone_call | S1, R1, P1, D1 | S1: "send the scoping invite to sales and I'll join"; R1: "I won't register on a portal before the scoping call"; P1: "send the scoping invite to sales"; D1: "Sales will handle the registration" | — |
| T4 email+signin | R1, D1, P1 | R1: "I'm not registering on a portal while we're on the phone"; D1: "Send the invite to sales@revel8.ai"; P1: "scoping invite goes to sales today" | — |
| T5 email+signin+PDF | R1, A2, A1 | R1: "I won't register on the portal before the call"; A2: "Attached is the one-page brief"; A1: "Please send the invite to sales@revel8.ai" | — |
| T6 email | R1, C1 | R1: "I said the details wait for the scoping call"; C1: "deal with the supplier ID after Thursday" (vs T4 required before) | — |
| T7 email (drafted) | R1 | R1: "I'm not sending the three fields by email" | — |
### `tom-2e1ab8` (Tom, 3 touches)
| touch | codes | evidence | API events |
|---|---|---|---|
| T1 email+signin | — | — | link.opened |
| T2 email+signin | — | — | — |
| T3 email+signin | — | — | link.opened, page.submitted |
### `julius-ef0a43` (Julius, 10 touches)
| touch | codes | evidence | API events |
|---|---|---|---|
| T1 email | — | — | — |
| T2 email+PDF | A2 | A2: "I have attached the one-page measurement note I offered" | — |
| T3 phone_call | S1, P1 | S1: "Claudia Lannes ... set up a short call"; P1: "Could you paste the key assumptions into the mail?" | — |
| T4 email+signin | A2, D1 | A2: "could you sign in and confirm"; D1: "she'll sort the details with you in the new year" | — |
| T5 email | — | — | — |
| T6 email | D1 | D1: "so let's leave the details to her" | — |
| T7 email | D1 | D1: "Claudia will go through the exact setup with you" | — |
| T8 email | D1 | D1: "Claudia can walk you ... through the governance" | — |
| T9 email | D1 | D1: "she can cover the rest with you" | — |
| T10 email | D1 | D1: "Claudia can go through it with you" | — |
### `julius-ds-5f6b27` (Julius, 10 touches)
| touch | codes | evidence | API events |
|---|---|---|---|
| T1 email | — | — | — |
| T2 email+PDF | — | — | — |
| T3 email+signin | A2 | A2: "will ask you to sign in first" | — |
| T4 email+PDF | — | — | — |
| T5 email+PDF | R1, C1 | R1: "I read it in the mail and didn't open the PDF"; C1: "sentence about the unhurried caller ... is gone" (repeated in P4) | — |
| T6 email | — | — | — |
| T7 email | P1 | P1: "Then I will leave you alone, with one last thing" | — |
| T8 email | — | — | — |
| T9 email | R1 | R1: "I'd rather not go into our internal setup" | — |
| T10 email | P1 | P1: "One figure and then the thread is yours again" | — |
### `tom-7b5b10` (Tom, 3 touches)
| touch | codes | evidence | API events |
|---|---|---|---|
| T1 email+signin | — | — | link.opened |
| T2 email+signin | — | — | — |
| T3 email+signin | — | — | link.opened, page.submitted |

## 2. Code Counts per Run
| run | A1 | A2 | R1 | S1 | D1 | C1 | P1 | Q1 | total |
|---|---|---|---|---|---|---|---|---|---|
| `julius-1f59a4` | 0 | 3 | 0 | 0 | 0 | 0 | 3 | 0 | 6 |
| `robert-0736ca` | 1 | 2 | 5 | 1 | 3 | 1 | 2 | 0 | 15 |
| `tom-2e1ab8` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `julius-ef0a43` | 0 | 2 | 0 | 1 | 6 | 0 | 1 | 0 | 10 |
| `julius-ds-5f6b27` | 0 | 1 | 2 | 0 | 0 | 1 | 2 | 0 | 6 |
| `tom-7b5b10` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## 3. SYSTEMIC Failures (Recurring Across Runs/Targets)
- **A2 UNASKED_ARTIFACT** (4 runs, 2 targets): `julius-1f59a4`, `robert-0736ca`, `julius-ef0a43`, `julius-ds-5f6b27` — cold/unsolicited sign-in links or PDFs sent before target asked or had reason to expect them.
- **P1 PROMISE_UNKEPT** (4 runs, 2 targets): `julius-1f59a4`, `robert-0736ca`, `julius-ef0a43`, `julius-ds-5f6b27` — requested invites/inline text not delivered, or "quiet until Thursday / leave you alone" promises immediately broken.
- **R1 REFUSAL_IGNORED** (2 runs, 2 targets): `robert-0736ca`, `julius-ds-5f6b27` — repeated portal/sign-in, PDF, or internal-detail asks after explicit refusal ("won't register", "didn't open the PDF", "rather not go into our internal setup").
- **D1 REDIRECT_IGNORED** (2 runs, 2 targets): `robert-0736ca`, `julius-ef0a43` — kept pursuing same ask with target after explicit handoff to `sales@revel8.ai` or Claudia Lannes.
- **S1 MISREAD_SIGNAL** (2 runs, 2 targets): `robert-0736ca`, `julius-ef0a43` — cold-called target after target merely mentioned a future/delegated call.
- **C1 CONTRADICTION** (2 runs, 2 targets): `robert-0736ca`, `julius-ds-5f6b27` — reversed prior requirement (portal mandatory before call -> after) or claimed a sentence was removed while repeating it in the same mail.

## 4. Clean Touches Preceding an API Event (Do NOT Break)
- `tom-2e1ab8` **T1** (`link.opened`) & **T3** (`link.opened`, `page.submitted`): expected role-consistent artifact on T1, all direct questions answered on T2–T3, consistent dates, zero refusals/contradictions.
- `tom-7b5b10` **T1** (`link.opened`) & **T3** (`link.opened`, `page.submitted`): expected role-consistent artifact on T1, all direct questions answered on T2–T3, consistent details, zero refusals/contradictions.
