#!/usr/bin/env python3
"""Verify the governed Sprint 12 formal case execution and evidence-capture path."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from orchestwin.evaluation.case_execution_validation import (
    verify_sprint12_case_execution_pipeline,
)


def _platform_commit(repo_root: Path) -> str:
    completed = subprocess.run(
        ("git", "-C", str(repo_root), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--platform-commit")
    arguments = parser.parse_args()
    platform_commit = arguments.platform_commit or _platform_commit(arguments.repo_root)
    summary = verify_sprint12_case_execution_pipeline(
        arguments.repo_root,
        platform_commit=platform_commit,
    )
    print(json.dumps(summary.to_snapshot(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
