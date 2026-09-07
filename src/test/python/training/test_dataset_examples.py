"""Tests for immutable evaluator-dataset examples."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest

from orchestwin.evaluation.findings import SyntheticFinding, SyntheticFindingCriterion
from orchestwin.training.dataset_examples import (
    DATASET_EXAMPLE_SCHEMA_VERSION,
    SIMULATED_FEEDBACK_DISCLAIMER,
    DatasetEvidenceReference,
    EvaluatorDatasetExample,
)


def test_dataset_example_preserves_complete_structured_training_unit(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    example = example_factory()

    snapshot = example.to_snapshot()

    assert snapshot["schema_version"] == DATASET_EXAMPLE_SCHEMA_VERSION
    assert snapshot["example_id"] == "UTE-000001"
    assert snapshot["language"] == "en"
    twin_reference = snapshot["user_twin_reference"]
    assert isinstance(twin_reference, dict)
    assert twin_reference["lifecycle_status"] == "OWNER_APPROVED_UT"
    expected_output = snapshot["expected_output"]
    assert isinstance(expected_output, dict)
    assert expected_output["disclaimer"] == SIMULATED_FEEDBACK_DISCLAIMER
    findings = expected_output["findings"]
    assert isinstance(findings, list)
    assert isinstance(findings[0], dict)
    assert findings[0]["epistemic_status"] == "MODEL_INFERRED"
    assert len(example.content_hash) == 64


def test_factory_canonicalizes_evidence_rubric_findings_and_profile_json(
    example_factory: Callable[..., EvaluatorDatasetExample],
    finding_factory: Callable[..., SyntheticFinding],
) -> None:
    first = example_factory()
    second_finding = finding_factory(
        finding_id="UTF-002",
        criterion=SyntheticFindingCriterion.TRUST,
        summary="The reason for the recommendation is not shown.",
    )
    second = example_factory(
        evidence=tuple(reversed(first.evidence)),
        rubric_criteria=tuple(reversed(first.rubric.criteria)),
        findings=(second_finding, first.expected_output.findings[0]),
        user_twin_profile={
            "validation_status": "OWNER_APPROVED_UT",
            "role": "Coordinates a time-sensitive operational workflow",
            "name": "Operations coordinator",
        },
    )
    third = example_factory(
        evidence=first.evidence,
        rubric_criteria=first.rubric.criteria,
        findings=(first.expected_output.findings[0], second_finding),
    )

    assert second.evidence == first.evidence
    assert second.rubric.criteria == first.rubric.criteria
    assert [item.finding_id for item in second.expected_output.findings] == ["UTF-001", "UTF-002"]
    assert second.user_twin_profile_json == first.user_twin_profile_json
    assert second.content_hash == third.content_hash


def test_dataset_example_rejects_noncanonical_or_inconsistent_values(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    example = example_factory()

    with pytest.raises(ValueError, match="UTE-NNNNNN"):
        example_factory(example_id="example-one")

    with pytest.raises(ValueError, match="canonical order"):
        replace(example, evidence=tuple(reversed(example.evidence)))

    with pytest.raises(ValueError, match="content hash is inconsistent"):
        replace(example, content_hash="0" * 64)


def test_evidence_reference_requires_flags_consistent_with_source_kind(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    evidence: DatasetEvidenceReference = example_factory().evidence[0]

    with pytest.raises(ValueError, match="empirical flag"):
        replace(evidence, is_target_user_empirical_evidence=True)
