# Self-hosted LLM benchmark — 2026-11-21

Same prompt everywhere: an engine-style decision call ("pick the next touch, return JSON", about 60–90 output
tokens in JSON mode). 3 calls one after another, then 6 at the same time (the swarm runs up to 6 sessions).
Raw results: [`docs/benchmarks/`](benchmarks/). Reproduce with `scripts/bench_endpoint.py`.

## TL;DR

| endpoint | model | median call (JSON mode) | single-stream tok/s | 6 parallel: wall | cost |
|---|---|---|---|---|---|
| Token Factory | DeepSeek-V4-Flash | **2.3 s** | **93** | 17.9 s (queued) | ~0.00025 pt/call (1 pt/day cap) |
| Self-host, **4× gfx1100, TP=4** | Qwen3-32B **BF16** | **5.0 s** | 19.7 | **5.3 s** | 4 pt/h |
| Self-host, 1× gfx1100 | Qwen3-32B AWQ 4-bit | 18.1 s | 3.9 | 20.8 s | 1 pt/h |

Not counting cold start: **4 GPUs answer in about 5 s, 1 GPU (AWQ) in about 18 s, Token Factory in about 2.3 s.**
With 6 calls at once, the 4-GPU server is **3.4× faster than Token Factory** (5.3 s against 17.9 s), because vLLM
batches them together while Token Factory queues them on one key.

## Instance timelines (UTC)

**Run A: 1 GPU, Model API, One-click pool, Qwen3-32B-AWQ**

| event | time | elapsed |
|---|---|---|
| Launch clicked (auto-delete 2 h) | 21:00:07 | 0:00 |
| Weights downloaded and loaded (18.36 GiB, 69 s) | 21:02:57 | 2:50 |
| API up (after torch.compile / graph capture) | 21:05:54 | **5:47** |
| Benchmark | 21:07:19 → 21:08:35 | 1:16 |
| Destroyed | 21:08:55 | 8:48 |

**Run B: 4 GPUs, Model API + Custom Model, Hackathon pool, Qwen3-32B BF16, `--tensor-parallel-size 4`**

| event | time | elapsed |
|---|---|---|
| Launch clicked (no auto-delete on this pool) | 21:31:06 | 0:00 |
| 4 TP workers up | 21:32:13 | 1:07 |
| Weights loaded (15.54 GiB per GPU, 126 s incl. download) | 21:34:20 | 3:14 |
| KV cache 26.66 GiB/GPU = **436,784 tokens**; graph capture 7 s | 21:35:27 | 4:21 |
| API up | 21:35:28 | **4:22** |
| Benchmark (JSON mode, then plain) | 21:36:16 → 21:37:52 | 1:36 |
| Destroyed | 21:38:05 | 6:59 |

Points: 48 → 47 (run A) → 43 (run B). Every started hour is billed in full.

## Hardware (from rocm-smi on the instance)
- GPU: `gfx1100` (RDNA3), **48 GiB VRAM per GPU** (51,522,830,336 B), card model 0x744b.
- 4-GPU topology: every pair is linked over **PCIe** (weight 40, 2 hops), with **no XGMI/Infinity Fabric**, all on NUMA node 1.
  "Shared memory" here means tensor parallel: each GPU holds 1/4 of the weights and they all-reduce over PCIe.
- Sizes: 1 GPU / 55 GB / 1 pt/h · 2 GPUs / 110 GB / 2 pt/h · 4 GPUs / 220 GB / 4 pt/h.

## Pools
- **One-click** (default): the 2- and 4-GPU sizes were full from 21:00 to 21:25 UTC; a 4-GPU launch queued 7+ min.
- **Hackathon**: 4 GPUs were free. To select it in **Model API**, click **Custom Model** first, which unlocks the
  Resource pool dropdown (it also appears under Notebook + Customize). **Auto-delete is fixed at "Never"**, so destroy the instance by hand.

## Results in detail

| run | median TTFT | median call | tok/s | 6 parallel wall | aggregate tok/s | JSON valid |
|---|---|---|---|---|---|---|
| Token Factory, DeepSeek-V4-Flash, JSON | 1.27 s | 2.29 s | 93.4 | 17.88 s | 30.6 | 9/9 |
| 1× GPU, Qwen3-32B-AWQ, JSON | 1.03 s | 18.13 s | 3.9 | 20.77 s | 18.3 | 9/9 |
| 4× GPU TP4, Qwen3-32B BF16, JSON | 0.60 s | **5.03 s** | 19.7 | **5.27 s** | 67.6 | 9/9 |
| 4× GPU TP4, Qwen3-32B BF16, no JSON mode | 0.42 s | 17.56 s | 19.3 | 22.81 s | 89.8 | 9/9 |

## Conclusions
1. **4 GPUs with BF16 are about 5× faster per token than 1 GPU with AWQ** (19.7 against 3.9 tok/s). Most of that is dropping
   AWQ (slow Triton kernels on RDNA3), plus 4× the memory bandwidth. PCIe-only tensor parallel still works fine.
2. **Keep JSON mode on.** Generation speed is the same (19.3 against 19.7 tok/s), so guided decoding costs nothing, and it
   stops Qwen3 from writing a `<think>` block (about 330 tokens) first, which made replies **3.5× faster** (5 s against 17.6 s).
3. **The self-hosted server wins under concurrency.** 6 parallel calls take about one call's time (5.3 s), while Token
   Factory queues them on one key (17.9 s). For the swarm (up to 6 sessions), the 4-GPU server is faster overall.
   For one call at a time, Token Factory is still faster (2.3 s against 5.0 s).
4. **Capacity left over.** With 32B BF16 on 4 GPUs, each GPU still has 26.66 GiB free for KV cache (437k tokens total), so
   a ~70B BF16 model (~140 GB) would fit with a smaller cache. Expect roughly half the speed (about 10 tok/s).
5. **Token Factory cap:** 1 pt/day per account, about 0.00025 pt per call, so about 4,000 calls/day per account.
6. **Recommendation:** Token Factory by default, since it costs no instance points. For the eval window, or heavy parallel swarm runs, a
   4-GPU Hackathon-pool instance (ready in about 4.5 min, 4 pt/h) is a real speed-up. Switch with
   `scripts/llm_switch.py selfhost …` and run swarm with `--max-parallel 6`. Remember to destroy it, since there is no auto-delete.
