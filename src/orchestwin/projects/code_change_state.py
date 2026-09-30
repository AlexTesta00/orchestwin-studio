from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.knowledge.state import MAX_FOLDER_TEST_RUNS, ProjectStateSources
from orchestwin.projects.persistence.acceptance_tests import SqlAlchemyAcceptanceTestRepository
from orchestwin.projects.persistence.code_changes import SqlAlchemyCodeChangeRepository
from orchestwin.projects.persistence.twin_learning import SqlAlchemyTwinLearningRepository
from orchestwin.projects.twin_learning import build_twin_learning
from orchestwin.twins.persistence.repositories import SqlAlchemyUserTwinVersionRepository


async def _learning(
    session: AsyncSession, *, owner_user_id: UUID, project_id: UUID
) -> tuple[dict[str, object], ...]:
    learned = await SqlAlchemyTwinLearningRepository(
        session, owner_user_id=owner_user_id
    ).project_observations(project_id)
    if not learned:
        return ()
    versions = {
        version.twin_id: version
        for version in await SqlAlchemyUserTwinVersionRepository(
            session, owner_user_id=owner_user_id
        ).list_current(project_id=project_id)
    }
    return tuple(
        build_twin_learning(
            twin_id=twin_id,
            twin_name=versions[twin_id].profile.name,
            profile_version_number=versions[twin_id].version_number,
            records=learned[twin_id],
        ).to_snapshot()
        for twin_id in sorted(learned, key=lambda value: value.hex)
        if twin_id in versions
    )


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
            tests = await SqlAlchemyAcceptanceTestRepository(
                session, owner_user_id=owner_user_id
            ).folder_runs(project_id, limit=MAX_FOLDER_TEST_RUNS)
            learning = await _learning(session, owner_user_id=owner_user_id, project_id=project_id)
        return ProjectStateSources(
            aligned=None if aligned is None else aligned.to_snapshot(),
            changes=tuple(change.to_snapshot() for change in changes),
            runs=tuple(run.to_snapshot() for run in runs),
            tasks=tuple(task.to_snapshot() for task in tasks),
            tests=tests,
            learning=learning,
        )


__all__ = ["SqlAlchemyProjectStateQueryService"]
