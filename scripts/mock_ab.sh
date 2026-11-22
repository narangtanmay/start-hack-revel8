#!/usr/bin/env bash
# Offline A/B: the controller policy vs. the LLM-only policy against the mock target,
# with a lightweight local model, then score both sets with the rubric benchmark.
#
#   scripts/mock_ab.sh [touches] [outdir]
#
# Uses the LLM from .env (Token Factory). For a fully local run:
#   LLM_BASE_URL=http://localhost:11434/v1 LLM_MODEL=qwen2.5:3b LLM_API_KEYS= LLM_API_KEY= scripts/mock_ab.sh
# Spends no API touches. Results: runs/mock_ab/{controller,llm}/*.json
set -uo pipefail
cd "$(dirname "$0")/.."
TOUCHES="${1:-6}"
OUT="${2:-runs/mock_ab}"
rm -rf "$OUT"; mkdir -p "$OUT/controller" "$OUT/llm"

for policy in controller llm; do
  for target in julius tom robert; do
    uv run python -m revel8_agent.cli run --mock --target "$target" --decider "$policy" --seed 7 \
      --touches "$TOUCHES" --runs-dir "$OUT/$policy" > "$OUT/$policy/$target.log" 2>&1 &
  done
done
wait

uv run python -m revel8_agent.benchmark "$OUT/controller" --vs "$OUT/llm" --labels controller llm-only
