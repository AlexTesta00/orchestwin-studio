from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.knowledge.state import ProjectStateSources
from orchestwin.projects.persistence.code_changes import SqlAlchemyCodeChangeRepository


class SqlAlchemyProjectStateQueryService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def current(self, *, owner_user_id: UUID, project_id: UUID) -> ProjectStateSources:
        async with self._session_factory() as session:
            repository = SqlAlchemyCodeChangeRepository(session, owner_user_id=owner_user_id)
            if not await repository.project_exists(project_id):
                return ProjectStateSources()
            aligned = await repository.aligned_point(project_id)
            changes = await repository.list(project_id, limit=None)
            runs = await repository.project_runs(project_id)
            tasks = await repository.tasks(project_id)
        return ProjectStateSources(
            aligned=None if aligned is None else aligned.to_snapshot(),
            changes=tuple(change.to_snapshot() for change in changes),
            runs=tuple(run.to_snapshot() for run in runs),
            tasks=tuple(task.to_snapshot() for task in tasks),
        )


__all__ = ["SqlAlchemyProjectStateQueryService"]
