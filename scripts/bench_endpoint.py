"""Benchmark an OpenAI-compatible LLM endpoint on the agent's real call shape, and save timings.

Measures, with engine-like JSON-mode prompts:
  - time to first token (streaming) and total latency per call
  - output tokens/s for a single stream
  - wall time and aggregate tokens/s for N parallel calls (the swarm runs up to 6)

Usage:
  uv run python scripts/bench_endpoint.py --label selfhost-1gpu \
      --url https://.../v1 --key sk-... --model qwen3-32b
  uv run python scripts/bench_endpoint.py --label tokenfactory     # uses LLM_* from .env
Results: runs/bench/<UTC timestamp>-<label>.json
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

SYSTEM = (
    "You are the decision policy of a social-engineering *training simulation* agent. "
    "Given the run so far, choose the next move. Return ONLY JSON: "
    '{"channel": "email"|"phone"|"sms"|"wait"|"stop", "warrant": str, "pressure": 0-3, "reason": str}'
)
USER = (
    "Target: Julius, Head of Finance at a 40-person Munich startup (simulated persona). "
    "Touch 1 (email, day 1): invoice-follow-up pretext referencing their public Series A news. Opened, no reply. "
    "Touch 2 (email, day 3): short nudge. Opened twice, no reply. Sentiment so far: neutral, not suspicious. "
    "Decide touch 3 and explain briefly in 2-3 sentences."
)


def one_call(client: httpx.Client, model: str, json_mode: bool) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER}],
        "temperature": 0.6,
        "max_tokens": 400,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    start = time.monotonic()
    ttft = None
    text, usage = [], {}
    with client.stream("POST", "chat/completions", json=payload) as r:
        if r.status_code != 200:
            body = r.read().decode(errors="replace")[:300]
            return {"ok": False, "status": r.status_code, "error": body, "total_s": time.monotonic() - start}
        for line in r.iter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            if chunk.get("usage"):
                usage = chunk["usage"]
            for ch in chunk.get("choices") or []:
                piece = (ch.get("delta") or {}).get("content") or ""
                if piece and ttft is None:
                    ttft = time.monotonic() - start
                text.append(piece)
    total = time.monotonic() - start
    out = "".join(text)
    try:
        json.loads(out.rsplit("</think>", 1)[-1].strip().strip("`").removeprefix("json").strip())
        valid = True
    except ValueError:
        valid = False
    toks = usage.get("completion_tokens") or max(1, len(out) // 4)
    gen = total - (ttft or 0)
    return {
        "ok": True, "ttft_s": ttft, "total_s": total, "completion_tokens": toks,
        "tok_per_s": toks / gen if gen > 0 else None, "json_valid": valid,
        "usage_reported": bool(usage), "sample": out[:200],
    }


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--url", default=(os.getenv("LLM_BASE_URL") or "").split(",")[0])
    ap.add_argument("--key", default=((os.getenv("LLM_API_KEYS") or os.getenv("LLM_API_KEY") or "").split(",")[0]))
    ap.add_argument("--model", default=os.getenv("LLM_MODEL", ""))
    ap.add_argument("--seq", type=int, default=3, help="sequential calls")
    ap.add_argument("--par", type=int, default=6, help="parallel calls")
    ap.add_argument("--no-json-mode", action="store_true")
    args = ap.parse_args()

    base = args.url.rstrip("/")
    headers = {"Authorization": f"Bearer {args.key}"} if args.key else {}
    client = httpx.Client(base_url=base + "/", headers=headers, timeout=300.0)
    json_mode = not args.no_json_mode
    started = datetime.now(UTC)
    print(f"[{started:%H:%M:%S}Z] {args.label}: {base}  model={args.model}")

    seq = []
    for i in range(args.seq):
        r = one_call(client, args.model, json_mode)
        seq.append(r)
        print(f"  seq {i + 1}: " + (f"ttft {r['ttft_s'] or 0:.2f}s total {r['total_s']:.2f}s "
                                     f"{r['completion_tokens']} tok {r['tok_per_s'] or 0:.1f} tok/s json={r['json_valid']}"
                                     if r["ok"] else f"HTTP {r['status']}: {r['error']}"))
        if not r["ok"]:
            break

    par, wall = [], None
    if seq and seq[-1]["ok"] and args.par > 0:
        t0 = time.monotonic()
        with ThreadPoolExecutor(args.par) as pool:
            par = list(pool.map(lambda _: one_call(client, args.model, json_mode), range(args.par)))
        wall = time.monotonic() - t0
        okp = [r for r in par if r["ok"]]
        agg = sum(r["completion_tokens"] for r in okp) / wall if wall else 0
        print(f"  par x{args.par}: wall {wall:.2f}s, {len(okp)}/{args.par} ok, aggregate {agg:.1f} tok/s, "
              f"json-valid {sum(r['json_valid'] for r in okp)}/{len(okp)}")

    ok_seq = [r for r in seq if r["ok"]]
    summary = {
        "label": args.label, "url": base, "model": args.model, "json_mode": json_mode,
        "started_utc": started.isoformat(), "finished_utc": datetime.now(UTC).isoformat(),
        "seq_median_ttft_s": statistics.median([r["ttft_s"] for r in ok_seq if r["ttft_s"]]) if ok_seq else None,
        "seq_median_total_s": statistics.median([r["total_s"] for r in ok_seq]) if ok_seq else None,
        "seq_median_tok_per_s": statistics.median([r["tok_per_s"] for r in ok_seq if r["tok_per_s"]]) if ok_seq else None,
        "par_n": args.par, "par_wall_s": wall,
        "par_aggregate_tok_per_s": (sum(r["completion_tokens"] for r in par if r["ok"]) / wall) if wall else None,
        "sequential": seq, "parallel": par,
    }
    out = Path("runs/bench")
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{started:%Y%m%dT%H%M%SZ}-{args.label}.json"
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"  saved {path}")
    return 0 if ok_seq else 1


if __name__ == "__main__":
    raise SystemExit(main())
