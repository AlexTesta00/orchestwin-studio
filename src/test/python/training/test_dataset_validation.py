"""Tests for dataset epistemic and provenance validation."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from orchestwin.evaluation.findings import (
    SyntheticFinding,
    SyntheticFindingEpistemicStatus,
)
from orchestwin.training.dataset_examples import (
    DatasetUserTwinReference,
    EvaluatorDatasetExample,
)
from orchestwin.training.dataset_validation import (
    DatasetValidationCode,
    validate_dataset_example,
)
from orchestwin.twins.user_twins import UserTwinLifecycleStatus


def _codes(example: EvaluatorDatasetExample) -> set[DatasetValidationCode]:
    return {issue.code for issue in validate_dataset_example(example).issues}


def test_valid_example_passes_epistemic_and_reference_validation(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    first = validate_dataset_example(example_factory())
    second = validate_dataset_example(example_factory())

    assert first.accepted is True
    assert first.issues == ()
    assert first.content_hash == second.content_hash


def test_validator_rejects_unknown_evidence_and_exact_identity_mismatches(
    example_factory: Callable[..., EvaluatorDatasetExample],
    finding_factory: Callable[..., SyntheticFinding],
) -> None:
    finding = finding_factory(
        twin_id=UUID("00000000-0000-4000-8000-000000119991"),
        artifact_version=6,
        evidence_refs=("missing-reference",),
    )
    report = validate_dataset_example(example_factory(findings=(finding,)))

    assert report.accepted is False
    assert {
        DatasetValidationCode.UNKNOWN_EVIDENCE_REFERENCE,
        DatasetValidationCode.TWIN_REFERENCE_MISMATCH,
        DatasetValidationCode.ARTIFACT_REFERENCE_MISMATCH,
    } <= {issue.code for issue in report.issues}


def test_validator_rejects_false_empirical_and_human_validation_claims(
    example_factory: Callable[..., EvaluatorDatasetExample],
    finding_factory: Callable[..., SyntheticFinding],
) -> None:
    empirical = finding_factory(
        epistemic_status=SyntheticFindingEpistemicStatus.EMPIRICALLY_SUPPORTED,
        requires_human_validation=False,
    )
    validated = finding_factory(
        epistemic_status=SyntheticFindingEpistemicStatus.HUMAN_VALIDATED,
        requires_human_validation=False,
    )

    assert DatasetValidationCode.FALSE_EMPIRICAL_FINDING in _codes(
        example_factory(findings=(empirical,))
    )
    assert DatasetValidationCode.FALSE_HUMAN_VALIDATION in _codes(
        example_factory(findings=(validated,))
    )


def test_validator_rejects_empirical_profile_status_without_empirical_sources(
    example_factory: Callable[..., EvaluatorDatasetExample],
) -> None:
    original = example_factory()
    empirical_reference = DatasetUserTwinReference(
        twin_id=original.user_twin_reference.twin_id,
        version_number=original.user_twin_reference.version_number,
        content_hash=original.user_twin_reference.content_hash,
        lifecycle_status=UserTwinLifecycleStatus.EMPIRICALLY_GROUNDED_UT,
    )
    example = example_factory(
        user_twin_reference=empirical_reference,
        user_twin_profile={
            "name": "Operations coordinator",
            "role": "Coordinates a time-sensitive operational workflow",
            "validation_status": "EMPIRICALLY_GROUNDED_UT",
        },
    )

    assert DatasetValidationCode.FALSE_EMPIRICAL_PROFILE_STATUS in _codes(example)


def test_validator_rejects_profile_status_and_rubric_mismatches(
    example_factory: Callable[..., EvaluatorDatasetExample],
    finding_factory: Callable[..., SyntheticFinding],
) -> None:
    # Exercise the mismatch using the canonical rubric from the factory.
    assert DatasetValidationCode.PROFILE_STATUS_MISMATCH in _codes(
        example_factory(
            user_twin_profile={
                "name": "Operations coordinator",
                "role": "Coordinates a time-sensitive operational workflow",
                "validation_status": "PROTO_UT",
            }
        )
    )
