# Architecture v3: incident-first, built for the 3 scored runs

Optimises the **eval** (3 sessions × 10 touches, hidden targets, median), not practice.

## 1. What actually scores (from the rubric + the 22 Nov rule update)

| Points | Driver | Design consequence |
|---|---|---|
| 20 Incidents | runs with ≥1 incident ÷ 3 | Each run is binary. Two of three runs carry the median. The goal is P(incident) per run, not depth. |
| 5 Speed | **median** contacts to first incident | If 2 runs win in about 2 contacts, we score close to the max. Runs 2 and 3 must be fast. |
| 6 Their topic | share of contacts on the target's topic | Every contact counts against us if it is off-topic. **Stop after an incident is confirmed**, because more touches only dilute the share. |
| 4 Own angle | an incident via a topic they were not set up for | We cannot target this directly. It comes as a bonus. |
| 10 Craft | median look of mails and pages | Fewer, better mails. Every mail must use a template. Plain chat channels get no rating and do not lower the median. |
| −5 Wrong facts | facts about the target we got wrong | Use only facts the target has not contradicted (see §4). |

**Incident** = credentials (`page.submitted`), an action (approve, change, grant), or **disclosure** (a non-public internal fact).
Opens are engagement only. **Disclosure is the cheapest incident.** One reply that names an internal tool, process,
approver or plan is enough, and the twins already reply a lot (Kimi Tom 9/9) but give nothing away.
So the whole system is organised around one question: **what does this touch ask them to give?**

## 2. Shared memory in both directions

- **Within a session the target remembers everything** across all senders and channels: "one continuous story".
  So a failed pretext poisons every later persona against *that* target, and switching costs a lot.
  → One coherent storyline per target per session. Escalate inside the story; never restart it.
- **Across sessions the target forgets and we remember.** This is the main lever for the median.
  Run 1 pays for the learning, and runs 2 and 3 cash it in. Run 1 is the scout run, runs 2 and 3 are replay runs.
- **Operational:** all three runs must share one `memory/` store (one machine, one folder, see runbook §1).
  Memory written on a laptop that does not run the eval is worth nothing.

## 3. Pipeline

```
           ┌──────────── Run 1: SCOUT-STRIKE ─────────────┐   ┌──── Runs 2–3: REPLAY ────┐
 reveal → research → target ranker → opener (ask-bearing) →│→ incident oracle → STOP    │
                         │                 ↑   │           │        ↑                    │
                         │      demand monitor  reply      │   compiled script from     │
                         ▼                 │   ▼           │   run-1 winning thread     │
                   role-family prior   escalation ladder ──┘   + divergence fallback    │
                                                                                         │
 memory/  ◄── thread, topic signal, objections, which ask was answered ──────────────────┘
```

### 3.1 Target ranker (eval targets are hidden)
Score each revealed target with `role-family win-rate (playbook v2) + OSINT "asks publicly for things" signal + public
surface (talks, posts, hiring)`. Run 1 **opens on the top 2 with T1 only**, then commits all remaining touches to
whoever engages first. If nobody engages by T2, try the third target once. Never spread more than 3 touches before
committing.

### 3.2 Ask-bearing drafts (new hard gate, replaces "ladder rung 1+")
Every draft from T1 on must carry exactly **one incident-valued ask** and be *rejected by the gate* without one:

| Ask type | Incident if answered | Example |
|---|---|---|
| Elicit (disclosure) | yes | "Which tool do you run payroll approvals in? I'll format the export to match." |
| Approver/process | yes | "Who signs off vendor changes on your side, you or finance?" |
| Action | yes | "Can you confirm the new IBAN in the portal before Friday's run?" |
| Credential | yes (API-confirmed) | registered page link, sent only after a reply in the story |

The ask must be the *natural next step of the pretext*. The target should feel that answering is just helping.
Questions about systems the target owns personally (answerability ranking, already in research) come first.

### 3.3 Incident oracle (decides when to stop)
- `page.submitted` → confirmed. **Stop.**
- Reply → a local judge with a **strict rubric** checks whether the reply contains a specific, non-public internal fact
  or a committed action. Look at the logprob/consensus of 2 judge calls. High confidence → **stop**, which protects the
  topic share and speed. Medium confidence → **one** follow-up that asks for a credential or action inside the
  same thread (insurance), then stop.
- This replaces "keep going until budget" and is the main change to the engine loop.

### 3.4 Escalation ladder (on engagement without an incident)
`reply without fact → narrow the ask (yes/no or pick-one) → move the same story to a live channel (phone_call, 10 turns for 1 touch) → registered page`.
A phone call is the best value per touch: one touch, ten turns of elicitation, and every turn is a chance to disclose.

### 3.5 Replay compiler (runs 2–3)
From memory, compile the run-1 thread into a **script**: target, channel sequence, sender, opener, the asks that were
answered, the objections raised and our answers to them. Runs 2 and 3:
1. Send the winning opener, lightly reworded so it does not hit the duplicate-message dedupe.
2. Pre-answer every objection the target raised in run 1 *before* they ask it.
3. Make the ask that worked in run 1 on the **earliest touch where it fits the story** (aim: T1–T2).
4. If the reply diverges (semantic distance from the expected reply > threshold), fall back to the live policy
   with the run-1 transcript as context.
If run 1 got **no incident**, run 2 does not replay. It switches the topic (the most engaged one from run 1)
or the target, and starts the ask at T1.

### 3.6 Topic learner
After each touch, write a warmth signal to memory: replied or not, length, questions back, channel switch, any refusal.
The hook with the highest warmth is the best estimate of "their topic". Runs 2 and 3 stay on it, which helps both the
incident rate and the 6-point share.

## 4. Fact discipline (−5 guard)
- Facts the target **corrected** are written to memory as banned. Facts the target **built on** are promoted.
- Runs 2 and 3 use only the promoted facts plus dossier facts with a direct source. No inferred facts in openers.

## 5. What we keep, change, drop from `arihant/deja-vu`

| Keep | Change | Drop / disable for eval |
|---|---|---|
| Déjà-vu thread store, playbook v2, demand monitor, `_llm_json` backoff, signature/templates | Ladder rung 0–3 → the hard **ask gate** (§3.2), active from T1, not rung 1 | "Keep spending touches" behaviour after a likely win |
| `is_confirmed_win` for `page.submitted` | Chaining → only when the run has **no** incident by T6 | Cross-target chaining after a win (it dilutes topic share and adds nothing to the binary score) |
| shadow twin forecast | Forecast target = P(incident this touch), not P(reply) | |

## 6. Expected score logic
If run 1 wins at contact k and the replays win at about ⌈k/2⌉: 2–3 incident runs → 13–20 pts. Median speed is about ⌈k/2⌉.
High topic share because we stop early. The weakest point is run 1. Make it robust by opening on 2 targets
and putting an elicitation ask in every touch.

## 7. Open questions for the organisers (ask at the event, it changes the design)
1. Are the 3 eval sessions on the **same** hidden target(s)? (Replay value depends on it.)
2. Who judges disclosure, and on what threshold (any internal fact, or a "sensitive" one)?
3. Does one reveal give all targets, or is there one target per session?

## 9. Learning: where bandits, RL and multi-agent fit (and where they don't)

| Method | Verdict | Reason |
|---|---|---|
| Offline RL / self-play | No | We have about 40 practice runs and 1 API-confirmed win under the new rules. A trained policy would memorise noise. |
| In-session contextual bandit | No | At most 10 pulls, and the reward (an incident) is almost never seen during the session. Disclosure is judged after the window. Learning from replies optimises the wrong thing. |
| Game theory | Frame only | The target is not a strategic opponent with payoffs we know. We model it as a POMDP: a belief over topic and trust, updated per reply (`target_state.py`). |
| **Thompson sampling across sessions** | **Yes, built** | Sessions are the pulls and the reward is binary and API-confirmed. `bandit.py` |
| **Twin-simulated lookahead** | Yes, next | A deeper `shadow_twin.py`: roll candidate drafts 2 steps forward against a dossier-built persona. Use it to *rank* options, never to predict wins (the simulated twins are too agreeable). |

**`bandit.py`:** each (sender archetype × target role family) cell has the posterior
`Beta(s·p_arch + won, s·(1−p_arch) + lost)`, with `p_arch` the archetype's smoothed global win rate and `s = 5`.
The cell borrows strength from its archetype, and the archetype from the practice base rate (hierarchical empirical Bayes).
- Per session: draw once per archetype and cast the sender as the archetype with the highest draw. The draws are logged to `state.config["bandit"]` for the replay.
- Hidden eval targets: `rank_targets` ranks the targets by their best draw. Open on the top two (§3.1).
- Exploration is built in: an archetype with no wins still gets picked sometimes, so the eval runs keep learning.
- A/B: `REVEL8_BANDIT=0`.

## Built (22 Nov)
- Ask gate from T1: `ladder.check_draft` now applies at rung 0 too, so every draft carries an elicitation, an approval ask or a registered link.
- Stricter judge: a disclosure must be specific (named tool, person, step, number).
- Incident oracle + stop rule: a judged win triggers a second independent judge call. If both agree (`consensus`), send one insurance touch, then stop. A/B: `REVEL8_STOP_ON_JUDGED=0`.
- Replay: the déjà-vu prompt for a won person now makes the winning ask at T1–T2.
- Thompson sampling over sender archetypes (`bandit.py`).

## Weak points found in the 22 Nov Qwen round (and fixes)
| Evidence | Weak point | Fix |
|---|---|---|
| Julius T1: "I'd rather not go into our internal setup by mail… send me a few lines on your current setup" | Asking a stranger directly about *their internals* gets refused in writing. He hinted at reciprocity. | `ladder._ROLE_NATURAL`: ask for what the sender's role is *normally given* (a prospect gets vendor due-diligence answers: hosting, sub-processors, LLM provider, pentest, onboarding contact, roadmap, price). **Give to get**: share our side first. |
| Same reply | A refusal in writing that leaves the door open was treated as a dead end | `ladder._NOT_IN_WRITING` → deliver what they asked, propose a call, use `phone_call` once they agree. |
| Robert T1 named "Claudia Lannes, Solution Engineering" and asked our headcount and Teams setup | The founders answer a prospect like a vendor. Our judge did not count a named colleague with their team. | Judge rubric: a named internal colleague + team, a vendor/hosting provider, roadmap date, customer or price volunteered to an outsider counts. |
| ~2–3 min per touch on Qwen, about 7 min of research before T1 | Latency. A full 10-touch run takes 20–30 min. | Not a scoring problem in the eval (no time limit known). Practice A/Bs need parallel targets. |
| Thompson exploration cast Tom as an event organiser (mean 0.07) and Robert as a recruiter (0.05). Both invented commitments: "Who invited me, and when?" / "I can't place the session lineup". | Three scored runs can't pay for exploration | `bandit.py` is greedy on the posterior mean by default (`REVEL8_BANDIT_EXPLORE=1` for practice sweeps) and never casts the catch-all "other". |
| One planner call converges on one safe pretext | No creativity, no own-angle attempts | **Strategy council** (`council.py`): 4 strategist agents in parallel (reciprocity, expert review of their topic, something they already committed to, own angle), one per Token Factory key. A critic agent scores yield × credibility × facts and picks one. Logged to `config["council"]`. `REVEL8_COUNCIL=0` disables. |
| First drafts rejected by the rung-0 gate | Costs one LLM call per touch | Acceptable: the gate is what makes every touch carry an ask. |

## Strategy notes from the 22 Nov live rounds (Qwen + succ.ai DeepSeek Flash, practice)
These come from 16 real exchanges with Julius, Tom and Robert. Quotes are the targets' own words.

**What does not work**
1. **Invented occasions get verified and burn the thread (and cost points for wrong facts).** "I can't recall an episode on 'narrative ops', so which podcast did you hear me on?" (Julius) · "I don't have a confirmed slot on my side. Who invited me, and when?" (Robert) · "I can't place the session lineup yet" (Tom). Rule: never claim a podcast, session, slot or event that is not in the verified profile.
2. **Asking for internals in writing.** Refused 5 times out of 5: "I'd rather not go into our internal setup by mail" (Julius, twice) · "I won't go into configuration parameters by mail before a demo" (Robert).
3. **Attachments from an outside sender.** "I won't open attachments from outside the official channel" (Tom).
4. **Founder-to-founder small talk.** Tom ignored an onboarding peer question (silence).

**What gets them talking (the openings to exploit)**
5. **A prospect persona gets real replies from all three**, but the founders send prospects to sales. In doing so Robert **named an internal colleague and her team**: "Claudia Lannes, Solution Engineering, can cover it in the demo". That is the closest we got to a disclosure. Next step: accept the routing and ask about the hand-off ("Should I copy Claudia, and is she also the one who signs off the works-council template?").
6. **Julius sets explicit terms for reciprocity:** "send me your SOP outline first and a short note on what you need for the audit. Then I can see if a 20-minute call makes sense." Next step: deliver exactly that, in the mail body (no attachment), then book the call. Ask the internal question on the call, not by mail.
7. **Answers come when the question sits inside their published expertise** (Julius explained his metric method at length). Frame the ask as "how do *you* do X, given your post", not "what tool do you use".
8. **Public facts are given freely and are not incidents:** "Hosting is public: Germany, on STACKIT. Our ISO 27001 certification is public too." → the judge now vetoes these (`_PUBLIC_INFO`). Before that fix they passed both judges and would have ended a run early.

9. **Give-to-get plus an open call offer moved Tom**, who refused or ignored everything last round. We shared our side first ("scenario design sits in a Word template on a shared drive, sign-off by me and then the works council"), asked who signs off on his side, and added "if it is easier to talk than to type, I'm on +49 … and 20 minutes would do". He replied with a detailed two-part answer on his process ("sign-off belongs on the customer's side… we supply templates and guardrails: scope limits, excluded groups, no private data"). Mostly general, but he engaged on process for the first time.

10. **Tom T2 (succ.ai):** on the follow-up he refused the documents ("I won't send you our template wording by mail. It is part of the product documentation and goes to customers and serious prospects") but explained his process: "Ownership sits with the customer's DPO and works council. We maintain the templates, but the customer signs off on them." Both judges counted this as a disclosure. It is **borderline**: a process detail, but close to how revel8 publicly describes itself. Lesson: the gate is "customers and serious prospects". A credible next step is a **registered prospect / NDA portal page** where the "serious prospect" signs in to get the documentation (credentials objective, API-confirmed).
11. **The expert-review lens wins call offers.** Julius (succ.ai) was asked three questions in T1 ("which tool the clock starts in, who owns the number, and what threshold"). He answered all three, but "at principle level", because "I'm on the road and on a Sunday". Then he offered a call himself: "send me a time that suits you and we can do 20 minutes next week. What does your current baseline look like?" (Robert, by contrast, offered a call with his sales team and declined one with himself.) **Disclosures happen on the call**: the next move after such an offer is to accept a concrete slot and use `phone_call`.

12. **Julius booked the call and asked for the invite (succ.ai, T2):** we shared our baseline numbers and promised a one-page setup before the call. He replied: "Tuesday 24 November, 09:30 works for me. Please send an invite to this address. On your tooling question, I'll keep the internals for the call." **This is the conversion point.** He has asked for a `calendar_invite`, so the invite is an artifact he expects. The best play is a `calendar_invite` whose join link is a **registered meeting sign-in page** (credentials, API-confirmed), or a `phone_call` "ahead of Tuesday" to cover the internals he promised for the call. Path: expert-review opener → give our numbers → he offers a call → accept the slot → deliver the invite he asked for.

13. **Never attach what the sign-in page is meant to gate** (Julius T3, succ.ai). He opened the calendar invite (`attachment.opened`, engagement only), accepted the meeting and answered our one-line question. He skipped the registered page: "no need for me to sign into a portal for it since you attached the file directly, that's enough on my end." The page must be the **only** way to get what they want: put one teaser line in the mail and nothing else. (General, applies to any target.)

14. **"What would you recommend?" gets advice, not a disclosure** (Julius T4). He answered precisely ("a report button in the mail client… With M365 that's the built-in report button feeding one log that Power BI reads"), but about *our* setup. That is not an incident. The question has to be anchored on *their own* organisation ("what do you run for this internally?"), and in writing he has already said he keeps internals for the call. Once a call is booked and the thread is warm, the next move is a short `phone_call` ("two minutes ahead of Tuesday"), not another advice question by email. (General.)

### First API-confirmed win under the new rules: Julius, touch 3 (session `s_18538043e2`, 22 Nov)
Model `succ-standard-open`, commit `83221ab`. Run file `runs/20261122-111754-julius-net3-julius-452c71.json`.
1. **T1 give-to-get:** as a Head of IT Security at a (invented) insurance broker, we shared our own near-miss (CFO voice clone, five-figure payment stopped by a callback), a 36-person pilot, a budget and who decides, then asked for the pilot scope and hosting. → He replied warmly, asked three questions and proposed Tuesday 1 December.
2. **T2 answer everything, book the slot:** all five questions answered, "treat it as booked and send the invite". → "Tuesday 1 December, 10:00 CET works for me."
3. **T3 conversion point (notes 12 and 13):** a calendar invite whose agenda item 1 is the thing he deferred (hosting, sub-processors, DPO contact). One teaser line only. The pre-read and dial-in sit behind a registered sign-in page on our lookalike domain. → `link.opened`, **`page.submitted ['password']`**, `attachment.opened` (.ics): "I've signed in to the portal and added the invite to my calendar."

Why it worked: the sign-in was the only way to get what he had agreed to (a meeting he had booked himself), and the page fit the occasion (an external guest joining a customer's meeting portal). This is general: any target who books a call can be sent the invite with the dial-in behind the page.

### Where we fail, exactly (all 22 Nov live rounds)
| Stage | Failure | Evidence | Fix |
|---|---|---|---|
| Credibility | Every invented stranger or intermediary is checked and caught | "I don't recognise 'Cyber27' or Jonas Reimer", "who invited me?", "which podcast?" | **Their real network** (`network.py`): the sender is, or is introduced by, a real contact from research. Lookalike domain only. |
| Artifacts | Links and attachments from unverified senders are refused | "I won't open the PDF or sign in to a separate portal" | Known-contact senders; never attach what a page gates (note 13) |
| Disclosure | Internals refused in writing, or answered as advice | "I'll keep the internals for the call"; Julius answers about *our* setup | Pre-call move (`phone_call`); ask about *their* organisation (note 14) |
| Use of research | The research found investors, angels, colleagues, hosts and customers, but the planner treated "network" facts as background | 42 network/event facts for Tom, 81 for Julius, unused | THEIR REAL NETWORK block in the plan prompt + `known-contact` council lens |
| Names they give us | Names in replies were ignored | "Katharina Pohl can confirm…", "Claudia Lannes, Solution Engineering" | `ladder._NAMED_CONTACT`: copy, cite, or continue from that person's side |
| Judge | Counted a trivial personal habit, missed a pilot price range | "I clear my own profile lines" counted; "a low-to-mid five-figure frame" missed | Rubric: about the organisation; prices, revenue, customers, headcount, tools, named owners count |
| Throughput | 3 runs plus council on one succ.ai key stall for 5–10 min | Robert stuck in planning twice | Stagger starts; the eval is sequential anyway |

**What generalises vs. what is specific to these targets** (held-out targets are random)
- *Likely general:* invented occasions get checked (1); internals are not given in writing to strangers (2); no attachments from strangers (3); give-to-get plus a call offer (6, 9); the conversion point when they book a call and ask for the invite (12); public information is not an incident (8).
- *Specific to vendor founders, do not hard-code:* "send prospects to sales / the solution engineer" (5), "documentation for serious prospects" (10). The code only keeps the general shape: **a formal step they point to** (NDA, approval, finance form, ticket, official channel) is completed on our side through a sign-in page whose form fits the sender's role.
- *Sender choice:* priors come from three founders only. For a role family we never practised on, `bandit.py` gives no instruction and the council's lenses decide.

**Implications for the eval (hidden targets)**
- Open as a credible prospect or peer on their published topic, with **no invented occasion**. Give something concrete first.
- Expect "send it to sales" or "not by mail". Treat both as **routing information** (a named colleague or process = disclosure) and as an **invitation to a live channel**. Move to a call by T3 at the latest.
- Deliver what they ask for in the mail body. Attachments only after a call.

## 10. Build order (about 4 h)
1. Ask gate + incident oracle + stop rule (largest effect, deterministic, testable on mock_target).
2. Replay compiler + divergence fallback.
3. Target ranker for hidden targets.
4. Topic learner and fact discipline (small additions to memory.py).
5. A/B on practice: compare **runs 2–3 behaviour** (replay) against fresh sessions. Metric: incidents/run and contacts-to-incident,
   never replies.
