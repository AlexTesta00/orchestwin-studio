"""Tests for immutable versioned persona profiles."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.twins.epistemics import (
    ConfidenceScore,
    EpistemicStatus,
    EvidenceReference,
    EvidenceSourceKind,
    HumanValidationRequirement,
    ObservationProvenance,
    ObservationValue,
    ProfileObservation,
)
from orchestwin.twins.personas import (
    PERSONA_PROFILE_SCHEMA_VERSION,
    PersonaConfirmationStatus,
    PersonaDecisionIssueCode,
    PersonaDecisionStatus,
    PersonaField,
    PersonaKind,
    PersonaProfile,
    PersonaProfileVersion,
    PersonaSource,
    confirm_proto_persona,
    create_owner_provided_persona,
    create_proto_persona,
    reject_proto_persona,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
PERSONA_ID = UUID("00000000-0000-4000-8000-000000000020")
VERSION_ID = UUID("00000000-0000-4000-8000-000000000030")
OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
CREATED_AT = datetime(
    2026,
    8,
    14,
    10,
    0,
    tzinfo=UTC,
)


def evidence(
    *,
    source_kind: EvidenceSourceKind,
    source_id: str,
    locator: str,
) -> EvidenceReference:
    """Create one deterministic evidence reference."""
    return EvidenceReference(
        source_kind=source_kind,
        source_id=source_id,
        source_version=1,
        content_hash=("a" * 64),
        locator=locator,
    )


def user_observation(
    field: PersonaField,
    value: ObservationValue,
) -> ProfileObservation:
    """Create one Project Brief-backed observation."""
    return ProfileObservation(
        observation_key=(field.observation_key),
        value=value,
        epistemic_status=(EpistemicStatus.USER_PROVIDED),
        confidence=ConfidenceScore(1.0),
        provenance=(
            ObservationProvenance.from_references(
                (
                    evidence(
                        source_kind=(EvidenceSourceKind.PROJECT_BRIEF),
                        source_id=("project-brief-version:1"),
                        locator=(f"brief.{field.value}"),
                    ),
                )
            )
        ),
        human_validation=(HumanValidationRequirement.NOT_REQUIRED),
    )


def inferred_observation(
    field: PersonaField,
    value: ObservationValue,
) -> ProfileObservation:
    """Create one inspectable fake-model inference."""
    return ProfileObservation(
        observation_key=(field.observation_key),
        value=value,
        epistemic_status=(EpistemicStatus.MODEL_INFERRED),
        confidence=ConfidenceScore(0.6),
        provenance=(
            ObservationProvenance.from_references(
                (
                    evidence(
                        source_kind=(EvidenceSourceKind.MODEL_OUTPUT),
                        source_id=("persona-proposal:1"),
                        locator=(f"personas.receptionist.{field.value}"),
                    ),
                )
            )
        ),
        human_validation=(HumanValidationRequirement.REQUIRED),
        rationale=(
            "The deterministic proposal derives this field from the approved Project Brief."
        ),
    )


def persona_observations() -> tuple[
    ProfileObservation,
    ...,
]:
    """Return a complete canonical persona observation set."""
    return (
        user_observation(
            PersonaField.ROLE,
            ObservationValue.from_text("Hotel receptionist"),
        ),
        user_observation(
            PersonaField.SUMMARY,
            ObservationValue.from_text("Front-desk staff coordinating guests and bookings."),
        ),
        user_observation(
            PersonaField.GOALS,
            ObservationValue.from_items(
                (
                    "Avoid booking conflicts",
                    "Check room availability quickly",
                )
            ),
        ),
        user_observation(
            PersonaField.CONTEXT_OF_USE,
            ObservationValue.from_text("Uses the application at the hotel front desk."),
        ),
    )


def proto_observations() -> tuple[
    ProfileObservation,
    ...,
]:
    """Return a complete proto-persona observation set."""
    return (
        user_observation(
            PersonaField.ROLE,
            ObservationValue.from_text("Hotel receptionist"),
        ),
        inferred_observation(
            PersonaField.SUMMARY,
            ObservationValue.from_text("Front-desk staff managing reservations and guests."),
        ),
        inferred_observation(
            PersonaField.GOALS,
            ObservationValue.from_items(
                (
                    "Reduce booking conflicts",
                    "Respond to guests quickly",
                )
            ),
        ),
        inferred_observation(
            PersonaField.CONTEXT_OF_USE,
            ObservationValue.abstained(
                "The Project Brief does not describe the physical workspace."
            ),
        ),
    )


def test_owner_provided_persona_remains_confirmed_and_user_owned() -> None:
    """Preserve the profile-level origin of an owner persona."""
    profile = create_owner_provided_persona(
        name="Hotel Receptionist",
        observations=reversed(persona_observations()),
    )

    assert profile.source is (PersonaSource.OWNER_PROVIDED)
    assert profile.kind is (PersonaKind.PERSONA)
    assert profile.confirmation_status is PersonaConfirmationStatus.CONFIRMED
    assert profile.requires_confirmation is False
    assert profile.ready_for_twin_creation is True
    assert tuple(observation.observation_key for observation in profile.observations) == tuple(
        field.observation_key
        for field in (
            PersonaField.ROLE,
            PersonaField.SUMMARY,
            PersonaField.GOALS,
            PersonaField.CONTEXT_OF_USE,
        )
    )


def test_system_proposal_is_a_pending_proto_persona() -> None:
    """Keep a generated candidate visibly provisional."""
    profile = create_proto_persona(
        name="Hotel Receptionist",
        observations=(proto_observations()),
    )

    assert profile.source is (PersonaSource.SYSTEM_PROPOSED)
    assert profile.kind is (PersonaKind.PROTO_PERSONA)
    assert profile.confirmation_status is PersonaConfirmationStatus.PENDING_CONFIRMATION
    assert profile.requires_confirmation is True
    assert profile.ready_for_twin_creation is False


def test_profile_rejects_inconsistent_origin_and_kind() -> None:
    """Prevent a generated profile from being labeled as owner persona."""
    with pytest.raises(
        ValueError,
        match=("source, kind, and confirmation"),
    ):
        PersonaProfile(
            name="Hotel Receptionist",
            source=(PersonaSource.SYSTEM_PROPOSED),
            kind=PersonaKind.PERSONA,
            confirmation_status=(PersonaConfirmationStatus.CONFIRMED),
            observations=(persona_observations()),
        )


def test_profile_requires_complete_unique_canonical_fields() -> None:
    """Protect required persona fields and deterministic order."""
    observations = persona_observations()

    with pytest.raises(
        ValueError,
        match="missing required fields",
    ):
        PersonaProfile(
            name="Hotel Receptionist",
            source=(PersonaSource.OWNER_PROVIDED),
            kind=PersonaKind.PERSONA,
            confirmation_status=(PersonaConfirmationStatus.CONFIRMED),
            observations=(observations[:-1]),
        )

    with pytest.raises(
        ValueError,
        match="unique fields",
    ):
        PersonaProfile(
            name="Hotel Receptionist",
            source=(PersonaSource.OWNER_PROVIDED),
            kind=PersonaKind.PERSONA,
            confirmation_status=(PersonaConfirmationStatus.CONFIRMED),
            observations=(
                observations[0],
                observations[0],
                *observations[1:],
            ),
        )

    with pytest.raises(
        ValueError,
        match="canonical field order",
    ):
        PersonaProfile(
            name="Hotel Receptionist",
            source=(PersonaSource.OWNER_PROVIDED),
            kind=PersonaKind.PERSONA,
            confirmation_status=(PersonaConfirmationStatus.CONFIRMED),
            observations=(
                observations[1],
                observations[0],
                *observations[2:],
            ),
        )


def test_profile_validates_field_value_shapes() -> None:
    """Keep role, summary, goals, and context structurally typed."""
    observations = persona_observations()
    invalid_goals = user_observation(
        PersonaField.GOALS,
        ObservationValue.from_text("Avoid booking conflicts"),
    )

    with pytest.raises(
        ValueError,
        match=("goals does not support TEXT"),
    ):
        create_owner_provided_persona(
            name="Hotel Receptionist",
            observations=(
                observations[0],
                observations[1],
                invalid_goals,
                observations[3],
            ),
        )


def test_age_range_is_optional_and_never_required_for_readiness() -> None:
    """Allow persona creation without demographic assumptions."""
    without_age = create_proto_persona(
        name="Hotel Receptionist",
        observations=(proto_observations()),
    )
    with_unknown_age = create_proto_persona(
        name="Hotel Receptionist",
        observations=(
            *proto_observations(),
            inferred_observation(
                PersonaField.AGE_RANGE,
                ObservationValue.unknown(),
            ),
        ),
    )

    assert without_age.observation_for(PersonaField.AGE_RANGE) is None
    assert with_unknown_age.observation_for(PersonaField.AGE_RANGE) is not None


def test_pending_proto_persona_can_be_confirmed_without_changing_origin() -> None:
    """Require confirmation while preserving proto-persona provenance."""
    pending = create_proto_persona(
        name="Hotel Receptionist",
        observations=(proto_observations()),
    )

    confirmed = confirm_proto_persona(pending)

    assert confirmed.status is (PersonaDecisionStatus.APPLIED)
    assert confirmed.issue is None
    assert confirmed.profile.source is (PersonaSource.SYSTEM_PROPOSED)
    assert confirmed.profile.kind is (PersonaKind.PROTO_PERSONA)
    assert confirmed.profile.confirmation_status is PersonaConfirmationStatus.CONFIRMED
    assert confirmed.profile.ready_for_twin_creation is True
    assert pending.requires_confirmation is True

    repeated = confirm_proto_persona(confirmed.profile)

    assert repeated.status is (PersonaDecisionStatus.NO_CHANGE)
    assert repeated.profile == confirmed.profile


def test_pending_proto_persona_rejection_requires_reason() -> None:
    """Keep owner rejection explicit and immutable."""
    pending = create_proto_persona(
        name="Hotel Receptionist",
        observations=(proto_observations()),
    )

    missing_reason = reject_proto_persona(
        pending,
        reason="   ",
    )

    assert missing_reason.status is (PersonaDecisionStatus.REJECTED)
    assert missing_reason.issue is (PersonaDecisionIssueCode.REASON_REQUIRED)
    assert missing_reason.profile == pending

    rejected = reject_proto_persona(
        pending,
        reason=("  This target-user group is not in scope. "),
    )

    assert rejected.status is (PersonaDecisionStatus.APPLIED)
    assert rejected.issue is None
    assert rejected.profile.confirmation_status is PersonaConfirmationStatus.REJECTED
    assert rejected.profile.rejection_reason == ("This target-user group is not in scope.")
    assert rejected.profile.ready_for_twin_creation is False

    confirm_rejected = confirm_proto_persona(rejected.profile)

    assert confirm_rejected.status is PersonaDecisionStatus.REJECTED
    assert confirm_rejected.issue is PersonaDecisionIssueCode.ALREADY_REJECTED


def test_owner_persona_cannot_enter_proto_persona_decisions() -> None:
    """Avoid relabeling owner personas through proposal decisions."""
    owner_profile = create_owner_provided_persona(
        name="Hotel Receptionist",
        observations=(persona_observations()),
    )

    confirmation = confirm_proto_persona(owner_profile)
    rejection = reject_proto_persona(
        owner_profile,
        reason="Not applicable.",
    )

    assert confirmation.status is (PersonaDecisionStatus.REJECTED)
    assert confirmation.issue is (PersonaDecisionIssueCode.NOT_A_PROTO_PERSONA)
    assert rejection.status is (PersonaDecisionStatus.REJECTED)
    assert rejection.issue is (PersonaDecisionIssueCode.NOT_A_PROTO_PERSONA)


def test_profile_snapshot_and_hash_are_deterministic() -> None:
    """Produce stable persona content for immutable persistence."""
    first = create_proto_persona(
        name="Hotel Receptionist",
        observations=(proto_observations()),
    )
    second = create_proto_persona(
        name="  Hotel   Receptionist ",
        observations=reversed(proto_observations()),
    )

    assert first == second
    assert first.to_snapshot()["schema_version"] == PERSONA_PROFILE_SCHEMA_VERSION
    assert json.loads(first.canonical_json()) == first.to_snapshot()
    assert first.content_hash == second.content_hash
    assert len(first.content_hash) == 64
    assert all(character in "0123456789abcdef" for character in first.content_hash)


def test_persona_version_protects_hash_timestamp_and_linear_lineage() -> None:
    """Represent persona history as immutable sequential versions."""
    profile = create_proto_persona(
        name="Hotel Receptionist",
        observations=(proto_observations()),
    )
    version = PersonaProfileVersion(
        id=VERSION_ID,
        project_id=PROJECT_ID,
        persona_id=PERSONA_ID,
        version_number=1,
        profile=profile,
        content_hash=(profile.content_hash),
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )

    assert version.to_snapshot()["profile"] == profile.to_snapshot()
    assert version.based_on_version_number is None

    confirmed = confirm_proto_persona(profile)
    assert confirmed.status is (PersonaDecisionStatus.APPLIED)

    next_version = PersonaProfileVersion(
        id=UUID("00000000-0000-4000-8000-000000000031"),
        project_id=PROJECT_ID,
        persona_id=PERSONA_ID,
        version_number=2,
        profile=confirmed.profile,
        content_hash=(confirmed.profile.content_hash),
        created_by_user_id=(OWNER_ID),
        created_at=CREATED_AT,
        based_on_version_number=1,
    )

    assert next_version.version_number == 2
    assert next_version.based_on_version_number == 1

    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        PersonaProfileVersion(
            id=VERSION_ID,
            project_id=PROJECT_ID,
            persona_id=PERSONA_ID,
            version_number=1,
            profile=profile,
            content_hash=(profile.content_hash),
            created_by_user_id=(OWNER_ID),
            created_at=(CREATED_AT.replace(tzinfo=None)),
        )

    with pytest.raises(
        ValueError,
        match="must match its profile",
    ):
        PersonaProfileVersion(
            id=VERSION_ID,
            project_id=PROJECT_ID,
            persona_id=PERSONA_ID,
            version_number=1,
            profile=profile,
            content_hash=("b" * 64),
            created_by_user_id=(OWNER_ID),
            created_at=CREATED_AT,
        )

    with pytest.raises(
        ValueError,
        match="immediately preceding",
    ):
        PersonaProfileVersion(
            id=VERSION_ID,
            project_id=PROJECT_ID,
            persona_id=PERSONA_ID,
            version_number=2,
            profile=profile,
            content_hash=(profile.content_hash),
            created_by_user_id=(OWNER_ID),
            created_at=CREATED_AT,
            based_on_version_number=None,
        )
