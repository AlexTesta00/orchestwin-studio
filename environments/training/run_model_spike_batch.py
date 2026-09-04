#!/usr/bin/env python3
"""Run selected evidence-bound model-spike requests sequentially and without retries."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Final

_REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
_SOURCE_ROOT: Final = _REPOSITORY_ROOT / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from orchestwin.training.model_spike_batch import (  # noqa: E402
    MODEL_SPIKE_BATCH_ALL_GATE,
    MODEL_SPIKE_BATCH_NETWORK_GATE,
    ModelSpikeBatchError,
    execute_model_spike_batch,
    select_model_spike_requests,
)
from orchestwin.training.model_spike_requests import (  # noqa: E402
    ModelSpikeRequestError,
    load_model_spike_execution_plan,
)

EXIT_INVALID_INPUT: Final = 22
EXIT_BATCH_CONTAINS_FAILURES: Final = 27


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Execute one or more frozen model-spike requests sequentially. There are no "
            "automatic retries. Use --all only with ORCHESTWIN_MODEL_SPIKE_ALLOW_ALL=1."
        )
    )
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--candidate-id", action="append", default=[])
    parser.add_argument("--all", action="store_true", dest="all_requested")
    parser.add_argument("--timeout-seconds", type=int, default=7_200)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    try:
        plan_path = arguments.plan.resolve()
        plan = load_model_spike_execution_plan(plan_path)
        selected = select_model_spike_requests(
            plan=plan,
            candidate_ids=tuple(arguments.candidate_id),
            all_requested=arguments.all_requested,
            all_authorized=os.environ.get(MODEL_SPIKE_BATCH_ALL_GATE) == "1",
        )
        record, record_path = execute_model_spike_batch(
            plan_path=plan_path,
            output_root=arguments.output_root.resolve(),
            runner_path=_REPOSITORY_ROOT / "environments" / "training" / "run_model_spike.py",
            selected=selected,
            network_authorized=os.environ.get(MODEL_SPIKE_BATCH_NETWORK_GATE) == "1",
            timeout_seconds=arguments.timeout_seconds,
        )
    except (ModelSpikeBatchError, ModelSpikeRequestError, OSError) as error:
        print(str(error), file=sys.stderr)
        return EXIT_INVALID_INPUT
    print(record_path)
    return 0 if record.all_succeeded else EXIT_BATCH_CONTAINS_FAILURES


if __name__ == "__main__":
    raise SystemExit(main())
