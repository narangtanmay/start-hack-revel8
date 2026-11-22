#!/usr/bin/env bash
# Eval rehearsal: 3 sessions on one target with a FRESH memory dir, 10 touches each, stop at first API incident.
# Measures whether deja-vu memory makes session 2/3 convert faster than session 1.
# usage: scripts/eval_sim.sh <target> [label]
set -u
T=$1; L=${2:-sim}; MEM=$(mktemp -d)/memory; export REVEL8_MEMORY_DIR=$MEM
echo "memory: $MEM"
for i in 1 2 3; do
  uv run python -m revel8_agent.cli run --target "$T" --touches 10 --policy --shadow-twin --label "$L-s$i" 2>&1 | tail -4
  uv run python - "$MEM" "$i" <<'PY'
import json,glob,sys
for f in glob.glob(sys.argv[1]+'/targets/*.json'):
    s=json.load(open(f))['sessions'][-1]
    print(f"SESSION {sys.argv[2]}: touches={s['touches']} replies={s['reply_rate']} incidents={s['incidents']}")
PY
done
