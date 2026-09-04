#!/usr/bin/env python3
"""Create a no-selection comparison report from validated live model-spike evidence."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Final

_REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
_SOURCE_ROOT: Final = _REPOSITORY_ROOT / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from orchestwin.training.benchmark_suite_files import (  # noqa: E402
    load_frozen_evaluator_benchmark_suite,
)
from orchestwin.training.model_candidate_matrix_files import (  # noqa: E402
    load_frozen_model_candidate_matrix,
)
from orchestwin.training.model_spike_reports import (  # noqa: E402
    ModelSpikeReportError,
    create_model_spike_comparison_report,
    write_model_spike_comparison_report,
)
from orchestwin.training.model_spike_requests import (  # noqa: E402
    ModelSpikeRequestError,
    load_model_spike_execution_plan,
    sha256_file,
)
from orchestwin.training.model_spike_results import (  # noqa: E402
    ModelSpikeResultError,
    load_validated_model_spike_bundle,
)

EXIT_INVALID_EVIDENCE: Final = 22


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a canonical comparison report without ranking or selecting a model. "
            "License review, QLoRA smoke, adapter export/load, and serving remain pending."
        )
    )
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--batch-result", required=True, type=Path)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def _timestamp(raw: str) -> datetime:
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as error:
        raise ModelSpikeReportError("created-at must use ISO-8601") from error
    if value.tzinfo is None or value.utcoffset() is None:
        raise ModelSpikeReportError("created-at must be timezone-aware")
    return value


def main() -> int:
    arguments = _parse_arguments()
    try:
        plan_path = arguments.plan.resolve()
        batch_result_path = arguments.batch_result.resolve()
        plan = load_model_spike_execution_plan(plan_path)
        bundle = load_validated_model_spike_bundle(
            plan_path=plan_path,
            batch_result_path=batch_result_path,
        )
        report = create_model_spike_comparison_report(
            plan=plan,
            plan_file_sha256=sha256_file(plan_path),
            bundle=bundle,
            matrix=load_frozen_model_candidate_matrix(_REPOSITORY_ROOT),
            suite=load_frozen_evaluator_benchmark_suite(_REPOSITORY_ROOT),
            created_at=_timestamp(arguments.created_at),
        )
        write_model_spike_comparison_report(arguments.output.resolve(), report)
    except (
        ModelSpikeReportError,
        ModelSpikeRequestError,
        ModelSpikeResultError,
        OSError,
        ValueError,
    ) as error:
        print(str(error), file=sys.stderr)
        return EXIT_INVALID_EVIDENCE
    print(arguments.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
