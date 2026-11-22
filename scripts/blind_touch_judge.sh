#!/usr/bin/env bash
# Blind per-touch judge: marks GENERAL failure types in run JSONs (no team context, no message writing).
# Usage: scripts/blind_touch_judge.sh <report.md> <run.json> [run.json ...]
# Model: AGY Gemini Neon medium, headless, read-only except the report.
set -euo pipefail
out="$1"; shift
files=$(printf -- '- %s\n' "$@")
prompt=$(cat <<EOF
You are a blind quality judge for a university hackathon (START Hack 2026, revel8 challenge): an agent runs *simulated*
security-awareness campaigns against consenting AI twins inside revel8's organiser API (no real people). You have never
seen the team's discussion. Judge ONLY from these run JSON files:
$files
For each run, go touch by touch (steps[]: action.channel, payload.subject/body/attachments, page (a sign-in link was sent),
transcript (calls), events (replies and API events: link.opened, page.submitted, attachment.opened)).
Mark every touch with zero or more of these GENERAL codes, each with a quote of at most 12 words from the target's
earlier reply or the agent's own message as evidence:
- A1 ARTIFACT_MISMATCH: the artifact sent is not the type the target asked for (e.g. asked for a calendar invite, got a PDF).
- A2 UNASKED_ARTIFACT: a file or sign-in link sent before the target asked for it or had reason to expect it.
- R1 REFUSAL_IGNORED: the target refused something in ANY wording (won't sign in/register/open, didn't open, not by email)
  and a later touch did it again.
- S1 MISREAD_SIGNAL: a move (call, link, escalation, new channel) justified by a signal the target did not give
  (a call merely mentioned is not an invitation to call).
- D1 REDIRECT_IGNORED: the target handed the matter to another person or department and the agent kept pursuing the same
  ask with the target instead of changing approach.
- C1 CONTRADICTION: the agent's message contradicts an earlier message (dates, claims about access or a page).
- P1 PROMISE_UNKEPT: the target is waiting for something the agent promised or the target requested, and the next touch
  does not deliver it.
- Q1 QUESTION_IGNORED: the target asked a direct question the next touch does not answer.
Do NOT write, rewrite or suggest any message wording, persona or pretext. Do not edit anything except the report.
Do not read .env or secrets, do not call any API, do not run anything.
Report (under 90 lines): (1) per run a table: touch | codes | evidence | API events; (2) code counts per run;
(3) SYSTEMIC: codes that recur across runs or targets (the general failures to fix), each with the runs it occurs in;
(4) touches that were clean and preceded an API event (what NOT to break). Write the report to: $out
EOF
)
cd /home/tanmay/Desktop/START_hack
agy -p "$prompt" --model gemini-4-neon-medium --effort medium --dangerously-skip-permissions --sandbox \
  --add-dir /home/tanmay/Desktop/START_hack-eval --add-dir /home/tanmay/Desktop/START_hack-exp --print-timeout 0
