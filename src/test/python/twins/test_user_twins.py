"""Tests for immutable User Twin profiles and modeling snapshots."""

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
    PersonaField,
    PersonaProfileVersion,
    create_owner_provided_persona,
    create_proto_persona,
)
from orchestwin.twins.user_twins import (
    MAX_PROJECT_USER_TWINS,
    USER_MODELING_SNAPSHOT_SCHEMA_VERSION,
    USER_TWIN_PROFILE_SCHEMA_VERSION,
    ConfirmedPersonaReference,
    UserModelingSnapshot,
    UserModelingSnapshotVersion,
    UserTwinField,
    UserTwinLifecycleStatus,
    UserTwinProfile,
    UserTwinProfileVersion,
    VersionedArtifactReference,
    create_project_grounded_user_twin,
    create_user_modeling_snapshot,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
BRIEF_ID = UUID("00000000-0000-4000-8000-000000000020")
TEAM_ID = UUID("00000000-0000-4000-8000-000000000030")
SNAPSHOT_ID = UUID("00000000-0000-4000-8000-000000000040")

BRIEF_HASH = "b" * 64
TEAM_HASH = "c" * 64
CATALOG_HASH = "d" * 64

CREATED_AT = datetime(
    2026,
    8,
    14,
    12,
    0,
    tzinfo=UTC,
)

BRIEF_REFERENCE = VersionedArtifactReference(
    artifact_id=BRIEF_ID,
    version_number=4,
    content_hash=BRIEF_HASH,
)

TEAM_REFERENCE = VersionedArtifactReference(
    artifact_id=TEAM_ID,
    version_number=2,
    content_hash=TEAM_HASH,
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
        content_hash="a" * 64,
        locator=locator,
    )


def user_observation(
    observation_key: str,
    value: ObservationValue,
) -> ProfileObservation:
    """Create one Project Brief-backed observation."""
    return ProfileObservation(
        observation_key=(observation_key),
        value=value,
        epistemic_status=(EpistemicStatus.USER_PROVIDED),
        confidence=ConfidenceScore(1.0),
        provenance=(
            ObservationProvenance.from_references(
                (
                    evidence(
                        source_kind=(EvidenceSourceKind.PROJECT_BRIEF),
                        source_id=("project-brief-version:4"),
                        locator=(observation_key),
                    ),
                )
            )
        ),
        human_validation=(HumanValidationRequirement.NOT_REQUIRED),
    )


def inferred_observation(
    field: UserTwinField,
    value: ObservationValue,
) -> ProfileObservation:
    """Create one inspectable deterministic-model observation."""
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
                        source_id=("user-modeling-proposal:1"),
                        locator=(field.observation_key),
                    ),
                )
            )
        ),
        human_validation=(HumanValidationRequirement.REQUIRED),
        rationale=(
            "The deterministic proposal derives this observation from the approved project context."
        ),
    )


def persona_observations() -> tuple[
    ProfileObservation,
    ...,
]:
    """Return one complete owner-provided persona."""
    return (
        user_observation(
            PersonaField.ROLE.observation_key,
            ObservationValue.from_text("Hotel receptionist"),
        ),
        user_observation(
            PersonaField.SUMMARY.observation_key,
            ObservationValue.from_text("Front-desk staff coordinating guests and reservations."),
        ),
        user_observation(
            PersonaField.GOALS.observation_key,
            ObservationValue.from_items(
                (
                    "Avoid booking conflicts",
                    "Serve guests quickly",
                )
            ),
        ),
        user_observation(
            PersonaField.CONTEXT_OF_USE.observation_key,
            ObservationValue.from_text("Uses the application at the hotel front desk."),
        ),
    )


def proto_persona_observations() -> tuple[
    ProfileObservation,
    ...,
]:
    """Return a pending proto-persona observation set."""
    return persona_observations()


def persona_version(
    index: int = 1,
) -> PersonaProfileVersion:
    """Create one confirmed persona version."""
    profile = create_owner_provided_persona(
        name=(f"Hotel Receptionist {index}"),
        observations=(persona_observations()),
    )

    return PersonaProfileVersion(
        id=UUID(int=1000 + index),
        project_id=PROJECT_ID,
        persona_id=UUID(int=2000 + index),
        version_number=1,
        profile=profile,
        content_hash=(profile.content_hash),
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )


def pending_persona_version() -> PersonaProfileVersion:
    """Create one unconfirmed proto-persona version."""
    profile = create_proto_persona(
        name="Pending Receptionist",
        observations=(proto_persona_observations()),
    )

    return PersonaProfileVersion(
        id=UUID(int=3001),
        project_id=PROJECT_ID,
        persona_id=UUID(int=3002),
        version_number=1,
        profile=profile,
        content_hash=(profile.content_hash),
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )


def complete_twin_observations(
    *,
    include_age_range: bool = False,
) -> tuple[
    ProfileObservation,
    ...,
]:
    """Return every required User Twin field."""
    observations: list[ProfileObservation] = [
        user_observation(
            UserTwinField.ROLE.observation_key,
            ObservationValue.from_text("Hotel receptionist"),
        ),
        inferred_observation(
            UserTwinField.EXPERTISE,
            ObservationValue.from_items(
                (
                    "Reservation management",
                    "Guest assistance",
                )
            ),
        ),
        inferred_observation(
            UserTwinField.GOALS,
            ObservationValue.from_items(
                (
                    "Avoid booking conflicts",
                    "Serve guests quickly",
                )
            ),
        ),
        inferred_observation(
            UserTwinField.RECURRING_TASKS,
            ObservationValue.from_items(
                (
                    "Check room availability",
                    "Create reservations",
                )
            ),
        ),
        inferred_observation(
            UserTwinField.CONTEXT_OF_USE,
            ObservationValue.from_text("Works at a busy hotel front desk."),
        ),
        inferred_observation(
            UserTwinField.INFORMATION_NEEDS,
            ObservationValue.from_items(
                (
                    "Current room availability",
                    "Guest reservation details",
                )
            ),
        ),
        inferred_observation(
            UserTwinField.DECISION_CRITERIA,
            ObservationValue.from_items(
                (
                    "Room availability",
                    "Guest requirements",
                )
            ),
        ),
        inferred_observation(
            UserTwinField.PREFERRED_VOCABULARY,
            ObservationValue.from_items(
                (
                    "Reservation",
                    "Check-in",
                    "Room status",
                )
            ),
        ),
        inferred_observation(
            UserTwinField.FRUSTRATIONS,
            ObservationValue.from_items(
                (
                    "Duplicate data entry",
                    "Slow availability checks",
                )
            ),
        ),
        inferred_observation(
            UserTwinField.PAIN_POINTS,
            ObservationValue.from_items(
                (
                    "Disconnected spreadsheets",
                    "Booking conflicts",
                )
            ),
        ),
        inferred_observation(
            UserTwinField.TRUST_CONCERNS,
            ObservationValue.from_items(("Outdated room information",)),
        ),
        inferred_observation(
            UserTwinField.ACCESSIBILITY_NEEDS,
            ObservationValue.abstained(
                "The approved brief does not provide accessibility evidence for this user group."
            ),
        ),
        inferred_observation(
            UserTwinField.OPERATIONAL_CONSTRAINTS,
            ObservationValue.from_items(
                (
                    "Frequent interruptions",
                    "Time-sensitive guest requests",
                )
            ),
        ),
        inferred_observation(
            UserTwinField.TECHNICAL_LITERACY,
            ObservationValue.from_text("Comfortable with standard office and hotel software."),
        ),
        inferred_observation(
            UserTwinField.RISK_SENSITIVITY,
            ObservationValue.from_text("Highly sensitive to booking and guest-data errors."),
        ),
        inferred_observation(
            UserTwinField.ASSUMPTIONS,
            ObservationValue.from_items(("The user works primarily from a desktop workstation.",)),
        ),
    ]

    if include_age_range:
        observations.append(
            user_observation(
                UserTwinField.AGE_RANGE.observation_key,
                ObservationValue.unknown(),
            )
        )

    return tuple(observations)


def twin_profile(
    *,
    grounded_persona: (PersonaProfileVersion | None) = None,
    include_age_range: bool = False,
) -> UserTwinProfile:
    """Create one project-grounded User Twin profile."""
    resolved_persona = grounded_persona if grounded_persona is not None else persona_version()

    return create_project_grounded_user_twin(
        name="Receptionist Twin",
        persona_version=(resolved_persona),
        project_brief_reference=(BRIEF_REFERENCE),
        agent_team_reference=(TEAM_REFERENCE),
        catalog_version=1,
        catalog_content_hash=(CATALOG_HASH),
        observations=reversed(complete_twin_observations(include_age_range=(include_age_range))),
    )


def twin_version(
    index: int = 1,
    *,
    grounded_persona: (PersonaProfileVersion | None) = None,
    profile: UserTwinProfile | None = None,
) -> UserTwinProfileVersion:
    """Create one immutable User Twin version."""
    resolved_persona = grounded_persona if grounded_persona is not None else persona_version(index)
    resolved_profile = (
        profile if profile is not None else twin_profile(grounded_persona=(resolved_persona))
    )

    return UserTwinProfileVersion(
        id=UUID(int=4000 + index),
        project_id=PROJECT_ID,
        twin_id=UUID(int=5000 + index),
        version_number=1,
        profile=resolved_profile,
        content_hash=(resolved_profile.content_hash),
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )


def modeling_pair(
    index: int,
) -> tuple[
    PersonaProfileVersion,
    UserTwinProfileVersion,
]:
    """Create matching persona and User Twin versions."""
    persona = persona_version(index)
    twin = twin_version(
        index,
        grounded_persona=persona,
    )

    return (
        persona,
        twin,
    )


def test_lifecycle_statuses_match_project_policy() -> None:
    """Expose only the lifecycle statuses required by the project."""
    assert tuple(UserTwinLifecycleStatus) == (
        UserTwinLifecycleStatus.PROTO_UT,
        UserTwinLifecycleStatus.PROJECT_GROUNDED_UT,
        UserTwinLifecycleStatus.OWNER_APPROVED_UT,
        UserTwinLifecycleStatus.EMPIRICALLY_GROUNDED_UT,
        UserTwinLifecycleStatus.EMPIRICALLY_VALIDATED_UT,
    )


def test_project_grounded_profile_preserves_exact_context() -> None:
    """Keep persona, brief, team, and catalog provenance inspectable."""
    persona = persona_version()
    profile = twin_profile(grounded_persona=persona)

    assert profile.validation_status is UserTwinLifecycleStatus.PROJECT_GROUNDED_UT
    assert profile.persona_reference == (ConfirmedPersonaReference.from_version(persona))
    assert profile.project_brief_reference == BRIEF_REFERENCE
    assert profile.agent_team_reference == TEAM_REFERENCE
    assert profile.catalog_version == 1
    assert profile.catalog_content_hash == CATALOG_HASH
    assert profile.requires_human_validation is True


def test_unconfirmed_persona_cannot_ground_user_twin() -> None:
    """Require explicit persona confirmation before twin creation."""
    with pytest.raises(
        ValueError,
        match="confirmed persona",
    ):
        twin_profile(grounded_persona=(pending_persona_version()))


def test_profile_requires_every_minimum_field() -> None:
    """Require all non-optional fields in the User Twin profile."""
    persona = persona_version()
    observations = tuple(
        observation
        for observation in complete_twin_observations()
        if (observation.observation_key != UserTwinField.ASSUMPTIONS.observation_key)
    )

    with pytest.raises(
        ValueError,
        match="missing required fields",
    ):
        create_project_grounded_user_twin(
            name="Receptionist Twin",
            persona_version=persona,
            project_brief_reference=(BRIEF_REFERENCE),
            agent_team_reference=(TEAM_REFERENCE),
            catalog_version=1,
            catalog_content_hash=(CATALOG_HASH),
            observations=observations,
        )


def test_age_range_is_optional_and_may_be_unknown() -> None:
    """Avoid creating demographic assumptions when age is unavailable."""
    without_age = twin_profile()
    with_unknown_age = twin_profile(include_age_range=True)

    assert without_age.observation_for(UserTwinField.AGE_RANGE) is None
    assert with_unknown_age.observation_for(UserTwinField.AGE_RANGE) is not None
    assert UserTwinField.AGE_RANGE in with_unknown_age.unresolved_fields


def test_profile_validates_field_value_shapes() -> None:
    """Keep list-oriented and scalar fields structurally distinct."""
    persona = persona_version()
    invalid_expertise = inferred_observation(
        UserTwinField.EXPERTISE,
        ObservationValue.from_text("Reservation management"),
    )
    observations = tuple(
        invalid_expertise
        if (observation.observation_key == UserTwinField.EXPERTISE.observation_key)
        else observation
        for observation in complete_twin_observations()
    )

    with pytest.raises(
        ValueError,
        match=("expertise does not support TEXT"),
    ):
        create_project_grounded_user_twin(
            name="Receptionist Twin",
            persona_version=persona,
            project_brief_reference=(BRIEF_REFERENCE),
            agent_team_reference=(TEAM_REFERENCE),
            catalog_version=1,
            catalog_content_hash=(CATALOG_HASH),
            observations=observations,
        )


def test_profile_rejects_duplicate_and_noncanonical_fields() -> None:
    """Protect unique fields and deterministic declaration order."""
    persona = persona_version()
    observations = complete_twin_observations()

    with pytest.raises(
        ValueError,
        match="unique fields",
    ):
        create_project_grounded_user_twin(
            name="Receptionist Twin",
            persona_version=persona,
            project_brief_reference=(BRIEF_REFERENCE),
            agent_team_reference=(TEAM_REFERENCE),
            catalog_version=1,
            catalog_content_hash=(CATALOG_HASH),
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
        UserTwinProfile(
            name="Receptionist Twin",
            persona_reference=(ConfirmedPersonaReference.from_version(persona)),
            project_brief_reference=(BRIEF_REFERENCE),
            agent_team_reference=(TEAM_REFERENCE),
            catalog_version=1,
            catalog_content_hash=(CATALOG_HASH),
            validation_status=(UserTwinLifecycleStatus.PROJECT_GROUNDED_UT),
            observations=tuple(reversed(observations)),
        )


def test_profile_snapshot_and_hash_are_deterministic() -> None:
    """Produce reproducible content for immutable persistence."""
    persona = persona_version()
    first = twin_profile(grounded_persona=persona)
    second = create_project_grounded_user_twin(
        name=("  Receptionist   Twin "),
        persona_version=persona,
        project_brief_reference=(BRIEF_REFERENCE),
        agent_team_reference=(TEAM_REFERENCE),
        catalog_version=1,
        catalog_content_hash=(CATALOG_HASH),
        observations=(complete_twin_observations()),
    )

    assert first == second
    assert first.to_snapshot()["schema_version"] == USER_TWIN_PROFILE_SCHEMA_VERSION
    assert json.loads(first.canonical_json()) == first.to_snapshot()
    assert first.content_hash == second.content_hash
    assert len(first.content_hash) == 64


def test_user_twin_version_protects_hash_timestamp_and_lineage() -> None:
    """Represent User Twin history as immutable sequential versions."""
    profile = twin_profile()
    version = twin_version(profile=profile)

    assert version.based_on_version_number is None
    assert version.to_snapshot()["profile"] == profile.to_snapshot()

    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        UserTwinProfileVersion(
            id=version.id,
            project_id=PROJECT_ID,
            twin_id=version.twin_id,
            version_number=1,
            profile=profile,
            content_hash=(profile.content_hash),
            created_by_user_id=OWNER_ID,
            created_at=(CREATED_AT.replace(tzinfo=None)),
        )

    with pytest.raises(
        ValueError,
        match="must match its profile",
    ):
        UserTwinProfileVersion(
            id=version.id,
            project_id=PROJECT_ID,
            twin_id=version.twin_id,
            version_number=1,
            profile=profile,
            content_hash="f" * 64,
            created_by_user_id=OWNER_ID,
            created_at=CREATED_AT,
        )

    with pytest.raises(
        ValueError,
        match="immediately preceding",
    ):
        UserTwinProfileVersion(
            id=version.id,
            project_id=PROJECT_ID,
            twin_id=version.twin_id,
            version_number=2,
            profile=profile,
            content_hash=(profile.content_hash),
            created_by_user_id=OWNER_ID,
            created_at=CREATED_AT,
            based_on_version_number=None,
        )


def test_snapshot_requires_between_one_and_four_twins() -> None:
    """Enforce the project-specific User Twin cardinality."""
    with pytest.raises(
        ValueError,
        match=("between one and four"),
    ):
        create_user_modeling_snapshot(
            project_id=PROJECT_ID,
            project_brief_reference=(BRIEF_REFERENCE),
            agent_team_reference=(TEAM_REFERENCE),
            catalog_version=1,
            catalog_content_hash=(CATALOG_HASH),
            persona_versions=(),
            twin_versions=(),
        )

    pairs = tuple(
        modeling_pair(index)
        for index in range(
            1,
            MAX_PROJECT_USER_TWINS + 2,
        )
    )

    with pytest.raises(
        ValueError,
        match=("between one and four"),
    ):
        create_user_modeling_snapshot(
            project_id=PROJECT_ID,
            project_brief_reference=(BRIEF_REFERENCE),
            agent_team_reference=(TEAM_REFERENCE),
            catalog_version=1,
            catalog_content_hash=(CATALOG_HASH),
            persona_versions=(pair[0] for pair in pairs),
            twin_versions=(pair[1] for pair in pairs),
        )


def test_snapshot_aligns_personas_twins_and_grounding() -> None:
    """Require exact persona and project-context references."""
    persona, twin = modeling_pair(1)
    snapshot = create_user_modeling_snapshot(
        project_id=PROJECT_ID,
        project_brief_reference=(BRIEF_REFERENCE),
        agent_team_reference=(TEAM_REFERENCE),
        catalog_version=1,
        catalog_content_hash=(CATALOG_HASH),
        persona_versions=(persona,),
        twin_versions=(twin,),
    )

    assert snapshot.persona_count == 1
    assert snapshot.twin_count == 1
    assert snapshot.twin_versions[
        0
    ].profile.persona_reference == ConfirmedPersonaReference.from_version(persona)
    assert snapshot.to_snapshot()["schema_version"] == USER_MODELING_SNAPSHOT_SCHEMA_VERSION


def test_snapshot_rejects_missing_persona_and_context_mismatch() -> None:
    """Keep snapshot membership and grounding internally consistent."""
    persona, twin = modeling_pair(1)

    with pytest.raises(
        ValueError,
        match=("one confirmed persona version"),
    ):
        create_user_modeling_snapshot(
            project_id=PROJECT_ID,
            project_brief_reference=(BRIEF_REFERENCE),
            agent_team_reference=(TEAM_REFERENCE),
            catalog_version=1,
            catalog_content_hash=(CATALOG_HASH),
            persona_versions=(),
            twin_versions=(twin,),
        )

    other_team = VersionedArtifactReference(
        artifact_id=UUID(int=9000),
        version_number=3,
        content_hash="e" * 64,
    )
    mismatched_profile = create_project_grounded_user_twin(
        name="Receptionist Twin",
        persona_version=persona,
        project_brief_reference=(BRIEF_REFERENCE),
        agent_team_reference=(other_team),
        catalog_version=1,
        catalog_content_hash=(CATALOG_HASH),
        observations=(complete_twin_observations()),
    )
    mismatched_twin = twin_version(
        grounded_persona=persona,
        profile=mismatched_profile,
    )

    with pytest.raises(
        ValueError,
        match=("same Project Brief and Agent Team"),
    ):
        create_user_modeling_snapshot(
            project_id=PROJECT_ID,
            project_brief_reference=(BRIEF_REFERENCE),
            agent_team_reference=(TEAM_REFERENCE),
            catalog_version=1,
            catalog_content_hash=(CATALOG_HASH),
            persona_versions=(persona,),
            twin_versions=(mismatched_twin,),
        )


def test_snapshot_order_and_hash_are_deterministic() -> None:
    """Canonicalize persona and User Twin identity ordering."""
    first_pair = modeling_pair(1)
    second_pair = modeling_pair(2)

    first = create_user_modeling_snapshot(
        project_id=PROJECT_ID,
        project_brief_reference=(BRIEF_REFERENCE),
        agent_team_reference=(TEAM_REFERENCE),
        catalog_version=1,
        catalog_content_hash=(CATALOG_HASH),
        persona_versions=(
            second_pair[0],
            first_pair[0],
        ),
        twin_versions=(
            second_pair[1],
            first_pair[1],
        ),
    )
    second = create_user_modeling_snapshot(
        project_id=PROJECT_ID,
        project_brief_reference=(BRIEF_REFERENCE),
        agent_team_reference=(TEAM_REFERENCE),
        catalog_version=1,
        catalog_content_hash=(CATALOG_HASH),
        persona_versions=(
            first_pair[0],
            second_pair[0],
        ),
        twin_versions=(
            first_pair[1],
            second_pair[1],
        ),
    )

    assert first == second
    assert first.content_hash == second.content_hash
    assert json.loads(first.canonical_json()) == first.to_snapshot()


def test_snapshot_version_protects_project_hash_and_lineage() -> None:
    """Represent complete User Modeling history immutably."""
    persona, twin = modeling_pair(1)
    snapshot = create_user_modeling_snapshot(
        project_id=PROJECT_ID,
        project_brief_reference=(BRIEF_REFERENCE),
        agent_team_reference=(TEAM_REFERENCE),
        catalog_version=1,
        catalog_content_hash=(CATALOG_HASH),
        persona_versions=(persona,),
        twin_versions=(twin,),
    )
    version = UserModelingSnapshotVersion(
        id=SNAPSHOT_ID,
        project_id=PROJECT_ID,
        version_number=1,
        snapshot=snapshot,
        content_hash=(snapshot.content_hash),
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )

    assert version.based_on_version_number is None
    assert version.to_snapshot()["snapshot"] == snapshot.to_snapshot()

    with pytest.raises(
        ValueError,
        match="must match its content",
    ):
        UserModelingSnapshotVersion(
            id=SNAPSHOT_ID,
            project_id=PROJECT_ID,
            version_number=1,
            snapshot=snapshot,
            content_hash="f" * 64,
            created_by_user_id=OWNER_ID,
            created_at=CREATED_AT,
        )

    with pytest.raises(
        ValueError,
        match="immediately preceding",
    ):
        UserModelingSnapshotVersion(
            id=SNAPSHOT_ID,
            project_id=PROJECT_ID,
            version_number=2,
            snapshot=snapshot,
            content_hash=(snapshot.content_hash),
            created_by_user_id=OWNER_ID,
            created_at=CREATED_AT,
            based_on_version_number=None,
        )


def test_snapshot_constructor_rejects_noncanonical_identity_order() -> None:
    """Protect deterministic ordering even without the factory."""
    first_pair = modeling_pair(1)
    second_pair = modeling_pair(2)

    with pytest.raises(
        ValueError,
        match=("canonical identity order"),
    ):
        UserModelingSnapshot(
            project_id=PROJECT_ID,
            project_brief_reference=(BRIEF_REFERENCE),
            agent_team_reference=(TEAM_REFERENCE),
            catalog_version=1,
            catalog_content_hash=(CATALOG_HASH),
            persona_versions=(
                second_pair[0],
                first_pair[0],
            ),
            twin_versions=(
                first_pair[1],
                second_pair[1],
            ),
        )
