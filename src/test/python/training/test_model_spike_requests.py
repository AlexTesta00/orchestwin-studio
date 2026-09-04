"""Tests for deterministic evidence-bound live model-spike requests."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

from orchestwin.training.model_candidate_matrix_files import (
    load_frozen_model_candidate_matrix,
)
from orchestwin.training.model_source_evidence import (
    ModelSourceCaptureMode,
    create_captured_model_source_evidence,
    expected_candidate_source_roles,
    serialize_captured_model_source_evidence,
)
from orchestwin.training.model_spike_requests import (
    ModelSpikeRequestError,
    load_model_spike_execution_plan,
    materialize_model_spike_execution_plan,
    request_payload_sha256,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
RUNNER_PATH = REPOSITORY_ROOT / "environments" / "training" / "run_model_spike.py"
CREATED_AT = datetime(2026, 9, 4, 13, 30, tzinfo=UTC)


def _runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_model_spike_for_requests", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source_evidence(matrix) -> tuple[tuple[object, str], ...]:
    items = []
    for candidate in matrix.candidates:
        captured = {
            path: f"{candidate.candidate_id}:{path}\n".encode()
            for path in expected_candidate_source_roles(candidate)
        }
        evidence = create_captured_model_source_evidence(
            candidate=candidate,
            captured_files=captured,
            capture_mode=ModelSourceCaptureMode.CACHE_ONLY,
            captured_at=CREATED_AT,
            resolved_revision=candidate.revision,
        )
        evidence_file_sha = (
            __import__("hashlib")
            .sha256(serialize_captured_model_source_evidence(evidence))
            .hexdigest()
        )
        items.append((evidence, evidence_file_sha))
    return tuple(items)


def test_materialization_creates_one_runner_valid_request_per_frozen_candidate(
    tmp_path: Path,
) -> None:
    matrix = load_frozen_model_candidate_matrix(REPOSITORY_ROOT)
    plan, plan_path = materialize_model_spike_execution_plan(
        matrix=matrix,
        source_evidence=_source_evidence(matrix),
        output_root=tmp_path / "spike",
        package_lock_sha256="a" * 64,
        environment_sha256="b" * 64,
        created_at=CREATED_AT,
    )

    assert [item.candidate_id for item in plan.requests] == [
        candidate.candidate_id for candidate in matrix.candidates
    ]
    assert load_model_spike_execution_plan(plan_path) == plan
    runner = _runner()
    for reference in plan.requests:
        request_path = plan_path.parent / reference.request_reference
        payload = json.loads(request_path.read_text())
        assert payload["request_sha256"] == request_payload_sha256(payload)
        assert runner._load_request(request_path) == payload
        assert payload["candidate_id"] == reference.candidate_id
        assert payload["generation"] == matrix.generation.to_snapshot()
        assert payload["request_sha256"] == reference.request_sha256


def test_materialization_is_byte_deterministic_for_same_inputs(tmp_path: Path) -> None:
    matrix = load_frozen_model_candidate_matrix(REPOSITORY_ROOT)
    common = {
        "matrix": matrix,
        "source_evidence": _source_evidence(matrix),
        "package_lock_sha256": "c" * 64,
        "environment_sha256": "d" * 64,
        "created_at": CREATED_AT,
    }
    first, first_path = materialize_model_spike_execution_plan(
        **common,
        output_root=tmp_path / "first",
    )
    second, second_path = materialize_model_spike_execution_plan(
        **common,
        output_root=tmp_path / "second",
    )

    assert first == second
    assert first_path.read_bytes() == second_path.read_bytes()
    for reference in first.requests:
        assert (first_path.parent / reference.request_reference).read_bytes() == (
            second_path.parent / reference.request_reference
        ).read_bytes()


def test_materialization_requires_complete_candidate_evidence_set(tmp_path: Path) -> None:
    matrix = load_frozen_model_candidate_matrix(REPOSITORY_ROOT)

    with pytest.raises(ModelSpikeRequestError, match="cover every frozen candidate"):
        materialize_model_spike_execution_plan(
            matrix=matrix,
            source_evidence=_source_evidence(matrix)[:-1],
            output_root=tmp_path,
            package_lock_sha256="e" * 64,
            environment_sha256="f" * 64,
            created_at=CREATED_AT,
        )


def test_plan_loader_rejects_tampering_and_unsafe_request_paths(tmp_path: Path) -> None:
    matrix = load_frozen_model_candidate_matrix(REPOSITORY_ROOT)
    _, plan_path = materialize_model_spike_execution_plan(
        matrix=matrix,
        source_evidence=_source_evidence(matrix),
        output_root=tmp_path,
        package_lock_sha256="1" * 64,
        environment_sha256="2" * 64,
        created_at=CREATED_AT,
    )
    payload = json.loads(plan_path.read_text())
    payload["requests"][0]["request_reference"] = "../escape.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ModelSpikeRequestError, match="traversal-free"):
        load_model_spike_execution_plan(plan_path)


def test_request_contains_no_credentials_or_frozen_expected_labels(tmp_path: Path) -> None:
    matrix = load_frozen_model_candidate_matrix(REPOSITORY_ROOT)
    _, plan_path = materialize_model_spike_execution_plan(
        matrix=matrix,
        source_evidence=_source_evidence(matrix),
        output_root=tmp_path,
        package_lock_sha256="3" * 64,
        environment_sha256="4" * 64,
        created_at=CREATED_AT,
    )

    payloads = [
        json.loads((plan_path.parent / item.request_reference).read_text())
        for item in load_model_spike_execution_plan(plan_path).requests
    ]

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value).union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value))
        return set()

    observed_keys = set().union(*(keys(payload) for payload in payloads))
    assert not {"hf_token", "api_key", "password", "access_token"}.intersection(observed_keys)
    assert "expected_criteria" not in observed_keys
    assert "required_role_terms" not in observed_keys
