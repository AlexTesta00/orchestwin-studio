"""Compose persisted User Modeling commands, queries, and the existing Gate 3 service."""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.agents.persistence.repositories import SqlAlchemyTeamProposalVersionRepository
from orchestwin.models.user_modeling_runtime import (
    UserModelingRuntimeMode,
    UserModelingRuntimeSettings,
    build_user_modeling_runtime,
)
from orchestwin.projects.persistence.briefs import SqlAlchemyProjectBriefRepository
from orchestwin.projects.persistence.repositories import (
    SqlAlchemyProjectRepository,
    owned_project_statement,
)
from orchestwin.twins.application import (
    GovernedUserModelingContext,
    LocalUserModelingApplicationService,
)
from orchestwin.twins.persistence.repositories import SqlAlchemyUserModelingSnapshotRepository
from orchestwin.twins.persistence.uow import SqlAlchemyUserModelingUnitOfWork
from orchestwin.twins.revision_application import LocalUserTwinProfileRevisionService
from orchestwin.twins.revision_persistence import SqlAlchemyUserTwinProfileDiffRepository
from orchestwin.twins.revisions import UserTwinProfileDiff
from orchestwin.twins.user_modeling_gate import LocalUserModelingGateService
from orchestwin.twins.user_twins import UserModelingSnapshotVersion, VersionedArtifactReference
from orchestwin.workflow.gates import GateArtifactReference, HumanGateStatus, HumanGateType
from orchestwin.workflow.persistence.repositories import SqlAlchemyHumanGateRepository


class ManagedUserModelingUnitOfWork(SqlAlchemyUserModelingUnitOfWork):
    """Keep explicit command commits and always release the owned session."""

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            await super().__aexit__(exc_type, exc_value, traceback)
        finally:
            await self._session.close()


class ManagedUserModelingUnitOfWorkFactory:
    """Allocate a fresh owner-scoped session for each generation/revision command."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def __call__(self, *, owner_user_id: UUID) -> ManagedUserModelingUnitOfWork:
        return ManagedUserModelingUnitOfWork(
            self._session_factory(),
            owner_user_id=owner_user_id,
        )


class LockedUserModelingSnapshotQuery:
    """Serialize Gate 3 changes by locking the active project before reading its snapshot."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> UserModelingSnapshotVersion | None:
        project = await self._session.scalar(
            owned_project_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
            ).with_for_update()
        )
        if project is None:
            return None
        return await SqlAlchemyUserModelingSnapshotRepository(
            self._session,
            owner_user_id=owner_user_id,
        ).current(project_id=project_id)


class SqlAlchemyUserModelingGateUnitOfWork:
    """Commit Gate 3 state and events atomically; roll back errors and release locks."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.current_snapshots = LockedUserModelingSnapshotQuery(session)
        self.gates = SqlAlchemyHumanGateRepository(session)

    async def __aenter__(self) -> SqlAlchemyUserModelingGateUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        try:
            if exc_type is not None:
                await self._session.rollback()
            else:
                try:
                    await self._session.commit()
                except BaseException:
                    await self._session.rollback()
                    raise
        finally:
            await self._session.close()


class SqlAlchemyUserModelingGateUnitOfWorkFactory:
    """Allocate a fresh session for the existing no-argument Gate 3 UoW contract."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def __call__(self) -> SqlAlchemyUserModelingGateUnitOfWork:
        return SqlAlchemyUserModelingGateUnitOfWork(self._session_factory())


class SqlAlchemyUserModelingGovernanceAdapter:
    """Read the actual owned Brief/Team versions and their approval gates."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def load_current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> GovernedUserModelingContext | None:
        async with self._session_factory() as session:
            project = await SqlAlchemyProjectRepository(session).get_owned(
                owner_user_id=owner_user_id,
                project_id=project_id,
            )
            if project is None:
                return None
            brief = await SqlAlchemyProjectBriefRepository(session).get_current_owned(
                owner_user_id=owner_user_id,
                project_id=project_id,
            )
            team = await SqlAlchemyTeamProposalVersionRepository(session).get_current_owned(
                owner_user_id=owner_user_id,
                project_id=project_id,
            )
            gates = SqlAlchemyHumanGateRepository(session)
            brief_gate = await gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.PROJECT_BRIEF,
            )
            team_gate = await gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.AGENT_TEAM,
            )
            team_reference = None
            approved_reference = None
            if team is not None:
                team_reference = VersionedArtifactReference(
                    artifact_id=team.id,
                    version_number=team.version_number,
                    content_hash=team.content_hash,
                )
                exact_artifact = GateArtifactReference(
                    project_id=project_id,
                    gate_type=HumanGateType.AGENT_TEAM,
                    artifact_id=team.id,
                    version=team.version_number,
                    content_hash=team.content_hash,
                )
                if (
                    team_gate is not None
                    and team_gate.status is HumanGateStatus.APPROVED
                    and team_gate.artifact == exact_artifact
                ):
                    approved_reference = team_reference
            return GovernedUserModelingContext(
                project_id=project_id,
                brief_version=brief,
                brief_gate=brief_gate,
                team_reference=team_reference,
                approved_team_reference=approved_reference,
                catalog_version=None if team is None else team.proposal.catalog_version,
                catalog_content_hash=None if team is None else team.proposal.catalog_content_hash,
            )


class SqlAlchemyUserModelingQueryService:
    """Owner-scoped queries with independent, short-lived sessions."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def current_snapshot(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> UserModelingSnapshotVersion | None:
        async with self._session_factory() as session:
            return await SqlAlchemyUserModelingSnapshotRepository(
                session,
                owner_user_id=owner_user_id,
            ).current(project_id=project_id)

    async def snapshot_history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[UserModelingSnapshotVersion, ...]:
        async with self._session_factory() as session:
            return await SqlAlchemyUserModelingSnapshotRepository(
                session,
                owner_user_id=owner_user_id,
            ).history(project_id=project_id)

    async def get_diff(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        diff_id: UUID,
    ) -> UserTwinProfileDiff | None:
        async with self._session_factory() as session:
            return await SqlAlchemyUserTwinProfileDiffRepository(
                session,
                owner_user_id=owner_user_id,
            ).get(project_id=project_id, diff_id=diff_id)


@dataclass(frozen=True, slots=True)
class UserModelingServices:
    """Concrete services and the declared provider mode (not formal-run readiness)."""

    runtime_mode: UserModelingRuntimeMode
    commands: LocalUserModelingApplicationService
    revisions: LocalUserTwinProfileRevisionService
    queries: SqlAlchemyUserModelingQueryService
    gates: LocalUserModelingGateService


def build_user_modeling_services(
    session_factory: async_sessionmaker[AsyncSession],
    settings: UserModelingRuntimeSettings | None = None,
) -> UserModelingServices:
    """Wire persistence and existing domain services without running a provider or opening SQL."""
    runtime = build_user_modeling_runtime(settings)
    command_units = ManagedUserModelingUnitOfWorkFactory(session_factory)
    return UserModelingServices(
        runtime_mode=runtime.mode,
        commands=LocalUserModelingApplicationService(
            governance=SqlAlchemyUserModelingGovernanceAdapter(session_factory),
            proposals=runtime.proposal_port,
            uow_factory=command_units,
        ),
        revisions=LocalUserTwinProfileRevisionService(uow_factory=command_units),
        queries=SqlAlchemyUserModelingQueryService(session_factory),
        gates=LocalUserModelingGateService(
            unit_of_work_factory=SqlAlchemyUserModelingGateUnitOfWorkFactory(session_factory),
        ),
    )
