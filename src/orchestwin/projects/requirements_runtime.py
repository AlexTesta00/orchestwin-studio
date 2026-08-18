"""SQLAlchemy adapters and composition for the Requirements stage."""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.agents.persistence.repositories import (
    SqlAlchemyTeamProposalVersionRepository,
)
from orchestwin.models.requirements import (
    RequirementsBriefInput,
    RequirementsTeamInput,
    RequirementsUserModelingInput,
    RequirementsUserTwinInput,
)
from orchestwin.models.requirements_runtime import (
    RequirementsRuntimeMode,
    RequirementsRuntimeSettings,
    build_requirements_runtime,
)
from orchestwin.projects.persistence.briefs import (
    SqlAlchemyProjectBriefRepository,
)
from orchestwin.projects.persistence.repositories import (
    SqlAlchemyProjectRepository,
)
from orchestwin.projects.requirements_application import (
    GovernedRequirementsContext,
    LocalRequirementsGenerationService,
)
from orchestwin.projects.requirements_gate import (
    LocalRequirementsGateService,
)
from orchestwin.projects.requirements_persistence import (
    SqlAlchemyRequirementsDiffRepository,
    SqlAlchemyRequirementsSpecificationRepository,
    SqlAlchemyRequirementsUnitOfWork,
)
from orchestwin.projects.requirements_primitives import (
    RequirementsContextKind,
    RequirementsContextReference,
    UserTwinVersionReference,
)
from orchestwin.projects.requirements_revision_application import (
    LocalRequirementsRevisionService,
)
from orchestwin.projects.requirements_revisions import (
    RequirementsSpecificationDiff,
)
from orchestwin.projects.requirements_specifications import (
    RequirementsSpecificationVersion,
)
from orchestwin.twins.persistence.repositories import (
    SqlAlchemyUserModelingSnapshotRepository,
)
from orchestwin.workflow.gates import HumanGateType
from orchestwin.workflow.persistence.repositories import (
    SqlAlchemyHumanGateRepository,
)


class ManagedRequirementsUnitOfWork:
    """Close the session owned by the existing requirements Unit of Work."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        owner_user_id: UUID,
    ) -> None:
        self._session = session
        self._inner = SqlAlchemyRequirementsUnitOfWork(
            session,
            owner_user_id=owner_user_id,
        )
        self.specifications = self._inner.specifications
        self.diffs = self._inner.diffs

    async def __aenter__(self) -> ManagedRequirementsUnitOfWork:
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
        """Commit delegated requirements persistence."""
        await self._inner.commit()

    async def rollback(self) -> None:
        """Rollback delegated requirements persistence."""
        await self._inner.rollback()


class ManagedRequirementsUnitOfWorkFactory:
    """Create requirements command Units of Work with owned sessions."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> ManagedRequirementsUnitOfWork:
        """Create one command Unit of Work with a fresh session."""
        return ManagedRequirementsUnitOfWork(
            self._session_factory(),
            owner_user_id=owner_user_id,
        )


class SqlAlchemyRequirementsGateUnitOfWork:
    """Auto-committing transaction boundary for Gate 4 use cases."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        owner_user_id: UUID,
    ) -> None:
        self._session = session
        self.specifications = SqlAlchemyRequirementsSpecificationRepository(
            session,
            owner_user_id=owner_user_id,
        )
        self.gates = SqlAlchemyHumanGateRepository(session)

    async def __aenter__(self) -> SqlAlchemyRequirementsGateUnitOfWork:
        """Enter the Gate 4 transaction."""
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


class SqlAlchemyRequirementsGateUnitOfWorkFactory:
    """Create owner-scoped Gate 4 Units of Work."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> SqlAlchemyRequirementsGateUnitOfWork:
        """Create one Gate 4 transaction with a fresh session."""
        return SqlAlchemyRequirementsGateUnitOfWork(
            self._session_factory(),
            owner_user_id=owner_user_id,
        )


class SqlAlchemyRequirementsQueryService:
    """Short-lived owner-scoped read service for Requirements API queries."""

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
    ) -> RequirementsSpecificationVersion | None:
        """Return the current requirements specification."""
        async with self._session_factory() as session:
            repository = SqlAlchemyRequirementsSpecificationRepository(
                session,
                owner_user_id=owner_user_id,
            )
            return await repository.current(project_id=project_id)

    async def history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[RequirementsSpecificationVersion, ...]:
        """Return immutable requirements history."""
        async with self._session_factory() as session:
            repository = SqlAlchemyRequirementsSpecificationRepository(
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
    ) -> RequirementsSpecificationDiff | None:
        """Return one exact requirements diff."""
        async with self._session_factory() as session:
            repository = SqlAlchemyRequirementsDiffRepository(
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
    ) -> tuple[RequirementsSpecificationDiff, ...]:
        """Return reviewable requirements diff history."""
        async with self._session_factory() as session:
            repository = SqlAlchemyRequirementsDiffRepository(
                session,
                owner_user_id=owner_user_id,
            )
            return await repository.history(project_id=project_id)


class SqlAlchemyRequirementsGovernanceAdapter:
    """Load Requirements inputs through current owner-scoped persistence."""

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
    ) -> GovernedRequirementsContext | None:
        """Load current Brief, Team, User Modeling, and approval gates."""
        async with self._session_factory() as session:
            project = await SqlAlchemyProjectRepository(session).get_owned(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )

            if project is None:
                return None

            brief_version = await SqlAlchemyProjectBriefRepository(session).get_current_owned(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )
            team_version = await SqlAlchemyTeamProposalVersionRepository(session).get_current_owned(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )
            user_modeling_version = await SqlAlchemyUserModelingSnapshotRepository(
                session,
                owner_user_id=owner_user_id,
            ).current(project_id=project_id)

            gate_repository = SqlAlchemyHumanGateRepository(session)
            brief_gate = await gate_repository.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.PROJECT_BRIEF,
            )
            team_gate = await gate_repository.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.AGENT_TEAM,
            )
            user_modeling_gate = await gate_repository.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.USER_MODELING,
            )

            brief = None if brief_version is None else _brief_input(brief_version)
            team = (
                None
                if team_version is None
                else RequirementsTeamInput(
                    reference=RequirementsContextReference(
                        kind=RequirementsContextKind.AGENT_TEAM,
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

            return GovernedRequirementsContext(
                project_id=project_id,
                project_mode=project.mode,
                brief=brief,
                team=team,
                user_modeling=user_modeling,
                catalog_version=(
                    None if team_version is None else team_version.proposal.catalog_version
                ),
                catalog_content_hash=(
                    None if team_version is None else team_version.proposal.catalog_content_hash
                ),
                brief_gate=brief_gate,
                team_gate=team_gate,
                user_modeling_gate=user_modeling_gate,
            )


def _brief_input(brief_version) -> RequirementsBriefInput:
    """Convert the current Project Brief into provider input."""
    brief = brief_version.brief

    return RequirementsBriefInput(
        reference=RequirementsContextReference(
            kind=RequirementsContextKind.PROJECT_BRIEF,
            artifact_id=brief_version.id,
            version_number=brief_version.version_number,
            content_hash=brief_version.content_hash,
        ),
        name=brief.name or "Untitled Project",
        description=brief.description,
        problem=brief.problem,
        goals=tuple(brief.goals or ()),
        target_users=tuple(brief.target_users or ()),
        domain=brief.domain,
        technical_constraints=tuple(brief.technical_constraints or ()),
        temporal_constraints=brief.temporal_constraints,
        budget=brief.budget,
        functional_requirements=tuple(brief.functional_requirements or ()),
        non_functional_requirements=tuple(brief.non_functional_requirements or ()),
        risks=tuple(brief.risks or ()),
        stakeholders=tuple(brief.stakeholders or ()),
        available_artifacts=tuple(brief.available_artifacts or ()),
        definition_of_done=tuple(brief.definition_of_done or ()),
        unknown_fields=brief.unknown_fields,
    )


def _user_modeling_input(user_modeling_version) -> RequirementsUserModelingInput:
    """Convert the current User Modeling snapshot into provider input."""
    return RequirementsUserModelingInput(
        reference=RequirementsContextReference(
            kind=RequirementsContextKind.USER_MODELING,
            artifact_id=user_modeling_version.id,
            version_number=user_modeling_version.version_number,
            content_hash=user_modeling_version.content_hash,
        ),
        user_twins=tuple(
            RequirementsUserTwinInput(
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
class RequirementsServices:
    """Concrete process-level services for the Requirements stage."""

    runtime_mode: RequirementsRuntimeMode
    generation: LocalRequirementsGenerationService
    revisions: LocalRequirementsRevisionService
    queries: SqlAlchemyRequirementsQueryService
    gate: LocalRequirementsGateService


def build_requirements_services(
    session_factory: async_sessionmaker[AsyncSession],
    settings: RequirementsRuntimeSettings | None = None,
) -> RequirementsServices:
    """Compose deterministic provider, SQLAlchemy adapters, and Gate 4."""
    runtime = build_requirements_runtime(settings)
    command_uow_factory = ManagedRequirementsUnitOfWorkFactory(session_factory)
    gate_uow_factory = SqlAlchemyRequirementsGateUnitOfWorkFactory(session_factory)

    return RequirementsServices(
        runtime_mode=runtime.mode,
        generation=LocalRequirementsGenerationService(
            governance=SqlAlchemyRequirementsGovernanceAdapter(session_factory),
            proposals=runtime.proposal_port,
            uow_factory=command_uow_factory,
        ),
        revisions=LocalRequirementsRevisionService(
            uow_factory=command_uow_factory,
        ),
        queries=SqlAlchemyRequirementsQueryService(session_factory),
        gate=LocalRequirementsGateService(
            unit_of_work_factory=gate_uow_factory,
        ),
    )


__all__ = [
    "ManagedRequirementsUnitOfWork",
    "ManagedRequirementsUnitOfWorkFactory",
    "RequirementsServices",
    "SqlAlchemyRequirementsGateUnitOfWork",
    "SqlAlchemyRequirementsGateUnitOfWorkFactory",
    "SqlAlchemyRequirementsGovernanceAdapter",
    "SqlAlchemyRequirementsQueryService",
    "build_requirements_services",
]
