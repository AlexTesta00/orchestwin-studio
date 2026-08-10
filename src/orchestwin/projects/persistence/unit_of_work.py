"""SQLAlchemy unit of work for Project Definition."""

from __future__ import annotations

from types import TracebackType

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from orchestwin.projects.persistence.briefs import (
    SqlAlchemyProjectBriefRepository,
)
from orchestwin.projects.persistence.repositories import (
    SqlAlchemyProjectRepository,
)


class SqlAlchemyProjectUnitOfWork:
    """One SQLAlchemy transaction for project use cases."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._projects: SqlAlchemyProjectRepository | None = None
        self._briefs: SqlAlchemyProjectBriefRepository | None = None

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

    async def __aenter__(
        self,
    ) -> SqlAlchemyProjectUnitOfWork:
        """Open a SQLAlchemy session and transaction."""
        self._session = self._session_factory()
        await self._session.begin()

        self._projects = SqlAlchemyProjectRepository(self._session)
        self._briefs = SqlAlchemyProjectBriefRepository(self._session)

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
            self._projects = None
            self._briefs = None


class SqlAlchemyProjectUnitOfWorkFactory:
    """Create a fresh project unit of work per use case."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    def __call__(
        self,
    ) -> SqlAlchemyProjectUnitOfWork:
        """Return one unopened unit of work."""
        return SqlAlchemyProjectUnitOfWork(self._session_factory)
