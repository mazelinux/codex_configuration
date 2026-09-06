#!/usr/bin/env python3
"""Copy the canonical service into a new, empty destination without overwriting it."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap the workflow-analytics service")
    parser.add_argument("--destination", required=True, help="New service directory; it must not exist or must be empty")
    parser.add_argument("--source", help="Canonical service template; defaults to this workspace's services/codex-history-analyzer")
    args = parser.parse_args()

    skill_dir = Path(__file__).resolve().parents[1]
    source = Path(args.source).resolve() if args.source else skill_dir.parents[1] / "services" / "codex-history-analyzer"
    source = source.resolve()
    destination = Path(args.destination).expanduser().resolve()
    if not source.is_dir() or not (source / "pyproject.toml").is_file():
        raise SystemExit(f"Canonical service template is unavailable: {source}. Supply --source.")
    if destination == source or source in destination.parents:
        raise SystemExit("Destination must be a new directory outside the canonical service.")
    if destination.exists() and any(destination.iterdir()):
        raise SystemExit(f"Refusing to overwrite non-empty destination: {destination}")
    if destination.exists():
        destination.rmdir()
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))
    print(f"Created complete service at {destination}")
    print(f"Run: cd {destination} && PYTHONPATH=src python -m codex_history_analyzer.cli serve --sessions-root <trace-root>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
