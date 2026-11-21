"""Switch the agent's LLM in .env between Token Factory and a self-hosted vLLM server.

Usage:
  uv run python scripts/llm_switch.py status
  uv run python scripts/llm_switch.py selfhost --url http://HOST:8000/v1 --key sk-local-... --model qwen3-32b
  uv run python scripts/llm_switch.py selfhost          # reuse the last self-host settings
  uv run python scripts/llm_switch.py tokenfactory      # restore the Token Factory values

The first switch to selfhost saves the current LLM_* values as TF_LLM_* so `tokenfactory`
can restore them; self-host settings are kept as SELFHOST_LLM_*. Comments and order in .env
are preserved, and a copy of the previous file is written to .env.bak.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

FIELDS = ("LLM_BASE_URL", "LLM_API_KEY", "LLM_API_KEYS", "LLM_MODEL")


def read_env(path: Path) -> tuple[list[str], dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    values: dict[str, str] = {}
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            values[k.strip()] = v.strip()
    return lines, values


def write_env(path: Path, lines: list[str], updates: dict[str, str]) -> None:
    pending = dict(updates)
    out: list[str] = []
    for line in lines:
        s = line.strip()
        key = s.split("=", 1)[0].strip() if s and not s.startswith("#") and "=" in s else None
        if key in pending:
            out.append(f"{key}={pending.pop(key)}")
        else:
            out.append(line)
    if pending:
        out.append("")
        out.append("# --- managed by scripts/llm_switch.py ---")
        out.extend(f"{k}={v}" for k, v in pending.items())
    if path.exists():
        shutil.copyfile(path, path.with_name(path.name + ".bak"))
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def mask(value: str) -> str:
    keys = [k for k in value.split(",") if k.strip()]
    return ", ".join(k.strip()[:8] + "…" for k in keys) or "(empty)"


def mode(values: dict[str, str]) -> str:
    url = values.get("LLM_BASE_URL", "")
    if url and url == values.get("SELFHOST_LLM_BASE_URL"):
        return "selfhost"
    if url and (url == values.get("TF_LLM_BASE_URL") or "anruicloud" in url):
        return "tokenfactory"
    return "custom"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["status", "selfhost", "tokenfactory"])
    ap.add_argument("--url", help="Self-hosted base URL, e.g. http://HOST:8000/v1")
    ap.add_argument("--key", help="The vLLM --api-key (cat ~/.vllm_api_key on the instance)")
    ap.add_argument("--model", help="The vLLM --served-model-name, e.g. qwen3-32b")
    ap.add_argument("--env", default=".env", help="Path to the .env file (default: .env)")
    args = ap.parse_args(argv)

    path = Path(args.env)
    lines, values = read_env(path)

    if args.command == "status":
        print(f"mode:   {mode(values)}")
        print(f"url:    {values.get('LLM_BASE_URL', '(unset)')}")
        print(f"model:  {values.get('LLM_MODEL', '(unset)')}")
        print(f"keys:   {mask(values.get('LLM_API_KEYS') or values.get('LLM_API_KEY', ''))}")
        return 0

    if args.command == "selfhost":
        url = args.url or values.get("SELFHOST_LLM_BASE_URL", "")
        key = args.key or values.get("SELFHOST_LLM_API_KEY", "")
        model = args.model or values.get("SELFHOST_LLM_MODEL", "")
        if not (url and key and model):
            print("Need --url, --key and --model the first time.", file=sys.stderr)
            return 2
        updates: dict[str, str] = {}
        if "TF_LLM_BASE_URL" not in values and mode(values) != "selfhost":
            updates.update({f"TF_{f}": values.get(f, "") for f in FIELDS})
        updates.update({
            "SELFHOST_LLM_BASE_URL": url, "SELFHOST_LLM_API_KEY": key, "SELFHOST_LLM_MODEL": model,
            # LLM_API_KEYS wins over LLM_API_KEY in the client, so both point at the one server key.
            "LLM_BASE_URL": url, "LLM_API_KEY": key, "LLM_API_KEYS": key, "LLM_MODEL": model,
        })
        write_env(path, lines, updates)
        print(f"-> self-hosted: {url}  model={model}")
        print("   swarm: one key now, so pass --max-parallel N (up to 6) to run sessions concurrently.")
        return 0

    if "TF_LLM_BASE_URL" not in values:
        print("No saved Token Factory values (TF_LLM_*) in .env; nothing to restore.", file=sys.stderr)
        return 1
    write_env(path, lines, {f: values.get(f"TF_{f}", "") for f in FIELDS})
    print(f"-> Token Factory: {values['TF_LLM_BASE_URL']}  model={values.get('TF_LLM_MODEL', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
