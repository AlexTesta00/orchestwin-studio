"""Owner editing and human approval for versioned agent teams."""

from __future__ import annotations

from collections import Counter
from collections.abc import (
    Callable,
    Iterable,
)
from dataclasses import (
    dataclass,
    replace,
)
from datetime import UTC, datetime
from enum import StrEnum
from types import TracebackType
from typing import Final, Protocol, Self
from uuid import UUID, uuid4

from orchestwin.agents.catalog import (
    AgentIdentifier,
    all_agent_catalog_entries,
)
from orchestwin.agents.proposals import (
    TeamProposalVersion,
    TeamSelectionContext,
    TeamSelectionContextRepository,
)
from orchestwin.agents.selection_rules import (
    TeamRoleConstraintKind,
)
from orchestwin.models.team_proposals import (
    MAX_PROPOSAL_JUSTIFICATION_LENGTH,
    AgentTeamProposal,
    ProposedTeamMember,
    TeamProposalJustification,
    TeamProposalJustificationKind,
    TeamProposalMemberSource,
)
from orchestwin.workflow.gate_flow import (
    Clock,
    GateOutcomes,
    UuidFactory,
    current_time,
    decide_current,
    gate_history,
    gate_is_currently_approved,
    latest_gate,
    submit_artifact,
)
from orchestwin.workflow.gates import (
    GateArtifactReference,
    HumanGate,
    HumanGateAction,
    HumanGateEvent,
    HumanGateIssueCode,
    HumanGateStatus,
    HumanGateTransitionStatus,
    HumanGateType,
    mark_human_gate_stale,
)
from orchestwin.workflow.repository import (
    HumanGateRepository,
)

_AGENT_ORDER = tuple(entry.agent_id for entry in all_agent_catalog_entries())
_AGENT_POSITION = {agent_id: position for position, agent_id in enumerate(_AGENT_ORDER)}

OWNER_CHOICE_STATEMENT: Final = "Chosen by the owner."


class TeamEditIssueCode(StrEnum):
    """Stable reasons an owner team edit may be rejected."""

    DUPLICATE_AGENT = "DUPLICATE_AGENT"
    DUPLICATE_RATIONALE = "DUPLICATE_RATIONALE"
    MANDATORY_AGENT_MISSING = "MANDATORY_AGENT_MISSING"
    AGENT_NOT_SELECTABLE = "AGENT_NOT_SELECTABLE"
    RATIONALE_REQUIRED = "RATIONALE_REQUIRED"
    UNUSED_RATIONALE = "UNUSED_RATIONALE"


class TeamEditStatus(StrEnum):
    """Stable outcomes of editing the current proposal."""

    UPDATED = "UPDATED"
    UNCHANGED = "UNCHANGED"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    BRIEF_NOT_FOUND = "BRIEF_NOT_FOUND"
    BRIEF_NOT_APPROVED = "BRIEF_NOT_APPROVED"
    PROPOSAL_NOT_FOUND = "PROPOSAL_NOT_FOUND"
    PROPOSAL_STALE = "PROPOSAL_STALE"
    CONTEXT_CHANGED = "CONTEXT_CHANGED"
    REJECTED = "REJECTED"


class OwnerEditedProposalPersistenceStatus(StrEnum):
    """Stable outcomes of persisting an owner-edited proposal."""

    CREATED = "CREATED"
    UNCHANGED = "UNCHANGED"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    BASE_VERSION_CHANGED = "BASE_VERSION_CHANGED"


class AgentTeamGateSubmissionStatus(StrEnum):
    """Stable outcomes of submitting Gate 2."""

    SUBMITTED = "SUBMITTED"
    ALREADY_PENDING = "ALREADY_PENDING"
    ALREADY_APPROVED = "ALREADY_APPROVED"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    BRIEF_NOT_FOUND = "BRIEF_NOT_FOUND"
    BRIEF_NOT_APPROVED = "BRIEF_NOT_APPROVED"
    PROPOSAL_NOT_FOUND = "PROPOSAL_NOT_FOUND"
    PROPOSAL_STALE = "PROPOSAL_STALE"
    NEW_PROPOSAL_REQUIRED = "NEW_PROPOSAL_REQUIRED"
    GATE_BLOCKED = "GATE_BLOCKED"
    ITERATION_LIMIT_REACHED = "ITERATION_LIMIT_REACHED"
    TRANSITION_REJECTED = "TRANSITION_REJECTED"


class AgentTeamGateDecisionStatus(StrEnum):
    """Stable outcomes of a Gate 2 owner decision."""

    APPLIED = "APPLIED"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    BRIEF_NOT_FOUND = "BRIEF_NOT_FOUND"
    BRIEF_NOT_APPROVED = "BRIEF_NOT_APPROVED"
    PROPOSAL_NOT_FOUND = "PROPOSAL_NOT_FOUND"
    PROPOSAL_STALE = "PROPOSAL_STALE"
    GATE_NOT_FOUND = "GATE_NOT_FOUND"
    ARTIFACT_STALE = "ARTIFACT_STALE"
    REJECTED = "REJECTED"


class ProjectWorkflowReadiness(StrEnum):
    """Derived readiness for the future main workflow."""

    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    BRIEF_APPROVAL_REQUIRED = "BRIEF_APPROVAL_REQUIRED"
    TEAM_PROPOSAL_REQUIRED = "TEAM_PROPOSAL_REQUIRED"
    TEAM_APPROVAL_REQUIRED = "TEAM_APPROVAL_REQUIRED"
    READY_FOR_MAIN_WORKFLOW = "READY_FOR_MAIN_WORKFLOW"


@dataclass(frozen=True, slots=True)
class OwnerAgentRationale:
    """Normalized owner rationale for adding one optional role."""

    agent_id: AgentIdentifier
    statement: str

    def __post_init__(self) -> None:
        """Protect rationale normalization and length."""
        normalized = " ".join(self.statement.split())

        if not normalized or normalized != self.statement:
            raise ValueError("owner agent rationale must be normalized")

        if len(self.statement) > MAX_PROPOSAL_JUSTIFICATION_LENGTH:
            raise ValueError("owner agent rationale exceeds maximum length")


@dataclass(frozen=True, slots=True)
class TeamEditIssue:
    """One validation issue in an owner team selection."""

    code: TeamEditIssueCode
    agent_id: AgentIdentifier


@dataclass(frozen=True, slots=True)
class TeamEditResult:
    """Typed result of an owner team edit."""

    status: TeamEditStatus
    version: TeamProposalVersion | None = None
    issues: tuple[
        TeamEditIssue,
        ...,
    ] = ()
    events: tuple[
        HumanGateEvent,
        ...,
    ] = ()

    def __post_init__(self) -> None:
        """Protect successful and rejected result shapes."""
        successful = self.status in {
            TeamEditStatus.UPDATED,
            TeamEditStatus.UNCHANGED,
        }

        if successful:
            if self.version is None or self.issues:
                raise ValueError("successful team edits require only a proposal version")

            return

        if self.status is TeamEditStatus.REJECTED:
            if self.version is not None or not self.issues:
                raise ValueError("rejected team edits require only validation issues")

            return

        if self.version is not None or self.issues:
            raise ValueError("failed team edits must not contain proposal data")


@dataclass(frozen=True, slots=True)
class OwnerEditedProposalPersistenceResult:
    """Typed result of persisting an owner-edited proposal."""

    status: OwnerEditedProposalPersistenceStatus
    version: TeamProposalVersion | None = None

    def __post_init__(self) -> None:
        """Associate a version only with successful outcomes."""
        successful = self.status in {
            OwnerEditedProposalPersistenceStatus.CREATED,
            OwnerEditedProposalPersistenceStatus.UNCHANGED,
        }

        if successful != (self.version is not None):
            raise ValueError("successful owner-edited persistence must contain a proposal version")


@dataclass(frozen=True, slots=True)
class AgentTeamGateSubmissionResult:
    """Typed result of submitting Gate 2."""

    status: AgentTeamGateSubmissionStatus
    gate: HumanGate | None = None
    events: tuple[
        HumanGateEvent,
        ...,
    ] = ()
    issue: HumanGateIssueCode | None = None


@dataclass(frozen=True, slots=True)
class AgentTeamGateDecisionResult:
    """Typed result of applying an owner decision to Gate 2."""

    status: AgentTeamGateDecisionStatus
    gate: HumanGate | None = None
    event: HumanGateEvent | None = None
    issue: HumanGateIssueCode | None = None


class EditableTeamProposalRepository(Protocol):
    """Owner-scoped persistence required by editable teams."""

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> TeamProposalVersion | None:
        """Lock and return the current proposal version."""

    async def create_owner_edited_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        based_on: TeamProposalVersion,
        proposal: AgentTeamProposal,
    ) -> OwnerEditedProposalPersistenceResult:
        """Create or reuse an immutable owner-edited version."""


class AgentTeamUnitOfWork(Protocol):
    """Transactional boundary for editing and approving agent teams."""

    @property
    def contexts(
        self,
    ) -> TeamSelectionContextRepository:
        """Return the current team-selection context repository."""

    @property
    def proposals(
        self,
    ) -> EditableTeamProposalRepository:
        """Return the editable proposal repository."""

    @property
    def gates(
        self,
    ) -> HumanGateRepository:
        """Return the human-gate repository."""

    async def __aenter__(
        self,
    ) -> Self:
        """Open the transaction."""

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Commit or roll back the transaction."""


AgentTeamUnitOfWorkFactory = Callable[
    [],
    AgentTeamUnitOfWork,
]


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def create_owner_agent_rationale(
    *,
    agent_id: AgentIdentifier,
    statement: str,
) -> OwnerAgentRationale:
    """Create a normalized owner rationale."""
    normalized = " ".join(statement.split())

    return OwnerAgentRationale(
        agent_id=agent_id,
        statement=normalized,
    )


def agent_team_artifact_reference(
    version: TeamProposalVersion,
) -> GateArtifactReference:
    """Create the exact Gate 2 reference for one team version."""
    return GateArtifactReference(
        project_id=version.project_id,
        gate_type=HumanGateType.AGENT_TEAM,
        artifact_id=version.id,
        version=version.version_number,
        content_hash=version.content_hash,
    )


def team_proposal_matches_context(
    version: TeamProposalVersion,
    context: TeamSelectionContext,
) -> bool:
    """Return whether a proposal targets the exact current brief."""
    brief = context.brief_version
    proposal = version.proposal

    if brief is None:
        return False

    return (
        version.project_id == context.project_id
        and proposal.project_id == context.project_id
        and proposal.project_mode is context.project_mode
        and proposal.brief_version_id == brief.id
        and proposal.brief_version_number == brief.version_number
        and proposal.brief_content_hash == brief.content_hash
    )


def agent_team_gate_is_currently_approved(
    gate: HumanGate | None,
    version: TeamProposalVersion | None,
) -> bool:
    """Return whether Gate 2 approves the exact current team."""
    return gate_is_currently_approved(gate, version, agent_team_artifact_reference)


def project_workflow_readiness(
    *,
    context: TeamSelectionContext | None,
    proposal: TeamProposalVersion | None,
    team_gate: HumanGate | None,
) -> ProjectWorkflowReadiness:
    """Derive readiness without storing a mutable workflow flag."""
    if context is None:
        return ProjectWorkflowReadiness.PROJECT_NOT_FOUND

    if not context.brief_is_approved:
        return ProjectWorkflowReadiness.BRIEF_APPROVAL_REQUIRED

    if proposal is None or not team_proposal_matches_context(
        proposal,
        context,
    ):
        return ProjectWorkflowReadiness.TEAM_PROPOSAL_REQUIRED

    if not agent_team_gate_is_currently_approved(
        team_gate,
        proposal,
    ):
        return ProjectWorkflowReadiness.TEAM_APPROVAL_REQUIRED

    return ProjectWorkflowReadiness.READY_FOR_MAIN_WORKFLOW


_OUTCOMES = GateOutcomes(
    submission=AgentTeamGateSubmissionResult,
    submission_status=AgentTeamGateSubmissionStatus,
    new_artifact_required=AgentTeamGateSubmissionStatus.NEW_PROPOSAL_REQUIRED,
    decision=AgentTeamGateDecisionResult,
    decision_status=AgentTeamGateDecisionStatus,
)


class LocalAgentTeamApprovalService:
    """Edit versioned teams and govern them through Gate 2."""

    def __init__(
        self,
        *,
        unit_of_work_factory: (AgentTeamUnitOfWorkFactory),
        clock: Clock = utc_now,
        gate_id_factory: UuidFactory = uuid4,
        event_id_factory: UuidFactory = uuid4,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._gate_id_factory = gate_id_factory
        self._event_id_factory = event_id_factory

    async def edit_current(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        selected_agent_ids: Iterable[AgentIdentifier],
        owner_rationales: Iterable[OwnerAgentRationale] = (),
    ) -> TeamEditResult:
        """Create a new owner-edited proposal version."""
        timestamp = self._current_time()
        selected_batch = tuple(selected_agent_ids)
        rationale_batch = tuple(owner_rationales)

        async with self._unit_of_work_factory() as unit:
            context = await unit.contexts.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=(owner_user_id),
            )

            precondition = self._precondition(context, TeamEditStatus)

            if precondition is not None:
                return TeamEditResult(status=precondition)

            current = await unit.proposals.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=(owner_user_id),
            )

            if current is None:
                return TeamEditResult(status=(TeamEditStatus.PROPOSAL_NOT_FOUND))

            if context is None or not team_proposal_matches_context(
                current,
                context,
            ):
                return TeamEditResult(status=(TeamEditStatus.PROPOSAL_STALE))

            issues = self._selection_issues(
                current=current,
                selected_agent_ids=(selected_batch),
                owner_rationales=(rationale_batch),
            )

            if issues:
                return TeamEditResult(
                    status=(TeamEditStatus.REJECTED),
                    issues=issues,
                )

            proposal = self._edited_proposal(
                current=current,
                selected_agent_ids=(selected_batch),
                owner_rationales=(rationale_batch),
            )
            persisted = await unit.proposals.create_owner_edited_owned(
                project_id=project_id,
                owner_user_id=(owner_user_id),
                based_on=current,
                proposal=proposal,
            )

            if persisted.status is OwnerEditedProposalPersistenceStatus.PROJECT_NOT_FOUND:
                return TeamEditResult(status=(TeamEditStatus.PROJECT_NOT_FOUND))

            if persisted.status is OwnerEditedProposalPersistenceStatus.BASE_VERSION_CHANGED:
                return TeamEditResult(status=(TeamEditStatus.CONTEXT_CHANGED))

            if persisted.version is None:
                raise RuntimeError("successful owner edit did not return a proposal version")

            if persisted.status is OwnerEditedProposalPersistenceStatus.UNCHANGED:
                return TeamEditResult(
                    status=(TeamEditStatus.UNCHANGED),
                    version=(persisted.version),
                )

            stale_events: list[HumanGateEvent] = []
            latest_gate = await unit.gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=(owner_user_id),
                gate_type=(HumanGateType.AGENT_TEAM),
            )

            if (
                latest_gate is not None
                and latest_gate.status
                not in {
                    HumanGateStatus.STALE,
                    HumanGateStatus.CANCELLED,
                }
                and latest_gate.artifact != agent_team_artifact_reference(persisted.version)
            ):
                stale_result = mark_human_gate_stale(
                    latest_gate,
                    current_artifact=(agent_team_artifact_reference(persisted.version)),
                    occurred_at=timestamp,
                    event_id=(self._event_id_factory()),
                )

                if stale_result.status is HumanGateTransitionStatus.REJECTED:
                    raise RuntimeError("current Agent Team gate could not be marked stale")

                if (
                    stale_result.status is HumanGateTransitionStatus.APPLIED
                    and stale_result.event is not None
                ):
                    await unit.gates.save_transition(
                        previous_gate=(latest_gate),
                        updated_gate=(stale_result.gate),
                        event=(stale_result.event),
                    )
                    stale_events.append(stale_result.event)

            return TeamEditResult(
                status=(TeamEditStatus.UPDATED),
                version=persisted.version,
                events=tuple(stale_events),
            )

    async def submit_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> AgentTeamGateSubmissionResult:
        """Submit the current team proposal as Gate 2."""
        timestamp = self._current_time()

        async with self._unit_of_work_factory() as unit:
            context = await unit.contexts.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=(owner_user_id),
            )
            failure = self._precondition(context, AgentTeamGateSubmissionStatus)

            if failure is not None:
                return AgentTeamGateSubmissionResult(status=failure)

            proposal = await unit.proposals.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=(owner_user_id),
            )

            if proposal is None:
                return AgentTeamGateSubmissionResult(
                    status=(AgentTeamGateSubmissionStatus.PROPOSAL_NOT_FOUND)
                )

            if context is None or not team_proposal_matches_context(
                proposal,
                context,
            ):
                return AgentTeamGateSubmissionResult(
                    status=(AgentTeamGateSubmissionStatus.PROPOSAL_STALE)
                )

            return await submit_artifact(
                unit.gates,
                agent_team_artifact_reference(proposal),
                project_id=project_id,
                owner_user_id=owner_user_id,
                occurred_at=timestamp,
                gate_id_factory=self._gate_id_factory,
                event_id_factory=self._event_id_factory,
                outcomes=_OUTCOMES,
            )

    async def decide_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        action: HumanGateAction,
        reason: str | None = None,
    ) -> AgentTeamGateDecisionResult:
        """Apply one owner decision to Gate 2."""
        timestamp = self._current_time()

        async with self._unit_of_work_factory() as unit:
            context = await unit.contexts.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=(owner_user_id),
            )
            failure = self._precondition(context, AgentTeamGateDecisionStatus)

            if failure is not None:
                return AgentTeamGateDecisionResult(status=failure)

            proposal = await unit.proposals.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=(owner_user_id),
            )

            if proposal is None:
                return AgentTeamGateDecisionResult(
                    status=(AgentTeamGateDecisionStatus.PROPOSAL_NOT_FOUND)
                )

            if context is None or not team_proposal_matches_context(
                proposal,
                context,
            ):
                return AgentTeamGateDecisionResult(
                    status=(AgentTeamGateDecisionStatus.PROPOSAL_STALE)
                )

            return await decide_current(
                unit.gates,
                agent_team_artifact_reference(proposal),
                project_id=project_id,
                owner_user_id=owner_user_id,
                action=action,
                reason=reason,
                occurred_at=timestamp,
                event_id_factory=self._event_id_factory,
                outcomes=_OUTCOMES,
            )

    async def readiness(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ProjectWorkflowReadiness:
        """Return the derived readiness for the future main workflow."""
        async with self._unit_of_work_factory() as unit:
            context = await unit.contexts.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=(owner_user_id),
            )

            if context is None:
                return ProjectWorkflowReadiness.PROJECT_NOT_FOUND

            proposal = await unit.proposals.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=(owner_user_id),
            )
            gate = await unit.gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=(owner_user_id),
                gate_type=(HumanGateType.AGENT_TEAM),
            )

            return project_workflow_readiness(
                context=context,
                proposal=proposal,
                team_gate=gate,
            )

    async def current_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> HumanGate | None:
        """Return the latest owner-scoped Agent Team gate."""
        return await latest_gate(
            self._unit_of_work_factory(),
            HumanGateType.AGENT_TEAM,
            project_id=project_id,
            owner_user_id=owner_user_id,
        )

    async def gate_events(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ) -> tuple[
        HumanGateEvent,
        ...,
    ]:
        """Return the append-only Gate 2 event history."""
        return await gate_history(
            self._unit_of_work_factory(),
            project_id=project_id,
            owner_user_id=owner_user_id,
            gate_id=gate_id,
        )

    @staticmethod
    def _precondition[Status: StrEnum](
        context: TeamSelectionContext | None, statuses: type[Status]
    ) -> Status | None:
        if context is None:
            return statuses.PROJECT_NOT_FOUND

        if context.brief_version is None:
            return statuses.BRIEF_NOT_FOUND

        if not context.brief_is_approved:
            return statuses.BRIEF_NOT_APPROVED

        return None

    @staticmethod
    def _selection_issues(
        *,
        current: TeamProposalVersion,
        selected_agent_ids: tuple[
            AgentIdentifier,
            ...,
        ],
        owner_rationales: tuple[
            OwnerAgentRationale,
            ...,
        ],
    ) -> tuple[
        TeamEditIssue,
        ...,
    ]:
        """Validate one complete owner-selected member set."""
        issues: list[TeamEditIssue] = []
        selected_counts = Counter(selected_agent_ids)
        rationale_counts = Counter(rationale.agent_id for rationale in owner_rationales)

        for agent_id, count in selected_counts.items():
            if count > 1:
                issues.append(
                    TeamEditIssue(
                        code=(TeamEditIssueCode.DUPLICATE_AGENT),
                        agent_id=agent_id,
                    )
                )

        for agent_id, count in rationale_counts.items():
            if count > 1:
                issues.append(
                    TeamEditIssue(
                        code=(TeamEditIssueCode.DUPLICATE_RATIONALE),
                        agent_id=agent_id,
                    )
                )

        selected = set(selected_agent_ids)
        current_selected = set(current.proposal.selected_agent_ids)
        mandatory = set(current.proposal.constraints.mandatory_agent_ids)

        for agent_id in mandatory - selected:
            issues.append(
                TeamEditIssue(
                    code=(TeamEditIssueCode.MANDATORY_AGENT_MISSING),
                    agent_id=agent_id,
                )
            )

        for agent_id in selected:
            constraint = current.proposal.constraints.constraint_for(agent_id)

            if constraint.kind is TeamRoleConstraintKind.IMPOSSIBLE:
                issues.append(
                    TeamEditIssue(
                        code=(TeamEditIssueCode.AGENT_NOT_SELECTABLE),
                        agent_id=agent_id,
                    )
                )

        newly_added = selected - current_selected
        rationale_ids = set(rationale_counts)

        for agent_id in rationale_ids - newly_added:
            issues.append(
                TeamEditIssue(
                    code=(TeamEditIssueCode.UNUSED_RATIONALE),
                    agent_id=agent_id,
                )
            )

        return tuple(
            sorted(
                issues,
                key=lambda issue: (
                    _AGENT_POSITION[issue.agent_id],
                    issue.code.value,
                ),
            )
        )

    @staticmethod
    def _edited_proposal(
        *,
        current: TeamProposalVersion,
        selected_agent_ids: tuple[
            AgentIdentifier,
            ...,
        ],
        owner_rationales: tuple[
            OwnerAgentRationale,
            ...,
        ],
    ) -> AgentTeamProposal:
        """Create a validated proposal containing the owner selection."""
        selected = set(selected_agent_ids)
        current_members = {member.agent_id: member for member in current.proposal.members}
        rationales = {rationale.agent_id: rationale for rationale in owner_rationales}
        members: list[ProposedTeamMember] = []

        for agent_id in _AGENT_ORDER:
            if agent_id not in selected:
                continue

            existing = current_members.get(agent_id)

            if existing is not None:
                members.append(existing)
                continue

            rationale = rationales.get(agent_id)
            members.append(
                ProposedTeamMember(
                    agent_id=agent_id,
                    source=(TeamProposalMemberSource.OWNER_ADDED),
                    justifications=(
                        TeamProposalJustification(
                            kind=(TeamProposalJustificationKind.OWNER_RATIONALE),
                            code=("OWNER_SELECTED_ROLE"),
                            statement=(
                                OWNER_CHOICE_STATEMENT if rationale is None else rationale.statement
                            ),
                        ),
                    ),
                )
            )

        return replace(
            current.proposal,
            members=tuple(members),
        )

    def _current_time(self) -> datetime:
        """Return and validate the injected application clock."""
        return current_time(self._clock, "Agent Team service clock must be timezone-aware")
