#!/usr/bin/env python3
"""Materialize all evidence-bound live model-spike requests without network access."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Final

_REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
_SOURCE_ROOT: Final = _REPOSITORY_ROOT / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from orchestwin.training.model_candidate_matrix_files import (  # noqa: E402
    load_frozen_model_candidate_matrix,
)
from orchestwin.training.model_source_evidence import (  # noqa: E402
    load_captured_model_source_evidence,
)
from orchestwin.training.model_spike_requests import (  # noqa: E402
    ModelSpikeRequestError,
    materialize_model_spike_execution_plan,
    sha256_file,
)

EXIT_INVALID_INPUT: Final = 22


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create canonical model-spike requests from already captured source evidence, "
            "the committed lock, and the observed environment record. No network is used."
        )
    )
    parser.add_argument("--source-evidence-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--requested-at", required=True)
    return parser.parse_args()


def _timestamp(raw: str) -> datetime:
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as error:
        raise ModelSpikeRequestError("requested-at must use ISO-8601") from error
    if value.tzinfo is None or value.utcoffset() is None:
        raise ModelSpikeRequestError("requested-at must be timezone-aware")
    return value


def _environment_identity(path: Path, lock_sha256: str) -> str:
    if path.is_symlink() or not path.is_file():
        raise ModelSpikeRequestError("training environment record must be a regular file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelSpikeRequestError("training environment record must be UTF-8 JSON") from error
    if not isinstance(payload, dict) or payload.get("complete") is not True:
        raise ModelSpikeRequestError("training environment record must be complete")
    if payload.get("uv_lock_sha256") != lock_sha256:
        raise ModelSpikeRequestError("training environment references a different lock")
    return sha256_file(path)


def main() -> int:
    arguments = _parse_arguments()
    try:
        matrix = load_frozen_model_candidate_matrix(_REPOSITORY_ROOT)
        lock_path = _REPOSITORY_ROOT / "environments" / "training" / "uv.lock"
        environment_path = (
            _REPOSITORY_ROOT / "environments" / "training" / "artifacts" / "environment.json"
        )
        lock_sha256 = sha256_file(lock_path)
        environment_sha256 = _environment_identity(environment_path, lock_sha256)
        evidence_root = arguments.source_evidence_root.resolve()
        evidence = []
        for candidate in matrix.candidates:
            evidence_path = evidence_root / candidate.candidate_id / "evidence.json"
            item = load_captured_model_source_evidence(evidence_path, matrix=matrix)
            evidence.append((item, sha256_file(evidence_path)))
        _, plan_path = materialize_model_spike_execution_plan(
            matrix=matrix,
            source_evidence=tuple(evidence),
            output_root=arguments.output_root.resolve(),
            package_lock_sha256=lock_sha256,
            environment_sha256=environment_sha256,
            created_at=_timestamp(arguments.requested_at),
        )
    except (ModelSpikeRequestError, ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return EXIT_INVALID_INPUT
    print(plan_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
