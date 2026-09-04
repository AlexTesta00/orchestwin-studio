"""Tests for the frozen live model candidate preflight matrix."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from orchestwin.training.model_candidate_matrix_files import (
    FROZEN_MODEL_CANDIDATE_MATRIX_CONTENT_HASH,
    FROZEN_MODEL_CANDIDATE_MATRIX_PATH,
    FROZEN_MODEL_CANDIDATE_MATRIX_SHA256,
    FROZEN_MODEL_CANDIDATE_SOURCE_MANIFEST_PATH,
    CandidateArtifactCaptureStatus,
    CandidateAvailabilityStatus,
    CandidateChatTemplateControlMode,
    CandidateLicenseReviewStatus,
    CandidateMatrixDecisionStatus,
    CandidateMatrixEvidenceStatus,
    CandidateServingEvidenceStatus,
    FrozenModelCandidateArtifactError,
    ScreenedOutModelReason,
    load_frozen_model_candidate_matrix,
    load_frozen_model_candidate_source_manifest,
    model_candidate_artifact_sha256,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
EXPECTED_REVISIONS = {
    "model-candidate-granite-3-3-2b-instruct": ("9e2a2e5159b7cd2c412346a8434b19990966d739"),
    "model-candidate-qwen3-4b-instruct-2507": ("abcc171021d4f320b2e7f47c6f0deca67ded870c"),
    "model-candidate-smollm3-3b": "320cd3ef7b805b4482ee3776fdd8cbf6ce3b5c53",
}


def _copy_frozen_artifacts(target_root: Path) -> None:
    for relative_path in (
        FROZEN_MODEL_CANDIDATE_MATRIX_PATH,
        FROZEN_MODEL_CANDIDATE_SOURCE_MANIFEST_PATH,
    ):
        target = target_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY_ROOT / relative_path, target)


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        result = set(value)
        for item in value.values():
            result.update(_all_keys(item))
        return result
    if isinstance(value, list):
        result: set[str] = set()
        for item in value:
            result.update(_all_keys(item))
        return result
    return set()


def test_frozen_matrix_loads_three_diverse_candidates_without_selection() -> None:
    manifest = load_frozen_model_candidate_source_manifest(REPOSITORY_ROOT)
    matrix = load_frozen_model_candidate_matrix(REPOSITORY_ROOT)

    assert matrix.decision_status is CandidateMatrixDecisionStatus.NO_MODEL_SELECTED
    assert matrix.evidence_status is CandidateMatrixEvidenceStatus.PREFLIGHT_ONLY
    assert matrix.content_hash == FROZEN_MODEL_CANDIDATE_MATRIX_CONTENT_HASH
    assert (
        model_candidate_artifact_sha256(REPOSITORY_ROOT / FROZEN_MODEL_CANDIDATE_MATRIX_PATH)
        == FROZEN_MODEL_CANDIDATE_MATRIX_SHA256
    )
    assert [candidate.candidate_id for candidate in matrix.candidates] == sorted(EXPECTED_REVISIONS)
    assert len({candidate.family_id for candidate in matrix.candidates}) == 3
    assert len(manifest.sources) == 4


def test_matrix_freezes_identical_generation_and_pending_evidence() -> None:
    matrix = load_frozen_model_candidate_matrix(REPOSITORY_ROOT)

    assert matrix.generation.to_snapshot() == {
        "max_sequence_length": 4096,
        "max_output_tokens": 1024,
        "repetitions": 1,
        "seed": 20260904,
        "load_in_4bit": True,
        "trust_remote_code": False,
    }
    for candidate in matrix.candidates:
        assert candidate.benchmark_languages == ("en", "it")
        assert candidate.availability_status is CandidateAvailabilityStatus.PENDING_DOWNLOAD_PROBE
        assert candidate.license.review_status is CandidateLicenseReviewStatus.REVIEW_REQUIRED
        assert candidate.license.capture_status is (
            CandidateArtifactCaptureStatus.PENDING_LOCAL_DIGEST
        )
        assert candidate.artifact_capture.capture_status is (
            CandidateArtifactCaptureStatus.PENDING_LOCAL_DIGEST
        )
        assert candidate.serving.status is (
            CandidateServingEvidenceStatus.DOCUMENTED_NOT_LOCALLY_OBSERVED
        )
        assert candidate.license.allows_adapter_redistribution is None
        assert candidate.license.allows_weight_redistribution is None
        assert candidate.license.attribution_required is None


def test_candidate_revisions_and_chat_template_controls_are_explicit() -> None:
    matrix = load_frozen_model_candidate_matrix(REPOSITORY_ROOT)

    assert {candidate.candidate_id: candidate.revision for candidate in matrix.candidates} == (
        EXPECTED_REVISIONS
    )
    controls = {
        candidate.candidate_id: (
            candidate.chat_template_control.mode,
            candidate.chat_template_control.argument_name,
            candidate.chat_template_control.argument_value,
        )
        for candidate in matrix.candidates
    }
    assert controls == {
        "model-candidate-granite-3-3-2b-instruct": (
            CandidateChatTemplateControlMode.TEMPLATE_ARGUMENT_FALSE,
            "thinking",
            False,
        ),
        "model-candidate-qwen3-4b-instruct-2507": (
            CandidateChatTemplateControlMode.DEFAULT_NON_THINKING,
            None,
            None,
        ),
        "model-candidate-smollm3-3b": (
            CandidateChatTemplateControlMode.TEMPLATE_ARGUMENT_FALSE,
            "enable_thinking",
            False,
        ),
    }


def test_upstream_sources_are_revision_pinned_and_cross_linked() -> None:
    manifest = load_frozen_model_candidate_source_manifest(REPOSITORY_ROOT)
    matrix = load_frozen_model_candidate_matrix(REPOSITORY_ROOT)
    source_by_id = {source.source_id: source for source in manifest.sources}

    for candidate in (*matrix.candidates, *matrix.screened_out):
        source = source_by_id[candidate.source_id]
        assert source.candidate_id == candidate.candidate_id
        assert source.repository_id == candidate.repository_id
        assert source.revision == candidate.revision
        for reference in (
            source.repository_tree_reference,
            source.model_card_reference,
            source.license_reference,
        ):
            assert source.revision in reference
            assert "/main" not in reference
            assert "/refs/" not in reference


def test_remote_code_candidate_is_screened_out_before_expensive_probes() -> None:
    manifest = load_frozen_model_candidate_source_manifest(REPOSITORY_ROOT)
    matrix = load_frozen_model_candidate_matrix(REPOSITORY_ROOT)

    assert len(matrix.screened_out) == 1
    screened = matrix.screened_out[0]
    assert screened.candidate_id == "model-candidate-phi-4-mini-instruct"
    assert screened.reason_code is ScreenedOutModelReason.REMOTE_CODE_REQUIRED
    assert "trust_remote_code=True" in screened.reason
    source = next(item for item in manifest.sources if item.source_id == screened.source_id)
    assert "CUSTOM_CODE_TAG_OBSERVED" in source.declared_claims
    assert "REMOTE_CODE_REQUIRED_BY_TRANSFORMERS_EXAMPLE" in source.declared_claims


def test_matrix_contains_no_fabricated_measurements_or_final_selection() -> None:
    payload = json.loads(
        (REPOSITORY_ROOT / FROZEN_MODEL_CANDIDATE_MATRIX_PATH).read_text(encoding="utf-8")
    )
    forbidden_keys = {
        "rank",
        "score",
        "selected",
        "winner",
        "latency_milliseconds",
        "peak_gpu_memory_mb",
        "model_card_sha256",
        "license_evidence_sha256",
        "tokenizer_vocabulary_sha256",
        "tokenizer_configuration_sha256",
        "adapter_export_load",
    }

    assert _all_keys(payload).isdisjoint(forbidden_keys)
    assert payload["decision_status"] == "NO_MODEL_SELECTED"
    assert payload["evidence_status"] == "PREFLIGHT_ONLY"


def test_changed_matrix_bytes_are_rejected(tmp_path: Path) -> None:
    _copy_frozen_artifacts(tmp_path)
    matrix_path = tmp_path / FROZEN_MODEL_CANDIDATE_MATRIX_PATH
    payload = json.loads(matrix_path.read_text(encoding="utf-8"))
    payload["generation"]["repetitions"] = 2
    matrix_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(FrozenModelCandidateArtifactError, match="matrix digest changed"):
        load_frozen_model_candidate_matrix(tmp_path)


def test_changed_source_manifest_bytes_are_rejected(tmp_path: Path) -> None:
    _copy_frozen_artifacts(tmp_path)
    source_path = tmp_path / FROZEN_MODEL_CANDIDATE_SOURCE_MANIFEST_PATH
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    payload["sources"][0]["capture_status"] = "CAPTURED"
    source_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(FrozenModelCandidateArtifactError, match="source manifest digest changed"):
        load_frozen_model_candidate_source_manifest(tmp_path)
