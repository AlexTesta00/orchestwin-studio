#!/usr/bin/env python3
"""Validate raw live model-spike evidence and emit a canonical derived bundle."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Final

_REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
_SOURCE_ROOT: Final = _REPOSITORY_ROOT / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from orchestwin.training.model_spike_results import (  # noqa: E402
    ModelSpikeResultError,
    load_validated_model_spike_bundle,
    write_validated_model_spike_bundle,
)

EXIT_INVALID_EVIDENCE: Final = 22


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate one immutable model-spike plan and batch-result bundle."
    )
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--batch-result", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    try:
        bundle = load_validated_model_spike_bundle(
            plan_path=arguments.plan.resolve(),
            batch_result_path=arguments.batch_result.resolve(),
        )
        write_validated_model_spike_bundle(arguments.output.resolve(), bundle)
    except (ModelSpikeResultError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return EXIT_INVALID_EVIDENCE
    print(arguments.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
