"""SQLAlchemy unit of work for identity use cases."""

from __future__ import annotations

from types import TracebackType

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from orchestwin.identity.persistence.repositories import (
    SqlAlchemyRefreshSessionRepository,
    SqlAlchemyUserRepository,
)


class SqlAlchemyIdentityUnitOfWork:
    """One SQLAlchemy session and transaction per use case."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._users: SqlAlchemyUserRepository | None = None
        self._refresh_sessions: SqlAlchemyRefreshSessionRepository | None = None

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

    async def __aenter__(
        self,
    ) -> SqlAlchemyIdentityUnitOfWork:
        """Open a SQLAlchemy session and transaction."""
        self._session = self._session_factory()
        await self._session.begin()

        self._users = SqlAlchemyUserRepository(self._session)
        self._refresh_sessions = SqlAlchemyRefreshSessionRepository(self._session)

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
            self._users = None
            self._refresh_sessions = None


class SqlAlchemyIdentityUnitOfWorkFactory:
    """Create a fresh identity unit of work per call."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    def __call__(
        self,
    ) -> SqlAlchemyIdentityUnitOfWork:
        """Return one unopened unit of work."""
        return SqlAlchemyIdentityUnitOfWork(self._session_factory)
