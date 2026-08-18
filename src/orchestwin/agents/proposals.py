"""Application services and domain values for versioned team proposals."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from orchestwin.agents.selection_rules import (
    TeamSelectionIssue,
    determine_team_constraints,
)
from orchestwin.models.team_proposals import (
    AgentTeamProposal,
    TeamProposalGenerationStatus,
    TeamProposalPort,
    TeamProposalRequest,
)
from orchestwin.projects.brief_gate import (
    project_brief_gate_is_currently_approved,
)
from orchestwin.projects.briefs import (
    ProjectBriefVersion,
)
from orchestwin.projects.domain import (
    ProjectMode,
)
from orchestwin.workflow.gates import (
    HumanGate,
    HumanGateType,
)


class TeamProposalRevisionKind(StrEnum):
    """Origins of immutable team-proposal versions."""

    PROPOSER_GENERATED = "PROPOSER_GENERATED"
    OWNER_EDITED = "OWNER_EDITED"


@dataclass(frozen=True, slots=True)
class TeamProposalVersion:
    """One immutable persisted version of an agent-team proposal."""

    id: UUID
    project_id: UUID
    version_number: int
    proposal: AgentTeamProposal = field(repr=False)
    revision_kind: TeamProposalRevisionKind
    created_by_user_id: UUID
    created_at: datetime
    based_on_version_number: int | None = None

    def __post_init__(self) -> None:
        """Protect proposal scope, lineage, and timestamp invariants."""
        if self.version_number < 1:
            raise ValueError("team-proposal version number must be positive")

        if self.proposal.project_id != self.project_id:
            raise ValueError("team proposal must belong to the persisted proposal project")

        if self.created_at.tzinfo is None:
            raise ValueError("team-proposal version timestamp must be timezone-aware")

        if self.revision_kind is TeamProposalRevisionKind.PROPOSER_GENERATED:
            if self.based_on_version_number is not None:
                raise ValueError(
                    "a generated proposal must not reference an earlier proposal version"
                )

            return

        if (
            self.based_on_version_number is None
            or self.based_on_version_number < 1
            or self.based_on_version_number >= self.version_number
        ):
            raise ValueError("an owner-edited proposal must reference an earlier proposal version")

    @property
    def content_hash(self) -> str:
        """Return the immutable proposal content hash."""
        return self.proposal.content_hash


class TeamProposalVersionCreationStatus(StrEnum):
    """Stable outcomes of creating a proposal version."""

    CREATED = "CREATED"
    UNCHANGED = "UNCHANGED"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"


@dataclass(frozen=True, slots=True)
class TeamProposalVersionCreationResult:
    """Typed result of persisting a proposal version."""

    status: TeamProposalVersionCreationStatus
    version: TeamProposalVersion | None = None

    def __post_init__(self) -> None:
        """Associate a version only with successful outcomes."""
        succeeded = self.status in {
            TeamProposalVersionCreationStatus.CREATED,
            TeamProposalVersionCreationStatus.UNCHANGED,
        }

        if succeeded != (self.version is not None):
            raise ValueError("successful proposal persistence must contain a version")


@dataclass(frozen=True, slots=True)
class TeamSelectionContext:
    """Current project state required to generate a team proposal."""

    project_id: UUID
    owner_user_id: UUID
    project_mode: ProjectMode
    brief_version: ProjectBriefVersion | None
    brief_gate: HumanGate | None

    def __post_init__(self) -> None:
        """Protect project, brief, and Gate 1 scope."""
        if self.brief_version is not None and self.brief_version.project_id != self.project_id:
            raise ValueError("team-selection brief must belong to the project")

        if self.brief_gate is None:
            return

        if (
            self.brief_gate.project_id != self.project_id
            or self.brief_gate.owner_user_id != self.owner_user_id
        ):
            raise ValueError("team-selection gate must belong to the project owner")

        if self.brief_gate.gate_type is not HumanGateType.PROJECT_BRIEF:
            raise ValueError("team-selection context requires a Project Brief gate")

    @property
    def brief_is_approved(self) -> bool:
        """Return whether Gate 1 approves the exact current brief."""
        return project_brief_gate_is_currently_approved(
            self.brief_gate,
            self.brief_version,
        )

    @property
    def selection_basis(
        self,
    ) -> tuple[object, ...]:
        """Return the immutable basis used to detect context changes."""
        brief_reference: (
            tuple[
                object,
                ...,
            ]
            | None
        ) = None

        if self.brief_version is not None:
            brief_reference = (
                self.brief_version.id,
                self.brief_version.version_number,
                self.brief_version.content_hash,
            )

        gate_reference: (
            tuple[
                object,
                ...,
            ]
            | None
        ) = None

        if self.brief_gate is not None:
            gate_reference = (
                self.brief_gate.id,
                self.brief_gate.status,
                self.brief_gate.artifact,
                self.brief_gate.event_sequence,
            )

        return (
            self.project_mode,
            brief_reference,
            gate_reference,
        )


class TeamSelectionContextRepository(Protocol):
    """Owner-scoped access to the current proposal-generation context."""

    async def get_current_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> TeamSelectionContext | None:
        """Return current project, brief, and Gate 1 state."""

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> TeamSelectionContext | None:
        """Lock the project and return its current selection context."""


class TeamProposalVersionRepository(Protocol):
    """Owner-scoped persistence operations for team proposals."""

    async def create_generated_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        proposal: AgentTeamProposal,
    ) -> TeamProposalVersionCreationResult:
        """Create or reuse an immutable generated proposal version."""

    async def get_current_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> TeamProposalVersion | None:
        """Return the latest proposal version for an owned project."""

    async def get_owned_version(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        version_number: int,
    ) -> TeamProposalVersion | None:
        """Return one proposal version for an owned project."""

    async def list_owned_versions(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[
        TeamProposalVersion,
        ...,
    ]:
        """Return immutable proposal history in version order."""


class TeamProposalUnitOfWork(Protocol):
    """Transactional boundary for team-proposal persistence."""

    @property
    def contexts(
        self,
    ) -> TeamSelectionContextRepository:
        """Return the current selection-context repository."""

    @property
    def proposals(
        self,
    ) -> TeamProposalVersionRepository:
        """Return the versioned proposal repository."""

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


TeamProposalUnitOfWorkFactory = Callable[
    [],
    TeamProposalUnitOfWork,
]


class TeamProposalApplicationStatus(StrEnum):
    """Stable outcomes of proposal generation and persistence."""

    CREATED = "CREATED"
    UNCHANGED = "UNCHANGED"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    BRIEF_NOT_FOUND = "BRIEF_NOT_FOUND"
    BRIEF_NOT_APPROVED = "BRIEF_NOT_APPROVED"
    BLOCKED_BY_CONSTRAINTS = "BLOCKED_BY_CONSTRAINTS"
    CONTEXT_CHANGED = "CONTEXT_CHANGED"
    INVALID_PROPOSAL = "INVALID_PROPOSAL"


@dataclass(frozen=True, slots=True)
class TeamProposalApplicationResult:
    """Typed result of generating a versioned team proposal."""

    status: TeamProposalApplicationStatus
    version: TeamProposalVersion | None = None
    issues: tuple[
        TeamSelectionIssue,
        ...,
    ] = ()

    def __post_init__(self) -> None:
        """Protect success, blocked, and failure result shapes."""
        successful = self.status in {
            TeamProposalApplicationStatus.CREATED,
            TeamProposalApplicationStatus.UNCHANGED,
        }

        if successful:
            if self.version is None or self.issues:
                raise ValueError(
                    "successful team-proposal results require only a persisted version"
                )

            return

        if self.status is TeamProposalApplicationStatus.BLOCKED_BY_CONSTRAINTS:
            if self.version is not None or not self.issues:
                raise ValueError("constraint-blocked team proposals require only selection issues")

            return

        if self.version is not None or self.issues:
            raise ValueError("failed team-proposal results must not contain proposal data")


class TeamProposalApplicationService(Protocol):
    """Use cases exposed to future team-selection API adapters."""

    async def generate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> TeamProposalApplicationResult:
        """Generate and persist a proposal for an approved brief."""

    async def current(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> TeamProposalVersion | None:
        """Return the latest owner-scoped proposal version."""

    async def history(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[
        TeamProposalVersion,
        ...,
    ]:
        """Return the immutable proposal history."""


class LocalTeamProposalApplicationService:
    """Generate proposals without holding a transaction across the adapter."""

    def __init__(
        self,
        *,
        unit_of_work_factory: (TeamProposalUnitOfWorkFactory),
        proposal_port: TeamProposalPort,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._proposal_port = proposal_port

    async def generate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> TeamProposalApplicationResult:
        """Generate a proposal and persist it if context remains current."""
        async with self._unit_of_work_factory() as unit:
            initial_context = await unit.contexts.get_current_owned(
                project_id=project_id,
                owner_user_id=(owner_user_id),
            )

        precondition = self._precondition_result(initial_context)

        if precondition is not None:
            return precondition

        if initial_context is None or initial_context.brief_version is None:
            raise RuntimeError("validated proposal context did not contain a brief")

        constraints = determine_team_constraints(
            project_mode=(initial_context.project_mode),
            brief=(initial_context.brief_version.brief),
        )
        request = TeamProposalRequest(
            project_mode=(initial_context.project_mode),
            brief_version=(initial_context.brief_version),
            constraints=constraints,
        )

        generation = await self._proposal_port.propose(request)

        if generation.status is TeamProposalGenerationStatus.BLOCKED_BY_CONSTRAINTS:
            return TeamProposalApplicationResult(
                status=(TeamProposalApplicationStatus.BLOCKED_BY_CONSTRAINTS),
                issues=generation.issues,
            )

        proposal = generation.proposal

        if proposal is None or not self._proposal_matches_request(
            proposal=proposal,
            request=request,
        ):
            return TeamProposalApplicationResult(
                status=(TeamProposalApplicationStatus.INVALID_PROPOSAL)
            )

        async with self._unit_of_work_factory() as unit:
            current_context = await unit.contexts.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=(owner_user_id),
            )

            if (
                current_context is None
                or not current_context.brief_is_approved
                or current_context.selection_basis != initial_context.selection_basis
            ):
                return TeamProposalApplicationResult(
                    status=(TeamProposalApplicationStatus.CONTEXT_CHANGED)
                )

            persisted = await unit.proposals.create_generated_owned(
                project_id=project_id,
                owner_user_id=(owner_user_id),
                proposal=proposal,
            )

        if persisted.status is TeamProposalVersionCreationStatus.PROJECT_NOT_FOUND:
            return TeamProposalApplicationResult(
                status=(TeamProposalApplicationStatus.CONTEXT_CHANGED)
            )

        if persisted.version is None:
            raise RuntimeError("successful proposal persistence did not return a version")

        application_status = (
            TeamProposalApplicationStatus.CREATED
            if persisted.status is TeamProposalVersionCreationStatus.CREATED
            else TeamProposalApplicationStatus.UNCHANGED
        )

        return TeamProposalApplicationResult(
            status=application_status,
            version=persisted.version,
        )

    async def current(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> TeamProposalVersion | None:
        """Return the latest owner-scoped proposal."""
        async with self._unit_of_work_factory() as unit:
            return await unit.proposals.get_current_owned(
                project_id=project_id,
                owner_user_id=(owner_user_id),
            )

    async def history(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[
        TeamProposalVersion,
        ...,
    ]:
        """Return immutable proposal history."""
        async with self._unit_of_work_factory() as unit:
            return await unit.proposals.list_owned_versions(
                project_id=project_id,
                owner_user_id=(owner_user_id),
            )

    @staticmethod
    def _precondition_result(
        context: TeamSelectionContext | None,
    ) -> TeamProposalApplicationResult | None:
        """Return a typed precondition failure when applicable."""
        if context is None:
            return TeamProposalApplicationResult(
                status=(TeamProposalApplicationStatus.PROJECT_NOT_FOUND)
            )

        if context.brief_version is None:
            return TeamProposalApplicationResult(
                status=(TeamProposalApplicationStatus.BRIEF_NOT_FOUND)
            )

        if not context.brief_is_approved:
            return TeamProposalApplicationResult(
                status=(TeamProposalApplicationStatus.BRIEF_NOT_APPROVED)
            )

        return None

    @staticmethod
    def _proposal_matches_request(
        *,
        proposal: AgentTeamProposal,
        request: TeamProposalRequest,
    ) -> bool:
        """Validate provider output against the exact request context."""
        brief = request.brief_version
        constraints = request.constraints

        return (
            proposal.project_id == brief.project_id
            and proposal.project_mode is request.project_mode
            and proposal.brief_version_id == brief.id
            and proposal.brief_version_number == brief.version_number
            and proposal.brief_content_hash == brief.content_hash
            and proposal.catalog_version == constraints.catalog_version
            and proposal.catalog_content_hash == constraints.catalog_content_hash
            and proposal.constraints == constraints
        )
