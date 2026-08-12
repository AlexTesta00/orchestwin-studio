"""Tests for owner-edited team versions and Gate 2."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import TracebackType
from uuid import UUID

from orchestwin.agents.catalog import (
    AgentIdentifier,
)
from orchestwin.agents.proposals import (
    TeamProposalRevisionKind,
    TeamProposalVersion,
    TeamSelectionContext,
)
from orchestwin.agents.selection_rules import (
    determine_team_constraints,
)
from orchestwin.agents.team_gate import (
    AgentTeamGateDecisionStatus,
    AgentTeamGateSubmissionStatus,
    LocalAgentTeamApprovalService,
    OwnerEditedProposalPersistenceResult,
    OwnerEditedProposalPersistenceStatus,
    ProjectWorkflowReadiness,
    TeamEditIssueCode,
    TeamEditStatus,
    agent_team_gate_is_currently_approved,
    create_owner_agent_rationale,
)
from orchestwin.models.fake_team_proposals import (
    FakeDeterministicTeamProposalAdapter,
)
from orchestwin.models.team_proposals import (
    TeamProposalMemberSource,
    TeamProposalRequest,
)
from orchestwin.projects.brief_gate import (
    project_brief_artifact_reference,
)
from orchestwin.projects.briefs import (
    BriefField,
    ProjectBriefVersion,
    create_project_brief,
)
from orchestwin.projects.domain import (
    ProjectMode,
)
from orchestwin.workflow.gates import (
    HumanGate,
    HumanGateAction,
    HumanGateEvent,
    HumanGateStatus,
    HumanGateTransitionStatus,
    HumanGateType,
    create_human_gate,
    transition_human_gate,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
OTHER_OWNER_ID = UUID("00000000-0000-4000-8000-000000000002")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
NOW = datetime(
    2026,
    8,
    12,
    12,
    0,
    tzinfo=UTC,
)


class IncrementingUuidFactory:
    """Return deterministic UUID values."""

    def __init__(
        self,
        *,
        start: int,
    ) -> None:
        self._next_value = start

    def __call__(self) -> UUID:
        value = UUID(int=self._next_value)
        self._next_value += 1
        return value


def complete_brief_version(
    *,
    description: str = ("A Vue web application with a FastAPI backend."),
) -> ProjectBriefVersion:
    """Create an epistemically complete Project Brief."""
    provided = {
        BriefField.NAME,
        BriefField.DESCRIPTION,
        BriefField.TECHNICAL_CONSTRAINTS,
    }
    brief = create_project_brief(
        name="Agent Team project",
        description=description,
        technical_constraints=[
            "Vue frontend",
            "FastAPI backend",
            "PostgreSQL database",
        ],
        unknown_fields=[field for field in BriefField if field not in provided],
    )

    return ProjectBriefVersion(
        id=UUID(int=100),
        project_id=PROJECT_ID,
        version_number=1,
        schema_version=(brief.SCHEMA_VERSION),
        brief=brief,
        content_hash=brief.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=NOW,
    )


def approved_brief_gate(
    version: ProjectBriefVersion,
) -> HumanGate:
    """Create one approved Gate 1."""
    draft = create_human_gate(
        gate_id=UUID(int=200),
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        gate_type=(HumanGateType.PROJECT_BRIEF),
        artifact=(project_brief_artifact_reference(version)),
        created_at=NOW,
    )
    submitted = transition_human_gate(
        draft,
        action=HumanGateAction.SUBMIT,
        actor_user_id=OWNER_ID,
        occurred_at=(NOW + timedelta(seconds=1)),
        event_id=UUID(int=201),
    )

    assert submitted.status is (HumanGateTransitionStatus.APPLIED)

    approved = transition_human_gate(
        submitted.gate,
        action=HumanGateAction.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=(NOW + timedelta(seconds=2)),
        event_id=UUID(int=202),
    )

    assert approved.status is (HumanGateTransitionStatus.APPLIED)

    return approved.gate


async def generated_version(
    version: ProjectBriefVersion,
) -> TeamProposalVersion:
    """Create the deterministic initial team proposal."""
    constraints = determine_team_constraints(
        project_mode=(ProjectMode.GREENFIELD_GENERATION),
        brief=version.brief,
    )
    generation = await FakeDeterministicTeamProposalAdapter().propose(
        TeamProposalRequest(
            project_mode=(ProjectMode.GREENFIELD_GENERATION),
            brief_version=version,
            constraints=constraints,
        )
    )

    assert generation.proposal is not None

    return TeamProposalVersion(
        id=UUID(int=300),
        project_id=PROJECT_ID,
        version_number=1,
        proposal=generation.proposal,
        revision_kind=(TeamProposalRevisionKind.PROPOSER_GENERATED),
        created_by_user_id=OWNER_ID,
        created_at=NOW,
    )


class InMemoryContextRepository:
    """Owner-scoped current team-selection context."""

    def __init__(self) -> None:
        self.contexts: dict[
            tuple[UUID, UUID],
            TeamSelectionContext,
        ] = {}

    def set_context(
        self,
        context: TeamSelectionContext,
    ) -> None:
        """Set the current context."""
        self.contexts[
            (
                context.project_id,
                context.owner_user_id,
            )
        ] = context

    async def get_current_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> TeamSelectionContext | None:
        """Return the current context."""
        return self.contexts.get(
            (
                project_id,
                owner_user_id,
            )
        )

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> TeamSelectionContext | None:
        """Return the current context as an in-memory row lock."""
        return await self.get_current_owned(
            project_id=project_id,
            owner_user_id=owner_user_id,
        )


class InMemoryEditableProposalRepository:
    """In-memory immutable proposal history."""

    def __init__(self) -> None:
        self.versions: dict[
            UUID,
            list[TeamProposalVersion],
        ] = {}

    def seed(
        self,
        version: TeamProposalVersion,
    ) -> None:
        """Seed the initial generated version."""
        self.versions.setdefault(
            version.project_id,
            [],
        ).append(version)

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> TeamProposalVersion | None:
        """Return the latest proposal."""
        del owner_user_id

        versions = self.versions.get(
            project_id,
            [],
        )

        return versions[-1] if versions else None

    async def create_owner_edited_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        based_on: TeamProposalVersion,
        proposal,
    ) -> OwnerEditedProposalPersistenceResult:
        """Create or reuse an owner-edited proposal."""
        current = await self.get_current_owned_for_update(
            project_id=project_id,
            owner_user_id=owner_user_id,
        )

        if (
            current is None
            or current.id != based_on.id
            or current.content_hash != based_on.content_hash
        ):
            return OwnerEditedProposalPersistenceResult(
                status=(OwnerEditedProposalPersistenceStatus.BASE_VERSION_CHANGED)
            )

        if proposal.content_hash == current.content_hash:
            return OwnerEditedProposalPersistenceResult(
                status=(OwnerEditedProposalPersistenceStatus.UNCHANGED),
                version=current,
            )

        next_version = TeamProposalVersion(
            id=UUID(int=300 + current.version_number),
            project_id=project_id,
            version_number=(current.version_number + 1),
            proposal=proposal,
            revision_kind=(TeamProposalRevisionKind.OWNER_EDITED),
            based_on_version_number=(current.version_number),
            created_by_user_id=(owner_user_id),
            created_at=NOW,
        )
        self.versions[project_id].append(next_version)

        return OwnerEditedProposalPersistenceResult(
            status=(OwnerEditedProposalPersistenceStatus.CREATED),
            version=next_version,
        )


class InMemoryGateRepository:
    """In-memory gate state and event history."""

    def __init__(self) -> None:
        self.gates: list[HumanGate] = []
        self.events: list[HumanGateEvent] = []

    async def add_with_event(
        self,
        *,
        gate: HumanGate,
        event: HumanGateEvent,
    ) -> HumanGate:
        """Add a gate and first event."""
        self.gates.append(gate)
        self.events.append(event)
        return gate

    async def get_latest_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_type: HumanGateType,
    ) -> HumanGate | None:
        """Return the latest matching gate."""
        matching = [
            gate
            for gate in self.gates
            if (
                gate.project_id == project_id
                and gate.owner_user_id == owner_user_id
                and gate.gate_type is gate_type
            )
        ]

        if not matching:
            return None

        return max(
            matching,
            key=lambda gate: (
                gate.iteration,
                gate.id,
            ),
        )

    async def save_transition(
        self,
        *,
        previous_gate: HumanGate,
        updated_gate: HumanGate,
        event: HumanGateEvent,
    ) -> HumanGate:
        """Replace one gate and append its event."""
        index = self.gates.index(previous_gate)
        self.gates[index] = updated_gate
        self.events.append(event)

        return updated_gate

    async def list_events_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ) -> tuple[
        HumanGateEvent,
        ...,
    ]:
        """Return ordered events for an owned gate."""
        gate = next(
            (
                candidate
                for candidate in self.gates
                if (
                    candidate.id == gate_id
                    and candidate.project_id == project_id
                    and candidate.owner_user_id == owner_user_id
                )
            ),
            None,
        )

        if gate is None:
            return ()

        return tuple(
            sorted(
                (event for event in self.events if event.gate_id == gate_id),
                key=lambda event: event.sequence_number,
            )
        )


class InMemoryAgentTeamUnitOfWork:
    """Reusable in-memory Agent Team transaction boundary."""

    def __init__(
        self,
        contexts: InMemoryContextRepository,
        proposals: InMemoryEditableProposalRepository,
        gates: InMemoryGateRepository,
    ) -> None:
        self.contexts = contexts
        self.proposals = proposals
        self.gates = gates

    async def __aenter__(
        self,
    ) -> InMemoryAgentTeamUnitOfWork:
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


def build_fixture(
    *,
    description: str = ("A Vue web application with a FastAPI backend."),
    brief_approved: bool = True,
):
    """Create context, initial proposal, repositories, and service."""
    brief = complete_brief_version(description=description)
    context = TeamSelectionContext(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        project_mode=(ProjectMode.GREENFIELD_GENERATION),
        brief_version=brief,
        brief_gate=(approved_brief_gate(brief) if brief_approved else None),
    )
    initial = asyncio.run(generated_version(brief))
    contexts = InMemoryContextRepository()
    contexts.set_context(context)
    proposals = InMemoryEditableProposalRepository()
    proposals.seed(initial)
    gates = InMemoryGateRepository()
    service = LocalAgentTeamApprovalService(
        unit_of_work_factory=lambda: InMemoryAgentTeamUnitOfWork(
            contexts,
            proposals,
            gates,
        ),
        clock=lambda: NOW,
        gate_id_factory=(IncrementingUuidFactory(start=1000)),
        event_id_factory=(IncrementingUuidFactory(start=2000)),
    )

    return (
        context,
        initial,
        contexts,
        proposals,
        gates,
        service,
    )


def test_owner_adds_optional_agent_in_new_version() -> None:
    """Add one optional role with explicit owner provenance."""
    (
        _,
        initial,
        _,
        proposals,
        _,
        service,
    ) = build_fixture()

    result = asyncio.run(
        service.edit_current(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            selected_agent_ids=(
                *initial.proposal.selected_agent_ids,
                AgentIdentifier.MOBILE_ENGINEER,
            ),
            owner_rationales=(
                create_owner_agent_rationale(
                    agent_id=(AgentIdentifier.MOBILE_ENGINEER),
                    statement=("The owner wants an optional mobile companion application."),
                ),
            ),
        )
    )

    assert result.status is (TeamEditStatus.UPDATED)
    assert result.version is not None
    assert result.version.version_number == 2
    assert result.version.revision_kind is (TeamProposalRevisionKind.OWNER_EDITED)
    assert result.version.based_on_version_number == 1

    mobile = result.version.proposal.member_for(AgentIdentifier.MOBILE_ENGINEER)

    assert mobile.source is (TeamProposalMemberSource.OWNER_ADDED)
    assert mobile.justifications[0].statement == (
        "The owner wants an optional mobile companion application."
    )
    assert len(proposals.versions[PROJECT_ID]) == 2


def test_same_selection_is_unchanged() -> None:
    """Avoid creating an owner-edited duplicate."""
    (
        _,
        initial,
        _,
        proposals,
        _,
        service,
    ) = build_fixture()

    result = asyncio.run(
        service.edit_current(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            selected_agent_ids=(initial.proposal.selected_agent_ids),
        )
    )

    assert result.status is (TeamEditStatus.UNCHANGED)
    assert result.version == initial
    assert len(proposals.versions[PROJECT_ID]) == 1


def test_owner_cannot_remove_mandatory_agent() -> None:
    """Protect deterministic mandatory membership."""
    (
        _,
        initial,
        _,
        _,
        _,
        service,
    ) = build_fixture()
    selected = tuple(
        agent_id
        for agent_id in initial.proposal.selected_agent_ids
        if agent_id is not AgentIdentifier.REQUIREMENTS_ANALYST
    )

    result = asyncio.run(
        service.edit_current(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            selected_agent_ids=selected,
        )
    )

    assert result.status is (TeamEditStatus.REJECTED)
    assert result.issues == (result.issues[0],)
    assert result.issues[0].code is (TeamEditIssueCode.MANDATORY_AGENT_MISSING)
    assert result.issues[0].agent_id is (AgentIdentifier.REQUIREMENTS_ANALYST)


def test_new_optional_agent_requires_owner_rationale() -> None:
    """Require inspectable owner reasoning for additions."""
    (
        _,
        initial,
        _,
        _,
        _,
        service,
    ) = build_fixture()

    result = asyncio.run(
        service.edit_current(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            selected_agent_ids=(
                *initial.proposal.selected_agent_ids,
                AgentIdentifier.MOBILE_ENGINEER,
            ),
        )
    )

    assert result.status is (TeamEditStatus.REJECTED)
    assert result.issues[0].code is (TeamEditIssueCode.RATIONALE_REQUIRED)
    assert result.issues[0].agent_id is (AgentIdentifier.MOBILE_ENGINEER)


def test_owner_cannot_add_impossible_agent() -> None:
    """Enforce explicit deterministic exclusions in the backend."""
    (
        _,
        initial,
        _,
        _,
        _,
        service,
    ) = build_fixture(description=("A Vue web application with no mobile application."))

    result = asyncio.run(
        service.edit_current(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            selected_agent_ids=(
                *initial.proposal.selected_agent_ids,
                AgentIdentifier.MOBILE_ENGINEER,
            ),
            owner_rationales=(
                create_owner_agent_rationale(
                    agent_id=(AgentIdentifier.MOBILE_ENGINEER),
                    statement=("The owner requested mobile."),
                ),
            ),
        )
    )

    assert result.status is (TeamEditStatus.REJECTED)
    assert result.issues[0].code is (TeamEditIssueCode.AGENT_NOT_SELECTABLE)


def test_gate_two_approval_produces_readiness() -> None:
    """Approve the exact current team before main-workflow readiness."""
    (
        _,
        initial,
        _,
        _,
        _,
        service,
    ) = build_fixture()

    submitted = asyncio.run(
        service.submit_gate(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert submitted.status is (AgentTeamGateSubmissionStatus.SUBMITTED)
    assert submitted.gate is not None
    assert submitted.gate.status is (HumanGateStatus.PENDING_APPROVAL)

    approved = asyncio.run(
        service.decide_gate(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            action=(HumanGateAction.APPROVE),
        )
    )

    assert approved.status is (AgentTeamGateDecisionStatus.APPLIED)
    assert approved.gate is not None
    assert approved.gate.status is (HumanGateStatus.APPROVED)
    assert (
        agent_team_gate_is_currently_approved(
            approved.gate,
            initial,
        )
        is True
    )

    readiness = asyncio.run(
        service.readiness(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert readiness is (ProjectWorkflowReadiness.READY_FOR_MAIN_WORKFLOW)


def test_team_edit_stales_gate_two_and_readiness() -> None:
    """Invalidate Gate 2 when the owner creates a new team version."""
    (
        _,
        initial,
        _,
        _,
        gates,
        service,
    ) = build_fixture()

    asyncio.run(
        service.submit_gate(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )
    asyncio.run(
        service.decide_gate(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            action=(HumanGateAction.APPROVE),
        )
    )

    edited = asyncio.run(
        service.edit_current(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            selected_agent_ids=(
                *initial.proposal.selected_agent_ids,
                AgentIdentifier.MOBILE_ENGINEER,
            ),
            owner_rationales=(
                create_owner_agent_rationale(
                    agent_id=(AgentIdentifier.MOBILE_ENGINEER),
                    statement=("Add a mobile specialist for future exploration."),
                ),
            ),
        )
    )

    assert edited.status is (TeamEditStatus.UPDATED)
    assert len(edited.events) == 1

    latest_gate = asyncio.run(
        gates.get_latest_owned_for_update(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            gate_type=(HumanGateType.AGENT_TEAM),
        )
    )

    assert latest_gate is not None
    assert latest_gate.status is (HumanGateStatus.STALE)

    readiness = asyncio.run(
        service.readiness(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert readiness is (ProjectWorkflowReadiness.TEAM_APPROVAL_REQUIRED)


def test_gate_two_requires_gate_one_approval() -> None:
    """Keep team approval blocked before Project Brief approval."""
    (
        _,
        _,
        _,
        _,
        _,
        service,
    ) = build_fixture(brief_approved=False)

    result = asyncio.run(
        service.submit_gate(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert result.status is (AgentTeamGateSubmissionStatus.BRIEF_NOT_APPROVED)


def test_other_owner_cannot_edit_team() -> None:
    """Hide the project and team from another user."""
    (
        _,
        initial,
        _,
        proposals,
        _,
        service,
    ) = build_fixture()

    result = asyncio.run(
        service.edit_current(
            project_id=PROJECT_ID,
            owner_user_id=(OTHER_OWNER_ID),
            selected_agent_ids=(initial.proposal.selected_agent_ids),
        )
    )

    assert result.status is (TeamEditStatus.PROJECT_NOT_FOUND)
    assert len(proposals.versions[PROJECT_ID]) == 1
