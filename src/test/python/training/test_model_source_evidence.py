"""Tests for immutable exact-revision model source evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from orchestwin.training.model_candidate_matrix_files import (
    load_frozen_model_candidate_matrix,
)
from orchestwin.training.model_source_evidence import (
    ModelSourceCaptureMode,
    ModelSourceEvidenceError,
    ModelSourceFileRole,
    create_captured_model_source_evidence,
    expected_candidate_source_roles,
    parse_captured_model_source_evidence,
)

CAPTURED_AT = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def _bytes_for(candidate) -> dict[str, bytes]:
    return {
        path: f"{candidate.candidate_id}:{path}\n".encode()
        for path in expected_candidate_source_roles(candidate)
    }


def test_capture_binds_exact_files_roles_revision_and_matrix() -> None:
    matrix = load_frozen_model_candidate_matrix()
    candidate = matrix.candidate("model-candidate-granite-3-3-2b-instruct")

    evidence = create_captured_model_source_evidence(
        candidate=candidate,
        captured_files=_bytes_for(candidate),
        capture_mode=ModelSourceCaptureMode.CACHE_ONLY,
        captured_at=CAPTURED_AT,
        resolved_revision=candidate.revision,
    )

    assert evidence.complete is True
    assert evidence.requested_revision == candidate.revision
    assert evidence.resolved_revision == candidate.revision
    assert evidence.file_for_role(ModelSourceFileRole.MODEL_CARD).relative_path == "README.md"
    assert evidence.file_for_role(ModelSourceFileRole.LICENSE).relative_path == "README.md"
    readme = next(item for item in evidence.files if item.relative_path == "README.md")
    assert readme.roles == (ModelSourceFileRole.LICENSE, ModelSourceFileRole.MODEL_CARD)
    assert len(evidence.content_hash) == 64


def test_capture_rejects_missing_unexpected_and_changed_revision() -> None:
    matrix = load_frozen_model_candidate_matrix()
    candidate = matrix.candidate("model-candidate-qwen3-4b-instruct-2507")
    captured = _bytes_for(candidate)
    captured.pop("LICENSE")

    with pytest.raises(ModelSourceEvidenceError, match="path set changed"):
        create_captured_model_source_evidence(
            candidate=candidate,
            captured_files=captured,
            capture_mode=ModelSourceCaptureMode.NETWORK_AUTHORIZED,
            captured_at=CAPTURED_AT,
            resolved_revision=candidate.revision,
        )

    with pytest.raises(ModelSourceEvidenceError, match="differs from the request"):
        create_captured_model_source_evidence(
            candidate=candidate,
            captured_files=_bytes_for(candidate),
            capture_mode=ModelSourceCaptureMode.NETWORK_AUTHORIZED,
            captured_at=CAPTURED_AT,
            resolved_revision="f" * 40,
        )


def test_content_hash_changes_when_upstream_bytes_change() -> None:
    matrix = load_frozen_model_candidate_matrix()
    candidate = matrix.candidate("model-candidate-smollm3-3b")
    original = _bytes_for(candidate)
    changed = dict(original)
    changed["tokenizer_config.json"] += b"changed"

    first = create_captured_model_source_evidence(
        candidate=candidate,
        captured_files=original,
        capture_mode=ModelSourceCaptureMode.CACHE_ONLY,
        captured_at=CAPTURED_AT,
        resolved_revision=candidate.revision,
    )
    second = create_captured_model_source_evidence(
        candidate=candidate,
        captured_files=changed,
        capture_mode=ModelSourceCaptureMode.CACHE_ONLY,
        captured_at=CAPTURED_AT,
        resolved_revision=candidate.revision,
    )

    assert first.content_hash != second.content_hash
    assert first.file_for_role(ModelSourceFileRole.TOKENIZER_CONFIGURATION).sha256 != (
        second.file_for_role(ModelSourceFileRole.TOKENIZER_CONFIGURATION).sha256
    )


def test_parser_rejects_noncanonical_or_tampered_evidence() -> None:
    matrix = load_frozen_model_candidate_matrix()
    candidate = matrix.candidates[0]
    evidence = create_captured_model_source_evidence(
        candidate=candidate,
        captured_files=_bytes_for(candidate),
        capture_mode=ModelSourceCaptureMode.CACHE_ONLY,
        captured_at=CAPTURED_AT,
        resolved_revision=candidate.revision,
    )

    assert (
        parse_captured_model_source_evidence(
            evidence.to_snapshot(),
            matrix=matrix,
        )
        == evidence
    )

    with pytest.raises(ModelSourceEvidenceError, match="content hash is inconsistent"):
        parse_captured_model_source_evidence(
            replace(evidence, repository_id="example/changed").to_snapshot(),
            matrix=matrix,
        )


def test_expected_paths_are_safe_and_complete_for_every_candidate() -> None:
    matrix = load_frozen_model_candidate_matrix()

    for candidate in matrix.candidates:
        expected = expected_candidate_source_roles(candidate)
        assert candidate.artifact_capture.model_card_path in expected
        assert candidate.license.artifact_path in expected
        assert candidate.artifact_capture.tokenizer_configuration_path in expected
        assert all(".." not in path.split("/") for path in expected)
