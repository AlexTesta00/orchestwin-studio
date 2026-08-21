"""Application service for governed Design Package generation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID, uuid4

from orchestwin.artifacts.design_packages import (
    DesignExplorationPackage,
    DesignPackageVersion,
    create_design_grounding,
)
from orchestwin.artifacts.references import VersionedArtifactReference
from orchestwin.models.design import (
    DesignAgentTeamInput,
    DesignProposalIssueCode,
    DesignProposalPort,
    DesignProposalRequest,
    DesignProposalStatus,
    DesignRequirementsInput,
    DesignUserModelingInput,
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


class DesignGenerationStatus(StrEnum):
    """Stable application-level Design Package generation outcomes."""

    CREATED = "CREATED"
    REJECTED = "REJECTED"


class DesignGenerationIssueCode(StrEnum):
    """Expected reasons governed design generation cannot continue."""

    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    REQUIREMENTS_APPROVAL_REQUIRED = "REQUIREMENTS_APPROVAL_REQUIRED"
    DESIGN_PACKAGE_ALREADY_EXISTS = "DESIGN_PACKAGE_ALREADY_EXISTS"
    PROPOSAL_REJECTED = "PROPOSAL_REJECTED"
    INVALID_PROPOSAL = "INVALID_PROPOSAL"
    CONTEXT_CHANGED = "CONTEXT_CHANGED"
    PERSISTENCE_REJECTED = "PERSISTENCE_REJECTED"


class DesignVersionAppendStatus(StrEnum):
    """Stable outcomes of appending one immutable Design Package version."""

    APPENDED = "APPENDED"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    CONTENT_CONFLICT = "CONTENT_CONFLICT"


@dataclass(frozen=True, slots=True)
class GovernedDesignContext:
    """Current approved inputs required by design generation."""

    project_id: UUID
    project_mode: ProjectMode
    requirements: DesignRequirementsInput | None = None
    team: DesignAgentTeamInput | None = None
    user_modeling: DesignUserModelingInput | None = None
    catalog_version: int | None = None
    catalog_content_hash: str | None = None
    requirements_gate: HumanGate | None = None

    def __post_init__(self) -> None:
        """Protect optional catalog metadata supplied by the governance adapter."""
        if (self.catalog_version is None) != (self.catalog_content_hash is None):
            raise ValueError("governed design catalog version and hash must be supplied together")

        if self.catalog_version is None or self.catalog_content_hash is None:
            return

        validate_positive_integer(
            self.catalog_version,
            label="governed design catalog version",
        )
        validate_sha256(
            self.catalog_content_hash,
            label="governed design catalog content hash",
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
                "team": None if self.team is None else self.team.to_snapshot(),
                "user_modeling": (
                    None if self.user_modeling is None else self.user_modeling.to_snapshot()
                ),
                "catalog": {
                    "version": self.catalog_version,
                    "content_hash": self.catalog_content_hash,
                },
            }
        )

    def to_proposal_request(self) -> DesignProposalRequest:
        """Create the exact provider request for this ready context."""
        if (
            self.requirements is None
            or self.team is None
            or self.user_modeling is None
            or self.catalog_version is None
            or self.catalog_content_hash is None
        ):
            raise RuntimeError(
                "ready design context requires Requirements, Team, User Modeling, and catalog"
            )

        return DesignProposalRequest(
            project_id=self.project_id,
            project_mode=self.project_mode,
            requirements=self.requirements,
            team=self.team,
            user_modeling=self.user_modeling,
            catalog_version=self.catalog_version,
            catalog_content_hash=self.catalog_content_hash,
        )


class DesignGovernancePort(Protocol):
    """Owner-scoped boundary exposing current approved design inputs."""

    async def load_current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> GovernedDesignContext | None:
        """Load current Requirements, Team, User Modeling, and Gate 4."""


class DesignPackageRepository(Protocol):
    """Persistence boundary for immutable Design Package versions."""

    async def current(
        self,
        *,
        project_id: UUID,
    ) -> DesignPackageVersion | None:
        """Return the latest owner-scoped Design Package version."""

    async def append(
        self,
        version: DesignPackageVersion,
    ) -> DesignVersionAppendStatus:
        """Append one immutable Design Package version."""


class DesignGenerationUnitOfWork(Protocol):
    """Transactional boundary for governed design generation."""

    packages: DesignPackageRepository

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


class DesignGenerationUnitOfWorkFactory(Protocol):
    """Create one owner-scoped design Unit of Work."""

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> DesignGenerationUnitOfWork:
        """Create one transactional boundary."""


@dataclass(frozen=True, slots=True)
class DesignGenerationResult:
    """Typed result of generating an initial Design Package."""

    status: DesignGenerationStatus
    version: DesignPackageVersion | None = None
    issue: DesignGenerationIssueCode | None = None
    proposal_issue: DesignProposalIssueCode | None = None
    persistence_status: DesignVersionAppendStatus | None = None


class LocalDesignGenerationService:
    """Coordinate governed design proposal and immutable package creation."""

    def __init__(
        self,
        *,
        governance: DesignGovernancePort,
        proposals: DesignProposalPort,
        uow_factory: DesignGenerationUnitOfWorkFactory,
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
    ) -> DesignGenerationResult:
        """Generate the initial Design Package from exact approved inputs."""
        context = await self._governance.load_current(
            owner_user_id=owner_user_id,
            project_id=project_id,
        )
        issue = _governance_issue(context)

        if issue is not None:
            return DesignGenerationResult(
                status=DesignGenerationStatus.REJECTED,
                issue=issue,
            )

        if context is None:
            raise RuntimeError("ready design context cannot be None")

        if (
            await self._current_version(
                owner_user_id=owner_user_id,
                project_id=project_id,
            )
            is not None
        ):
            return DesignGenerationResult(
                status=DesignGenerationStatus.REJECTED,
                issue=DesignGenerationIssueCode.DESIGN_PACKAGE_ALREADY_EXISTS,
            )

        proposal = await self._proposals.propose(context.to_proposal_request())

        if proposal.status is not DesignProposalStatus.PROPOSED:
            return DesignGenerationResult(
                status=DesignGenerationStatus.REJECTED,
                issue=DesignGenerationIssueCode.PROPOSAL_REJECTED,
                proposal_issue=proposal.issue,
            )

        if proposal.package is None or not _proposal_matches_context(
            proposal.package,
            context,
        ):
            return DesignGenerationResult(
                status=DesignGenerationStatus.REJECTED,
                issue=DesignGenerationIssueCode.INVALID_PROPOSAL,
            )

        if not await self._context_is_unchanged(
            owner_user_id=owner_user_id,
            project_id=project_id,
            previous=context,
        ):
            return DesignGenerationResult(
                status=DesignGenerationStatus.REJECTED,
                issue=DesignGenerationIssueCode.CONTEXT_CHANGED,
            )

        async with self._uow_factory(owner_user_id=owner_user_id) as unit:
            if await unit.packages.current(project_id=project_id) is not None:
                return DesignGenerationResult(
                    status=DesignGenerationStatus.REJECTED,
                    issue=DesignGenerationIssueCode.CONTEXT_CHANGED,
                )

            version = DesignPackageVersion(
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

            if append_status is not DesignVersionAppendStatus.APPENDED:
                return DesignGenerationResult(
                    status=DesignGenerationStatus.REJECTED,
                    issue=DesignGenerationIssueCode.PERSISTENCE_REJECTED,
                    persistence_status=append_status,
                )

            await unit.commit()

        return DesignGenerationResult(
            status=DesignGenerationStatus.CREATED,
            version=version,
        )

    async def _current_version(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> DesignPackageVersion | None:
        """Read current state without holding a provider-call transaction."""
        async with self._uow_factory(owner_user_id=owner_user_id) as unit:
            return await unit.packages.current(project_id=project_id)

    async def _context_is_unchanged(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        previous: GovernedDesignContext,
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
    context: GovernedDesignContext | None,
) -> DesignGenerationIssueCode | None:
    """Return the first approval blocker for design generation."""
    if context is None:
        return DesignGenerationIssueCode.PROJECT_NOT_FOUND

    if context.requirements is None or not _gate_approves(
        context.requirements_gate,
        project_id=context.project_id,
        reference=(context.requirements.reference if context.requirements is not None else None),
    ):
        return DesignGenerationIssueCode.REQUIREMENTS_APPROVAL_REQUIRED

    if (
        context.team is None
        or context.user_modeling is None
        or context.catalog_version is None
        or context.catalog_content_hash is None
    ):
        return DesignGenerationIssueCode.REQUIREMENTS_APPROVAL_REQUIRED

    try:
        context.to_proposal_request()
    except ValueError:
        return DesignGenerationIssueCode.REQUIREMENTS_APPROVAL_REQUIRED

    return None


def _gate_approves(
    gate: HumanGate | None,
    *,
    project_id: UUID,
    reference: VersionedArtifactReference | None,
) -> bool:
    """Return whether Gate 4 approves the exact current Requirements version."""
    if gate is None or reference is None:
        return False

    expected = GateArtifactReference(
        project_id=project_id,
        gate_type=HumanGateType.REQUIREMENTS,
        artifact_id=reference.artifact_id,
        version=reference.version_number,
        content_hash=reference.content_hash,
    )

    return gate.status is HumanGateStatus.APPROVED and gate.artifact == expected


def _proposal_matches_context(
    package: DesignExplorationPackage,
    context: GovernedDesignContext,
) -> bool:
    """Validate exact provider grounding and preserve owner authority."""
    if (
        context.requirements is None
        or context.team is None
        or context.user_modeling is None
        or context.catalog_version is None
        or context.catalog_content_hash is None
    ):
        return False

    expected_grounding = create_design_grounding(context.requirements.version)

    return (
        package.project_id == context.project_id
        and package.grounding == expected_grounding
        and package.grounding.agent_team_reference == context.team.reference
        and package.grounding.user_modeling_reference == context.user_modeling.reference
        and package.grounding.catalog_version == context.catalog_version
        and package.grounding.catalog_content_hash == context.catalog_content_hash
        and package.grounding.user_twin_references == context.user_modeling.user_twin_references
        and package.owner_selected_alternative_id is None
        and package.prototype is None
        and not package.ready_for_gate
    )


def _aware(value: datetime) -> datetime:
    """Require timezone-aware application timestamps."""
    if value.utcoffset() is None:
        raise ValueError("design generation clock must be timezone-aware")

    return value


def _utc_now() -> datetime:
    """Return current UTC time."""
    return datetime.now(UTC)


__all__ = [
    "DesignGenerationIssueCode",
    "DesignGenerationResult",
    "DesignGenerationStatus",
    "DesignGenerationUnitOfWork",
    "DesignGenerationUnitOfWorkFactory",
    "DesignGovernancePort",
    "DesignPackageRepository",
    "DesignVersionAppendStatus",
    "GovernedDesignContext",
    "LocalDesignGenerationService",
]
