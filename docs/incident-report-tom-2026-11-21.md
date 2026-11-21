# First API-Confirmed Incident & A/B Progression — 2026-11-21

**Run type:** REAL (live Revel8 Practice API; all incidents strictly `confirmed_by_api_event: true`)
**Branch / Commit:** `feat/shadow-twin-engine` @ `4b69b90` (`186/186` pytest passing)
**Target:** `tom` (Co-Founder & Co-CEO, revel8) — Session `s_1cb26ff20b`
**Local Replay Artifacts (gitignored `runs/`):**
- `runs/20261121-234816-tom-ab-kimi-v2.html`
- `runs/20261121-234816-tom-ab-kimi-v2.json`

## A/B Progression on `tom` (Practice, 10-Touch Budget)

| Arm | Model | Policy & Fixes | Plan Schema | Reply Rate | API-Confirmed Incident | First Touch | Est. Results (/25) | Key Finding |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Baseline** (`224051-tom`) | `DeepSeek-V4-Flash` | `--no-policy`, old `timing()` | Valid | Low | No | — | `0.0` | Past Jan 2026 hooks labeled `current`; garbled tokens (`"Skip"`/`"UTE"`). |
| **Arm A** (`232014-tom-ab-ds-policy`) | `DeepSeek-V4-Flash` | `--policy` (v1), early `STOP` | `hook=None, obj=None` | `3 / 6` | No | — | `0.0` | Pitched Jan 2026 again; invented `"Sarah Klein"`; stopped at T7. |
| **Arm B v1** (`232318-tom-ab-kimi-policy`) | `succ-zero` (Kimi K3.1 Pro) | `--policy` (v1) | `hook=h3, obj=action` | `10 / 10` | No | — | `0.0` | 100% reply rate in German; missed T9 due to cross-turn contradiction (*"you said no attachment needed"*). |
| **Arm B v2** (`234816-tom-ab-kimi-v2`) | `succ-zero` (Kimi K3.1 Pro) | `--policy` + `dfbc4fa` + `4b69b90` | `hook=h3, obj=credentials` | `2 / 3` + submit | **YES (`credentials`)** | **3** | **`23.3`** | `timing()` stamped Jan 2026 hooks `PAST` → picked upcoming 2027 `h3` → **`page.submitted` at T3**. |

## Turn-by-Turn Proof (`s_1cb26ff20b`, `tom`)

- **Plan:** `hook=h3` (`Cybersicherheitsforschung 2027`, upcoming), `objective=credentials`, persona `Mara Lenzen` (`Nordstern Research Events`, `cyberforschung-speakerhub.de`), uploaded brand logo `a_505960dc36`.
- **Touch 1 (`STAY`, email):** Clean German speaker-check email → API event `link.opened` (`https://cyberforschung-speakerhub.de/session/startups-takeoff`) + reply correcting title to Co-Founder & Co-CEO.
- **Touch 2 (`STAY`, email):** Clean follow-up applying his exact title correction → reply confirming the two profile lines.
- **Touch 3 (`STAY`, email):** Clean final confirmation → API events:
  - `e_1969`: `link.opened` (`https://cyberforschung-speakerhub.de/session/startups-takeoff`)
  - `e_1970`: `page.submitted` (`page_id: p_274558d7e9`, `fields: ["email", "password"]`, `values: {"email": "tom@revel8.ai", "password": "(entered, not shown)"}`)
- **Result:** `confirmed_by_api_event: true`, `touches_used: 3`, **`results_points: 23.3 / 25`**, session closed immediately after first confirmed incident.

## Additional Live Verification (`julius` partial run, cancelled at T4 to preserve credit)

- On `runs/20261121-235451-julius-ab-kimi-v2.html`, the new cross-turn commitment gate (`validate_session_consistency()` in `src/revel8_agent/gate.py`) fired live at T2:
  `draft rejected by gate: Cross-turn contradiction: an earlier message attached a file but this draft claims no attachment.`
- Run was manually stopped at T4 after Julius directed inquiries to the press address, preserving `$4.72` `succ.ai` balance for Sunday eval runs.
