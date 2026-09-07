"""Tests for immutable model-spike candidates and license evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from orchestwin.training.dataset_examples import DatasetLanguage
from orchestwin.training.model_candidates import (
    ModelCandidateAvailability,
    ModelLicenseCompatibility,
    ModelLicenseEvidence,
    ModelQuantizationPath,
    ModelServingCompatibility,
    ModelTokenizerIdentity,
    create_model_benchmark_candidate,
)

CAPTURED_AT = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def _license(*, compatibility: ModelLicenseCompatibility = ModelLicenseCompatibility.COMPATIBLE):
    return ModelLicenseEvidence(
        license_id="Apache-2.0",
        source_url="https://example.test/models/license",
        source_revision="1" * 40,
        document_sha256="2" * 64,
        compatibility=compatibility,
        allows_adapter_redistribution=compatibility is ModelLicenseCompatibility.COMPATIBLE,
        allows_weight_redistribution=True,
        attribution_required=True,
        captured_at=CAPTURED_AT,
        notes="Captured from the exact model repository revision.",
    )


def _candidate(*, serving: tuple[ModelServingCompatibility, ...] | None = None):
    compatibilities = serving or (
        ModelServingCompatibility(
            runtime_id="openai-compatible-local",
            runtime_version="1.0.0",
            compatible=True,
            evidence_reference="spike:structured-generation",
            evidence_sha256="3" * 64,
        ),
        ModelServingCompatibility(
            runtime_id="unsloth",
            runtime_version="2026.8.22",
            compatible=True,
            evidence_reference="spike:adapter-export",
            evidence_sha256="4" * 64,
        ),
    )
    return create_model_benchmark_candidate(
        candidate_id="model-candidate-small-instruct",
        repository_id="example/small-instruct",
        revision="5" * 40,
        model_card_sha256="6" * 64,
        parameter_count_millions=3_000,
        context_limit_tokens=16_384,
        languages=(DatasetLanguage.ITALIAN, DatasetLanguage.ENGLISH),
        instruct_tuned=True,
        availability=ModelCandidateAvailability.AVAILABLE,
        tokenizer=ModelTokenizerIdentity(
            repository_id="example/small-instruct",
            revision="7" * 40,
            vocabulary_sha256="8" * 64,
            configuration_sha256="9" * 64,
        ),
        quantization=ModelQuantizationPath(
            implementation="bitsandbytes",
            format_name="nf4",
            bit_width=4,
            compute_dtype="bfloat16",
            double_quantization=True,
        ),
        license_evidence=_license(),
        serving_compatibility=compatibilities,
        created_at=CAPTURED_AT,
    )


def test_candidate_is_canonical_content_addressed_and_complete() -> None:
    candidate = _candidate()

    assert candidate.languages == (DatasetLanguage.ENGLISH, DatasetLanguage.ITALIAN)
    assert [item.runtime_id for item in candidate.serving_compatibility] == [
        "openai-compatible-local",
        "unsloth",
    ]
    assert candidate.content_hash == candidate.to_snapshot()["content_hash"]
    assert len(candidate.content_hash) == 64
    assert candidate.license_evidence.content_hash != candidate.content_hash


def test_candidate_hash_detects_any_evidence_change() -> None:
    candidate = _candidate()

    with pytest.raises(ValueError, match="content hash is inconsistent"):
        replace(candidate, context_limit_tokens=8_192)


def test_candidate_rejects_duplicate_runtime_evidence() -> None:
    evidence = ModelServingCompatibility(
        runtime_id="unsloth",
        runtime_version="2026.8.22",
        compatible=True,
        evidence_reference="spike:adapter-export",
        evidence_sha256="4" * 64,
    )

    with pytest.raises(ValueError, match="must be unique"):
        _candidate(serving=(evidence, evidence))


def test_license_compatibility_cannot_claim_redistribution_without_permission() -> None:
    with pytest.raises(ValueError, match="must allow adapter redistribution"):
        ModelLicenseEvidence(
            license_id="Custom",
            source_url="https://example.test/models/license",
            source_revision="a" * 40,
            document_sha256="b" * 64,
            compatibility=ModelLicenseCompatibility.COMPATIBLE,
            allows_adapter_redistribution=False,
            allows_weight_redistribution=False,
            attribution_required=True,
            captured_at=CAPTURED_AT,
        )


def test_candidate_requires_exact_revisions_and_timezone_aware_evidence() -> None:
    with pytest.raises(ValueError, match="exact lowercase hexadecimal revision"):
        ModelTokenizerIdentity(
            repository_id="example/tokenizer",
            revision="main",
            vocabulary_sha256="c" * 64,
            configuration_sha256="d" * 64,
        )

    with pytest.raises(ValueError, match="timezone-aware"):
        replace(_license(), captured_at=datetime(2026, 10, 13, 12, 0))
