"""Tests for deterministic persona-candidate derivation."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

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
    EvidenceSourceKind,
    HumanValidationRequirement,
)
from orchestwin.twins.persona_candidates import (
    PersonaCandidateDerivationStatus,
    PersonaCandidateIssueCode,
    derive_project_persona_candidates,
)
from orchestwin.twins.personas import (
    PersonaField,
    PersonaKind,
    PersonaSource,
)
from orchestwin.twins.user_twins import (
    MAX_PROJECT_USER_TWINS,
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
OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
BRIEF_VERSION_ID = UUID("00000000-0000-4000-8000-000000000020")
GATE_ID = UUID("00000000-0000-4000-8000-000000000030")
SUBMIT_EVENT_ID = UUID("00000000-0000-4000-8000-000000000031")
APPROVE_EVENT_ID = UUID("00000000-0000-4000-8000-000000000032")

CREATED_AT = datetime(
    2026,
    8,
    14,
    16,
    0,
    tzinfo=UTC,
)


def brief_version(
    *,
    target_users: (list[str] | None) = None,
    target_users_unknown: bool = False,
    version_number: int = 1,
    version_id: UUID = BRIEF_VERSION_ID,
) -> ProjectBriefVersion:
    """Create one epistemically complete Project Brief fixture."""
    unknown_fields = [
        field
        for field in BriefField
        if field
        not in {
            BriefField.NAME,
            BriefField.TARGET_USERS,
        }
    ]

    if target_users_unknown:
        unknown_fields.append(BriefField.TARGET_USERS)

    brief = create_project_brief(
        name="Hotel Operations Studio",
        target_users=target_users,
        unknown_fields=(unknown_fields),
    )

    return ProjectBriefVersion(
        id=version_id,
        project_id=PROJECT_ID,
        version_number=(version_number),
        schema_version=(brief.SCHEMA_VERSION),
        brief=brief,
        content_hash=(brief.content_hash),
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )


def approved_gate(
    version: ProjectBriefVersion,
) -> HumanGate:
    """Create Gate 1 approved on the exact supplied brief version."""
    draft = create_human_gate(
        gate_id=GATE_ID,
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        gate_type=(HumanGateType.PROJECT_BRIEF),
        artifact=(project_brief_artifact_reference(version)),
        created_at=(CREATED_AT + timedelta(minutes=1)),
    )

    submitted = transition_human_gate(
        draft,
        action=(HumanGateAction.SUBMIT),
        actor_user_id=OWNER_ID,
        occurred_at=(CREATED_AT + timedelta(minutes=2)),
        event_id=(SUBMIT_EVENT_ID),
    )

    assert submitted.status is (HumanGateTransitionStatus.APPLIED)

    approved = transition_human_gate(
        submitted.gate,
        action=(HumanGateAction.APPROVE),
        actor_user_id=OWNER_ID,
        occurred_at=(CREATED_AT + timedelta(minutes=3)),
        event_id=(APPROVE_EVENT_ID),
    )

    assert approved.status is (HumanGateTransitionStatus.APPLIED)

    return approved.gate


def test_approved_target_users_derive_candidates_in_owner_order() -> None:
    """Create one evidence-backed candidate per supplied target user."""
    version = brief_version(
        target_users=[
            "Hotel receptionist",
            "Hotel manager",
        ]
    )

    result = derive_project_persona_candidates(
        brief_version=version,
        brief_gate=(approved_gate(version)),
    )

    assert result.status is (PersonaCandidateDerivationStatus.DERIVED)
    assert result.issue is None

    assert tuple(candidate.target_user for candidate in result.candidates) == (
        "Hotel receptionist",
        "Hotel manager",
    )

    assert tuple(candidate.ordinal for candidate in result.candidates) == (
        1,
        2,
    )


def test_candidate_role_preserves_exact_user_provided_provenance() -> None:
    """Keep the supplied target role user-provided rather than inferred."""
    version = brief_version(
        target_users=[
            "Hotel receptionist",
        ]
    )
    result = derive_project_persona_candidates(
        brief_version=version,
        brief_gate=(approved_gate(version)),
    )
    candidate = result.candidates[0]
    observation = candidate.role_observation

    assert observation.observation_key == PersonaField.ROLE.observation_key
    assert observation.value.text == "Hotel receptionist"
    assert observation.epistemic_status is EpistemicStatus.USER_PROVIDED
    assert observation.confidence.value == 1.0
    assert observation.human_validation is HumanValidationRequirement.NOT_REQUIRED

    assert len(observation.provenance.references) == 1

    reference = observation.provenance.references[0]

    assert reference.source_kind is (EvidenceSourceKind.PROJECT_BRIEF)
    assert reference.source_id == str(version.id)
    assert reference.source_version == version.version_number
    assert reference.content_hash == version.content_hash
    assert reference.locator == "brief.target_users[0]"


def test_candidate_marks_future_profile_as_confirmable_proto_persona() -> None:
    """Distinguish the supplied role from the future generated profile."""
    version = brief_version(
        target_users=[
            "Hotel receptionist",
        ]
    )
    result = derive_project_persona_candidates(
        brief_version=version,
        brief_gate=(approved_gate(version)),
    )
    candidate = result.candidates[0]

    assert candidate.future_profile_source is PersonaSource.SYSTEM_PROPOSED
    assert candidate.future_profile_kind is PersonaKind.PROTO_PERSONA
    assert candidate.confirmation_required is True


def test_candidate_does_not_fabricate_a_complete_persona() -> None:
    """Keep unsupported persona attributes out of deterministic derivation."""
    version = brief_version(
        target_users=[
            "Hotel receptionist",
        ]
    )
    result = derive_project_persona_candidates(
        brief_version=version,
        brief_gate=(approved_gate(version)),
    )

    snapshot = result.candidates[0].to_snapshot()

    assert set(snapshot) == {
        "schema_version",
        "project_id",
        "ordinal",
        "target_user",
        "role_observation",
        "source_brief",
        "future_profile",
    }

    assert "summary" not in snapshot
    assert "goals" not in snapshot
    assert "context_of_use" not in snapshot
    assert "age_range" not in snapshot


def test_candidate_derivation_requires_current_gate_one_approval() -> None:
    """Reject derivation when Gate 1 does not approve this brief."""
    version = brief_version(
        target_users=[
            "Hotel receptionist",
        ]
    )

    draft_gate = create_human_gate(
        gate_id=GATE_ID,
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        gate_type=(HumanGateType.PROJECT_BRIEF),
        artifact=(project_brief_artifact_reference(version)),
        created_at=CREATED_AT,
    )

    result = derive_project_persona_candidates(
        brief_version=version,
        brief_gate=draft_gate,
    )

    assert result.status is (PersonaCandidateDerivationStatus.REJECTED)
    assert result.issue is (PersonaCandidateIssueCode.BRIEF_NOT_APPROVED)
    assert result.candidates == ()


def test_old_gate_one_approval_cannot_ground_new_brief_version() -> None:
    """Reject persona derivation after the approved brief is superseded."""
    first = brief_version(
        target_users=[
            "Hotel receptionist",
        ]
    )
    gate = approved_gate(first)

    second = brief_version(
        target_users=[
            "Hotel receptionist",
        ],
        version_number=2,
        version_id=UUID("00000000-0000-4000-8000-000000000021"),
    )

    result = derive_project_persona_candidates(
        brief_version=second,
        brief_gate=gate,
    )

    assert result.status is (PersonaCandidateDerivationStatus.REJECTED)
    assert result.issue is (PersonaCandidateIssueCode.BRIEF_NOT_APPROVED)


def test_unknown_target_users_do_not_create_invented_candidates() -> None:
    """Abstain when the approved brief explicitly marks users unknown."""
    version = brief_version(target_users_unknown=True)

    result = derive_project_persona_candidates(
        brief_version=version,
        brief_gate=(approved_gate(version)),
    )

    assert result.status is (PersonaCandidateDerivationStatus.REJECTED)
    assert result.issue is (PersonaCandidateIssueCode.TARGET_USERS_UNKNOWN)
    assert result.candidates == ()


def test_missing_target_users_do_not_create_default_personas() -> None:
    """Do not invent a generic user when no target group is supplied."""
    version = brief_version()

    result = derive_project_persona_candidates(
        brief_version=version,
        brief_gate=(approved_gate(version)),
    )

    assert result.status is (PersonaCandidateDerivationStatus.REJECTED)
    assert result.issue is (PersonaCandidateIssueCode.TARGET_USERS_MISSING)
    assert result.candidates == ()


def test_four_target_users_are_supported_without_silent_reordering() -> None:
    """Support the maximum User Twin cardinality."""
    target_users = [
        "Receptionist",
        "Hotel manager",
        "Operations manager",
        "Property owner",
    ]

    assert len(target_users) == MAX_PROJECT_USER_TWINS

    version = brief_version(target_users=target_users)

    result = derive_project_persona_candidates(
        brief_version=version,
        brief_gate=(approved_gate(version)),
    )

    assert result.status is (PersonaCandidateDerivationStatus.DERIVED)
    assert [candidate.target_user for candidate in result.candidates] == target_users


def test_more_than_four_target_users_are_not_silently_truncated() -> None:
    """Require explicit owner prioritization beyond the supported limit."""
    version = brief_version(
        target_users=[
            "User 1",
            "User 2",
            "User 3",
            "User 4",
            "User 5",
        ]
    )

    result = derive_project_persona_candidates(
        brief_version=version,
        brief_gate=(approved_gate(version)),
    )

    assert result.status is (PersonaCandidateDerivationStatus.REJECTED)
    assert result.issue is (PersonaCandidateIssueCode.TARGET_USER_LIMIT_EXCEEDED)
    assert result.candidates == ()


def test_candidate_set_snapshot_and_hash_are_deterministic() -> None:
    """Produce reproducible input for the future proposal adapter."""
    version = brief_version(
        target_users=[
            "Hotel receptionist",
            "Hotel manager",
        ]
    )
    gate = approved_gate(version)

    first = derive_project_persona_candidates(
        brief_version=version,
        brief_gate=gate,
    )
    second = derive_project_persona_candidates(
        brief_version=version,
        brief_gate=gate,
    )

    assert first == second
    assert first.to_snapshot() == second.to_snapshot()
    assert first.canonical_json() == second.canonical_json()
    assert first.content_hash == second.content_hash

    assert json.loads(first.canonical_json()) == first.to_snapshot()

    assert len(first.content_hash) == 64

    assert all(character in "0123456789abcdef" for character in first.content_hash)

    assert all(len(candidate.content_hash) == 64 for candidate in first.candidates)
