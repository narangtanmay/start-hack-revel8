"""Smoke-check the LLM endpoint in .env before spending a real run on it.

Checks: the server answers, LLM_MODEL is among the served models, a JSON-mode call
(what the engine uses every touch) parses, and how long it takes. Spends 4 short calls.

Usage: uv run python scripts/check_llm.py
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from revel8_agent.llm_client import LocalLLMClient, LocalLLMError

PROMPT = [
    {"role": "system", "content": "Return ONLY JSON: {\"channel\": \"email\"|\"phone\"|\"sms\", \"reason\": str}"},
    {"role": "user", "content": "The target opened our email yesterday but did not reply. Pick the next channel."},
]


def main() -> int:
    llm = LocalLLMClient(timeout=180.0)
    print(f"endpoint: {llm._client.base_url}   model: {llm.model}")

    try:
        served = [m.get("id") for m in llm._client.get("models").json().get("data", [])]
        print(f"served:   {', '.join(map(str, served)) or '(none listed)'}")
        if served and llm.model not in served:
            print(f"!! LLM_MODEL={llm.model!r} is not served here; set it to one of the names above.")
            return 1
    except (httpx.HTTPError, ValueError) as error:
        print(f"!! could not list models: {error}")
        return 1

    start = time.monotonic()
    try:
        out = llm.chat(PROMPT, json_mode=True, temperature=0.2)
    except LocalLLMError as error:
        print(f"!! JSON-mode call failed: {error}")
        return 1
    print(f"json call: {time.monotonic() - start:.1f}s -> {out}")

    # The swarm runs up to 6 sessions at once; check the server batches rather than queues.
    n = int(os.getenv("CHECK_PARALLEL", "3"))
    start = time.monotonic()
    with ThreadPoolExecutor(n) as pool:
        results = list(pool.map(lambda _: llm.chat(PROMPT, json_mode=True, temperature=0.2), range(n)))
    ok = sum(isinstance(r, dict) for r in results)
    print(f"{n} parallel calls: {time.monotonic() - start:.1f}s wall, {ok}/{n} valid JSON")
    llm.close()
    return 0 if ok == n else 1


if __name__ == "__main__":
    raise SystemExit(main())
