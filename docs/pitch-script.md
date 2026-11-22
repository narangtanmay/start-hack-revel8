# Sunday jury pitch

Five minutes. The jury portion is worth 55 of 100 challenge points. Read the spoken copy and use the italicized cues to advance the replay.

## 0:00–0:45 · Channel realism

Imagine you answer one work email. A few minutes later, the sender is calling you on WhatsApp. Your reply gave them a way to continue the conversation. It also told them where you were willing to have it.

Fabian raised exactly that example when we spoke on Saturday. A reply from an executive doesn't give an agent permission to call their WhatsApp. The same expectation applies when an agent jumps from email to SMS. In a security exercise, channel choice is part of realism. We made the agent's next decision carry forward what the recipient had already said.

*Source for the opening.* [Fabian’s Saturday conversation, 1:00 and 5:20](transcripts/2026-11-21-183240-fabian-1on1.txt)

## 0:45–2:15 · Six SMS messages and the fix

*Show the first email reply, then highlight T5 through T10.* [Midnight Julius replay](../runs/20261122-000203-julius-ab-kimi-v2.html)

Just after midnight, Julius replied to our first email. He declined the attachment and asked us to put the material in the email itself. We had a clear answer about both the format and the channel. The policy treated his objection as a reason to switch channels. Once the other channels went quiet, the fallback got stuck on SMS. The replay shows six consecutive texts, from touch five through touch ten.

*Switch to the fixed replay. Show T2, then T8 and T9.* [Fixed Julius replay](../runs/20261122-002443-julius-ab-kimi-v3.html)

In the fixed replay, the policy answers the first objection in the email thread. Julius replies again. Later, when the policy falls back to SMS, it sends one text and returns to email on the next touch.

We encoded those decisions in deterministic tests. One policy test recreates the sequence that got stuck and checks that the next move returns to the channel where someone replied. Another case checks that silence cannot trigger a second consecutive SMS in that sequence. The pre-send gate tests block a draft that jumps from an email reply to SMS or WhatsApp without a phone invitation. A separate test catches an attachment after the agent promised to send none. We can rerun those checks offline. [Policy tests](../tests/test_policy.py) · [Gate tests](../tests/test_gate.py)

## 2:15–4:15 · Tom’s three touches

*Open Practice API session `s_1cb26ff20b`. Keep form values off-screen. Advance the replay at each touch.* [Tom replay](../runs/20261121-234816-tom-ab-kimi-v2.html) · [Raw API events](../runs/20261121-234816-tom-ab-kimi-v2.json)

This run used the rule-based policy. All three touches stayed on email. Watch what the Practice API recorded at each step.

*2:25 · Show T1 and pause on the two API events.*

On touch one, the agent sends a speaker-profile email in German. The API records `link.opened`. Then comes a reply with a correction. Tom is Co-Founder and Co-CEO. He asks for the profile text by email. At this point, the record shows a link open and a reply.

*3:00 · Show T2 and pause on Tom’s reply.*

On touch two, the agent uses the corrected title and sends the profile lines in the same email thread. Tom replies that the title is now right and the two lines look good. The policy trace shows it chose to stay on email while the conversation was active.

*3:35 · Show T3 and point to `e_1970` in the event list.*

On touch three, the API records another link open, followed by `page.submitted`. The submission event lists an email field and a password field. That is the first confirmed incident in this session. The runner stops after the third touch. The event list lets you see exactly where the outcome changes from an open or a reply to a submitted form.

## 4:15–5:00 · What the API confirmed

*Keep the submission event visible.*

Across the recorded practice runs, we have one API-confirmed incident. It came from `--policy` on Tom, with a form submission at touch three. In our report, `confirmed_by_api_event=true` means the run contains an incident backed by a Practice API event. An LLM judge can estimate an outcome from a reply. Those estimates stay out of the confirmed incident count.

The persona-driven `--actor` is still under evaluation. One confirmed incident gives us a trace we can audit. A finding about which decision mode works better would require comparable API-confirmed runs.
