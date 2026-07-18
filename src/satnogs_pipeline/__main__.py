"""Command-line entry point for the SatNOGS pipeline."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from satnogs_pipeline.api_client import SatnogsNetworkClient
from satnogs_pipeline.config import load_config
from satnogs_pipeline.scheduler import apply_plan, plan_observations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan SatNOGS METEOR observations.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/targets.yaml"),
        help="Path to targets.yaml",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute the plan without POSTing observations to SatNOGS",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)

    token = os.environ.get("SATNOGS_API_TOKEN")
    if args.dry_run:
        client = SatnogsNetworkClient(token=token) if token else None
    else:
        if not token:
            print("SATNOGS_API_TOKEN is required for live scheduling", file=sys.stderr)
            return 2
        client = SatnogsNetworkClient(token=token)

    plan = plan_observations(config, client=client)
    results = apply_plan(config, plan, client=client or SatnogsNetworkClient(), dry_run=args.dry_run)

    for item in results:
        start = item.pass_window.start.isoformat().replace("+00:00", "Z")
        end = item.pass_window.end.isoformat().replace("+00:00", "Z")
        print(
            f"{item.action:9} | {item.target.name:12} | "
            f"max_el={item.pass_window.max_elevation_deg:5.1f}° | "
            f"{start} -> {end} | {item.reason}"
        )

    scheduled = sum(1 for item in results if item.action == "scheduled")
    failed = sum(1 for item in results if item.action == "failed")
    skipped = sum(1 for item in results if item.action == "skip")
    print(f"\nSummary: {scheduled} scheduled, {skipped} skipped, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
