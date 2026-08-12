"""SQLAlchemy unit of work for versioned team proposals."""

from __future__ import annotations

from types import TracebackType

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from orchestwin.agents.persistence.repositories import (
    SqlAlchemyTeamProposalVersionRepository,
    SqlAlchemyTeamSelectionContextRepository,
)


class SqlAlchemyTeamProposalUnitOfWork:
    """One SQLAlchemy transaction for team-proposal use cases."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._contexts: SqlAlchemyTeamSelectionContextRepository | None = None
        self._proposals: SqlAlchemyTeamProposalVersionRepository | None = None

    @property
    def contexts(
        self,
    ) -> SqlAlchemyTeamSelectionContextRepository:
        """Return the context repository after entry."""
        if self._contexts is None:
            raise RuntimeError("team-proposal unit of work is not open")

        return self._contexts

    @property
    def proposals(
        self,
    ) -> SqlAlchemyTeamProposalVersionRepository:
        """Return the proposal repository after entry."""
        if self._proposals is None:
            raise RuntimeError("team-proposal unit of work is not open")

        return self._proposals

    async def __aenter__(
        self,
    ) -> SqlAlchemyTeamProposalUnitOfWork:
        """Open a SQLAlchemy session and transaction."""
        self._session = self._session_factory()
        await self._session.begin()

        self._contexts = SqlAlchemyTeamSelectionContextRepository(self._session)
        self._proposals = SqlAlchemyTeamProposalVersionRepository(self._session)

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
            self._contexts = None
            self._proposals = None


class SqlAlchemyTeamProposalUnitOfWorkFactory:
    """Create a fresh proposal unit of work per use case."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    def __call__(
        self,
    ) -> SqlAlchemyTeamProposalUnitOfWork:
        """Return one unopened proposal unit of work."""
        return SqlAlchemyTeamProposalUnitOfWork(self._session_factory)
