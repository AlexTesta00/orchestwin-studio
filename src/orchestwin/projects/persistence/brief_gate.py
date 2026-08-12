"""SQLAlchemy unit of work for Project Brief approval gates."""

from __future__ import annotations

from types import TracebackType
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from orchestwin.projects.briefs import (
    ProjectBriefVersion,
)
from orchestwin.projects.persistence.briefs import (
    brief_record_to_domain,
)
from orchestwin.projects.persistence.models import (
    ProjectBriefVersionRecord,
    ProjectRecord,
)
from orchestwin.workflow.persistence.repositories import (
    SqlAlchemyHumanGateRepository,
)


def owned_project_for_gate_statement(
    *,
    project_id: UUID,
    owner_user_id: UUID,
):
    """Build the owner-scoped project lock used by Gate 1."""
    return (
        select(ProjectRecord)
        .where(
            ProjectRecord.id == project_id,
            ProjectRecord.owner_user_id == owner_user_id,
            ProjectRecord.archived_at.is_(None),
        )
        .with_for_update()
    )


class SqlAlchemyCurrentProjectBriefRepository:
    """Lock and load the current brief through project ownership."""

    def __init__(
        self,
        session: AsyncSession,
    ) -> None:
        self._session = session

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ProjectBriefVersion | None:
        """Lock the owned project and return its current brief."""
        project = await self._session.scalar(
            owned_project_for_gate_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )
        )

        if project is None or project.current_brief_version < 1:
            return None

        record = await self._session.scalar(
            select(ProjectBriefVersionRecord).where(
                ProjectBriefVersionRecord.project_id == project.id,
                ProjectBriefVersionRecord.version_number == project.current_brief_version,
            )
        )

        if record is None:
            raise RuntimeError("project current brief version is missing")

        return brief_record_to_domain(record)


class SqlAlchemyProjectBriefGateUnitOfWork:
    """One SQLAlchemy transaction for a Gate 1 use case."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._current_briefs: SqlAlchemyCurrentProjectBriefRepository | None = None
        self._gates: SqlAlchemyHumanGateRepository | None = None

    @property
    def current_briefs(
        self,
    ) -> SqlAlchemyCurrentProjectBriefRepository:
        """Return the current-brief repository after entry."""
        if self._current_briefs is None:
            raise RuntimeError("Project Brief gate unit of work is not open")

        return self._current_briefs

    @property
    def gates(
        self,
    ) -> SqlAlchemyHumanGateRepository:
        """Return the gate repository after entry."""
        if self._gates is None:
            raise RuntimeError("Project Brief gate unit of work is not open")

        return self._gates

    async def __aenter__(
        self,
    ) -> SqlAlchemyProjectBriefGateUnitOfWork:
        """Open a SQLAlchemy session and transaction."""
        self._session = self._session_factory()
        await self._session.begin()

        self._current_briefs = SqlAlchemyCurrentProjectBriefRepository(self._session)
        self._gates = SqlAlchemyHumanGateRepository(self._session)

        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Commit successful work or roll back failures."""
        if self._session is None:
            return

        try:
            if exception_type is None:
                await self._session.commit()
            else:
                await self._session.rollback()
        finally:
            await self._session.close()
            self._session = None
            self._current_briefs = None
            self._gates = None


class SqlAlchemyProjectBriefGateUnitOfWorkFactory:
    """Create a fresh Gate 1 unit of work per use case."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    def __call__(
        self,
    ) -> SqlAlchemyProjectBriefGateUnitOfWork:
        """Return one unopened Gate 1 unit of work."""
        return SqlAlchemyProjectBriefGateUnitOfWork(self._session_factory)
