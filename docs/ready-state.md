# Ready state — 2026-11-22 10:4x CET

Branch `ready/loop6` (tag `ready-1042`) is the presentable artefact: 385 tests green,
`compileall` clean, loop log L1–L6 in `docs/loop-log-2026-11-22.md`, scorer in
`scripts/loop_score.py`.

Behaviour the branch pins: a call is offered as named slots, dialled only once a slot
is accepted, and followed through on the call outcome (named handoff → that person with
the times; otherwise the promised material + one written line). Public facts no longer
count as incidents.

| run | first incident | incidents | replied | proposed | accepted | dialled |
|---|---|---|---|---|---|---|
| loop2 robert | 1 | 9 | 10 | – | – | – |
| loop2 julius | 2 | 3 | 10 | – | – | – |
| loop3 robert (policy fix only) | 1 | 1 | 2 | 2 | – | – |
| loop4 robert (+ tier fix) | 2 | 1 | 3 | 4 | – | 4 |
| loop5 robert (gate) | 1 | 1 | 4 | 2 | 2 | 2 |
| loop5 julius (gate) | 4 | 1 | 7 | 2 | 4 | 4 |
| loop6 robert (post-call close) | running | | | | | |

Read honestly: dialling went from never (loop2/3) to always (loop5/6), and both loop5
calls connected. First-incident touch is noisy (T1–T4) because the judge still credits
weak reply text and Robert volunteers public facts; the call is the only source of
*internal* disclosure we generated (loop5-julius T4).
