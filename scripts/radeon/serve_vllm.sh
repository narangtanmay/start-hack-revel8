#!/usr/bin/env bash
# Serve one model across all GPUs of an AMD Radeon Cloud instance with vLLM (tensor parallel),
# behind an OpenAI-compatible API the agent can use as LLM_BASE_URL.
#
# Run ON THE INSTANCE (Base image: ROCm + PyTorch + vLLM preinstalled):
#   bash serve_vllm.sh                      # default preset (qwen3-32b), all GPUs
#   bash serve_vllm.sh llama-70b            # another preset
#   bash serve_vllm.sh org/any-hf-model     # any Hugging Face model id
#   TP=2 PORT=8001 bash serve_vllm.sh ...   # overrides
#
# Keep it alive after you close the Jupyter terminal:
#   nohup bash serve_vllm.sh qwen3-32b > vllm.log 2>&1 &   then: tail -f vllm.log
#
# Env overrides: TP, PORT, MAX_MODEL_LEN, GPU_UTIL, MAX_SEQS, SERVED_NAME, VLLM_API_KEY,
#                HF_TOKEN (gated models such as Llama), HF_HOME (where weights are cached).
set -euo pipefail

PRESET="${1:-qwen3-32b}"
case "$PRESET" in
  qwen3-32b)     MODEL="Qwen/Qwen3-32B";                      NAME="qwen3-32b";      LEN=32768 ;;  # ~64 GB BF16, safest choice
  llama-70b)     MODEL="meta-llama/Llama-3.3-70B-Instruct";   NAME="llama-3.3-70b";  LEN=16384 ;;  # ~140 GB BF16, needs HF_TOKEN, tight on 4x48 GB
  gpt-oss-120b)  MODEL="openai/gpt-oss-120b";                 NAME="gpt-oss-120b";   LEN=32768 ;;  # ~65 GB MXFP4; ROCm/Radeon support is newer, test first
  */*)           MODEL="$PRESET"; NAME="$(basename "$PRESET" | tr '[:upper:]' '[:lower:]')"; LEN=16384 ;;
  *) echo "Unknown preset '$PRESET'. Use qwen3-32b | llama-70b | gpt-oss-120b | <hf-org>/<model>" >&2; exit 2 ;;
esac
NAME="${SERVED_NAME:-$NAME}"
LEN="${MAX_MODEL_LEN:-$LEN}"
PORT="${PORT:-8000}"

echo "== GPUs ==================================================="
if command -v rocm-smi >/dev/null; then
  rocm-smi --showproductname --showmeminfo vram 2>/dev/null || rocm-smi
  echo "-- topology (how the GPUs talk to each other) --"
  rocm-smi --showtopo 2>/dev/null | sed -n '1,40p' || true
fi
NGPU="$(python3 -c 'import torch; print(torch.cuda.device_count())')"
TP="${TP:-$NGPU}"
echo "visible GPUs: $NGPU  -> tensor-parallel size: $TP"
if [ "$NGPU" -lt 1 ]; then echo "No GPU visible to PyTorch." >&2; exit 1; fi
if [ "$TP" -gt "$NGPU" ]; then echo "TP=$TP but only $NGPU GPU(s) visible." >&2; exit 1; fi

# One API key per server, kept across restarts so .env stays valid.
KEY_FILE="$HOME/.vllm_api_key"
if [ -n "${VLLM_API_KEY:-}" ]; then
  API_KEY="$VLLM_API_KEY"
elif [ -s "$KEY_FILE" ]; then
  API_KEY="$(cat "$KEY_FILE")"
else
  API_KEY="sk-local-$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
  umask 077; printf '%s' "$API_KEY" > "$KEY_FILE"
fi

cat <<EOF
== Serving ===============================================
model:        $MODEL
served name:  $NAME   (this is your LLM_MODEL)
port:         $PORT
api key:      saved in $KEY_FILE   (cat it to copy into .env)
max context:  $LEN tokens

When the log says "Application startup complete", on your laptop run:
  uv run python scripts/llm_switch.py selfhost --url http://<instance-host>:$PORT/v1 --key <key> --model $NAME
  uv run python scripts/check_llm.py
===========================================================
EOF

# --enable-prefix-caching: the engine resends the same long system prompts every touch.
# --max-num-seqs: up to 6 Revel8 sessions + OSINT extraction in parallel, batched on one server.
exec vllm serve "$MODEL" \
  --served-model-name "$NAME" \
  --tensor-parallel-size "$TP" \
  --host 0.0.0.0 --port "$PORT" \
  --api-key "$API_KEY" \
  --max-model-len "$LEN" \
  --gpu-memory-utilization "${GPU_UTIL:-0.90}" \
  --max-num-seqs "${MAX_SEQS:-16}" \
  --enable-prefix-caching
