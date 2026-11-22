#!/usr/bin/env bash
# Point the agent's LLM at Kimi K3.1 Pro on NVIDIA's hosted API (build.nvidia.com), for this shell only.
#
#   source scripts/use_kimi_nvidia.sh            # then run the agent as usual, e.g.
#   python -m revel8_agent.cli run --target tom --policy --touches 10
#
# Needs NVIDIA_API_KEY in .env (or the environment). The DeepSeek / Token Factory settings in .env stay untouched;
# open a new shell (or unset these variables) to go back to them.
_repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -z "${NVIDIA_API_KEY:-}" ] && [ -f "$_repo/.env" ]; then
  NVIDIA_API_KEY="$(grep -E '^NVIDIA_API_KEY=' "$_repo/.env" | tail -1 | cut -d= -f2-)"
fi
if [ -z "${NVIDIA_API_KEY:-}" ]; then
  echo "NVIDIA_API_KEY is not set (add NVIDIA_API_KEY=nvapi-... to .env)" >&2
  return 1 2>/dev/null || exit 1
fi
export LLM_BASE_URL="https://integrate.api.nvidia.com/v1"
export LLM_MODEL="moonshotai/kimi-k3.1-pro"
export LLM_API_KEY="$NVIDIA_API_KEY"
export LLM_API_KEYS="$NVIDIA_API_KEY"      # the pool prefers LLM_API_KEYS; one NVIDIA key here
export LLM_EXTRA_BODY='{"stream": false}'  # NVIDIA streams by default; the client expects one JSON response
export LLM_REASONING=0                     # endpoint default reasoning_effort is "low" (accepted: low|high|max)
export LLM_RPM_PER_KEY="${LLM_RPM_PER_KEY:-35}"
unset LLM_FALLBACK_MODEL
echo "LLM -> $LLM_MODEL @ $LLM_BASE_URL (key ${NVIDIA_API_KEY:0:6}…)"
