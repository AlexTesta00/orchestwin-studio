"""SQLAlchemy unit of work for Project Brief clarification."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.persistence.unit_of_work import SqlAlchemyUnitOfWork, SqlAlchemyUnitOfWorkFactory
from orchestwin.projects.persistence.brief_gate import (
    SqlAlchemyCurrentProjectBriefRepository,
)
from orchestwin.projects.persistence.briefs import (
    SqlAlchemyProjectBriefRepository,
)
from orchestwin.projects.persistence.clarification import (
    SqlAlchemyBriefAssumptionRepository,
)


class SqlAlchemyProjectClarificationUnitOfWork(SqlAlchemyUnitOfWork):
    """One SQLAlchemy transaction for clarification use cases."""

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
    def assumptions(
        self,
    ) -> SqlAlchemyBriefAssumptionRepository:
        """Return the brief-assumption repository after entry."""
        if self._assumptions is None:
            raise RuntimeError("Project clarification unit of work is not open")

        return self._assumptions

    def _bind(self, session: AsyncSession) -> None:
        self._current_briefs = SqlAlchemyCurrentProjectBriefRepository(session)
        self._briefs = SqlAlchemyProjectBriefRepository(session)
        self._assumptions = SqlAlchemyBriefAssumptionRepository(session)

    def _release(self) -> None:
        self._current_briefs = None
        self._briefs = None
        self._assumptions = None


class SqlAlchemyProjectClarificationUnitOfWorkFactory(SqlAlchemyUnitOfWorkFactory):
    """Create a fresh clarification unit of work per use case."""

    unit_of_work = SqlAlchemyProjectClarificationUnitOfWork
