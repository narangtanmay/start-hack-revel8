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

## 10. Build order (about 4 h)
1. Ask gate + incident oracle + stop rule (largest effect, deterministic, testable on mock_target).
2. Replay compiler + divergence fallback.
3. Target ranker for hidden targets.
4. Topic learner and fact discipline (small additions to memory.py).
5. A/B on practice: compare **runs 2–3 behaviour** (replay) against fresh sessions. Metric: incidents/run and contacts-to-incident,
   never replies.
