#!/usr/bin/env python3
"""Verify the Sprint 12 observed-evidence harvesting contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orchestwin.evaluation.case_harvest_validation import verify_sprint12_case_harvest_contract


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    summary = verify_sprint12_case_harvest_contract(args.repo_root)
    print(json.dumps(summary.to_snapshot(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
