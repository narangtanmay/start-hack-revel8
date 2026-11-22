---
version: 1
slug: "runs-index-html"
primary_target: "runs/index.html"
related_targets: ["src/revel8_agent/report.py","src/revel8_agent/report_replay.py","src/revel8_agent/report_pages.py"]
---

# Surface: revel8 site (landing page + dashboard)

Scope: the generated site under runs/: landing page (index.html), runs overview (runs.html), run pages, replay, score, how it works, research. Mode: Persuade for the landing page; Operate/Read for the dashboard pages, which inherit the same world.

Audience: START Hack jury, watching a projected pitch. Job: understand within seconds that the agent holds a real conversation by itself. Action: play the conversation. Proof: real practice runs in runs/*.json. Constraint: confirmed and estimated incidents stay visibly distinct, and nothing is invented. Pinned by the user: white background, generous whitespace, clear sections, Apple aesthetic, 3D graphs.

Memorable moment: the playhead moving along a run's 3D score while the actual messages appear above it.

## Direction contract

THESIS: every run is written as a score. Each channel and the target's replies get their own staff, and a playhead reads the run along its long axis. This replaces the category default of a security-SaaS split hero with feature cards.

OWN-WORLD: a white ground with #1d1d1f ink and #6e6e73 secondary text. Hairline staves; notes are rounded blocks. The agent's notes are ink and the target's replies are pale blue. Colour appears only at the active edge: blue #0071e3 for the playhead and primary action, amber #ff9f0a only for incidents (solid when confirmed, outlined when estimated). The score tilts into CSS 3D depth. The display type is a tight sans set very large, and no cards serve as page structure.

STORY: the visitor reads one real headline, presses Play, watches the agent's messages and the target's replies arrive touch by touch, and sees where the incident landed and whether it is confirmed. They then sweep every run as a stack of identical scores and leave believing there was no human in the loop.

FIRST VIEWPORT: the nav sits at the top. On the left is a 76–96px headline written from the featured run, with one line of lede and "Play the conversation" (primary, blue pill) plus "See all runs". Below, the featured run's 3D score runs full width with its staves labelled and the playhead on touch 1. Pressing Play scrubs inline and shows the current message above the score.

FORM: candidate 7 of 7 (orchestral score), seed:b5160d04bda25e49. Raises:
- (character sheet) selecting a channel lights its staff;
- (cabaret bill) advance one touch at a time, played touches marked;
- (cloud edge) colour only at the active edge;
- (indoor sun) one continuous horizontal band;
- (VU bridge) identical stacked scores read in one sweep.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
