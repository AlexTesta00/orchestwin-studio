"""Application service for governed requirements generation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID, uuid4

from orchestwin.models.requirements import (
    RequirementsBriefInput,
    RequirementsProposalIssueCode,
    RequirementsProposalPort,
    RequirementsProposalRequest,
    RequirementsProposalStatus,
    RequirementsTeamInput,
    RequirementsUserModelingInput,
)
from orchestwin.projects.domain import (
    ProjectMode,
)
from orchestwin.projects.requirements_primitives import (
    RequirementsContextReference,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.projects.requirements_specifications import (
    RequirementsSpecification,
    RequirementsSpecificationVersion,
)
from orchestwin.workflow.gates import (
    GateArtifactReference,
    HumanGate,
    HumanGateStatus,
    HumanGateType,
)


class RequirementsGenerationStatus(StrEnum):
    """Stable application-level requirements generation outcomes."""

    CREATED = "CREATED"
    REJECTED = "REJECTED"


class RequirementsGenerationIssueCode(StrEnum):
    """Expected reasons requirements generation cannot continue."""

    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    BRIEF_APPROVAL_REQUIRED = "BRIEF_APPROVAL_REQUIRED"
    TEAM_APPROVAL_REQUIRED = "TEAM_APPROVAL_REQUIRED"
    USER_MODELING_APPROVAL_REQUIRED = "USER_MODELING_APPROVAL_REQUIRED"
    SPECIFICATION_ALREADY_EXISTS = "SPECIFICATION_ALREADY_EXISTS"
    PROPOSAL_REJECTED = "PROPOSAL_REJECTED"
    INVALID_PROPOSAL = "INVALID_PROPOSAL"
    CONTEXT_CHANGED = "CONTEXT_CHANGED"
    PERSISTENCE_REJECTED = "PERSISTENCE_REJECTED"


class RequirementsVersionAppendStatus(StrEnum):
    """Stable outcomes of appending one specification version."""

    APPENDED = "APPENDED"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    CONTENT_CONFLICT = "CONTENT_CONFLICT"


@dataclass(
    frozen=True,
    slots=True,
)
class GovernedRequirementsContext:
    """Current governed inputs required by requirements generation."""

    project_id: UUID
    project_mode: ProjectMode
    brief: RequirementsBriefInput
    team: RequirementsTeamInput
    user_modeling: RequirementsUserModelingInput
    catalog_version: int
    catalog_content_hash: str
    brief_gate: HumanGate
    team_gate: HumanGate
    user_modeling_gate: HumanGate

    def __post_init__(
        self,
    ) -> None:
        """Protect catalog metadata supplied by the governance adapter."""
        validate_positive_integer(
            self.catalog_version,
            label=("governed requirements catalog version"),
        )
        validate_sha256(
            self.catalog_content_hash,
            label=("governed requirements catalog content hash"),
        )

    @property
    def fingerprint(
        self,
    ) -> str:
        """Return a stable identity for stale-provider checks."""
        return snapshot_content_hash(
            {
                "project_id": str(self.project_id),
                "project_mode": (self.project_mode.value),
                "brief": (self.brief.to_snapshot()),
                "team": (self.team.to_snapshot()),
                "user_modeling": (self.user_modeling.to_snapshot()),
                "catalog": {
                    "version": (self.catalog_version),
                    "content_hash": (self.catalog_content_hash),
                },
            }
        )

    def to_proposal_request(
        self,
    ) -> RequirementsProposalRequest:
        """Create the exact provider request for this governed context."""
        return RequirementsProposalRequest(
            project_id=(self.project_id),
            project_mode=(self.project_mode),
            brief=self.brief,
            team=self.team,
            user_modeling=(self.user_modeling),
            catalog_version=(self.catalog_version),
            catalog_content_hash=(self.catalog_content_hash),
        )


class RequirementsGovernancePort(Protocol):
    """Owner-scoped boundary exposing current approved project inputs."""

    async def load_current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> GovernedRequirementsContext | None:
        """Load current Brief, Team, User Modeling, and their gates."""


class RequirementsSpecificationRepository(Protocol):
    """Persistence boundary for immutable requirements versions."""

    async def current(
        self,
        *,
        project_id: UUID,
    ) -> RequirementsSpecificationVersion | None:
        """Return the latest owner-scoped specification version."""

    async def append(
        self,
        version: (RequirementsSpecificationVersion),
    ) -> RequirementsVersionAppendStatus:
        """Append one immutable specification version."""


class RequirementsGenerationUnitOfWork(Protocol):
    """Transactional boundary for requirements generation."""

    specifications: RequirementsSpecificationRepository

    async def __aenter__(
        self,
    ) -> Self:
        """Enter the transactional boundary."""

    async def __aexit__(
        self,
        exc_type: (type[BaseException] | None),
        exc_value: (BaseException | None),
        traceback: (TracebackType | None),
    ) -> None:
        """Leave the transactional boundary."""

    async def commit(
        self,
    ) -> None:
        """Commit all persistence changes."""

    async def rollback(
        self,
    ) -> None:
        """Rollback all persistence changes."""


class RequirementsGenerationUnitOfWorkFactory(Protocol):
    """Create one owner-scoped requirements Unit of Work."""

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> RequirementsGenerationUnitOfWork:
        """Create one transactional boundary."""


@dataclass(
    frozen=True,
    slots=True,
)
class RequirementsGenerationResult:
    """Typed result of generating an initial specification."""

    status: RequirementsGenerationStatus
    version: RequirementsSpecificationVersion | None = None
    issue: RequirementsGenerationIssueCode | None = None
    proposal_issue: RequirementsProposalIssueCode | None = None
    persistence_status: RequirementsVersionAppendStatus | None = None


class LocalRequirementsGenerationService:
    """Coordinate governed proposal and immutable specification creation."""

    def __init__(
        self,
        *,
        governance: (RequirementsGovernancePort),
        proposals: (RequirementsProposalPort),
        uow_factory: (RequirementsGenerationUnitOfWorkFactory),
        uuid_factory: (Callable[[], UUID]) = uuid4,
        clock: (Callable[[], datetime] | None) = None,
    ) -> None:
        """Configure explicit application dependencies."""
        self._governance = governance
        self._proposals = proposals
        self._uow_factory = uow_factory
        self._uuid_factory = uuid_factory
        self._clock = clock if clock is not None else _utc_now

    async def generate(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> RequirementsGenerationResult:
        """Generate the initial specification from exact approved inputs."""
        context = await self._governance.load_current(
            owner_user_id=(owner_user_id),
            project_id=project_id,
        )

        issue = _governance_issue(context)

        if issue is not None:
            return RequirementsGenerationResult(
                status=(RequirementsGenerationStatus.REJECTED),
                issue=issue,
            )

        if context is None:
            raise RuntimeError("ready requirements context cannot be None")

        current = await self._current_version(
            owner_user_id=(owner_user_id),
            project_id=project_id,
        )

        if current is not None:
            return RequirementsGenerationResult(
                status=(RequirementsGenerationStatus.REJECTED),
                issue=(RequirementsGenerationIssueCode.SPECIFICATION_ALREADY_EXISTS),
            )

        proposal = await self._proposals.propose(context.to_proposal_request())

        if proposal.status is not RequirementsProposalStatus.PROPOSED:
            return RequirementsGenerationResult(
                status=(RequirementsGenerationStatus.REJECTED),
                issue=(RequirementsGenerationIssueCode.PROPOSAL_REJECTED),
                proposal_issue=(proposal.issue),
            )

        if proposal.specification is None or not _proposal_matches_context(
            proposal.specification,
            context,
        ):
            return RequirementsGenerationResult(
                status=(RequirementsGenerationStatus.REJECTED),
                issue=(RequirementsGenerationIssueCode.INVALID_PROPOSAL),
            )

        unchanged = await self._context_is_unchanged(
            owner_user_id=(owner_user_id),
            project_id=project_id,
            previous=context,
        )

        if not unchanged:
            return RequirementsGenerationResult(
                status=(RequirementsGenerationStatus.REJECTED),
                issue=(RequirementsGenerationIssueCode.CONTEXT_CHANGED),
            )

        async with self._uow_factory(owner_user_id=owner_user_id) as unit:
            current = await unit.specifications.current(project_id=project_id)

            if current is not None:
                return RequirementsGenerationResult(
                    status=(RequirementsGenerationStatus.REJECTED),
                    issue=(RequirementsGenerationIssueCode.CONTEXT_CHANGED),
                )

            version = RequirementsSpecificationVersion(
                id=(self._uuid_factory()),
                project_id=(project_id),
                version_number=1,
                based_on_version_number=None,
                specification=(proposal.specification),
                content_hash=(proposal.specification.content_hash),
                created_by_user_id=(owner_user_id),
                created_at=_aware(self._clock()),
            )

            append_status = await unit.specifications.append(version)

            if append_status is not RequirementsVersionAppendStatus.APPENDED:
                return RequirementsGenerationResult(
                    status=(RequirementsGenerationStatus.REJECTED),
                    issue=(RequirementsGenerationIssueCode.PERSISTENCE_REJECTED),
                    persistence_status=(append_status),
                )

            await unit.commit()

        return RequirementsGenerationResult(
            status=(RequirementsGenerationStatus.CREATED),
            version=version,
        )

    async def _current_version(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> RequirementsSpecificationVersion | None:
        """Read current state without holding a provider-call transaction."""
        async with self._uow_factory(owner_user_id=owner_user_id) as unit:
            return await unit.specifications.current(project_id=project_id)

    async def _context_is_unchanged(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        previous: (GovernedRequirementsContext),
    ) -> bool:
        """Reject provider output when governed inputs changed in flight."""
        current = await self._governance.load_current(
            owner_user_id=(owner_user_id),
            project_id=project_id,
        )

        return (
            current is not None
            and _governance_issue(current) is None
            and current.fingerprint == previous.fingerprint
        )


def _governance_issue(
    context: (GovernedRequirementsContext | None),
) -> RequirementsGenerationIssueCode | None:
    """Return the first approval blocker for requirements generation."""
    if context is None:
        return RequirementsGenerationIssueCode.PROJECT_NOT_FOUND

    if not _gate_approves(
        context.brief_gate,
        project_id=(context.project_id),
        gate_type=(HumanGateType.PROJECT_BRIEF),
        reference=(context.brief.reference),
    ):
        return RequirementsGenerationIssueCode.BRIEF_APPROVAL_REQUIRED

    if not _gate_approves(
        context.team_gate,
        project_id=(context.project_id),
        gate_type=(HumanGateType.AGENT_TEAM),
        reference=(context.team.reference),
    ):
        return RequirementsGenerationIssueCode.TEAM_APPROVAL_REQUIRED

    if not _gate_approves(
        context.user_modeling_gate,
        project_id=(context.project_id),
        gate_type=(HumanGateType.USER_MODELING),
        reference=(context.user_modeling.reference),
    ):
        return RequirementsGenerationIssueCode.USER_MODELING_APPROVAL_REQUIRED

    return None


def _gate_approves(
    gate: HumanGate,
    *,
    project_id: UUID,
    gate_type: HumanGateType,
    reference: (RequirementsContextReference),
) -> bool:
    """Return whether one gate approves an exact current artifact."""
    expected = GateArtifactReference(
        project_id=project_id,
        gate_type=gate_type,
        artifact_id=(reference.artifact_id),
        version=(reference.version_number),
        content_hash=(reference.content_hash),
    )

    return gate.status is HumanGateStatus.APPROVED and gate.artifact == expected


def _proposal_matches_context(
    specification: (RequirementsSpecification),
    context: (GovernedRequirementsContext),
) -> bool:
    """Validate exact provider output grounding before persistence."""
    return (
        specification.project_id == context.project_id
        and specification.project_brief_reference == context.brief.reference
        and specification.agent_team_reference == context.team.reference
        and specification.user_modeling_reference == context.user_modeling.reference
        and specification.catalog_version == context.catalog_version
        and specification.catalog_content_hash == context.catalog_content_hash
        and specification.user_twin_references == context.user_modeling.user_twin_references
    )


def _aware(
    value: datetime,
) -> datetime:
    """Require timezone-aware application timestamps."""
    if value.utcoffset() is None:
        raise ValueError("requirements generation clock must be timezone-aware")

    return value


def _utc_now() -> datetime:
    """Return current UTC time."""
    return datetime.now(UTC)


__all__ = [
    "GovernedRequirementsContext",
    "LocalRequirementsGenerationService",
    "RequirementsGenerationIssueCode",
    "RequirementsGenerationResult",
    "RequirementsGenerationStatus",
    "RequirementsGenerationUnitOfWork",
    "RequirementsGenerationUnitOfWorkFactory",
    "RequirementsGovernancePort",
    "RequirementsSpecificationRepository",
    "RequirementsVersionAppendStatus",
]
