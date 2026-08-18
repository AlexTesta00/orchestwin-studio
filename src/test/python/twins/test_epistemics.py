"""Tests for User Twin epistemic provenance primitives."""

from __future__ import annotations

import json
import math

import pytest

from orchestwin.twins.epistemics import (
    ConfidenceScore,
    EpistemicStatus,
    EvidenceReference,
    EvidenceSourceKind,
    HumanValidationRequirement,
    ObservationProvenance,
    ObservationValue,
    ObservationValueKind,
    ProfileObservation,
)

PROJECT_BRIEF_HASH = "a" * 64


def project_brief_evidence() -> EvidenceReference:
    """Create one deterministic Project Brief evidence reference."""
    return EvidenceReference(
        source_kind=(EvidenceSourceKind.PROJECT_BRIEF),
        source_id=("project-brief-version:1"),
        source_version=1,
        content_hash=(PROJECT_BRIEF_HASH),
        locator=("brief.target_users"),
        summary=("Target users supplied in the approved Project Brief."),
    )


def model_output_evidence() -> EvidenceReference:
    """Create one deterministic fake-model output reference."""
    return EvidenceReference(
        source_kind=(EvidenceSourceKind.MODEL_OUTPUT),
        source_id=("user-modeling-proposal:1"),
        source_version=1,
        locator=("personas.hotel_receptionist.goals"),
        summary=("Deterministic fake proposal output."),
    )


def test_epistemic_statuses_match_project_policy() -> None:
    """Expose only the epistemic states permitted by the project."""
    assert tuple(EpistemicStatus) == (
        EpistemicStatus.USER_PROVIDED,
        EpistemicStatus.EMPIRICALLY_SUPPORTED,
        EpistemicStatus.HUMAN_VALIDATED,
        EpistemicStatus.MODEL_INFERRED,
        EpistemicStatus.UNSUPPORTED_ASSUMPTION,
    )


@pytest.mark.parametrize(
    "value",
    (
        0.0,
        0.5,
        1.0,
    ),
)
def test_confidence_accepts_inclusive_unit_interval(
    value: float,
) -> None:
    """Accept finite confidence values from zero through one."""
    confidence = ConfidenceScore(value)

    assert confidence.value == value
    assert confidence.to_snapshot() == value


@pytest.mark.parametrize(
    (
        "value",
        "expected_message",
    ),
    (
        (
            -0.01,
            "between 0.0 and 1.0",
        ),
        (
            1.01,
            "between 0.0 and 1.0",
        ),
        (
            math.nan,
            "must be finite",
        ),
        (
            math.inf,
            "must be finite",
        ),
        (
            -math.inf,
            "must be finite",
        ),
    ),
)
def test_confidence_rejects_invalid_numeric_values(
    value: float,
    expected_message: str,
) -> None:
    """Reject non-finite or out-of-range confidence values."""
    with pytest.raises(
        ValueError,
        match=expected_message,
    ):
        ConfidenceScore(value)


def test_confidence_rejects_boolean_values() -> None:
    """Prevent booleans from being interpreted as confidence."""
    with pytest.raises(
        TypeError,
        match="real number",
    ):
        ConfidenceScore(True)


def test_evidence_reference_validates_auditable_metadata() -> None:
    """Keep source identity, version, hash, and locator inspectable."""
    reference = project_brief_evidence()

    assert reference.to_snapshot() == {
        "source_kind": ("PROJECT_BRIEF"),
        "source_id": ("project-brief-version:1"),
        "source_version": 1,
        "content_hash": (PROJECT_BRIEF_HASH),
        "locator": ("brief.target_users"),
        "summary": ("Target users supplied in the approved Project Brief."),
    }

    with pytest.raises(
        ValueError,
        match="source version",
    ):
        EvidenceReference(
            source_kind=(EvidenceSourceKind.PROJECT_BRIEF),
            source_id=("project-brief"),
            source_version=0,
        )

    with pytest.raises(
        ValueError,
        match="SHA-256",
    ):
        EvidenceReference(
            source_kind=(EvidenceSourceKind.PROJECT_BRIEF),
            source_id=("project-brief"),
            content_hash=("not-a-digest"),
        )


def test_provenance_requires_unique_references() -> None:
    """Require inspectable and duplicate-free provenance."""
    reference = project_brief_evidence()

    with pytest.raises(
        ValueError,
        match="must not be empty",
    ):
        ObservationProvenance(references=())

    with pytest.raises(
        ValueError,
        match="must be unique",
    ):
        ObservationProvenance(
            references=(
                reference,
                reference,
            )
        )


def test_observation_values_preserve_text_items_unknown_and_abstention() -> None:
    """Represent values and uncertainty without conflation."""
    text = ObservationValue.from_text("  Hotel   receptionist  ")
    items = ObservationValue.from_items(
        (
            "  Manage reservations ",
            "Check room availability",
        )
    )
    unknown = ObservationValue.unknown()
    abstained = ObservationValue.abstained("  The available evidence is insufficient. ")

    assert text.to_snapshot() == {
        "kind": "TEXT",
        "text": "Hotel receptionist",
        "items": [],
        "reason": None,
    }
    assert items.to_snapshot() == {
        "kind": "ITEMS",
        "text": None,
        "items": [
            "Manage reservations",
            "Check room availability",
        ],
        "reason": None,
    }
    assert unknown.kind is (ObservationValueKind.UNKNOWN)
    assert abstained.to_snapshot() == {
        "kind": "ABSTAINED",
        "text": None,
        "items": [],
        "reason": ("The available evidence is insufficient."),
    }


def test_observation_items_are_non_empty_and_unique() -> None:
    """Reject empty and duplicate item collections."""
    with pytest.raises(
        ValueError,
        match="non-empty items",
    ):
        ObservationValue.from_items(())

    with pytest.raises(
        ValueError,
        match="must be unique",
    ):
        ObservationValue.from_items(
            (
                "Hotel staff",
                " Hotel   staff ",
            )
        )


def test_user_provided_observation_exposes_epistemic_metadata() -> None:
    """Keep provenance, status, confidence, and validation explicit."""
    observation = ProfileObservation(
        observation_key=("target_users.primary_role"),
        value=(ObservationValue.from_text("Hotel receptionist")),
        epistemic_status=(EpistemicStatus.USER_PROVIDED),
        confidence=ConfidenceScore(1.0),
        provenance=(ObservationProvenance.from_references((project_brief_evidence(),))),
        human_validation=(HumanValidationRequirement.NOT_REQUIRED),
    )

    assert observation.requires_human_validation is False

    serialized = json.dumps(
        observation.to_snapshot(),
        sort_keys=True,
    )

    assert json.loads(serialized) == observation.to_snapshot()


def test_model_inference_requires_rationale_and_human_validation() -> None:
    """Keep model-generated claims inspectable and reviewable."""
    provenance = ObservationProvenance.from_references((model_output_evidence(),))

    with pytest.raises(
        ValueError,
        match="require human validation",
    ):
        ProfileObservation(
            observation_key=("goals.reduce_booking_conflicts"),
            value=(ObservationValue.from_text("Reduce booking conflicts")),
            epistemic_status=(EpistemicStatus.MODEL_INFERRED),
            confidence=ConfidenceScore(0.7),
            provenance=provenance,
            human_validation=(HumanValidationRequirement.NOT_REQUIRED),
            rationale=("The goal is inferred from the described workflow."),
        )

    with pytest.raises(
        ValueError,
        match="require a rationale",
    ):
        ProfileObservation(
            observation_key=("goals.reduce_booking_conflicts"),
            value=(ObservationValue.from_text("Reduce booking conflicts")),
            epistemic_status=(EpistemicStatus.MODEL_INFERRED),
            confidence=ConfidenceScore(0.7),
            provenance=provenance,
            human_validation=(HumanValidationRequirement.REQUIRED),
        )

    valid_observation = ProfileObservation(
        observation_key=("goals.reduce_booking_conflicts"),
        value=(ObservationValue.from_text("Reduce booking conflicts")),
        epistemic_status=(EpistemicStatus.MODEL_INFERRED),
        confidence=ConfidenceScore(0.7),
        provenance=provenance,
        human_validation=(HumanValidationRequirement.REQUIRED),
        rationale=("The goal is inferred from the described workflow."),
    )

    assert valid_observation.requires_human_validation is True


def test_unsupported_assumption_requires_a_tentative_value() -> None:
    """Do not label an unknown value as a concrete assumption."""
    with pytest.raises(
        ValueError,
        match="tentative value",
    ):
        ProfileObservation(
            observation_key=("trust_concerns.unknown"),
            value=(ObservationValue.unknown()),
            epistemic_status=(EpistemicStatus.UNSUPPORTED_ASSUMPTION),
            confidence=ConfidenceScore(0.2),
            provenance=(ObservationProvenance.from_references((model_output_evidence(),))),
            human_validation=(HumanValidationRequirement.REQUIRED),
            rationale=("No direct evidence supports a specific trust concern."),
        )
