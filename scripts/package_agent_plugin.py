"""Build WatchDock's versioned, self-contained agent marketplace ZIP."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from agent_distribution import (
    DistributionValidationError,
    package_agent_distribution,
    repository_root,
    sha256_file,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=repository_root(),
        help="WatchDock repository root (defaults to the script checkout)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("agent-dist"),
        help="directory for the versioned ZIP",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        archive = package_agent_distribution(args.repo_root, args.output_dir)
    except DistributionValidationError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"built {archive}")
    print(f"sha256 {sha256_file(archive)}  {archive.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
