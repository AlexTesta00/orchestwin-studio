"""SQLAlchemy unit of work for Project Brief clarification."""

from __future__ import annotations

from types import TracebackType

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from orchestwin.projects.persistence.brief_gate import (
    SqlAlchemyCurrentProjectBriefRepository,
)
from orchestwin.projects.persistence.briefs import (
    SqlAlchemyProjectBriefRepository,
)
from orchestwin.projects.persistence.clarification import (
    SqlAlchemyBriefAssumptionRepository,
    SqlAlchemyClarificationRoundRepository,
)


class SqlAlchemyProjectClarificationUnitOfWork:
    """One SQLAlchemy transaction for clarification use cases."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._current_briefs: SqlAlchemyCurrentProjectBriefRepository | None = None
        self._briefs: SqlAlchemyProjectBriefRepository | None = None
        self._rounds: SqlAlchemyClarificationRoundRepository | None = None
        self._assumptions: SqlAlchemyBriefAssumptionRepository | None = None

    @property
    def current_briefs(
        self,
    ) -> SqlAlchemyCurrentProjectBriefRepository:
        """Return the current-brief repository after entry."""
        if self._current_briefs is None:
            raise RuntimeError("Project clarification unit of work is not open")

        return self._current_briefs

    @property
    def briefs(
        self,
    ) -> SqlAlchemyProjectBriefRepository:
        """Return the immutable brief-version repository after entry."""
        if self._briefs is None:
            raise RuntimeError("Project clarification unit of work is not open")

        return self._briefs

    @property
    def rounds(
        self,
    ) -> SqlAlchemyClarificationRoundRepository:
        """Return the clarification-round repository after entry."""
        if self._rounds is None:
            raise RuntimeError("Project clarification unit of work is not open")

        return self._rounds

    @property
    def assumptions(
        self,
    ) -> SqlAlchemyBriefAssumptionRepository:
        """Return the brief-assumption repository after entry."""
        if self._assumptions is None:
            raise RuntimeError("Project clarification unit of work is not open")

        return self._assumptions

    async def __aenter__(
        self,
    ) -> SqlAlchemyProjectClarificationUnitOfWork:
        """Open a SQLAlchemy session and transaction."""
        self._session = self._session_factory()
        await self._session.begin()

        self._current_briefs = SqlAlchemyCurrentProjectBriefRepository(self._session)
        self._briefs = SqlAlchemyProjectBriefRepository(self._session)
        self._rounds = SqlAlchemyClarificationRoundRepository(self._session)
        self._assumptions = SqlAlchemyBriefAssumptionRepository(self._session)

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
            self._briefs = None
            self._rounds = None
            self._assumptions = None


class SqlAlchemyProjectClarificationUnitOfWorkFactory:
    """Create a fresh clarification unit of work per use case."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    def __call__(
        self,
    ) -> SqlAlchemyProjectClarificationUnitOfWork:
        """Return one unopened clarification unit of work."""
        return SqlAlchemyProjectClarificationUnitOfWork(self._session_factory)
