"""Application service for governed Architecture Package generation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID, uuid4

from orchestwin.artifacts.architecture_packages import (
    ArchitecturePackageVersion,
    ArchitecturePlanningPackage,
    create_architecture_grounding,
)
from orchestwin.artifacts.references import VersionedArtifactReference
from orchestwin.models.architecture import (
    ArchitectureAgentTeamInput,
    ArchitectureDesignInput,
    ArchitectureProposalIssueCode,
    ArchitectureProposalPort,
    ArchitectureProposalRequest,
    ArchitectureProposalStatus,
    ArchitectureRequirementsInput,
)
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.requirements_primitives import (
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.workflow.gates import (
    GateArtifactReference,
    HumanGate,
    HumanGateStatus,
    HumanGateType,
)


class ArchitectureGenerationStatus(StrEnum):
    """Stable application-level Architecture Package generation outcomes."""

    CREATED = "CREATED"
    REJECTED = "REJECTED"


class ArchitectureGenerationIssueCode(StrEnum):
    """Expected reasons governed architecture planning cannot continue."""

    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    DESIGN_APPROVAL_REQUIRED = "DESIGN_APPROVAL_REQUIRED"
    ARCHITECTURE_PACKAGE_ALREADY_EXISTS = "ARCHITECTURE_PACKAGE_ALREADY_EXISTS"
    PROPOSAL_REJECTED = "PROPOSAL_REJECTED"
    INVALID_PROPOSAL = "INVALID_PROPOSAL"
    CONTEXT_CHANGED = "CONTEXT_CHANGED"
    PERSISTENCE_REJECTED = "PERSISTENCE_REJECTED"


class ArchitectureVersionAppendStatus(StrEnum):
    """Stable outcomes of appending one immutable Architecture Package version."""

    APPENDED = "APPENDED"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    CONTENT_CONFLICT = "CONTENT_CONFLICT"


@dataclass(frozen=True, slots=True)
class GovernedArchitectureContext:
    """Current approved inputs required by architecture planning."""

    project_id: UUID
    project_mode: ProjectMode
    requirements: ArchitectureRequirementsInput | None = None
    design: ArchitectureDesignInput | None = None
    team: ArchitectureAgentTeamInput | None = None
    catalog_version: int | None = None
    catalog_content_hash: str | None = None
    design_gate: HumanGate | None = None

    def __post_init__(self) -> None:
        """Protect optional catalog metadata supplied by the governance adapter."""
        if (self.catalog_version is None) != (self.catalog_content_hash is None):
            raise ValueError(
                "governed architecture catalog version and hash must be supplied together"
            )

        if self.catalog_version is None or self.catalog_content_hash is None:
            return

        validate_positive_integer(
            self.catalog_version,
            label="governed architecture catalog version",
        )
        validate_sha256(
            self.catalog_content_hash,
            label="governed architecture catalog content hash",
        )

    @property
    def fingerprint(self) -> str:
        """Return a stable identity for stale-provider checks."""
        return snapshot_content_hash(
            {
                "project_id": str(self.project_id),
                "project_mode": self.project_mode.value,
                "requirements": (
                    None if self.requirements is None else self.requirements.to_snapshot()
                ),
                "design": None if self.design is None else self.design.to_snapshot(),
                "team": None if self.team is None else self.team.to_snapshot(),
                "catalog": {
                    "version": self.catalog_version,
                    "content_hash": self.catalog_content_hash,
                },
            }
        )

    def to_proposal_request(self) -> ArchitectureProposalRequest:
        """Create the exact provider request for this ready context."""
        if (
            self.requirements is None
            or self.design is None
            or self.team is None
            or self.catalog_version is None
            or self.catalog_content_hash is None
        ):
            raise RuntimeError(
                "ready architecture context requires Requirements, Design, Team, and catalog"
            )

        return ArchitectureProposalRequest(
            project_id=self.project_id,
            project_mode=self.project_mode,
            requirements=self.requirements,
            design=self.design,
            team=self.team,
            catalog_version=self.catalog_version,
            catalog_content_hash=self.catalog_content_hash,
        )


class ArchitectureGovernancePort(Protocol):
    """Owner-scoped boundary exposing current approved architecture inputs."""

    async def load_current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> GovernedArchitectureContext | None:
        """Load current Requirements, Design Package, Team, and Gate 5."""


class ArchitecturePackageRepository(Protocol):
    """Persistence boundary for immutable Architecture Package versions."""

    async def current(
        self,
        *,
        project_id: UUID,
    ) -> ArchitecturePackageVersion | None:
        """Return the latest owner-scoped Architecture Package version."""

    async def append(
        self,
        version: ArchitecturePackageVersion,
    ) -> ArchitectureVersionAppendStatus:
        """Append one immutable Architecture Package version."""


class ArchitectureGenerationUnitOfWork(Protocol):
    """Transactional boundary for governed architecture generation."""

    packages: ArchitecturePackageRepository

    async def __aenter__(self) -> Self:
        """Enter the transactional boundary."""

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Leave the transactional boundary."""

    async def commit(self) -> None:
        """Commit all persistence changes."""

    async def rollback(self) -> None:
        """Rollback all persistence changes."""


class ArchitectureGenerationUnitOfWorkFactory(Protocol):
    """Create one owner-scoped architecture Unit of Work."""

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> ArchitectureGenerationUnitOfWork:
        """Create one transactional boundary."""


@dataclass(frozen=True, slots=True)
class ArchitectureGenerationResult:
    """Typed result of generating an initial Architecture Package."""

    status: ArchitectureGenerationStatus
    version: ArchitecturePackageVersion | None = None
    issue: ArchitectureGenerationIssueCode | None = None
    proposal_issue: ArchitectureProposalIssueCode | None = None
    persistence_status: ArchitectureVersionAppendStatus | None = None


class LocalArchitectureGenerationService:
    """Coordinate governed architecture proposal and immutable package creation."""

    def __init__(
        self,
        *,
        governance: ArchitectureGovernancePort,
        proposals: ArchitectureProposalPort,
        uow_factory: ArchitectureGenerationUnitOfWorkFactory,
        uuid_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] | None = None,
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
    ) -> ArchitectureGenerationResult:
        """Generate the initial Architecture Package from exact approved inputs."""
        context = await self._governance.load_current(
            owner_user_id=owner_user_id,
            project_id=project_id,
        )
        issue = _governance_issue(context)

        if issue is not None:
            return ArchitectureGenerationResult(
                status=ArchitectureGenerationStatus.REJECTED,
                issue=issue,
            )

        if context is None:
            raise RuntimeError("ready architecture context cannot be None")

        if (
            await self._current_version(
                owner_user_id=owner_user_id,
                project_id=project_id,
            )
            is not None
        ):
            return ArchitectureGenerationResult(
                status=ArchitectureGenerationStatus.REJECTED,
                issue=ArchitectureGenerationIssueCode.ARCHITECTURE_PACKAGE_ALREADY_EXISTS,
            )

        proposal = await self._proposals.propose(context.to_proposal_request())

        if proposal.status is not ArchitectureProposalStatus.PROPOSED:
            return ArchitectureGenerationResult(
                status=ArchitectureGenerationStatus.REJECTED,
                issue=ArchitectureGenerationIssueCode.PROPOSAL_REJECTED,
                proposal_issue=proposal.issue,
            )

        if proposal.package is None or not _proposal_matches_context(
            proposal.package,
            context,
        ):
            return ArchitectureGenerationResult(
                status=ArchitectureGenerationStatus.REJECTED,
                issue=ArchitectureGenerationIssueCode.INVALID_PROPOSAL,
            )

        if not await self._context_is_unchanged(
            owner_user_id=owner_user_id,
            project_id=project_id,
            previous=context,
        ):
            return ArchitectureGenerationResult(
                status=ArchitectureGenerationStatus.REJECTED,
                issue=ArchitectureGenerationIssueCode.CONTEXT_CHANGED,
            )

        async with self._uow_factory(owner_user_id=owner_user_id) as unit:
            if await unit.packages.current(project_id=project_id) is not None:
                return ArchitectureGenerationResult(
                    status=ArchitectureGenerationStatus.REJECTED,
                    issue=ArchitectureGenerationIssueCode.CONTEXT_CHANGED,
                )

            version = ArchitecturePackageVersion(
                id=self._uuid_factory(),
                project_id=project_id,
                version_number=1,
                based_on_version_number=None,
                package=proposal.package,
                content_hash=proposal.package.content_hash,
                created_by_user_id=owner_user_id,
                created_at=_aware(self._clock()),
            )
            append_status = await unit.packages.append(version)

            if append_status is not ArchitectureVersionAppendStatus.APPENDED:
                return ArchitectureGenerationResult(
                    status=ArchitectureGenerationStatus.REJECTED,
                    issue=ArchitectureGenerationIssueCode.PERSISTENCE_REJECTED,
                    persistence_status=append_status,
                )

            await unit.commit()

        return ArchitectureGenerationResult(
            status=ArchitectureGenerationStatus.CREATED,
            version=version,
        )

    async def _current_version(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> ArchitecturePackageVersion | None:
        """Read current state without holding a provider-call transaction."""
        async with self._uow_factory(owner_user_id=owner_user_id) as unit:
            return await unit.packages.current(project_id=project_id)

    async def _context_is_unchanged(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        previous: GovernedArchitectureContext,
    ) -> bool:
        """Reject provider output when governed inputs changed in flight."""
        current = await self._governance.load_current(
            owner_user_id=owner_user_id,
            project_id=project_id,
        )

        return (
            current is not None
            and _governance_issue(current) is None
            and current.fingerprint == previous.fingerprint
        )


def _governance_issue(
    context: GovernedArchitectureContext | None,
) -> ArchitectureGenerationIssueCode | None:
    """Return the first approval blocker for architecture generation."""
    if context is None:
        return ArchitectureGenerationIssueCode.PROJECT_NOT_FOUND

    if context.design is None or not _gate_approves(
        context.design_gate,
        project_id=context.project_id,
        reference=context.design.reference if context.design is not None else None,
    ):
        return ArchitectureGenerationIssueCode.DESIGN_APPROVAL_REQUIRED

    if (
        not context.design.ready_for_architecture
        or context.requirements is None
        or context.team is None
        or context.catalog_version is None
        or context.catalog_content_hash is None
    ):
        return ArchitectureGenerationIssueCode.DESIGN_APPROVAL_REQUIRED

    try:
        context.to_proposal_request()
    except ValueError:
        return ArchitectureGenerationIssueCode.DESIGN_APPROVAL_REQUIRED

    return None


def _gate_approves(
    gate: HumanGate | None,
    *,
    project_id: UUID,
    reference: VersionedArtifactReference | None,
) -> bool:
    """Return whether Gate 5 approves the exact current Design Package version."""
    if gate is None or reference is None:
        return False

    expected = GateArtifactReference(
        project_id=project_id,
        gate_type=HumanGateType.DESIGN,
        artifact_id=reference.artifact_id,
        version=reference.version_number,
        content_hash=reference.content_hash,
    )

    return gate.status is HumanGateStatus.APPROVED and gate.artifact == expected


def _proposal_matches_context(
    package: ArchitecturePlanningPackage,
    context: GovernedArchitectureContext,
) -> bool:
    """Validate exact provider grounding before immutable persistence."""
    if (
        context.requirements is None
        or context.design is None
        or context.team is None
        or context.catalog_version is None
        or context.catalog_content_hash is None
    ):
        return False

    expected_grounding = create_architecture_grounding(context.design.version)

    return (
        package.project_id == context.project_id
        and package.grounding == expected_grounding
        and package.grounding.requirements_reference == context.requirements.reference
        and package.grounding.agent_team_reference == context.team.reference
        and package.grounding.catalog_version == context.catalog_version
        and package.grounding.catalog_content_hash == context.catalog_content_hash
    )


def _aware(value: datetime) -> datetime:
    """Require timezone-aware application timestamps."""
    if value.utcoffset() is None:
        raise ValueError("architecture generation clock must be timezone-aware")

    return value


def _utc_now() -> datetime:
    """Return current UTC time."""
    return datetime.now(UTC)


__all__ = [
    "ArchitectureGenerationIssueCode",
    "ArchitectureGenerationResult",
    "ArchitectureGenerationStatus",
    "ArchitectureGenerationUnitOfWork",
    "ArchitectureGenerationUnitOfWorkFactory",
    "ArchitectureGovernancePort",
    "ArchitecturePackageRepository",
    "ArchitectureVersionAppendStatus",
    "GovernedArchitectureContext",
    "LocalArchitectureGenerationService",
]
