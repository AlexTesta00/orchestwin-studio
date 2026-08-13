"""Sprint 03 acceptance tests for governed project setup."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from orchestwin.agents.catalog import (
    AgentIdentifier,
    all_agent_catalog_entries,
)
from orchestwin.agents.proposals import (
    TeamProposalRevisionKind,
    TeamProposalVersion,
    TeamSelectionContext,
)
from orchestwin.agents.selection_rules import (
    TeamRoleConstraintKind,
    determine_team_constraints,
)
from orchestwin.agents.team_gate import (
    ProjectWorkflowReadiness,
    agent_team_artifact_reference,
    agent_team_gate_is_currently_approved,
    project_workflow_readiness,
    team_proposal_matches_context,
)
from orchestwin.models.fake_team_proposals import (
    FakeDeterministicTeamProposalAdapter,
)
from orchestwin.models.team_proposals import (
    AgentTeamProposal,
    ProposedTeamMember,
    TeamProposalGenerationStatus,
    TeamProposalJustification,
    TeamProposalJustificationKind,
    TeamProposalMemberSource,
    TeamProposalRequest,
)
from orchestwin.projects.brief_gate import (
    project_brief_artifact_reference,
    project_brief_gate_is_currently_approved,
)
from orchestwin.projects.briefs import (
    BriefField,
    ProjectBriefVersion,
    create_project_brief,
)
from orchestwin.projects.clarification import (
    ClarificationAnswer,
    ClarificationApplicationStatus,
    ClarificationQuestionSpec,
    apply_clarification_answers,
    focused_clarification_questions,
)
from orchestwin.projects.clarification_state import (
    MAX_CLARIFICATION_ROUNDS,
)
from orchestwin.projects.domain import (
    ProjectMode,
)
from orchestwin.workflow.gates import (
    GateArtifactReference,
    HumanGate,
    HumanGateAction,
    HumanGateStatus,
    HumanGateTransitionStatus,
    HumanGateType,
    create_human_gate,
    mark_human_gate_stale,
    transition_human_gate,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")

GATE_ONE_ID = UUID("00000000-0000-4000-8000-000000000020")
GATE_ONE_SUBMIT_EVENT_ID = UUID("00000000-0000-4000-8000-000000000021")
GATE_ONE_APPROVE_EVENT_ID = UUID("00000000-0000-4000-8000-000000000022")
GATE_ONE_STALE_EVENT_ID = UUID("00000000-0000-4000-8000-000000000023")

GENERATED_TEAM_ID = UUID("00000000-0000-4000-8000-000000000030")
EDITED_TEAM_ID = UUID("00000000-0000-4000-8000-000000000031")
REVISED_TEAM_ID = UUID("00000000-0000-4000-8000-000000000032")

GATE_TWO_ID = UUID("00000000-0000-4000-8000-000000000040")
GATE_TWO_SUBMIT_EVENT_ID = UUID("00000000-0000-4000-8000-000000000041")
GATE_TWO_APPROVE_EVENT_ID = UUID("00000000-0000-4000-8000-000000000042")
GATE_TWO_STALE_EVENT_ID = UUID("00000000-0000-4000-8000-000000000043")

BASE_TIME = datetime(
    2026,
    8,
    13,
    10,
    0,
    tzinfo=UTC,
)


@dataclass(frozen=True, slots=True)
class ReadyProjectScenario:
    """Artifacts produced by the complete governed setup journey."""

    clarification_round_count: int
    brief_version: ProjectBriefVersion
    brief_gate: HumanGate
    context: TeamSelectionContext
    generated_team_version: TeamProposalVersion
    team_version: TeamProposalVersion
    team_gate: HumanGate
    readiness: ProjectWorkflowReadiness


def brief_version_id(
    version_number: int,
) -> UUID:
    """Return a deterministic ID for one Project Brief version."""
    return UUID(int=1000 + version_number)


def initial_brief_version() -> ProjectBriefVersion:
    """Create a partially specified web Project Brief."""
    brief = create_project_brief(
        name="Hotel Operations Studio",
        description=(
            "A browser-based application for managing "
            "hotel rooms, guests, reservations, and "
            "room availability."
        ),
        technical_constraints=[
            "Vue 3 frontend",
            "FastAPI backend",
            "PostgreSQL database",
            "Docker Compose local runtime",
        ],
        functional_requirements=[
            "Users authenticate locally.",
            "Staff manage rooms and guests.",
            "Staff create and cancel reservations.",
            "The system prevents overlapping reservations.",
        ],
    )

    return ProjectBriefVersion(
        id=brief_version_id(1),
        project_id=PROJECT_ID,
        version_number=1,
        schema_version=(brief.SCHEMA_VERSION),
        brief=brief,
        content_hash=brief.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=BASE_TIME,
    )


def answer_for_question(
    question: ClarificationQuestionSpec,
) -> ClarificationAnswer:
    """Return one deterministic answer for a focused question."""
    text_answers = {
        BriefField.PROBLEM: (
            "Hotel staff currently coordinate bookings through disconnected spreadsheets."
        ),
        BriefField.DOMAIN: ("Hospitality and hotel operations."),
    }
    text_value = text_answers.get(question.field)

    if text_value is not None:
        return ClarificationAnswer.text(
            question_id=(question.question_id),
            value=text_value,
        )

    if not question.unknown_allowed:
        raise AssertionError(
            f"the acceptance fixture requires UNKNOWN support for {question.field.value}"
        )

    return ClarificationAnswer.unknown(question_id=(question.question_id))


def clarify_brief(
    source: ProjectBriefVersion,
) -> tuple[
    ProjectBriefVersion,
    int,
]:
    """Resolve every missing field within the configured round limit."""
    current = source
    round_count = 0

    while current.brief.missing_fields:
        if round_count >= MAX_CLARIFICATION_ROUNDS:
            break

        questions = focused_clarification_questions(
            current.brief,
            maximum_questions=5,
        )

        if not questions:
            raise AssertionError("missing fields must produce clarification questions")

        answers = tuple(answer_for_question(question) for question in questions)
        application = apply_clarification_answers(
            current.brief,
            answers,
        )

        if (
            application.status is not ClarificationApplicationStatus.APPLIED
            or application.updated_brief is None
        ):
            raise AssertionError("valid clarification answers must update the Project Brief")

        round_count += 1
        updated_brief = application.updated_brief
        version_number = current.version_number + 1
        current = ProjectBriefVersion(
            id=brief_version_id(version_number),
            project_id=PROJECT_ID,
            version_number=version_number,
            schema_version=(updated_brief.SCHEMA_VERSION),
            brief=updated_brief,
            content_hash=(updated_brief.content_hash),
            created_by_user_id=OWNER_ID,
            created_at=(BASE_TIME + timedelta(minutes=round_count)),
        )

    return (
        current,
        round_count,
    )


def approved_gate(
    *,
    gate_id: UUID,
    gate_type: HumanGateType,
    artifact: GateArtifactReference,
    submit_event_id: UUID,
    approve_event_id: UUID,
    created_at: datetime,
) -> HumanGate:
    """Create, submit, and approve one deterministic human gate."""
    draft = create_human_gate(
        gate_id=gate_id,
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        gate_type=gate_type,
        artifact=artifact,
        created_at=created_at,
    )
    submitted = transition_human_gate(
        draft,
        action=HumanGateAction.SUBMIT,
        actor_user_id=OWNER_ID,
        occurred_at=(created_at + timedelta(minutes=1)),
        event_id=submit_event_id,
    )

    if submitted.status is not HumanGateTransitionStatus.APPLIED:
        raise AssertionError("a draft gate must be submittable")

    approved = transition_human_gate(
        submitted.gate,
        action=HumanGateAction.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=(created_at + timedelta(minutes=2)),
        event_id=approve_event_id,
    )

    if approved.status is not HumanGateTransitionStatus.APPLIED:
        raise AssertionError("a submitted gate must be approvable")

    return approved.gate


def catalog_ordered_members(
    *members: ProposedTeamMember,
) -> tuple[
    ProposedTeamMember,
    ...,
]:
    """Return unique members in fixed-catalog declaration order."""
    members_by_agent = {member.agent_id: member for member in members}

    if len(members_by_agent) != len(members):
        raise ValueError("team fixture contains duplicate agents")

    return tuple(
        members_by_agent[entry.agent_id]
        for entry in all_agent_catalog_entries()
        if entry.agent_id in members_by_agent
    )


def owner_added_member(
    *,
    agent_id: AgentIdentifier,
    statement: str,
) -> ProposedTeamMember:
    """Create one owner-added optional team member."""
    return ProposedTeamMember(
        agent_id=agent_id,
        source=(TeamProposalMemberSource.OWNER_ADDED),
        justifications=(
            TeamProposalJustification(
                kind=(TeamProposalJustificationKind.OWNER_RATIONALE),
                code=("OWNER_SELECTED_ROLE"),
                statement=statement,
            ),
        ),
    )


def generated_team_proposal(
    brief_version: ProjectBriefVersion,
) -> AgentTeamProposal:
    """Generate the deterministic mandatory-only proposal."""
    constraints = determine_team_constraints(
        project_mode=(ProjectMode.GREENFIELD_GENERATION),
        brief=brief_version.brief,
    )

    if constraints.has_conflicts:
        raise AssertionError("the acceptance fixture must not contain contradictory role signals")

    mobile_constraint = constraints.constraint_for(AgentIdentifier.MOBILE_ENGINEER)

    if mobile_constraint.kind is not TeamRoleConstraintKind.OPTIONAL:
        raise AssertionError("Mobile Engineer must remain optional for the web acceptance fixture")

    generation = asyncio.run(
        FakeDeterministicTeamProposalAdapter().propose(
            TeamProposalRequest(
                project_mode=(ProjectMode.GREENFIELD_GENERATION),
                brief_version=(brief_version),
                constraints=constraints,
            )
        )
    )

    if (
        generation.status is not TeamProposalGenerationStatus.PROPOSED
        or generation.proposal is None
    ):
        raise AssertionError("the deterministic adapter must produce a typed team proposal")

    return generation.proposal


def build_ready_project() -> ReadyProjectScenario:
    """Run the complete Sprint 03 governed setup journey."""
    brief_version, round_count = clarify_brief(initial_brief_version())

    if brief_version.brief.missing_fields:
        raise AssertionError("clarification must resolve every missing field")

    brief_gate = approved_gate(
        gate_id=GATE_ONE_ID,
        gate_type=(HumanGateType.PROJECT_BRIEF),
        artifact=(project_brief_artifact_reference(brief_version)),
        submit_event_id=(GATE_ONE_SUBMIT_EVENT_ID),
        approve_event_id=(GATE_ONE_APPROVE_EVENT_ID),
        created_at=(BASE_TIME + timedelta(minutes=10)),
    )
    context = TeamSelectionContext(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        project_mode=(ProjectMode.GREENFIELD_GENERATION),
        brief_version=brief_version,
        brief_gate=brief_gate,
    )
    proposal = generated_team_proposal(brief_version)
    generated_version = TeamProposalVersion(
        id=GENERATED_TEAM_ID,
        project_id=PROJECT_ID,
        version_number=1,
        proposal=proposal,
        revision_kind=(TeamProposalRevisionKind.PROPOSER_GENERATED),
        created_by_user_id=(OWNER_ID),
        created_at=(BASE_TIME + timedelta(minutes=20)),
    )

    mobile_member = owner_added_member(
        agent_id=(AgentIdentifier.MOBILE_ENGINEER),
        statement=("The owner wants optional mobile expertise for a future companion application."),
    )
    edited_proposal = replace(
        proposal,
        members=(
            catalog_ordered_members(
                *proposal.members,
                mobile_member,
            )
        ),
    )
    edited_version = TeamProposalVersion(
        id=EDITED_TEAM_ID,
        project_id=PROJECT_ID,
        version_number=2,
        proposal=edited_proposal,
        revision_kind=(TeamProposalRevisionKind.OWNER_EDITED),
        based_on_version_number=1,
        created_by_user_id=OWNER_ID,
        created_at=(BASE_TIME + timedelta(minutes=21)),
    )
    team_gate = approved_gate(
        gate_id=GATE_TWO_ID,
        gate_type=(HumanGateType.AGENT_TEAM),
        artifact=(agent_team_artifact_reference(edited_version)),
        submit_event_id=(GATE_TWO_SUBMIT_EVENT_ID),
        approve_event_id=(GATE_TWO_APPROVE_EVENT_ID),
        created_at=(BASE_TIME + timedelta(minutes=30)),
    )
    readiness = project_workflow_readiness(
        context=context,
        proposal=edited_version,
        team_gate=team_gate,
    )

    return ReadyProjectScenario(
        clarification_round_count=(round_count),
        brief_version=brief_version,
        brief_gate=brief_gate,
        context=context,
        generated_team_version=(generated_version),
        team_version=edited_version,
        team_gate=team_gate,
        readiness=readiness,
    )


def revised_brief_version(
    current: ProjectBriefVersion,
) -> ProjectBriefVersion:
    """Create one newer immutable Project Brief version."""
    revised_brief = replace(
        current.brief,
        description=("A revised browser-based application for managing hotel operations."),
    )
    version_number = current.version_number + 1

    return ProjectBriefVersion(
        id=brief_version_id(version_number),
        project_id=current.project_id,
        version_number=version_number,
        schema_version=(revised_brief.SCHEMA_VERSION),
        brief=revised_brief,
        content_hash=(revised_brief.content_hash),
        created_by_user_id=OWNER_ID,
        created_at=(BASE_TIME + timedelta(hours=2)),
    )


def revised_team_version(
    current: TeamProposalVersion,
) -> TeamProposalVersion:
    """Create one newer team version with another optional role."""
    constraint = current.proposal.constraints.constraint_for(AgentIdentifier.ACCESSIBILITY_REVIEWER)

    if constraint.kind is not TeamRoleConstraintKind.OPTIONAL:
        raise AssertionError(
            "Accessibility Reviewer must remain optional for the acceptance fixture"
        )

    accessibility_member = owner_added_member(
        agent_id=(AgentIdentifier.ACCESSIBILITY_REVIEWER),
        statement=("The owner wants an explicit accessibility review before implementation."),
    )
    proposal = replace(
        current.proposal,
        members=(
            catalog_ordered_members(
                *current.proposal.members,
                accessibility_member,
            )
        ),
    )

    return TeamProposalVersion(
        id=REVISED_TEAM_ID,
        project_id=current.project_id,
        version_number=(current.version_number + 1),
        proposal=proposal,
        revision_kind=(TeamProposalRevisionKind.OWNER_EDITED),
        based_on_version_number=(current.version_number),
        created_by_user_id=OWNER_ID,
        created_at=(BASE_TIME + timedelta(hours=3)),
    )


def test_governed_project_setup_reaches_readiness_after_two_approvals() -> None:
    """Complete clarification, team selection, and both human gates."""
    scenario = build_ready_project()

    assert scenario.clarification_round_count == MAX_CLARIFICATION_ROUNDS
    assert scenario.brief_version.brief.missing_fields == frozenset()
    assert BriefField.TEMPORAL_CONSTRAINTS in scenario.brief_version.brief.unknown_fields
    assert BriefField.BUDGET in scenario.brief_version.brief.unknown_fields

    assert (
        project_brief_gate_is_currently_approved(
            scenario.brief_gate,
            scenario.brief_version,
        )
        is True
    )
    assert scenario.brief_gate.status is HumanGateStatus.APPROVED
    assert scenario.brief_gate.artifact.artifact_id == scenario.brief_version.id
    assert scenario.brief_gate.artifact.version == scenario.brief_version.version_number
    assert scenario.brief_gate.artifact.content_hash == scenario.brief_version.content_hash

    assert (
        team_proposal_matches_context(
            scenario.team_version,
            scenario.context,
        )
        is True
    )
    assert scenario.team_version.proposal.brief_version_id == scenario.brief_version.id
    assert (
        scenario.team_version.proposal.brief_version_number == scenario.brief_version.version_number
    )
    assert scenario.team_version.proposal.brief_content_hash == scenario.brief_version.content_hash

    assert scenario.generated_team_version.version_number == 1
    assert scenario.team_version.version_number == 2
    assert scenario.team_version.based_on_version_number == 1
    assert scenario.team_version.revision_kind is TeamProposalRevisionKind.OWNER_EDITED

    mobile = scenario.team_version.proposal.member_for(AgentIdentifier.MOBILE_ENGINEER)

    assert mobile.source is (TeamProposalMemberSource.OWNER_ADDED)
    assert mobile.justifications[0].kind is TeamProposalJustificationKind.OWNER_RATIONALE
    assert mobile.justifications[0].statement == (
        "The owner wants optional mobile expertise for a future companion application."
    )

    assert (
        agent_team_gate_is_currently_approved(
            scenario.team_gate,
            scenario.team_version,
        )
        is True
    )
    assert scenario.team_gate.status is HumanGateStatus.APPROVED
    assert scenario.team_gate.artifact.artifact_id == scenario.team_version.id
    assert scenario.team_gate.artifact.version == scenario.team_version.version_number
    assert scenario.team_gate.artifact.content_hash == scenario.team_version.content_hash

    assert scenario.readiness is (ProjectWorkflowReadiness.READY_FOR_MAIN_WORKFLOW)

    for content_hash in (
        scenario.brief_version.content_hash,
        scenario.team_version.content_hash,
        scenario.team_version.proposal.constraints.content_hash,
    ):
        assert len(content_hash) == 64
        assert all(character in "0123456789abcdef" for character in content_hash)


def test_new_brief_version_invalidates_ready_project() -> None:
    """Require Gate 1 again when the current Project Brief changes."""
    scenario = build_ready_project()
    revised_version = revised_brief_version(scenario.brief_version)
    stale_result = mark_human_gate_stale(
        scenario.brief_gate,
        current_artifact=(project_brief_artifact_reference(revised_version)),
        occurred_at=(
            BASE_TIME
            + timedelta(
                hours=2,
                minutes=1,
            )
        ),
        event_id=(GATE_ONE_STALE_EVENT_ID),
    )

    assert stale_result.status is (HumanGateTransitionStatus.APPLIED)
    assert stale_result.event is not None
    assert stale_result.gate.status is (HumanGateStatus.STALE)

    revised_context = TeamSelectionContext(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        project_mode=(ProjectMode.GREENFIELD_GENERATION),
        brief_version=(revised_version),
        brief_gate=(stale_result.gate),
    )

    assert (
        project_brief_gate_is_currently_approved(
            stale_result.gate,
            revised_version,
        )
        is False
    )
    assert (
        team_proposal_matches_context(
            scenario.team_version,
            revised_context,
        )
        is False
    )
    assert (
        project_workflow_readiness(
            context=revised_context,
            proposal=(scenario.team_version),
            team_gate=(scenario.team_gate),
        )
        is ProjectWorkflowReadiness.BRIEF_APPROVAL_REQUIRED
    )


def test_new_team_version_requires_gate_two_reapproval() -> None:
    """Require Gate 2 again when the owner changes the current team."""
    scenario = build_ready_project()
    revised_version = revised_team_version(scenario.team_version)

    assert (
        team_proposal_matches_context(
            revised_version,
            scenario.context,
        )
        is True
    )
    assert (
        agent_team_gate_is_currently_approved(
            scenario.team_gate,
            revised_version,
        )
        is False
    )
    assert (
        project_workflow_readiness(
            context=scenario.context,
            proposal=revised_version,
            team_gate=(scenario.team_gate),
        )
        is ProjectWorkflowReadiness.TEAM_APPROVAL_REQUIRED
    )

    stale_result = mark_human_gate_stale(
        scenario.team_gate,
        current_artifact=(agent_team_artifact_reference(revised_version)),
        occurred_at=(
            BASE_TIME
            + timedelta(
                hours=3,
                minutes=1,
            )
        ),
        event_id=(GATE_TWO_STALE_EVENT_ID),
    )

    assert stale_result.status is (HumanGateTransitionStatus.APPLIED)
    assert stale_result.event is not None
    assert stale_result.gate.status is (HumanGateStatus.STALE)
    assert stale_result.event.artifact.artifact_id == revised_version.id
    assert stale_result.event.artifact.version == revised_version.version_number
    assert stale_result.event.artifact.content_hash == revised_version.content_hash
