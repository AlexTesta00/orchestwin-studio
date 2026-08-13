"""Tests for User Twin lifecycle and empirical-grounding policy."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

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
from orchestwin.twins.lifecycle import (
    UserTwinLifecycleIssueCode,
    UserTwinLifecycleTransitionStatus,
    UserTwinOwnerApprovalStatus,
    assess_empirical_grounding,
    effective_user_twin_lifecycle,
    promote_user_twin_lifecycle,
)
from orchestwin.twins.personas import (
    PersonaField,
    PersonaProfileVersion,
    create_owner_provided_persona,
)
from orchestwin.twins.user_twins import (
    UserTwinField,
    UserTwinLifecycleStatus,
    UserTwinProfile,
    VersionedArtifactReference,
    create_project_grounded_user_twin,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
PERSONA_ID = UUID("00000000-0000-4000-8000-000000000020")
PERSONA_VERSION_ID = UUID("00000000-0000-4000-8000-000000000021")
BRIEF_ID = UUID("00000000-0000-4000-8000-000000000030")
TEAM_ID = UUID("00000000-0000-4000-8000-000000000040")

CREATED_AT = datetime(
    2026,
    8,
    14,
    14,
    0,
    tzinfo=UTC,
)

BRIEF_REFERENCE = VersionedArtifactReference(
    artifact_id=BRIEF_ID,
    version_number=4,
    content_hash="b" * 64,
)
TEAM_REFERENCE = VersionedArtifactReference(
    artifact_id=TEAM_ID,
    version_number=2,
    content_hash="c" * 64,
)
CATALOG_HASH = "d" * 64

_LIST_FIELDS = frozenset(
    {
        UserTwinField.EXPERTISE,
        UserTwinField.GOALS,
        UserTwinField.RECURRING_TASKS,
        UserTwinField.INFORMATION_NEEDS,
        UserTwinField.DECISION_CRITERIA,
        UserTwinField.PREFERRED_VOCABULARY,
        UserTwinField.FRUSTRATIONS,
        UserTwinField.PAIN_POINTS,
        UserTwinField.TRUST_CONCERNS,
        UserTwinField.ACCESSIBILITY_NEEDS,
        UserTwinField.OPERATIONAL_CONSTRAINTS,
        UserTwinField.ASSUMPTIONS,
    }
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


def project_brief_evidence(
    locator: str,
) -> EvidenceReference:
    """Create one approved Project Brief evidence reference."""
    return evidence(
        source_kind=(EvidenceSourceKind.PROJECT_BRIEF),
        source_id=("project-brief-version:4"),
        locator=locator,
    )


def model_evidence(
    locator: str,
) -> EvidenceReference:
    """Create one deterministic model-output reference."""
    return evidence(
        source_kind=(EvidenceSourceKind.MODEL_OUTPUT),
        source_id=("user-modeling-proposal:1"),
        locator=locator,
    )


def empirical_evidence(
    locator: str,
) -> EvidenceReference:
    """Create one empirical-research evidence reference."""
    return evidence(
        source_kind=(EvidenceSourceKind.EMPIRICAL_RESEARCH),
        source_id=("user-research-study:1"),
        locator=locator,
    )


def human_review_evidence(
    locator: str,
) -> EvidenceReference:
    """Create one non-empirical human-review reference."""
    return evidence(
        source_kind=(EvidenceSourceKind.HUMAN_REVIEW),
        source_id=("owner-review:1"),
        locator=locator,
    )


def user_observation(
    observation_key: str,
    value: ObservationValue,
) -> ProfileObservation:
    """Create one user-provided observation."""
    return ProfileObservation(
        observation_key=(observation_key),
        value=value,
        epistemic_status=(EpistemicStatus.USER_PROVIDED),
        confidence=ConfidenceScore(1.0),
        provenance=(
            ObservationProvenance.from_references((project_brief_evidence(observation_key),))
        ),
        human_validation=(HumanValidationRequirement.NOT_REQUIRED),
    )


def abstained_model_observation(
    field: UserTwinField,
) -> ProfileObservation:
    """Create one explicit model abstention for unavailable evidence."""
    return ProfileObservation(
        observation_key=(field.observation_key),
        value=(
            ObservationValue.abstained(
                "The available project evidence does not support a concrete value."
            )
        ),
        epistemic_status=(EpistemicStatus.MODEL_INFERRED),
        confidence=ConfidenceScore(0.2),
        provenance=(
            ObservationProvenance.from_references((model_evidence(field.observation_key),))
        ),
        human_validation=(HumanValidationRequirement.REQUIRED),
        rationale=("The deterministic adapter abstains instead of inventing missing evidence."),
    )


def empirical_observation(
    field: UserTwinField,
    *,
    source_kind: EvidenceSourceKind = (EvidenceSourceKind.EMPIRICAL_RESEARCH),
) -> ProfileObservation:
    """Create one empirically-supported substantive observation."""
    if field in _LIST_FIELDS:
        value = ObservationValue.from_items(("Reduce booking conflicts",))
    else:
        value = ObservationValue.from_text("Moderate")

    reference = (
        empirical_evidence(field.observation_key)
        if (source_kind is EvidenceSourceKind.EMPIRICAL_RESEARCH)
        else human_review_evidence(field.observation_key)
    )

    return ProfileObservation(
        observation_key=(field.observation_key),
        value=value,
        epistemic_status=(EpistemicStatus.EMPIRICALLY_SUPPORTED),
        confidence=ConfidenceScore(0.9),
        provenance=(ObservationProvenance.from_references((reference,))),
        human_validation=(HumanValidationRequirement.NOT_REQUIRED),
    )


def human_validated_observation(
    field: UserTwinField,
) -> ProfileObservation:
    """Create a substantive human-validated but non-empirical claim."""
    if field in _LIST_FIELDS:
        value = ObservationValue.from_items(("Prefers concise terminology",))
    else:
        value = ObservationValue.from_text("Moderate")

    return ProfileObservation(
        observation_key=(field.observation_key),
        value=value,
        epistemic_status=(EpistemicStatus.HUMAN_VALIDATED),
        confidence=ConfidenceScore(0.8),
        provenance=(
            ObservationProvenance.from_references((human_review_evidence(field.observation_key),))
        ),
        human_validation=(HumanValidationRequirement.NOT_REQUIRED),
    )


def persona_version() -> PersonaProfileVersion:
    """Create one confirmed owner-provided persona version."""
    profile = create_owner_provided_persona(
        name="Hotel Receptionist",
        observations=(
            user_observation(
                PersonaField.ROLE.observation_key,
                ObservationValue.from_text("Hotel receptionist"),
            ),
            user_observation(
                PersonaField.SUMMARY.observation_key,
                ObservationValue.from_text(
                    "Front-desk staff coordinating guests and reservations."
                ),
            ),
            user_observation(
                PersonaField.GOALS.observation_key,
                ObservationValue.from_items(("Avoid booking conflicts",)),
            ),
            user_observation(
                PersonaField.CONTEXT_OF_USE.observation_key,
                ObservationValue.from_text("Uses the application at the hotel front desk."),
            ),
        ),
    )

    return PersonaProfileVersion(
        id=PERSONA_VERSION_ID,
        project_id=PROJECT_ID,
        persona_id=PERSONA_ID,
        version_number=1,
        profile=profile,
        content_hash=(profile.content_hash),
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )


def twin_observations(
    overrides: dict[
        UserTwinField,
        ProfileObservation,
    ]
    | None = None,
) -> tuple[
    ProfileObservation,
    ...,
]:
    """Create a complete profile with explicit abstention by default."""
    resolved_overrides = overrides if overrides is not None else {}
    observations: list[ProfileObservation] = []

    for field in UserTwinField:
        if field is UserTwinField.AGE_RANGE:
            continue

        override = resolved_overrides.get(field)

        if override is not None:
            observations.append(override)
            continue

        if field is UserTwinField.ROLE:
            observations.append(
                user_observation(
                    field.observation_key,
                    ObservationValue.from_text("Hotel receptionist"),
                )
            )
            continue

        observations.append(abstained_model_observation(field))

    return tuple(observations)


def twin_profile(
    overrides: dict[
        UserTwinField,
        ProfileObservation,
    ]
    | None = None,
) -> UserTwinProfile:
    """Create one complete project-grounded User Twin profile."""
    return create_project_grounded_user_twin(
        name="Receptionist Twin",
        persona_version=(persona_version()),
        project_brief_reference=(BRIEF_REFERENCE),
        agent_team_reference=(TEAM_REFERENCE),
        catalog_version=1,
        catalog_content_hash=(CATALOG_HASH),
        observations=(twin_observations(overrides)),
    )


def test_owner_approval_is_derived_without_mutating_profile() -> None:
    """Keep Gate 3 approval distinct from persisted profile content."""
    profile = twin_profile()

    assert profile.validation_status is UserTwinLifecycleStatus.PROJECT_GROUNDED_UT

    not_approved = effective_user_twin_lifecycle(
        profile,
        owner_approval=(UserTwinOwnerApprovalStatus.NOT_APPROVED),
    )
    approved = effective_user_twin_lifecycle(
        profile,
        owner_approval=(UserTwinOwnerApprovalStatus.APPROVED),
    )

    assert not_approved is (UserTwinLifecycleStatus.PROJECT_GROUNDED_UT)
    assert approved is (UserTwinLifecycleStatus.OWNER_APPROVED_UT)
    assert profile.validation_status is UserTwinLifecycleStatus.PROJECT_GROUNDED_UT


def test_owner_approved_status_is_not_persisted_by_promotion() -> None:
    """Require Gate 3 rather than mutating a profile to owner-approved."""
    profile = twin_profile()

    result = promote_user_twin_lifecycle(
        profile,
        target_status=(UserTwinLifecycleStatus.OWNER_APPROVED_UT),
        owner_approval=(UserTwinOwnerApprovalStatus.APPROVED),
    )

    assert result.status is (UserTwinLifecycleTransitionStatus.REJECTED)
    assert result.issue is (UserTwinLifecycleIssueCode.OWNER_APPROVAL_IS_DERIVED)
    assert result.profile is profile


def test_proto_profile_can_become_project_grounded() -> None:
    """Allow the first persisted grounding transition."""
    grounded = twin_profile()
    proto = replace(
        grounded,
        validation_status=(UserTwinLifecycleStatus.PROTO_UT),
    )

    result = promote_user_twin_lifecycle(
        proto,
        target_status=(UserTwinLifecycleStatus.PROJECT_GROUNDED_UT),
    )

    assert result.status is (UserTwinLifecycleTransitionStatus.APPLIED)
    assert result.issue is None
    assert result.profile.validation_status is UserTwinLifecycleStatus.PROJECT_GROUNDED_UT
    assert proto.validation_status is UserTwinLifecycleStatus.PROTO_UT
    assert result.profile.content_hash != proto.content_hash

    repeated = promote_user_twin_lifecycle(
        result.profile,
        target_status=(UserTwinLifecycleStatus.PROJECT_GROUNDED_UT),
    )

    assert repeated.status is (UserTwinLifecycleTransitionStatus.NO_CHANGE)
    assert repeated.profile == result.profile


def test_empirical_grounding_requires_current_owner_approval() -> None:
    """Do not bypass the human-governance boundary."""
    profile = twin_profile({UserTwinField.GOALS: (empirical_observation(UserTwinField.GOALS))})

    result = promote_user_twin_lifecycle(
        profile,
        target_status=(UserTwinLifecycleStatus.EMPIRICALLY_GROUNDED_UT),
    )

    assert result.status is (UserTwinLifecycleTransitionStatus.REJECTED)
    assert result.issue is (UserTwinLifecycleIssueCode.OWNER_APPROVAL_REQUIRED)


def test_empirical_grounding_requires_empirical_support() -> None:
    """Reject empirical lifecycle labels without empirical observations."""
    profile = twin_profile()

    result = promote_user_twin_lifecycle(
        profile,
        target_status=(UserTwinLifecycleStatus.EMPIRICALLY_GROUNDED_UT),
        owner_approval=(UserTwinOwnerApprovalStatus.APPROVED),
    )

    assert result.status is (UserTwinLifecycleTransitionStatus.REJECTED)
    assert result.issue is (UserTwinLifecycleIssueCode.EMPIRICAL_EVIDENCE_REQUIRED)


def test_empirical_status_without_empirical_provenance_is_rejected() -> None:
    """Prevent an empirical label backed only by human review."""
    profile = twin_profile(
        {
            UserTwinField.GOALS: (
                empirical_observation(
                    UserTwinField.GOALS,
                    source_kind=(EvidenceSourceKind.HUMAN_REVIEW),
                )
            )
        }
    )

    assessment = assess_empirical_grounding(profile)

    assert assessment.empirical_evidence_mismatch_fields == (UserTwinField.GOALS,)

    result = promote_user_twin_lifecycle(
        profile,
        target_status=(UserTwinLifecycleStatus.EMPIRICALLY_GROUNDED_UT),
        owner_approval=(UserTwinOwnerApprovalStatus.APPROVED),
    )

    assert result.status is (UserTwinLifecycleTransitionStatus.REJECTED)
    assert result.issue is (UserTwinLifecycleIssueCode.EMPIRICAL_EVIDENCE_MISMATCH)


def test_valid_empirical_evidence_allows_grounding() -> None:
    """Promote immutably when empirical support is inspectable."""
    profile = twin_profile({UserTwinField.GOALS: (empirical_observation(UserTwinField.GOALS))})
    original_hash = profile.content_hash

    assessment = assess_empirical_grounding(profile)

    assert assessment.empirically_supported_fields == (UserTwinField.GOALS,)
    assert assessment.empirical_evidence_reference_count == 1
    assert assessment.has_empirical_support is True

    result = promote_user_twin_lifecycle(
        profile,
        target_status=(UserTwinLifecycleStatus.EMPIRICALLY_GROUNDED_UT),
        owner_approval=(UserTwinOwnerApprovalStatus.APPROVED),
    )

    assert result.status is (UserTwinLifecycleTransitionStatus.APPLIED)
    assert result.profile.validation_status is UserTwinLifecycleStatus.EMPIRICALLY_GROUNDED_UT
    assert profile.validation_status is UserTwinLifecycleStatus.PROJECT_GROUNDED_UT
    assert result.profile.content_hash != original_hash


def test_human_validation_does_not_count_as_empirical_support() -> None:
    """Keep human confirmation distinct from empirical evidence."""
    profile = twin_profile(
        {UserTwinField.GOALS: (human_validated_observation(UserTwinField.GOALS))}
    )

    assessment = assess_empirical_grounding(profile)

    assert assessment.has_empirical_support is False
    assert assessment.non_empirical_substantive_fields == (UserTwinField.GOALS,)

    result = promote_user_twin_lifecycle(
        profile,
        target_status=(UserTwinLifecycleStatus.EMPIRICALLY_GROUNDED_UT),
        owner_approval=(UserTwinOwnerApprovalStatus.APPROVED),
    )

    assert result.issue is (UserTwinLifecycleIssueCode.EMPIRICAL_EVIDENCE_REQUIRED)


def test_empirical_validation_requires_complete_substantive_coverage() -> None:
    """Do not call a twin empirically validated with non-empirical claims."""
    project_profile = twin_profile(
        {
            UserTwinField.GOALS: (empirical_observation(UserTwinField.GOALS)),
            UserTwinField.TECHNICAL_LITERACY: (
                human_validated_observation(UserTwinField.TECHNICAL_LITERACY)
            ),
        }
    )
    grounded = promote_user_twin_lifecycle(
        project_profile,
        target_status=(UserTwinLifecycleStatus.EMPIRICALLY_GROUNDED_UT),
        owner_approval=(UserTwinOwnerApprovalStatus.APPROVED),
    )

    assert grounded.status is (UserTwinLifecycleTransitionStatus.APPLIED)

    assessment = assess_empirical_grounding(grounded.profile)

    assert assessment.non_empirical_substantive_fields == (UserTwinField.TECHNICAL_LITERACY,)
    assert assessment.fully_empirically_covered is False

    validated = promote_user_twin_lifecycle(
        grounded.profile,
        target_status=(UserTwinLifecycleStatus.EMPIRICALLY_VALIDATED_UT),
        owner_approval=(UserTwinOwnerApprovalStatus.APPROVED),
    )

    assert validated.status is (UserTwinLifecycleTransitionStatus.REJECTED)
    assert validated.issue is (UserTwinLifecycleIssueCode.EMPIRICAL_COVERAGE_INCOMPLETE)


def test_honest_abstention_does_not_fake_missing_empirical_claims() -> None:
    """Allow validation when unknown fields remain explicit abstentions."""
    project_profile = twin_profile(
        {UserTwinField.GOALS: (empirical_observation(UserTwinField.GOALS))}
    )
    grounded = promote_user_twin_lifecycle(
        project_profile,
        target_status=(UserTwinLifecycleStatus.EMPIRICALLY_GROUNDED_UT),
        owner_approval=(UserTwinOwnerApprovalStatus.APPROVED),
    )

    assert grounded.status is (UserTwinLifecycleTransitionStatus.APPLIED)

    assessment = assess_empirical_grounding(grounded.profile)

    assert assessment.non_empirical_substantive_fields == ()
    assert assessment.fully_empirically_covered is True

    validated = promote_user_twin_lifecycle(
        grounded.profile,
        target_status=(UserTwinLifecycleStatus.EMPIRICALLY_VALIDATED_UT),
        owner_approval=(UserTwinOwnerApprovalStatus.APPROVED),
    )

    assert validated.status is (UserTwinLifecycleTransitionStatus.APPLIED)
    assert validated.profile.validation_status is UserTwinLifecycleStatus.EMPIRICALLY_VALIDATED_UT
    assert grounded.profile.validation_status is UserTwinLifecycleStatus.EMPIRICALLY_GROUNDED_UT


def test_empirical_validation_still_requires_owner_approval() -> None:
    """Keep human governance required after empirical grounding."""
    project_profile = twin_profile(
        {UserTwinField.GOALS: (empirical_observation(UserTwinField.GOALS))}
    )
    grounded = promote_user_twin_lifecycle(
        project_profile,
        target_status=(UserTwinLifecycleStatus.EMPIRICALLY_GROUNDED_UT),
        owner_approval=(UserTwinOwnerApprovalStatus.APPROVED),
    )

    assert grounded.status is (UserTwinLifecycleTransitionStatus.APPLIED)

    validated = promote_user_twin_lifecycle(
        grounded.profile,
        target_status=(UserTwinLifecycleStatus.EMPIRICALLY_VALIDATED_UT),
        owner_approval=(UserTwinOwnerApprovalStatus.NOT_APPROVED),
    )

    assert validated.status is (UserTwinLifecycleTransitionStatus.REJECTED)
    assert validated.issue is (UserTwinLifecycleIssueCode.OWNER_APPROVAL_REQUIRED)


def test_lifecycle_rejects_skipped_and_backward_transitions() -> None:
    """Keep lifecycle progression explicit and monotonic."""
    project_profile = twin_profile()

    skipped = promote_user_twin_lifecycle(
        project_profile,
        target_status=(UserTwinLifecycleStatus.EMPIRICALLY_VALIDATED_UT),
        owner_approval=(UserTwinOwnerApprovalStatus.APPROVED),
    )

    assert skipped.status is (UserTwinLifecycleTransitionStatus.REJECTED)
    assert skipped.issue is (UserTwinLifecycleIssueCode.INVALID_TRANSITION)

    empirical_profile = twin_profile(
        {UserTwinField.GOALS: (empirical_observation(UserTwinField.GOALS))}
    )
    grounded = promote_user_twin_lifecycle(
        empirical_profile,
        target_status=(UserTwinLifecycleStatus.EMPIRICALLY_GROUNDED_UT),
        owner_approval=(UserTwinOwnerApprovalStatus.APPROVED),
    )

    assert grounded.status is (UserTwinLifecycleTransitionStatus.APPLIED)

    backward = promote_user_twin_lifecycle(
        grounded.profile,
        target_status=(UserTwinLifecycleStatus.PROJECT_GROUNDED_UT),
        owner_approval=(UserTwinOwnerApprovalStatus.APPROVED),
    )

    assert backward.status is (UserTwinLifecycleTransitionStatus.REJECTED)
    assert backward.issue is (UserTwinLifecycleIssueCode.INVALID_TRANSITION)
