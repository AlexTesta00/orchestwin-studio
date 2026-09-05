#!/usr/bin/env python3
"""Reanalyze frozen model-spike evidence offline without changing original reports."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPOSITORY_ROOT / "src"))

from orchestwin.training.model_spike_reanalysis import (  # noqa: E402
    reanalyze_model_spike_v2,
    write_reanalysis_report_v2,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--batch-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--created-at", required=True)
    arguments = parser.parse_args()
    try:
        report = reanalyze_model_spike_v2(
            repository_root=_REPOSITORY_ROOT,
            plan_path=arguments.plan,
            batch_result_path=arguments.batch_result,
            created_at=datetime.fromisoformat(arguments.created_at),
        )
        write_reanalysis_report_v2(
            path=arguments.output,
            report=report,
            protected_roots=(arguments.plan.parent, arguments.batch_result.parent),
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Offline reanalysis failed: {error}", file=sys.stderr)
        return 22
    print(arguments.output.resolve())
    for candidate in report["candidates"]:
        summary = candidate["summary"]
        print(
            f"{candidate['candidate_id']}: "
            f"generated={summary['successful_generation_count']}/"
            f"{summary['expected_task_count']} "
            f"json={summary['json_object_valid_count']} "
            f"schema={summary['json_schema_valid_count']} "
            f"semantic_coverage={summary['semantic_evaluated_task_count']}"
        )
    print("offline_model_spike_reanalysis_v2: PASSED (no model selected)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
