"""SQLAlchemy unit of work for Project Definition."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.persistence.unit_of_work import SqlAlchemyUnitOfWork, SqlAlchemyUnitOfWorkFactory
from orchestwin.projects.persistence.briefs import (
    SqlAlchemyProjectBriefRepository,
)
from orchestwin.projects.persistence.progress import SqlAlchemyProjectOverviewRepository
from orchestwin.projects.persistence.repositories import (
    SqlAlchemyProjectRepository,
)


class SqlAlchemyProjectUnitOfWork(SqlAlchemyUnitOfWork):
    """One SQLAlchemy transaction for project use cases."""

    @property
    def overviews(self) -> SqlAlchemyProjectOverviewRepository:
        if self._overviews is None:
            raise RuntimeError("project unit of work is not open")

        return self._overviews

    @property
    def projects(
        self,
    ) -> SqlAlchemyProjectRepository:
        """Return the project repository after entry."""
        if self._projects is None:
            raise RuntimeError("project unit of work is not open")

        return self._projects

    @property
    def briefs(
        self,
    ) -> SqlAlchemyProjectBriefRepository:
        """Return the brief repository after entry."""
        if self._briefs is None:
            raise RuntimeError("project unit of work is not open")

        return self._briefs

    def _bind(self, session: AsyncSession) -> None:
        self._projects = SqlAlchemyProjectRepository(session)
        self._briefs = SqlAlchemyProjectBriefRepository(session)
        self._overviews = SqlAlchemyProjectOverviewRepository(session)

    def _release(self) -> None:
        self._projects = None
        self._briefs = None
        self._overviews = None


class SqlAlchemyProjectUnitOfWorkFactory(SqlAlchemyUnitOfWorkFactory):
    """Create a fresh project unit of work per use case."""

    unit_of_work = SqlAlchemyProjectUnitOfWork
