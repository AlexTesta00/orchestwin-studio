"""SQLAlchemy unit of work for identity use cases."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.identity.persistence.repositories import (
    SqlAlchemyRefreshSessionRepository,
    SqlAlchemyUserRepository,
)
from orchestwin.persistence.unit_of_work import SqlAlchemyUnitOfWork, SqlAlchemyUnitOfWorkFactory


class SqlAlchemyIdentityUnitOfWork(SqlAlchemyUnitOfWork):
    """One SQLAlchemy session and transaction per use case."""

    @property
    def users(self) -> SqlAlchemyUserRepository:
        """Return the user repository after entry."""
        if self._users is None:
            raise RuntimeError("identity unit of work is not open")

        return self._users

    @property
    def refresh_sessions(
        self,
    ) -> SqlAlchemyRefreshSessionRepository:
        """Return the session repository after entry."""
        if self._refresh_sessions is None:
            raise RuntimeError("identity unit of work is not open")

        return self._refresh_sessions

    def _bind(self, session: AsyncSession) -> None:
        self._users = SqlAlchemyUserRepository(session)
        self._refresh_sessions = SqlAlchemyRefreshSessionRepository(session)

    def _release(self) -> None:
        self._users = None
        self._refresh_sessions = None


class SqlAlchemyIdentityUnitOfWorkFactory(SqlAlchemyUnitOfWorkFactory):
    """Create a fresh identity unit of work per call."""

    unit_of_work = SqlAlchemyIdentityUnitOfWork
