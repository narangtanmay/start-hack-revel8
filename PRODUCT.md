# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary: the START Hack jury judging the revel8 "Agentic Social Engineer" challenge. They see it projected or on a laptop during a short live pitch, so it has to read at a glance from across a room. Secondary: our own team, who open the same pages to check and debug practice runs.

## Product Purpose

The revel8 agent runs authorised social-engineering simulations against consenting practice targets with no human in the loop. It researches a target, casts a believable persona, and holds a multi-touch conversation over email, phone and chat until the target clicks, discloses or acts. The site makes that work visible: what the agent learned, what it said, how the target answered, and whether it reached an incident. Success means a judge walks away remembering a real conversation in which the agent talked a target into acting.

## Positioning

A "method actor" decision path: the agent stays in character across touches, keeps a notebook of what it has learned and which routes are closed, and adapts each message to the target's last reply. It is not a one-shot phishing template generator. Every run is a full, replayable conversation with the agent's reasoning beside each message.

## Operating Context

- Static HTML generated in Python by `uv run python -m revel8_agent.cli report`. Run state lives in `runs/*.json`, target research in `dossiers/*.json`.
- Pages today: overview (`index.html`), one page per run, `replay.html`, `score.html`, `how.html` and `research-<target>.html`.
- A public snapshot mode (`public=True`) redacts landing-page HTML.

## Capabilities and Constraints

- Channels: email, phone/voice and chat. Incidents are either confirmed by the revel8 API (submitted landing page, opened attachment) or estimated by an LLM judge. The site must keep that distinction visible.
- Counting rule: a run counts when it is finished and has at least one touch. Every page uses the same rule.
- Decision paths: method actor, shadow twin, rule policy, escalation controller and LLM planner.
- No build step or JS framework in the repo. Pages must open from disk (`file://`), and external libraries come only from CDN.

## Brand Commitments

- Name: revel8 (lowercase).
- The user set the direction for this site: white background, generous whitespace, clear sections, an Apple aesthetic, and "3D and cool" graphs.

## Evidence on Hand

- Real practice runs in `runs/` against the targets tom, julius and robert, with full transcripts, judge verdicts and incidents.
- Target research in `dossiers/`.
- Absent: customer logos, testimonials, benchmarks against competitors and pricing. These must not be invented.

## Product Principles

1. Show the conversation, not a claim about it.
2. Be honest about evidence: confirmed means confirmed and estimated is labelled as an estimate.
3. No human in the loop. Show the agent deciding, not a script.
4. Readable from across the room in a pitch, and still usable afterwards as a tool.
