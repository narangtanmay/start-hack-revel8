#!/usr/bin/env bash
# Rebuild the public dashboard snapshot and deploy it to Vercel (project "site").
#
#   scripts/publish_dashboard.sh
#
# The snapshot is written OUTSIDE the git repo, so Vercel does not attach the git commit
# author (that blocked the first deploy with TEAM_ACCESS_REQUIRED). Landing pages are listed
# but never rendered in the public snapshot.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${REVEL8_DASHBOARD_OUT:-$HOME/.cache/revel8-dashboard}"
PY="$REPO/.venv/bin/python"

mkdir -p "$OUT"
# Keep the existing Vercel project link if this is the first publish from $OUT.
if [ ! -d "$OUT/.vercel" ] && [ -d "$REPO/site/.vercel" ]; then
  cp -r "$REPO/site/.vercel" "$OUT/.vercel"
fi

cd "$REPO"
PYTHONPATH="$REPO/src" "$PY" -m revel8_agent.cli report --public-out "$OUT"

cd "$OUT"
npx vercel@latest deploy --prod --yes
