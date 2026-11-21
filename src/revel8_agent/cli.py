"""Command-line entry points for the Revel8 agent."""

import argparse
import sys
from collections.abc import Sequence

from .api_client import Revel8APIError, Revel8Client


def _status() -> int:
    try:
        with Revel8Client() as client:
            scenarios = client.get_scenarios()
            channels = client.get_channels()
    except Revel8APIError as error:
        print(f"Revel8 API status check failed. {error}", file=sys.stderr)
        return 1

    open_scenarios = sum(
        isinstance(scenario, dict) and scenario.get("open") is True for scenario in scenarios
    )
    entries = channels.get("channels") if isinstance(channels, dict) else channels
    if not isinstance(entries, (list, dict)):
        entries = channels
    print("Revel8 API reachable")
    print(f"Scenarios: {len(scenarios)} ({open_scenarios} open)")
    print(f"Channel entries: {len(entries)}")
    return 0


def _osint(scenario_id: str, target_ids: list[str], budget: float, out_dir: str) -> int:
    from concurrent.futures import ThreadPoolExecutor

    from .llm_client import LocalLLMClient, LocalLLMError
    from .osint import Target, build_dossier, write_dossier

    try:
        with Revel8Client() as client:
            scenarios = client.get_scenarios()
    except Revel8APIError as error:
        print(f"Could not load scenarios. {error}", file=sys.stderr)
        return 1
    scenario = next((s for s in scenarios if isinstance(s, dict) and s.get("id") == scenario_id), None)
    if not scenario or not scenario.get("open"):
        print(f"Scenario {scenario_id!r} not found or not open.", file=sys.stderr)
        return 1

    company = str(scenario.get("company", ""))
    targets = [
        Target(str(t["id"]), str(t["name"]), str(t.get("role", "")), company)
        for t in scenario.get("targets", [])
        if isinstance(t, dict) and (not target_ids or t.get("id") in target_ids)
    ]
    if not targets:
        print("No matching targets.", file=sys.stderr)
        return 1

    try:
        llm = LocalLLMClient(timeout=60.0)
    except LocalLLMError as error:
        print(error, file=sys.stderr)
        return 1

    def run(t: Target) -> str:
        dossier, stats = build_dossier(t, llm, budget_s=budget)
        path = write_dossier(dossier, stats, out_dir)
        return f"{t.id}: {len(dossier.facts)} facts, {len(dossier.hypotheses)} hooks, {stats['elapsed_s']}s -> {path}"

    with ThreadPoolExecutor(len(targets)) as pool:
        for line in pool.map(run, targets):
            print(line)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Revel8 agent tools.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Check API connectivity and list scenario and channel counts.")
    osint = sub.add_parser("osint", help="Build verified dossiers for scenario targets.")
    osint.add_argument("--scenario", default="practice")
    osint.add_argument("--target", action="append", default=[], help="Target id (repeatable). Default: all.")
    osint.add_argument("--budget", type=float, default=150.0, help="Seconds per target.")
    osint.add_argument("--out", default="dossiers")
    args = parser.parse_args(argv)

    if args.command == "osint":
        return _osint(args.scenario, args.target, args.budget, args.out)
    return _status()


if __name__ == "__main__":
    raise SystemExit(main())
