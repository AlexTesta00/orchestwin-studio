"""SQLAlchemy adapters and composition for Architecture Planning."""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.agents.persistence.repositories import (
    SqlAlchemyTeamProposalVersionRepository,
)
from orchestwin.artifacts.architecture_gate import LocalArchitectureGateService
from orchestwin.artifacts.architecture_packages import ArchitecturePackageVersion
from orchestwin.artifacts.architecture_persistence import (
    SqlAlchemyArchitectureDiffRepository,
    SqlAlchemyArchitecturePackageRepository,
    SqlAlchemyArchitectureUnitOfWork,
)
from orchestwin.artifacts.architecture_revision_application import (
    LocalArchitectureRevisionService,
)
from orchestwin.artifacts.architecture_revisions import ArchitecturePackageDiff
from orchestwin.artifacts.design_persistence import SqlAlchemyDesignPackageRepository
from orchestwin.artifacts.references import ArtifactKind, VersionedArtifactReference
from orchestwin.models.architecture import (
    ArchitectureAgentTeamInput,
    ArchitectureDesignInput,
    ArchitectureRequirementsInput,
)
from orchestwin.models.architecture_runtime import (
    ArchitectureRuntimeMode,
    ArchitectureRuntimeSettings,
    build_architecture_runtime,
)
from orchestwin.projects.architecture_application import (
    GovernedArchitectureContext,
    LocalArchitectureGenerationService,
)
from orchestwin.projects.persistence.repositories import SqlAlchemyProjectRepository
from orchestwin.projects.requirements_persistence import (
    SqlAlchemyRequirementsSpecificationRepository,
)
from orchestwin.workflow.gates import HumanGateType
from orchestwin.workflow.persistence.repositories import (
    SqlAlchemyHumanGateRepository,
)


class ManagedArchitectureUnitOfWork:
    """Close the session owned by the existing Architecture Unit of Work."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        owner_user_id: UUID,
    ) -> None:
        self._session = session
        self._inner = SqlAlchemyArchitectureUnitOfWork(
            session,
            owner_user_id=owner_user_id,
        )
        self.packages = self._inner.packages
        self.diffs = self._inner.diffs

    async def __aenter__(self) -> ManagedArchitectureUnitOfWork:
        """Enter the delegated transactional boundary."""
        await self._inner.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Rollback unfinished work and always release the session."""
        try:
            await self._inner.__aexit__(exc_type, exc_value, traceback)
        finally:
            await self._session.close()

    async def commit(self) -> None:
        """Commit delegated Architecture persistence."""
        await self._inner.commit()

    async def rollback(self) -> None:
        """Rollback delegated Architecture persistence."""
        await self._inner.rollback()


class ManagedArchitectureUnitOfWorkFactory:
    """Create Architecture command Units of Work with owned sessions."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> ManagedArchitectureUnitOfWork:
        """Create one command Unit of Work with a fresh session."""
        return ManagedArchitectureUnitOfWork(
            self._session_factory(),
            owner_user_id=owner_user_id,
        )


class SqlAlchemyArchitectureGateUnitOfWork:
    """Auto-committing transaction boundary for Gate 6 use cases."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        owner_user_id: UUID,
    ) -> None:
        self._session = session
        self.packages = SqlAlchemyArchitecturePackageRepository(
            session,
            owner_user_id=owner_user_id,
        )
        self.gates = SqlAlchemyHumanGateRepository(session)

    async def __aenter__(self) -> SqlAlchemyArchitectureGateUnitOfWork:
        """Enter the Gate 6 transaction."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Commit successful transitions or roll back failures."""
        del exc_value, traceback

        try:
            if exc_type is None:
                await self._session.commit()
            else:
                await self._session.rollback()
        finally:
            await self._session.close()


class SqlAlchemyArchitectureGateUnitOfWorkFactory:
    """Create owner-scoped Gate 6 Units of Work."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> SqlAlchemyArchitectureGateUnitOfWork:
        """Create one Gate 6 transaction with a fresh session."""
        return SqlAlchemyArchitectureGateUnitOfWork(
            self._session_factory(),
            owner_user_id=owner_user_id,
        )


class SqlAlchemyArchitectureQueryService:
    """Short-lived owner-scoped read service for Architecture API queries."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    async def current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> ArchitecturePackageVersion | None:
        """Return the current Architecture Package version."""
        async with self._session_factory() as session:
            repository = SqlAlchemyArchitecturePackageRepository(
                session,
                owner_user_id=owner_user_id,
            )
            return await repository.current(project_id=project_id)

    async def history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[ArchitecturePackageVersion, ...]:
        """Return immutable Architecture Package history."""
        async with self._session_factory() as session:
            repository = SqlAlchemyArchitecturePackageRepository(
                session,
                owner_user_id=owner_user_id,
            )
            return await repository.history(project_id=project_id)

    async def get_diff(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        diff_id: UUID,
    ) -> ArchitecturePackageDiff | None:
        """Return one exact Architecture Package diff."""
        async with self._session_factory() as session:
            repository = SqlAlchemyArchitectureDiffRepository(
                session,
                owner_user_id=owner_user_id,
            )
            return await repository.get(
                project_id=project_id,
                diff_id=diff_id,
            )

    async def diff_history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[ArchitecturePackageDiff, ...]:
        """Return reviewable Architecture Package diff history."""
        async with self._session_factory() as session:
            repository = SqlAlchemyArchitectureDiffRepository(
                session,
                owner_user_id=owner_user_id,
            )
            return await repository.history(project_id=project_id)


class SqlAlchemyArchitectureGovernanceAdapter:
    """Load exact owner-scoped inputs for governed architecture generation."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    async def load_current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> GovernedArchitectureContext | None:
        """Load current Requirements, Design, Team, and Gate 5."""
        async with self._session_factory() as session:
            project = await SqlAlchemyProjectRepository(session).get_owned(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )

            if project is None:
                return None

            requirements_version = await SqlAlchemyRequirementsSpecificationRepository(
                session,
                owner_user_id=owner_user_id,
            ).current(project_id=project_id)
            design_version = await SqlAlchemyDesignPackageRepository(
                session,
                owner_user_id=owner_user_id,
            ).current(project_id=project_id)
            team_version = await SqlAlchemyTeamProposalVersionRepository(
                session,
            ).get_current_owned(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )
            design_gate = await SqlAlchemyHumanGateRepository(
                session,
            ).get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.DESIGN,
            )

            requirements = (
                None
                if requirements_version is None
                else ArchitectureRequirementsInput(version=requirements_version)
            )
            design = (
                None if design_version is None else ArchitectureDesignInput(version=design_version)
            )
            team = (
                None
                if team_version is None
                else ArchitectureAgentTeamInput(
                    reference=VersionedArtifactReference(
                        kind=ArtifactKind.AGENT_TEAM,
                        artifact_id=team_version.id,
                        version_number=team_version.version_number,
                        content_hash=team_version.content_hash,
                    ),
                    selected_agent_ids=team_version.proposal.selected_agent_ids,
                )
            )

            return GovernedArchitectureContext(
                project_id=project_id,
                project_mode=project.mode,
                requirements=requirements,
                design=design,
                team=team,
                catalog_version=(
                    None if team_version is None else team_version.proposal.catalog_version
                ),
                catalog_content_hash=(
                    None if team_version is None else team_version.proposal.catalog_content_hash
                ),
                design_gate=design_gate,
            )


@dataclass(frozen=True, slots=True)
class ArchitectureServices:
    """Concrete process-level services for Architecture Planning and Gate 6."""

    runtime_mode: ArchitectureRuntimeMode
    generation: LocalArchitectureGenerationService
    revisions: LocalArchitectureRevisionService
    queries: SqlAlchemyArchitectureQueryService
    gate: LocalArchitectureGateService


def build_architecture_services(
    session_factory: async_sessionmaker[AsyncSession],
    settings: ArchitectureRuntimeSettings | None = None,
) -> ArchitectureServices:
    """Compose deterministic provider, SQLAlchemy adapters, and Gate 6."""
    runtime = build_architecture_runtime(settings)
    command_uow_factory = ManagedArchitectureUnitOfWorkFactory(session_factory)
    gate_uow_factory = SqlAlchemyArchitectureGateUnitOfWorkFactory(session_factory)

    return ArchitectureServices(
        runtime_mode=runtime.mode,
        generation=LocalArchitectureGenerationService(
            governance=SqlAlchemyArchitectureGovernanceAdapter(session_factory),
            proposals=runtime.proposal_port,
            uow_factory=command_uow_factory,
        ),
        revisions=LocalArchitectureRevisionService(
            uow_factory=command_uow_factory,
        ),
        queries=SqlAlchemyArchitectureQueryService(session_factory),
        gate=LocalArchitectureGateService(
            unit_of_work_factory=gate_uow_factory,
        ),
    )


__all__ = [
    "ArchitectureServices",
    "ManagedArchitectureUnitOfWork",
    "ManagedArchitectureUnitOfWorkFactory",
    "SqlAlchemyArchitectureGateUnitOfWork",
    "SqlAlchemyArchitectureGateUnitOfWorkFactory",
    "SqlAlchemyArchitectureGovernanceAdapter",
    "SqlAlchemyArchitectureQueryService",
    "build_architecture_services",
]
