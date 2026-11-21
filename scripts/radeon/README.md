# Self-hosting the agent's LLM on AMD Radeon Cloud (multi-GPU)

> **Measured 2026-11-21** (see `docs/selfhost-benchmark-2026-11-21.md`): GPUs are gfx1100 (RDNA3), 48 GiB each,
> 1 pt per GPU-hour (instance pts). Token Factory has its own 1 pt/day cap, but 104 calls used only 0.026 pt (about 4k calls/day). Qwen3-32B-AWQ on 1 GPU managed only ~4 tok/s, against
> ~93 tok/s for Token Factory DeepSeek-V4-Flash. Avoid AWQ on these GPUs and prefer BF16 with tensor parallel.
> The easiest path is the console's **Model API** deploy type: paste a `vllm serve ...` command
> and it returns an HTTPS endpoint plus an API key (ready in about 6 minutes).

Token Factory gives one credit a day. Instead, rent a 1/2/4-GPU instance and serve
your own model with vLLM; the agent only needs an OpenAI-compatible URL.

**Tensor parallel, not shared memory.** Each GPU keeps its own VRAM. With
`--tensor-parallel-size 4`, vLLM gives each GPU a quarter of the weights, so you
can fit roughly 4× one card's VRAM. The GPUs sync over the bus on every token, so one
stream is slower than on one big card; for this agent's few calls per touch that's fine.

One server on all GPUs beats one server per agent: vLLM batches concurrent requests,
so all swarm sessions + OSINT share one big model.

## 1. Check billing first
Check in the console whether a GPU instance spends the same daily credit as Token
Factory, and how fast a 4-GPU instance burns it. Start with 1–2 GPUs if unsure.

## 2. Start the instance
Console → Deploy type **Notebook**, size **4 GPUs**, image **Base** (ROCm 7.2.1, vLLM 0.16.1).
(Also try **Model API** first — if it offers the model you want, it gives you an
endpoint without this script.)

## 3. Serve the model (on the instance, in a Jupyter terminal)
Upload `serve_vllm.sh`, then:

```bash
nohup bash serve_vllm.sh qwen3-32b > vllm.log 2>&1 &
tail -f vllm.log          # wait for "Application startup complete"
cat ~/.vllm_api_key       # the key for .env
```

The script prints the GPU model, VRAM and topology first. Read those lines before picking a bigger preset.

| preset         | weights      | fits on               | note |
|----------------|--------------|-----------------------|------|
| `qwen3-32b`    | ~64 GB BF16  | 2× 48 GB              | default, best-supported |
| `llama-70b`    | ~140 GB BF16 | 4× 48 GB (tight)      | gated: `export HF_TOKEN=...` |
| `gpt-oss-120b` | ~65 GB MXFP4 | 2× 48 GB              | newer on ROCm/Radeon — test first |
| `org/model`    | any HF id    | —                     | set `MAX_MODEL_LEN`, `SERVED_NAME` as needed |

Download time: weights download on first start (tens of GB). Do it well before the eval.

## 4. Reach it from your laptop
The server listens on `0.0.0.0:8000`. You need a URL your laptop can reach: an exposed
port or proxy from the console, if the console provides one. If nothing is exposed, use
the **Model API** deploy type instead, or a tunnel you trust.

## 5. Point the agent at it
```bash
uv run python scripts/llm_switch.py selfhost --url http://<host>:8000/v1 --key <key> --model qwen3-32b
uv run python scripts/check_llm.py               # served name, JSON mode, parallel batching
uv run python -m revel8_agent.swarm --all --max-parallel 6
uv run python scripts/llm_switch.py tokenfactory  # switch back any time
uv run python scripts/llm_switch.py status
```

`--max-parallel` matters: with one self-hosted key the swarm otherwise runs one
session at a time (by default it allows one worker per key).

Stop the instance when you're done; it costs credits while it runs.
