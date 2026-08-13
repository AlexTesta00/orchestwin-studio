"""Transactional Unit of Work for User Modeling persistence."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from orchestwin.twins.persistence.repositories import (
    PersonaVersionRepository,
    SqlAlchemyPersonaVersionRepository,
    SqlAlchemyUserModelingSnapshotRepository,
    SqlAlchemyUserTwinVersionRepository,
    UserModelingSnapshotRepository,
    UserTwinVersionRepository,
)


class UserModelingUnitOfWork(Protocol):
    """Transactional boundary used by User Modeling application services."""

    personas: PersonaVersionRepository
    twins: UserTwinVersionRepository
    snapshots: UserModelingSnapshotRepository

    async def __aenter__(
        self,
    ) -> UserModelingUnitOfWork:
        """Enter the transactional boundary."""

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Leave the transactional boundary."""

    async def commit(
        self,
    ) -> None:
        """Commit all persistence changes."""

    async def rollback(
        self,
    ) -> None:
        """Rollback all persistence changes."""


class SqlAlchemyUserModelingUnitOfWork:
    """SQLAlchemy transaction coordinator for User Modeling."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        owner_user_id: UUID,
    ) -> None:
        """Create owner-scoped repositories over one shared session."""
        self._session = session
        self._completed = False

        self.personas = SqlAlchemyPersonaVersionRepository(
            session,
            owner_user_id=(owner_user_id),
        )
        self.twins = SqlAlchemyUserTwinVersionRepository(
            session,
            owner_user_id=(owner_user_id),
        )
        self.snapshots = SqlAlchemyUserModelingSnapshotRepository(
            session,
            owner_user_id=(owner_user_id),
        )

    async def __aenter__(
        self,
    ) -> SqlAlchemyUserModelingUnitOfWork:
        """Return this transactional boundary."""
        self._completed = False

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Rollback any transaction that was not explicitly committed."""
        del exc_type
        del exc_value
        del traceback

        if not self._completed:
            await self.rollback()

    async def commit(
        self,
    ) -> None:
        """Commit the shared SQLAlchemy transaction."""
        await self._session.commit()
        self._completed = True

    async def rollback(
        self,
    ) -> None:
        """Rollback the shared SQLAlchemy transaction."""
        await self._session.rollback()
        self._completed = True
