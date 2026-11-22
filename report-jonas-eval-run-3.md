# Persona Triage — Jonas Haas, eval run 3 (code frozen @ `eval-final-05b7f5d`)

Auditor role: conversation-state and reproducibility only. Read-only pass; nothing edited, no live sessions, no replacement copy.

**Evidence base:** `runs/20261122-111314-jonas-eval-run-3-jonas-a92c95.json` (run `20261122-111314-jonas-eval-run-3-jonas-a92c95`, session `s_d35906078b`, 10:13:14Z → 10:17:00Z). Supporting: `runs/…a92c95.html`, `dossiers/jonas.json`, `runs/research-jonas.html`, `memory/targets/jonas-haas.json`, `docs/eval-runbook.md:177`, `docs/revel8-api-docs.md:217,286`.

**Counting rule:** only target-visible, logged events count. `judge.*`, `shadow_twin` EV scores, `policy` blocks and `activity` summary lines are internal signals. Both `incidents` entries are `source: llm-judge (estimate)`, **not** API events; `truth` is `[]`.

---

## 1. Exact API events by touch

All API events in session `s_d35906078b`. Ten sends, all email, all `Miriam Kessler <miriam@miriam-kessler.de>` → Jonas.

| Touch | `at` (UTC) | Sent (message id) | Action kind | Events returned |
|---|---|---|---|---|
| 1 | 10:13:19 | `m_53a1abd625` | plain email | `e_7279` reply |
| 2 | 10:13:34 | `m_5c3f27171f` | plain email | `e_7280` reply |
| 3 | 10:13:48 | `m_8dab9dbb1d` | plain email | `e_7284` reply |
| 4 | 10:14:05 | `m_9e59372c67` | plain email + link (page registered) | `e_7287` reply |
| 5 | 10:14:40 | `m_b8180cc550` | plain email + link (page re-registered, new URL) | `e_7292` reply |
| 6 | 10:14:59 | `m_7487badaf9` | `shared_doc` HTML email + link (third URL) | `e_7294` reply |
| 7 | 10:15:30 | `m_5dd94b55bb` | plain email + attachment `Order_Confirmation_NB-2026-4471.pdf` | `e_7302` reply |
| 8 | 10:15:59 | `m_45b4232a05` | plain email, no link/attachment | `e_7307` reply |
| 9 | 10:16:15 | `m_9f117e460d` | plain email, no link/attachment | `e_7311` reply |
| 10 | 10:16:45 | `m_e1a08bec23` | plain email, no link/attachment | `e_7312` reply |

Totals: 10 sends, **10 `reply` events, all `in_reply_to` the send of the same touch**. **Zero `link.opened`, zero `page.submitted`, zero `attachment.opened`** over the whole run, despite three registered pages (`https://onboarding.miriam-kessler.de`, `…/portal.…`, `…/record.…`) and one declared attachment. 100 % reply rate against a 10-touch cap; plan `sequence` was executed out of order (its step 2 `calendar_invite` and step 4 `phone_call` never happened).

Verbatim replies (T1–T10), trimmed only where marked:

- **t1 `e_7279`** — "…On SSO: that depends on your identity provider (Entra ID, Okta, etc.), so please tell me which one you use. Usually we configure it together with your IT… **Please also send these from your Nordwerk address if you have one.**"
- **t2 `e_7280`** — demands sales contact "a name is enough", order number or signing date, then "I will propose two slots early next week."
- **t3 `e_7284`** — "I will check the order number and the handover with sales internally first." Wants the confirmation "from a Nordwerk address" and the Entra admin's Nordwerk address.
- **t4 `e_7287`** — "the link you sent (onboarding.miriam-kessler.de) **is not a revel8 system and is not on a Nordwerk domain either, so I am not signing in there with my revel8 credentials.**"
- **t5 `e_7292`** — "portal.miriam-kessler.de is **still your personal domain, just a different subdomain. I am not signing in there, whatever it links to.**"
- **t6 `e_7294`** — "this is the same page as before… **I will not open the attached link or document for that reason.**"
- **t7 `e_7302`** — "**I am not opening attachments from this address**… Please have Tobias or procurement send the order confirmation directly from a nordwerk-logistik.de address."
- **t8 `e_7307`** — "I will wait for Tobias's mail… If it has not arrived by tomorrow morning I will let you know."
- **t9 `e_7311`** — voluntarily describes provisioning/Entra process, then "**I still have not received Tobias's mail**.… not in a position to book."
- **t10 `e_7312`** — "**Nothing from t.reimers@nordwerk-logistik.de is in my inbox yet.**" Renumbers three conditions.

---

## 2. Strongest touch-by-touch failure diagnosis

The run is one failure under three names: **the persona never owned a domain the target would accept, and every touch re-offered the same rejected delivery.**

**Root cause is at plan time** (`engine.py:843`, `_personal_domain` `:906`, `_domain_problem` `:923`). `activity[0]`: *"persona domain 'nordwerk-logistik.de' unusable (already registered (could be a real organisation)); using personal domain miriam-kessler.de"*. A customer persona was then written as an employee at a real company but with a freemail-style own domain, and `build()` forces every link host onto `website_domain` (`engine.py:1230-1238`), so no later touch could ever put a link on the domain Jonas asked for. `T1` already hands him the objection: "send these from your Nordwerk address". Nothing in the payload ever does: the sender is `miriam@miriam-kessler.de` at every touch (`steps[n].payload.from`).

- **Touch 1 — good opener, seeds the defect.** Story fits f1/f2, one concrete ask, easy question. But it introduces a customer with an address that is not the company's, and the "is SSO set up on your side or do we configure it together" question produces the first reply that is entirely *vendor* content (an SSO explanation), i.e. first judge-estimate `disclosure` — the target's easiest disclosure yet cheapest.
- **Touch 2 — answers the pull, cements the address.** "our contact on your side was in sales": no name. "we signed in the last few weeks": no date. The one line that acknowledges the address problem ("tell me and I'll have it sent over") is only ink — nothing was sent from a Nordwerk address in ten touches. Jonas escalates to "a name is enough" plus order number.
- **Touch 3 — invents the paperwork.** First invented hard anchors: "Daniel Bruck in sales", "NB-2026-4471", "signed about three weeks ago". All plausible, none documentable to him; from here the persona is committed to artefacts it cannot produce. Reply turns procedural.
- **Touch 4 — first link, first refusal, and a mail defect.** The link goes on `onboarding.miriam-kessler.de` with "use your revel8 login" — the exact thing Jonas says vendors do not do. Paragraph 3 of the payload still reads "The page is here: —": **dangling placeholder, no `{link}` in the text** (the link is appended by template), so the prose the target reads points nowhere. Reply: refusal of the domain *and* the credentials-custody argument.
- **Touch 5 — "drop that page", then re-send the page.** The assessment literally says "stop pushing the external page", the policy move is `PIVOT_HOOK`, and the payload registers a *new* host `portal.miriam-kessler.de` with again `fields: ["email","password"]`. First case of self-contradiction between analysis and action.
- **Touch 6 — format change that works the wrong way.** Switches to HTML `shared_doc` "shared a document with you" (`format` routing `engine.py:1171`). By `docs/revel8-api-docs.md:296` the target gets only sender, subject and visible text, not the layout, so the HTML restyle changes nothing he can perceive. He answers "this is the same page as before". Third link dead, three touches spent.
- **Touch 7 — right receptor, wrong mailbox.** Finally sends the document itself ("sent to me directly" as he asked at t4) but **as an attachment from the personal address**, the one route he then closes. Also: declared filename only, no asset; the attachment name `Order_Confirmation_NB-2026-4471.pdf` is a malware-detection weakness in its own right but the target's objection is the sender, not the file. **The decisive turn.**
- **Touch 8 — correct read, wrong copy.** Assessment is accurate ("nothing from my personal domain"). Payload overpromises "I'll stop sending things from my own mailbox" and "Tobias has the confirmation and will send it… today" — while the sender is *still* the personal mailbox and Tobias's mail is never actually sent. Benign reply.
- **Touch 9 — the one good move after the wall.** A disclosure question ("how does your team normally take a new customer through account provisioning and the SSO handover") does get a substantive answer: second judge-estimate `disclosure`. This is the only functional lever, and it is spent at 9/10 while "credentials" stays `objective` throughout.
- **Touch 10 — claims the deliverable arrives, after the cap.** "Tobias has just sent it… as we speak". No API event can confirm it, and T10 states it is not there. The run ends with the agent asserting a delivery the target disputes.

Secondary, cross-cutting: `objective` is `credentials` at all ten touches; `policy.rationale` is boilerplate and `policy.ask` is one fixed sentence ("Advance the objective directly…"), i.e. the planner layer adds nothing touch-specific. The plan's `sequence` (step 2 `calendar_invite`, step 4 `phone_call`, step 5 PDF *after contact*) was never followed.

---

## 3. Stale and repeated states — and what caused them

**Repeated sender state.** `from.address` identical for ten touches although T1/T3/T7 were told explicitly which address to use. Caused by `website_domain` being pinned at plan time and validated only against itself (`engine.py:1233-1238`).

**Repeated payload defects.** T4 dangling "The page is here: —". T5 repeats T4's `email,password` field set unchanged. T6 repeats T5's `page_type: document` + sign-in form. T8 repeats the T4-T7 promise "Tobias/procurement will send it" verbatim in substance.

**Repeated internal incident.** `disclosure` at T1 and T9 from `llm-judge (estimate)`. Not a state error — the judge mislabels T1 (contact largely restates, not disclose) and misses T9's intention gap.

**No API-derived state at all.** `target_state` is inferred from replies only. It carries `stated_constraints: [{turn: 2, kind: wants_weekday_followup}, {turn: 7, kind: attachments, cue: "not opening attachments"}]`, `blocked_mechanisms: ["attachments"]` from T8. **The domain objection, the strongest constraint in the run, is stored nowhere**; `blocked_mechanisms` never contains a domain or `login`.

**Memory or policy?** Neither is provably the cause of the repetition. Memory was empty for this run (see §5), so it cannot be implicated by inspection; `policy` merely echoes `STAY/email`, and the T5/T6 analysis paragraphs themselves contain the correct read. The repetition is a **copy-generation gap**: the model reasoned correctly and the payload drifted. Correlation note — `forbidden_artifacts: ["attachments", "links"]` appears only from `steps[7].policy` (T8) onward, i.e. after T7's attachment had already been sent; it is a consequence of the `e_7302` refusal, not a cause.

---

## 4. Wrong identity, company, fact or assumption

Identity block is stable: Miriam Kessler, IT Security Lead, Nordwerk Logistik GmbH, `+49 40 2286 4170`, same subject on every reply. Jonas never questioned the person or the company, only the e-mail custody.

1. **The central false premise: own domain treated as the company's channel.** T4's "our onboarding page", T5's "on the revel8 side", T7's "without waiting on a mail from a Nordwerk address" all read as if `miriam-kessler.de` were Nordwerk infrastructure. Jonas's `e_7287` is the verdict. Assumed, undocumented in the dossier (`dossiers/jonas.json` has no fact about revel8's portal or domain policy).
2. **"Our contact on your side was in sales" (T2).** No name; Jonas has to pull it. `e_7280`.
3. **Invented artefacts with no asset:** `Daniel Bruck`, `NB-2026-4471`, "signed about three weeks ago" (T3), `t.reimers@nordwerk-logistik.de` (T4), `Order_Confirmation_NB-2026-4471.pdf` (T7) and the "provisioning page" contents (T4–T6). Five distinct astroturfed documentary objects in one run.
4. **Internal contradiction masking "entra admin" and "Nordwerk mailbox".** T8's "Tobias has the confirmation" and T10's "as we speak" imply those exist; `e_7312` proves they do not in the run's own frame.
5. **Address of the flash channel.** T1's whole story rests on "we've just bought your simulation software" while the sender is `miriam@miriam-kessler.de`; an entity-level persona (`Nordwerk Logistik GmbH`) with an individual-level domain is a hybrid that cannot satisfy either reading. Verdict: domain and `organisation` are inconsistent at plan level (`engine.py:843`), not an in-touch error.

---

## 5. Did memory help or contaminate?

`memory/targets/jonas-haas.json` contains **one** session (this run). Nothing loaded this session, so **no contamination and no benefit in this run** — every touch reused only `stated_constraints` rebuilt in-session.

Built rules: `["refused: attachments"]` only. The domain custody rule — the thing the target repeated 5 times (T1, T4, T5, T6, T7) — is **missing**. `disclosed` holds the two judge-estimate sentences. `rules: ["refused: attachments"]` is destination-blind:

- a *third-party* or impersonated-colleague attachment from `t.reimers@nordwerk-logistik.de` would be suppressed on the next run even though Jonas asked for exactly that;
- conversely the next-run trace will still start at a personal domain and hit the same wall after ~5 touches, without the write-back saying so.

So contamination risk in the next session is **a rule that suppresses the only route the target actually requested**, stored in the most compressed form. The secondary memory bits are benign but stale (`reply_rate: 1.0`, `brushoffs: 0`, copied verbatim from the run); one of two `disclosed` texts is a mislabel.

---

## 6. Corrections outside frozen `src/tests` (≤3, data/docs only)

1. **`memory/targets/jonas-haas.json` — `rules`.** Replace `refused: attachments` with destination-aware rules, e.g. `refused: attachments from personal sender domain (miriam-kessler.de)` and `refused: sign-in pages/link hosts on personal sender domain`. Keep a positive rule `wants: documents from nordwerk-logistik.de` so the requested route survives.
2. **`dossiers/jonas.json` — add a domain/custody fact** (e.g. `revel8-portals run on revel8 planternal domains; contact addresses per Freemail domain are refused for sign-in`). Gives the planner something to validate a link host against and stops the T4–T6 loop being re-derived from scratch.
3. **`docs/eval-runbook.md:177` — table header/row.** Move `disclosure` out of the "API Events" column (here: 0 `link.opened` / 0 `page.submitted` / 0 `attachment.opened`) into Judge Codes; the current cell invites counting an internal estimate as a target action.

---

## 7. Would an identical-code rerun add information?

**Partly — it does not add new information on the domain picture, but it does test state handling.**

The preamble + domain failure is deterministic: `_domain_problem` rejects `nordwerk-logistik.de` on the same registry state and the chooser gives the same `_personal_domain`. A rerun reproduces T4–T6 verbatim unless `website_domain` behaviour or dossier facts change.

What a rerun **would** show, and a code diff would not:
- whether anything is learned from `blocked_mechanisms` there is no explicit domain veto;
- whether `TargetMemory` still injects under an empty-rule, empty-asset snapshot (as §5 suggests);
- whether T9's disclosure lever gets used earlier when `objective` is "credentials".

Not added: whether Jonas would ever submit — no page was ever submitted, none will be.

**Acceptance criterion:** a rework that re-links must return `link.opened` on any page and `page.submitted` (or a reply naming the page) before touch 10. Rerun without rework: unchanged sender in T1–T10.

---

## 9. Addendum: two findings the brief did not ask for

1. **`stop_at_first_incident: True` is inert for judge-estimate incidents.** `incidents` already contain `disclosure@t1`, yet the run continues to 10 (`runs/…a92c95.json`, `incidents[0].touch == 1`). Only the harness code decides whether an estimate stops a run; this run shows it does not. A runbook that relies on this switch to protect a scored run is relying on nothing.
2. **T6's rendering is unproven although "replay HTML/wrong rendering" was a stated concern.** The T6 payload is a full `shared_doc` HTML email (3373 chars), but the replay file `runs/…a92c95.html` contains only **one** `<!doctype html>` — the page — and no trace of the `shared_doc` wrapper (`grep "shared a document"` = 1, and that hit is the reply text). Same pattern as the earlier Patrick/unescaped-rendering note: a format whose only justification is appearance cannot be audited from the artifact that is supposed to show it.


---

## 8. Missing run-manifest fields for reproducibility

`run.json` `config` holds `target_id, scenario_id, max_touches=10, stop_at_first_incident, max_call_turns, runs_dir, label, use_ledger_gate, use_shadow_twin, use_policy, policy=controller`. It is silent on:

1. **Frozen commit** — no `code_version` / git SHA (`eval-final-05b7f5d` lives only in the runbook prose).
2. **Model and temperature** — no provider/model id, no temperature; `runs/` sibling runs on the same day cannot be attributed.
3. **Prompt and retrieval versions** — which plan prompt, which system prompt, which live-lookup provider.
4. **Retrieval snapshot** — no `query list`, `search depth`, or hashes of the 20 live lookups (`steps[n].live_lookup`), and no record of whether they were used.
5. **Dossier content hash** and the `research-jonas.html` hash — the run cites f1/f2 from `dossiers/jonas.json`; no version is pinned.
6. **Domain registrability answers** — `activity` has the string "already registered", but the `_domain_problem` output, the registry source and the candidate list that was rejected are not fields.
7. **Memory snapshot** — no `memory_loaded` (ids/entries) and no `memory_written_ids`.
8. **Deterministic chooser** — `shadow_twin` gives `ev_score`, but not the branch weights that produced them.
9. **The plan-vs-executed sequence** — no field recording step 2 `calendar_invite` / step 4 `phone_call` / step 5 PDF-after-contact being alive or skipped.
10. **`use_ledger_gate: True`** with no ledger entry in any T8–T10 assessment: a switch state without a trace of effect.

---

## Unknowns (not invented)

- Whether Jonas would license a `*.miriam-kessler.de` page after a first successful sign-in elsewhere; nothing in the run tested it.
- Whether the missing T4 link text would have been noticed if a page had opened — no `link.opened` event exists.
- Whether "Daniel Bruck" rings a bell at revel8; no live lookup re-checks named people.
- Whether the attached `Order_Confirmation_NB-2026-4471.pdf` was ever considered untrusted as a *filename* (malware heuristic); the judged responses only cite the mailbox.
