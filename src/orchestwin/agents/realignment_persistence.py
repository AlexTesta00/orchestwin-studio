from __future__ import annotations

from types import TracebackType
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.agents.persistence.models import TeamProposalVersionRecord
from orchestwin.agents.persistence.repositories import (
    SqlAlchemyTeamProposalVersionRepository,
    SqlAlchemyTeamSelectionContextRepository,
)
from orchestwin.agents.proposals import TeamProposalVersion
from orchestwin.agents.realignment_service import TeamRealignmentService
from orchestwin.workflow.persistence.repositories import SqlAlchemyHumanGateRepository


class SqlAlchemyTeamRealignmentProposals:
    def __init__(self, session: AsyncSession, *, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id
        self._queries = SqlAlchemyTeamProposalVersionRepository(session)

    async def current(self, *, owner_user_id: UUID, project_id: UUID) -> TeamProposalVersion | None:
        if owner_user_id != self._owner_user_id:
            return None
        return await self._queries.get_current_owned(
            owner_user_id=owner_user_id, project_id=project_id
        )

    async def append(self, version: TeamProposalVersion) -> bool:
        if version.created_by_user_id != self._owner_user_id:
            return False
        current = await self.current(
            owner_user_id=self._owner_user_id, project_id=version.project_id
        )
        if (
            current is None
            or version.based_on_version_number != current.version_number
            or version.version_number != current.version_number + 1
        ):
            return False
        proposal = version.proposal
        self._session.add(
            TeamProposalVersionRecord(
                id=version.id,
                project_id=version.project_id,
                version_number=version.version_number,
                schema_version=proposal.schema_version,
                revision_kind=version.revision_kind.value,
                based_on_version_number=version.based_on_version_number,
                brief_version_id=proposal.brief_version_id,
                brief_version_number=proposal.brief_version_number,
                brief_content_hash=proposal.brief_content_hash,
                catalog_version=proposal.catalog_version,
                catalog_content_hash=proposal.catalog_content_hash,
                constraints_content_hash=proposal.constraints.content_hash,
                provider_kind=proposal.provider_kind.value,
                provider_id=proposal.provider_id,
                provider_version=proposal.provider_version,
                content=proposal.to_snapshot(),
                content_hash=version.content_hash,
                created_by_user_id=version.created_by_user_id,
                created_at=version.created_at,
            )
        )
        await self._session.flush()
        return True


class ManagedTeamRealignmentUnitOfWork:
    def __init__(self, session: AsyncSession, *, owner_user_id: UUID) -> None:
        self._session = session
        self.contexts = SqlAlchemyTeamSelectionContextRepository(session)
        self.proposals = SqlAlchemyTeamRealignmentProposals(session, owner_user_id=owner_user_id)
        self.gates = SqlAlchemyHumanGateRepository(session)

    async def __aenter__(self) -> ManagedTeamRealignmentUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            await self._session.rollback()
        finally:
            await self._session.close()

    async def commit(self) -> None:
        await self._session.commit()


class ManagedTeamRealignmentUnitOfWorkFactory:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def __call__(self, *, owner_user_id: UUID) -> ManagedTeamRealignmentUnitOfWork:
        return ManagedTeamRealignmentUnitOfWork(
            self._session_factory(), owner_user_id=owner_user_id
        )


def build_team_realignment_service(
    session_factory: async_sessionmaker[AsyncSession],
) -> TeamRealignmentService:
    return TeamRealignmentService(
        uow_factory=ManagedTeamRealignmentUnitOfWorkFactory(session_factory)
    )


__all__ = [
    "ManagedTeamRealignmentUnitOfWork",
    "ManagedTeamRealignmentUnitOfWorkFactory",
    "SqlAlchemyTeamRealignmentProposals",
    "build_team_realignment_service",
]
