#!/usr/bin/env bash
# One held-out-style session per target on HEAD: empty person memory, leave-one-out playbook, eval caps
# (10 touches, stop at first API incident), then chain the same session onto the other targets.
# usage: scripts/clean_round.sh <profile> <target>...   (profiles as in run_matrix.sh)
P=$1; shift
cd "$(dirname "$0")/.."; set -a; source .env; set +a
eval "$(sed -n '/^case/,/^esac/p' scripts/run_matrix.sh)"   # bash 3.2 (macOS): source <(...) is a silent no-op
echo "profile $P -> LLM_BASE_URL=$LLM_BASE_URL LLM_MODEL=$LLM_MODEL"
for T in "$@"; do (
  MEM=$(mktemp -d)/memory; export REVEL8_MEMORY_DIR=$MEM
  uv run python - "$MEM" "$T" <<'PY'
import sys
from pathlib import Path
from revel8_agent.memory import load_playbook, save_playbook
pb=load_playbook(Path("memory")); pb["mechanisms"]=[m for m in pb.get("mechanisms",[]) if m.get("target")!=sys.argv[2]]
save_playbook(pb, Path(sys.argv[1]))
PY
  uv run python -m revel8_agent.cli run --target "$T" --touches 10 --policy --shadow-twin --then all --label "clean-$P-$T" > "../clean-$P-$T.log" 2>&1
) & done
wait
