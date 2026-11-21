"""Command-line status check for the Revel8 API."""

import argparse
import sys
from collections.abc import Sequence

from .api_client import Revel8APIError, Revel8Client


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect the Revel8 API.")
    parser.add_subparsers(dest="command", required=True).add_parser(
        "status", help="Check API connectivity and list scenario and channel counts."
    )
    parser.parse_args(argv)

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


if __name__ == "__main__":
    raise SystemExit(main())
