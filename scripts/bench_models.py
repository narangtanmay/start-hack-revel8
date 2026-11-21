"""Compare Token Factory models on the real fact-extraction task: latency and JSON validity.

Usage: .venv/bin/python scripts/bench_models.py [model ...]
"""

import statistics
import sys
import time

import httpx
from dotenv import load_dotenv

from revel8_agent.llm_client import LocalLLMClient, LocalLLMError
from revel8_agent.osint import SourceDoc, Target, extract_facts, verify_fact

DEFAULT_MODELS = ["DeepSeek-V4-Flash", "DeepSeek-V4.1-Flash", "Qwen3.8-27B", "Gemma-4-31B-IT"]

TARGET = Target("tom", "Tom Müller", "Co-Founder & Co-CEO, revel8 (product)", "revel8")
DOC = SourceDoc("doc_bench", "https://example.test/bench", "revel8 team", (
    "revel8 is a Munich-based security awareness startup. Tom Müller, co-founder and co-CEO of revel8, "
    "leads product. In March 2026 he spoke on a panel at the Munich Cyber Security Conference about "
    "deepfake voice phishing. The company announced a partnership with a German insurer in February 2026 "
    "and is hiring a senior frontend engineer. Tom Müller previously worked as a consultant and studied "
    "at TUM. He regularly posts about AI-generated phishing simulations."
))


def main() -> int:
    load_dotenv()
    models = sys.argv[1:] or DEFAULT_MODELS
    try:
        probe = LocalLLMClient(model="probe")
        listed = probe._client.get("models").json()
        names = [m.get("id") for m in listed.get("data", [])]
        print("models served:", ", ".join(map(str, names)))
    except (LocalLLMError, httpx.HTTPError, ValueError) as error:
        print("could not list models:", error)

    for model in models:
        times, ok, verified = [], 0, 0
        for _ in range(3):
            llm = LocalLLMClient(model=model, timeout=90.0)
            start = time.monotonic()
            raw = extract_facts(llm, TARGET, DOC)
            times.append(time.monotonic() - start)
            ok += bool(raw)
            verified += sum(verify_fact(r, DOC, TARGET) is not None for r in raw)
            llm.close()
        print(f"{model:28s} median {statistics.median(times):5.1f}s  "
              f"json-ok {ok}/3  verified facts {verified / 3:.1f}/run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
