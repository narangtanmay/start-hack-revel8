# Self-hosted LLM benchmark — 2026-11-21

Same prompt for both: an engine-style JSON-mode decision call (about 60–90 output tokens).
3 calls one after another, then 6 at the same time (the swarm runs up to 6 sessions).
Raw results: [`docs/benchmarks/`](benchmarks/). Reproduce with `scripts/bench_endpoint.py`.

## Instance timeline (UTC)

| event | time | elapsed |
|---|---|---|
| Launch clicked (Model API, 1 GPU, auto-delete 2 h) | 21:00:07 | 0:00 |
| GPU detected, vLLM 0.16.1 starting | 21:00:29 | 0:22 |
| Weights downloaded and loaded (18.36 GiB, 69 s) | 21:02:57 | 2:50 |
| torch.compile / graph capture finished, API up | 21:05:54 | 5:47 |
| Benchmark start → end | 21:07:19 → 21:08:35 | 1:16 |
| Instance destroyed | 21:08:55 | 8:48 |

Cost: **1 pt** (48 → 47). Every started hour is billed, so a short test still costs a full hour.

## Hardware (from rocm-smi on the instance)
- GPU: `gfx1100` (RDNA3), **48 GiB VRAM per GPU** (51,522,830,336 B), card model 0x744b
- Sizes offered: 1 GPU / 55 GB / 1 pt/h · 2 GPUs / 110 GB / 2 pt/h · 4 GPUs / 220 GB / 4 pt/h
- In the **One-click** pool, the 2- and 4-GPU sizes were **full** from 21:00 to 21:25 UTC (a 4-GPU launch sat
  queued at #1 of 1 for 7+ min and was cancelled), so tensor parallel over several GPUs is **not tested yet**.
- There is a separate **Hackathon** pool where 4 GPUs showed *Available*. It is only selectable as
  **Notebook + Customize** (Model API is locked to One-click), and it has **no auto-delete** (fixed at "Never"),
  so the instance must be destroyed by hand.

## Results

Response time once the model is loaded (no cold start): self-hosted **~18 s per ~65-token reply**, Token Factory **~2.3 s**.

| endpoint | model | median TTFT | median call | single-stream tok/s | 6 parallel: wall | 6 parallel: aggregate tok/s | JSON valid |
|---|---|---|---|---|---|---|---|
| Token Factory (free) | DeepSeek-V4-Flash | 1.27 s | **2.3 s** | **93** | 17.9 s | 30.6 | 9/9 |
| Self-host, 1× gfx1100 | Qwen3-32B-AWQ (4-bit) | 1.03 s | 18.1 s | **3.9** | 20.8 s | 18.3 | 9/9 |

## Conclusions
1. **Token Factory is about 8× faster per call, and its daily cap goes a long way.** It has a separate
   *daily model cap* of 1 pt per account (resets daily, separate from the 48 instance pts). Measured: 104
   DeepSeek-V4-Flash requests used 0.0256 pt, about 0.00025 pt per request, so about **4,000 requests/day per
   account**. One 10-touch run is roughly 50–100 calls, so the cap allows about 40–80 runs a day per key.
2. **On this GPU, the 4-bit AWQ Qwen3-32B is very slow (~4 tok/s).** On RDNA3, vLLM runs AWQ through
   Triton fallback kernels. JSON-mode constrained decoding may add to that; not tested separately.
   A 10-touch run with about 4 calls per touch would take about 12 minutes of LLM time, compared with about 1.5 minutes on Token Factory.
3. **Batching works.** 6 parallel calls took about 21 s, roughly the time of one call, so one server
   can serve the whole swarm. Token Factory queued the same 6 calls (17.9 s against 2.3 s for one call).
4. **If you self-host again:** use BF16 weights rather than AWQ on RDNA3. On 2 GPUs (96 GiB), Qwen3-32B
   at BF16 (~64 GB) fits with tensor parallel 2, and 4 GPUs (192 GiB) can take a ~70B BF16 model.
   Try it when the 2/4-GPU pool frees up, and also run once without JSON mode to see what guided decoding costs.
