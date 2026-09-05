#!/usr/bin/env python3
"""Prepare fictional smoke data and exact configuration; never execute training."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPOSITORY_ROOT / "src"))

from orchestwin.training.qlora_smoke_fixtures import SmokePreparationError  # noqa: E402
from orchestwin.training.qlora_smoke_preparation import prepare_qlora_smoke  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--reanalysis", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--created-at", required=True)
    args = parser.parse_args()
    try:
        path = prepare_qlora_smoke(
            repository_root=_REPOSITORY_ROOT,
            reanalysis_path=args.reanalysis,
            candidate_id=args.candidate_id,
            output_root=args.output_root,
            created_at=datetime.fromisoformat(args.created_at),
        )
    except (SmokePreparationError, ValueError, KeyError, TypeError, OSError) as error:
        print(f"QLoRA smoke preparation failed: {error}", file=sys.stderr)
        return 22
    print(path)
    print("train=16 validation=4 languages=en,it scenario_families=10")
    print("qlora_smoke_preparation: PASSED (training not authorized)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
