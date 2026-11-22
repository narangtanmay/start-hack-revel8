# revel8 — pitch site

Static, self-contained build of the revel8 pitch site. No build step, no
server required: every asset is bundled and referenced by a relative path.

## Pages

| File | What it is |
|---|---|
| `index.html` | Landing page: the pitch, plus a **scripted live demo** of the agent running a sample simulation (no real target, no practice results). |
| `architecture.html` | **System architecture**: the "method actor inside a deterministic guardrail shell", a 3D shadow-block pipeline, and an interactive **"whole machine"** diagram — hover any station to lift it, highlight it, and read what it does. |

## Assets

- `three.min.js` — self-hosted three.js (r128) for the 3D backdrop; works offline and from `file://`.
- `fonts/` — self-hosted Wix Madefor Display/Text (woff2).

## View it

**Open directly** — double-click `index.html` (or `architecture.html`). It
runs from `file://`: the 3D backdrop, fonts and interactions all work.

**Serve locally** (optional):

```bash
cd site
python3 -m http.server 8777
# http://localhost:8777/index.html
```

**Share a link** — enable GitHub Pages (repo → Settings → Pages → deploy from
`main`), then the pages are at `…/site/index.html` and `…/site/architecture.html`.

## Notes

- These pages are **generated** from `src/revel8_agent/report.py`
  (`uv run python -m revel8_agent.cli report`). Edit the Python, not the HTML.
- Deliberately shows **no practice results** — the demo is an illustrative
  sample, labelled as such.
