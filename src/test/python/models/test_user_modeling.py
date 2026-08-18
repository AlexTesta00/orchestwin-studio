"""Tests for the typed User Modeling port and deterministic fake adapter."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from orchestwin.models.fake_user_modeling import (
    FAKE_USER_MODELING_PROVIDER_ID,
    FAKE_USER_MODELING_PROVIDER_VERSION,
    FakeDeterministicUserModelingAdapter,
)
from orchestwin.models.user_modeling import (
    PersonaProposalRequest,
    UserModelingProposalIssueCode,
    UserModelingProposalProviderKind,
    UserModelingProposalStatus,
    UserTwinProposalRequest,
)
from orchestwin.projects.brief_gate import (
    project_brief_artifact_reference,
)
from orchestwin.projects.briefs import (
    BriefField,
    ProjectBriefVersion,
    create_project_brief,
)
from orchestwin.twins.epistemics import (
    EpistemicStatus,
    HumanValidationRequirement,
    ObservationValueKind,
)
from orchestwin.twins.persona_candidates import (
    PersonaCandidateDerivationStatus,
    derive_project_persona_candidates,
)
from orchestwin.twins.personas import (
    PersonaConfirmationStatus,
    PersonaField,
    PersonaKind,
    PersonaProfileVersion,
    PersonaSource,
    confirm_proto_persona,
)
from orchestwin.twins.user_twins import (
    UserTwinField,
    UserTwinLifecycleStatus,
    VersionedArtifactReference,
)
from orchestwin.workflow.gates import (
    HumanGate,
    HumanGateAction,
    HumanGateTransitionStatus,
    HumanGateType,
    create_human_gate,
    transition_human_gate,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
OTHER_PROJECT_ID = UUID("00000000-0000-4000-8000-000000000011")
OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
BRIEF_ID = UUID("00000000-0000-4000-8000-000000000020")
GATE_ID = UUID("00000000-0000-4000-8000-000000000030")
SUBMIT_EVENT_ID = UUID("00000000-0000-4000-8000-000000000031")
APPROVE_EVENT_ID = UUID("00000000-0000-4000-8000-000000000032")
PERSONA_ID = UUID("00000000-0000-4000-8000-000000000040")
PENDING_PERSONA_VERSION_ID = UUID("00000000-0000-4000-8000-000000000041")
CONFIRMED_PERSONA_VERSION_ID = UUID("00000000-0000-4000-8000-000000000042")

CREATED_AT = datetime(
    2026,
    8,
    14,
    18,
    0,
    tzinfo=UTC,
)

BRIEF_REFERENCE = VersionedArtifactReference(
    artifact_id=BRIEF_ID,
    version_number=1,
    content_hash="b" * 64,
)

TEAM_REFERENCE = VersionedArtifactReference(
    artifact_id=UUID("00000000-0000-4000-8000-000000000050"),
    version_number=2,
    content_hash="c" * 64,
)

CATALOG_HASH = "d" * 64


def brief_version() -> ProjectBriefVersion:
    """Create one approved brief containing one target-user group."""
    unknown_fields = [
        field
        for field in BriefField
        if field
        not in {
            BriefField.NAME,
            BriefField.TARGET_USERS,
        }
    ]

    brief = create_project_brief(
        name="Hotel Operations Studio",
        target_users=[
            "Hotel receptionist",
        ],
        unknown_fields=(unknown_fields),
    )

    return ProjectBriefVersion(
        id=BRIEF_ID,
        project_id=PROJECT_ID,
        version_number=1,
        schema_version=(brief.SCHEMA_VERSION),
        brief=brief,
        content_hash=(brief.content_hash),
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )


def approved_gate(
    version: ProjectBriefVersion,
) -> HumanGate:
    """Approve Gate 1 for the exact supplied Project Brief version."""
    draft = create_human_gate(
        gate_id=GATE_ID,
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        gate_type=(HumanGateType.PROJECT_BRIEF),
        artifact=(project_brief_artifact_reference(version)),
        created_at=CREATED_AT,
    )

    submitted = transition_human_gate(
        draft,
        action=(HumanGateAction.SUBMIT),
        actor_user_id=OWNER_ID,
        occurred_at=(CREATED_AT + timedelta(minutes=1)),
        event_id=(SUBMIT_EVENT_ID),
    )

    assert submitted.status is (HumanGateTransitionStatus.APPLIED)

    approved = transition_human_gate(
        submitted.gate,
        action=(HumanGateAction.APPROVE),
        actor_user_id=OWNER_ID,
        occurred_at=(CREATED_AT + timedelta(minutes=2)),
        event_id=(APPROVE_EVENT_ID),
    )

    assert approved.status is (HumanGateTransitionStatus.APPLIED)

    return approved.gate


def candidates():
    """Derive the canonical candidate fixture."""
    version = brief_version()
    result = derive_project_persona_candidates(
        brief_version=version,
        brief_gate=(approved_gate(version)),
    )

    assert result.status is (PersonaCandidateDerivationStatus.DERIVED)

    return result.candidates


def proposed_proto_persona():
    """Return one persona produced by the deterministic fake adapter."""
    adapter = FakeDeterministicUserModelingAdapter()
    result = asyncio.run(
        adapter.propose_personas(
            PersonaProposalRequest(
                project_id=PROJECT_ID,
                candidates=candidates(),
            )
        )
    )

    assert result.status is (UserModelingProposalStatus.PROPOSED)

    return result.proposals[0].profile


def pending_persona_version() -> PersonaProfileVersion:
    """Persist the proposed profile conceptually as persona version 1."""
    profile = proposed_proto_persona()

    return PersonaProfileVersion(
        id=(PENDING_PERSONA_VERSION_ID),
        project_id=PROJECT_ID,
        persona_id=PERSONA_ID,
        version_number=1,
        profile=profile,
        content_hash=(profile.content_hash),
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )


def confirmed_persona_version() -> PersonaProfileVersion:
    """Create the immutable confirmation revision as persona version 2."""
    pending = pending_persona_version()
    decision = confirm_proto_persona(pending.profile)

    assert decision.profile.confirmation_status is PersonaConfirmationStatus.CONFIRMED

    return PersonaProfileVersion(
        id=(CONFIRMED_PERSONA_VERSION_ID),
        project_id=PROJECT_ID,
        persona_id=PERSONA_ID,
        version_number=2,
        profile=decision.profile,
        content_hash=(decision.profile.content_hash),
        created_by_user_id=OWNER_ID,
        created_at=(CREATED_AT + timedelta(minutes=5)),
        based_on_version_number=1,
    )


def test_fake_persona_proposal_is_explicitly_deterministic() -> None:
    """Expose fake-provider identity and reproducible output."""
    adapter = FakeDeterministicUserModelingAdapter()
    request = PersonaProposalRequest(
        project_id=PROJECT_ID,
        candidates=candidates(),
    )

    first = asyncio.run(adapter.propose_personas(request))
    second = asyncio.run(adapter.propose_personas(request))

    assert first.status is (UserModelingProposalStatus.PROPOSED)
    assert first.provider_kind is (UserModelingProposalProviderKind.FAKE_DETERMINISTIC)
    assert first.provider_id == FAKE_USER_MODELING_PROVIDER_ID
    assert first.provider_version == FAKE_USER_MODELING_PROVIDER_VERSION
    assert first == second
    assert first.content_hash == second.content_hash


def test_fake_persona_preserves_role_and_abstains_from_unsupported_claims() -> None:
    """Generate a usable proto-persona without inventing behavior."""
    profile = proposed_proto_persona()

    assert profile.source is (PersonaSource.SYSTEM_PROPOSED)
    assert profile.kind is (PersonaKind.PROTO_PERSONA)
    assert profile.confirmation_status is PersonaConfirmationStatus.PENDING_CONFIRMATION
    assert profile.ready_for_twin_creation is False

    role = profile.observation_for(PersonaField.ROLE)
    summary = profile.observation_for(PersonaField.SUMMARY)
    goals = profile.observation_for(PersonaField.GOALS)
    context = profile.observation_for(PersonaField.CONTEXT_OF_USE)

    assert role is not None
    assert summary is not None
    assert goals is not None
    assert context is not None

    assert role.epistemic_status is EpistemicStatus.USER_PROVIDED
    assert role.value.text == "Hotel receptionist"

    assert summary.epistemic_status is EpistemicStatus.MODEL_INFERRED
    assert summary.human_validation is HumanValidationRequirement.REQUIRED

    assert goals.value.kind is (ObservationValueKind.ABSTAINED)
    assert context.value.kind is (ObservationValueKind.ABSTAINED)

    assert profile.observation_for(PersonaField.AGE_RANGE) is None


def test_fake_persona_proposal_rejects_empty_and_mismatched_input() -> None:
    """Return typed failures for expected invalid request context."""
    adapter = FakeDeterministicUserModelingAdapter()

    empty = asyncio.run(
        adapter.propose_personas(
            PersonaProposalRequest(
                project_id=PROJECT_ID,
                candidates=(),
            )
        )
    )

    assert empty.status is (UserModelingProposalStatus.REJECTED)
    assert empty.issue is (UserModelingProposalIssueCode.CANDIDATES_REQUIRED)

    mismatched = asyncio.run(
        adapter.propose_personas(
            PersonaProposalRequest(
                project_id=(OTHER_PROJECT_ID),
                candidates=candidates(),
            )
        )
    )

    assert mismatched.status is (UserModelingProposalStatus.REJECTED)
    assert mismatched.issue is (UserModelingProposalIssueCode.CANDIDATE_PROJECT_MISMATCH)


def test_pending_proto_persona_cannot_generate_user_twin() -> None:
    """Require owner confirmation before User Twin proposal."""
    adapter = FakeDeterministicUserModelingAdapter()
    pending = pending_persona_version()

    result = asyncio.run(
        adapter.propose_user_twins(
            UserTwinProposalRequest(
                project_id=PROJECT_ID,
                persona_versions=(pending,),
                project_brief_reference=(BRIEF_REFERENCE),
                agent_team_reference=(TEAM_REFERENCE),
                catalog_version=1,
                catalog_content_hash=(CATALOG_HASH),
            )
        )
    )

    assert result.status is (UserModelingProposalStatus.REJECTED)
    assert result.issue is (UserModelingProposalIssueCode.PERSONA_NOT_CONFIRMED)
    assert result.proposals == ()


def test_confirmed_persona_produces_project_grounded_twin() -> None:
    """Ground the twin in the exact confirmed persona and project state."""
    adapter = FakeDeterministicUserModelingAdapter()
    persona = confirmed_persona_version()

    result = asyncio.run(
        adapter.propose_user_twins(
            UserTwinProposalRequest(
                project_id=PROJECT_ID,
                persona_versions=(persona,),
                project_brief_reference=(BRIEF_REFERENCE),
                agent_team_reference=(TEAM_REFERENCE),
                catalog_version=1,
                catalog_content_hash=(CATALOG_HASH),
            )
        )
    )

    assert result.status is (UserModelingProposalStatus.PROPOSED)
    assert len(result.proposals) == 1

    profile = result.proposals[0].profile

    assert profile.validation_status is UserTwinLifecycleStatus.PROJECT_GROUNDED_UT
    assert profile.persona_reference.persona_id == PERSONA_ID
    assert profile.persona_reference.version_number == 2
    assert profile.project_brief_reference == BRIEF_REFERENCE
    assert profile.agent_team_reference == TEAM_REFERENCE
    assert profile.catalog_version == 1
    assert profile.catalog_content_hash == CATALOG_HASH


def test_twin_transfers_persona_evidence_and_abstains_elsewhere() -> None:
    """Reuse compatible persona fields and abstain from unsupported ones."""
    adapter = FakeDeterministicUserModelingAdapter()
    persona = confirmed_persona_version()

    result = asyncio.run(
        adapter.propose_user_twins(
            UserTwinProposalRequest(
                project_id=PROJECT_ID,
                persona_versions=(persona,),
                project_brief_reference=(BRIEF_REFERENCE),
                agent_team_reference=(TEAM_REFERENCE),
                catalog_version=1,
                catalog_content_hash=(CATALOG_HASH),
            )
        )
    )
    profile = result.proposals[0].profile

    role = profile.observation_for(UserTwinField.ROLE)
    goals = profile.observation_for(UserTwinField.GOALS)
    context = profile.observation_for(UserTwinField.CONTEXT_OF_USE)
    expertise = profile.observation_for(UserTwinField.EXPERTISE)
    pain_points = profile.observation_for(UserTwinField.PAIN_POINTS)
    technical_literacy = profile.observation_for(UserTwinField.TECHNICAL_LITERACY)

    assert role is not None
    assert goals is not None
    assert context is not None
    assert expertise is not None
    assert pain_points is not None
    assert technical_literacy is not None

    assert role.epistemic_status is EpistemicStatus.USER_PROVIDED

    assert goals.value.kind is (ObservationValueKind.ABSTAINED)
    assert context.value.kind is (ObservationValueKind.ABSTAINED)

    for observation in (
        expertise,
        pain_points,
        technical_literacy,
    ):
        assert observation.value.kind is (ObservationValueKind.ABSTAINED)
        assert observation.epistemic_status is EpistemicStatus.MODEL_INFERRED
        assert observation.human_validation is HumanValidationRequirement.REQUIRED


def test_fake_user_twin_output_is_reproducible() -> None:
    """Produce identical proposal content for identical typed input."""
    adapter = FakeDeterministicUserModelingAdapter()
    persona = confirmed_persona_version()
    request = UserTwinProposalRequest(
        project_id=PROJECT_ID,
        persona_versions=(persona,),
        project_brief_reference=(BRIEF_REFERENCE),
        agent_team_reference=(TEAM_REFERENCE),
        catalog_version=1,
        catalog_content_hash=(CATALOG_HASH),
    )

    first = asyncio.run(adapter.propose_user_twins(request))
    second = asyncio.run(adapter.propose_user_twins(request))

    assert first == second
    assert first.content_hash == second.content_hash
    assert first.proposals[0].profile.content_hash == second.proposals[0].profile.content_hash
