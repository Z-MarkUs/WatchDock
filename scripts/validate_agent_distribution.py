"""Command-line validator for WatchDock's agent marketplace distribution."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from agent_distribution import (
    DistributionValidationError,
    format_validation_success,
    repository_root,
    validate_agent_archive,
    validate_agent_distribution,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate WatchDock's agent plugin, marketplace, and MCP inventory."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=repository_root(),
        help="WatchDock repository root (defaults to the script checkout)",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        help="also validate an already-built watchdock-agent ZIP",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        info = validate_agent_distribution(args.repo_root)
        if args.archive:
            validate_agent_archive(args.archive, args.repo_root, info)
    except DistributionValidationError as exc:
        raise SystemExit(str(exc)) from exc
    print(format_validation_success(info))
    if args.archive:
        print(f"validated archive: {args.archive.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
