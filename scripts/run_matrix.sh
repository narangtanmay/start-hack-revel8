#!/usr/bin/env bash
# One 3-session eval rehearsal per (target, model profile). usage: scripts/run_matrix.sh <profile> <target>...
# profiles: ds (Token Factory DeepSeek-V4.1-Flash), qwen (Token Factory Qwen3.8-27B), self (self-hosted abliterated Qwen)
P=$1; shift
cd "$(dirname "$0")/.."; set -a; source .env; set +a
case $P in
  ds)   export LLM_MODEL=DeepSeek-V4.1-Flash LLM_REASONING=0 ;;
  qwen) export LLM_MODEL=Qwen3.8-27B LLM_REASONING=0 LLM_EXTRA_BODY='{"chat_template_kwargs":{"enable_thinking":false}}' ;;
  self) export LLM_BASE_URL=${SELF_LLM_BASE_URL:?} LLM_MODEL=${SELF_LLM_MODEL:?} LLM_API_KEY=${SELF_LLM_API_KEY:?} \
               LLM_API_KEYS=${SELF_LLM_API_KEY:?} LLM_REASONING=0 LLM_EXTRA_BODY='{"chat_template_kwargs":{"enable_thinking":false}}' ;;
  kimi) export LLM_BASE_URL=$KIMI_BASE_URL LLM_MODEL=$KIMI_MODEL LLM_API_KEY=$KIMI_API_KEY LLM_API_KEYS=$KIMI_API_KEY LLM_JSON_MODE=0 ;;  # PAID: only with explicit permission
  *) echo "unknown profile $P"; exit 1 ;;
esac
cd "$(dirname "$0")/.."
for T in "$@"; do scripts/eval_sim.sh "$T" "sim-$T-$P" > "../sim-$T-$P.log" 2>&1 & done
wait
