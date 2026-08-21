"""SQLAlchemy adapters and composition for the Design stage."""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.agents.persistence.repositories import (
    SqlAlchemyTeamProposalVersionRepository,
)
from orchestwin.artifacts.design_gate import LocalDesignGateService
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.design_persistence import (
    SqlAlchemyDesignDiffRepository,
    SqlAlchemyDesignPackageRepository,
    SqlAlchemyDesignUnitOfWork,
)
from orchestwin.artifacts.design_revision_application import (
    LocalDesignRevisionService,
)
from orchestwin.artifacts.design_revisions import DesignPackageDiff
from orchestwin.artifacts.references import ArtifactKind, VersionedArtifactReference
from orchestwin.models.design import (
    DesignAgentTeamInput,
    DesignRequirementsInput,
    DesignUserModelingInput,
    DesignUserTwinInput,
)
from orchestwin.models.design_runtime import (
    DesignRuntimeMode,
    DesignRuntimeSettings,
    build_design_runtime,
)
from orchestwin.projects.design_application import (
    GovernedDesignContext,
    LocalDesignGenerationService,
)
from orchestwin.projects.persistence.repositories import SqlAlchemyProjectRepository
from orchestwin.projects.requirements_persistence import (
    SqlAlchemyRequirementsSpecificationRepository,
)
from orchestwin.projects.requirements_primitives import UserTwinVersionReference
from orchestwin.twins.persistence.repositories import (
    SqlAlchemyUserModelingSnapshotRepository,
)
from orchestwin.workflow.gates import HumanGateType
from orchestwin.workflow.persistence.repositories import (
    SqlAlchemyHumanGateRepository,
)


class ManagedDesignUnitOfWork:
    """Close the session owned by the existing Design Unit of Work."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        owner_user_id: UUID,
    ) -> None:
        self._session = session
        self._inner = SqlAlchemyDesignUnitOfWork(
            session,
            owner_user_id=owner_user_id,
        )
        self.packages = self._inner.packages
        self.diffs = self._inner.diffs

    async def __aenter__(self) -> ManagedDesignUnitOfWork:
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
        """Commit delegated Design persistence."""
        await self._inner.commit()

    async def rollback(self) -> None:
        """Rollback delegated Design persistence."""
        await self._inner.rollback()


class ManagedDesignUnitOfWorkFactory:
    """Create Design command Units of Work with owned sessions."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> ManagedDesignUnitOfWork:
        """Create one command Unit of Work with a fresh session."""
        return ManagedDesignUnitOfWork(
            self._session_factory(),
            owner_user_id=owner_user_id,
        )


class SqlAlchemyDesignGateUnitOfWork:
    """Auto-committing transaction boundary for Gate 5 use cases."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        owner_user_id: UUID,
    ) -> None:
        self._session = session
        self.packages = SqlAlchemyDesignPackageRepository(
            session,
            owner_user_id=owner_user_id,
        )
        self.gates = SqlAlchemyHumanGateRepository(session)

    async def __aenter__(self) -> SqlAlchemyDesignGateUnitOfWork:
        """Enter the Gate 5 transaction."""
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


class SqlAlchemyDesignGateUnitOfWorkFactory:
    """Create owner-scoped Gate 5 Units of Work."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> SqlAlchemyDesignGateUnitOfWork:
        """Create one Gate 5 transaction with a fresh session."""
        return SqlAlchemyDesignGateUnitOfWork(
            self._session_factory(),
            owner_user_id=owner_user_id,
        )


class SqlAlchemyDesignQueryService:
    """Short-lived owner-scoped read service for Design API queries."""

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
    ) -> DesignPackageVersion | None:
        """Return the current Design Package version."""
        async with self._session_factory() as session:
            repository = SqlAlchemyDesignPackageRepository(
                session,
                owner_user_id=owner_user_id,
            )
            return await repository.current(project_id=project_id)

    async def history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[DesignPackageVersion, ...]:
        """Return immutable Design Package history."""
        async with self._session_factory() as session:
            repository = SqlAlchemyDesignPackageRepository(
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
    ) -> DesignPackageDiff | None:
        """Return one exact Design Package diff."""
        async with self._session_factory() as session:
            repository = SqlAlchemyDesignDiffRepository(
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
    ) -> tuple[DesignPackageDiff, ...]:
        """Return reviewable Design Package diff history."""
        async with self._session_factory() as session:
            repository = SqlAlchemyDesignDiffRepository(
                session,
                owner_user_id=owner_user_id,
            )
            return await repository.history(project_id=project_id)


class SqlAlchemyDesignGovernanceAdapter:
    """Load exact owner-scoped inputs for governed design generation."""

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
    ) -> GovernedDesignContext | None:
        """Load current Requirements, Team, User Modeling, and Gate 4."""
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
            team_version = await SqlAlchemyTeamProposalVersionRepository(
                session,
            ).get_current_owned(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )
            user_modeling_version = await SqlAlchemyUserModelingSnapshotRepository(
                session,
                owner_user_id=owner_user_id,
            ).current(project_id=project_id)
            requirements_gate = await SqlAlchemyHumanGateRepository(
                session,
            ).get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.REQUIREMENTS,
            )

            requirements = (
                None
                if requirements_version is None
                else DesignRequirementsInput(version=requirements_version)
            )
            team = (
                None
                if team_version is None
                else DesignAgentTeamInput(
                    reference=VersionedArtifactReference(
                        kind=ArtifactKind.AGENT_TEAM,
                        artifact_id=team_version.id,
                        version_number=team_version.version_number,
                        content_hash=team_version.content_hash,
                    ),
                    selected_agent_ids=team_version.proposal.selected_agent_ids,
                )
            )
            user_modeling = (
                None
                if user_modeling_version is None
                else _user_modeling_input(user_modeling_version)
            )

            return GovernedDesignContext(
                project_id=project_id,
                project_mode=project.mode,
                requirements=requirements,
                team=team,
                user_modeling=user_modeling,
                catalog_version=(
                    None if team_version is None else team_version.proposal.catalog_version
                ),
                catalog_content_hash=(
                    None if team_version is None else team_version.proposal.catalog_content_hash
                ),
                requirements_gate=requirements_gate,
            )


def _user_modeling_input(user_modeling_version) -> DesignUserModelingInput:
    """Convert the current User Modeling snapshot into design-provider input."""
    return DesignUserModelingInput(
        reference=VersionedArtifactReference(
            kind=ArtifactKind.USER_MODELING,
            artifact_id=user_modeling_version.id,
            version_number=user_modeling_version.version_number,
            content_hash=user_modeling_version.content_hash,
        ),
        user_twins=tuple(
            DesignUserTwinInput(
                reference=UserTwinVersionReference(
                    twin_id=version.twin_id,
                    version_number=version.version_number,
                    content_hash=version.content_hash,
                    name=version.profile.name,
                ),
                observations=version.profile.observations,
            )
            for version in user_modeling_version.snapshot.twin_versions
        ),
    )


@dataclass(frozen=True, slots=True)
class DesignServices:
    """Concrete process-level services for Design Exploration and Gate 5."""

    runtime_mode: DesignRuntimeMode
    generation: LocalDesignGenerationService
    revisions: LocalDesignRevisionService
    queries: SqlAlchemyDesignQueryService
    gate: LocalDesignGateService


def build_design_services(
    session_factory: async_sessionmaker[AsyncSession],
    settings: DesignRuntimeSettings | None = None,
) -> DesignServices:
    """Compose deterministic provider, SQLAlchemy adapters, and Gate 5."""
    runtime = build_design_runtime(settings)
    command_uow_factory = ManagedDesignUnitOfWorkFactory(session_factory)
    gate_uow_factory = SqlAlchemyDesignGateUnitOfWorkFactory(session_factory)

    return DesignServices(
        runtime_mode=runtime.mode,
        generation=LocalDesignGenerationService(
            governance=SqlAlchemyDesignGovernanceAdapter(session_factory),
            proposals=runtime.proposal_port,
            uow_factory=command_uow_factory,
        ),
        revisions=LocalDesignRevisionService(
            uow_factory=command_uow_factory,
        ),
        queries=SqlAlchemyDesignQueryService(session_factory),
        gate=LocalDesignGateService(
            unit_of_work_factory=gate_uow_factory,
        ),
    )


__all__ = [
    "DesignServices",
    "ManagedDesignUnitOfWork",
    "ManagedDesignUnitOfWorkFactory",
    "SqlAlchemyDesignGateUnitOfWork",
    "SqlAlchemyDesignGateUnitOfWorkFactory",
    "SqlAlchemyDesignGovernanceAdapter",
    "SqlAlchemyDesignQueryService",
    "build_design_services",
]
