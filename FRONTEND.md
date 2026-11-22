# Frontend redesign (branch `frontend`)

**Goal:** turn the generated dashboard (`runs/*.html`) into a modern agentic product site: white background, lots of whitespace, clear sections, Apple aesthetic, 3D graphs.

**Skill used:** [impeccable](https://github.com/pbakaus/impeccable), installed at `.claude/skills/impeccable` (agents in `.claude/agents`). Product context is in `PRODUCT.md`; the chosen direction ("The Score") is in `.impeccable/surfaces/runs-index-html.md`.

## Direction
Every run is drawn as a score: one staff per channel, the target's replies on their own staff, and a playhead. Colour appears only at the active edge: blue for the playhead and primary action, amber for an incident (solid when API-confirmed, outlined when it is our judge's estimate). Graphs are CSS 3D (perspective), no library.

## What is in this branch
| File | State |
|---|---|
| `src/revel8_agent/report_style.py` | New white/Apple stylesheet, shared by every page. Wired in. Fonts are self-hosted from `src/revel8_agent/assets/fonts/` (Wix Madefor Display/Text). |
| `src/revel8_agent/report_home.py` | New landing page and the 3D score / 3D bar chart. **Not wired in yet.** |
| `src/revel8_agent/report.py`, `report_pages.py`, `report_replay.py` | Dashboard pages from earlier work (light-first theme, estimate vs confirmed incidents, replay). `report.py` now imports its CSS from `report_style.py`. |
| `PRODUCT.md`, `.impeccable/config.json`, `.impeccable/surfaces/` | impeccable context. |

## Not finished
- `render_index` does not call `render_home` yet: `index.html` is still the old overview. The plan is landing page at `index.html`, the table at `runs.html`, and a nav update in `_page`.
- `render_home` needs a `stats` dict (`bars`, `sentences`) built from `scorecard.compute`.
- The page files' fonts path (`fonts/…`) must be copied next to the generated HTML.
- Nothing has been looked at in a browser or run through impeccable's `shot` / `detect` / finish review. Run/replay/research/score pages were not restyled beyond the shared stylesheet.
- The 5 report tests pass; the new modules have no tests.

## Run
`uv run python -m revel8_agent.cli report --open`
