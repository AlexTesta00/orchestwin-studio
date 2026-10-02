"""Transactional Unit of Work for User Modeling persistence."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.models.proposal_evidence_persistence import SqlAlchemyProposalEvidenceBindings
from orchestwin.projects.persistence.repositories import owned_project_statement
from orchestwin.projects.persistence.twin_learning import UPDATES
from orchestwin.twins.persistence.repositories import (
    PersonaVersionRepository,
    SqlAlchemyPersonaVersionRepository,
    SqlAlchemyUserModelingSnapshotRepository,
    SqlAlchemyUserTwinVersionRepository,
    UserModelingSnapshotRepository,
    UserTwinVersionRepository,
)
from orchestwin.twins.revision_persistence import (
    DIFFS,
    SqlAlchemyUserTwinProfileDiffRepository,
    UserTwinProfileDiffRepository,
)
from orchestwin.twins.revisions import UserTwinProfileDiffStatus


class UserModelingUnitOfWork(Protocol):
    """Transactional boundary used by User Modeling application services."""

    personas: PersonaVersionRepository
    twins: UserTwinVersionRepository
    snapshots: UserModelingSnapshotRepository
    diffs: UserTwinProfileDiffRepository

    async def lock_project(self, *, project_id: UUID) -> bool: ...

    async def has_pending_revision(self, *, project_id: UUID) -> bool: ...

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

    async def commit(self) -> None:
        """Commit all persistence changes."""

    async def rollback(self) -> None:
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
        self._owner_user_id = owner_user_id
        self.proposal_evidence = SqlAlchemyProposalEvidenceBindings(session)
        self._completed = False

        self.personas = SqlAlchemyPersonaVersionRepository(
            session,
            owner_user_id=owner_user_id,
        )
        self.twins = SqlAlchemyUserTwinVersionRepository(
            session,
            owner_user_id=owner_user_id,
        )
        self.snapshots = SqlAlchemyUserModelingSnapshotRepository(
            session,
            owner_user_id=owner_user_id,
        )
        self.diffs = SqlAlchemyUserTwinProfileDiffRepository(
            session,
            owner_user_id=owner_user_id,
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

    async def commit(self) -> None:
        """Commit the shared SQLAlchemy transaction."""
        await self._session.commit()
        self._completed = True

    async def lock_project(self, *, project_id: UUID) -> bool:
        return (
            await self._session.scalar(
                owned_project_statement(
                    project_id=project_id, owner_user_id=self._owner_user_id
                ).with_for_update()
            )
            is not None
        )

    async def has_pending_revision(self, *, project_id: UUID) -> bool:
        return await self.has_pending_manual_revision(
            project_id=project_id
        ) or await self.has_pending_evidence_update(project_id=project_id)

    async def has_pending_evidence_update(self, *, project_id: UUID) -> bool:
        return (
            await self._session.scalar(
                sa.select(UPDATES.c.id)
                .where(
                    UPDATES.c.project_id == project_id,
                    UPDATES.c.owner_user_id == self._owner_user_id,
                    UPDATES.c.status == "PROPOSED",
                    UPDATES.c.evidence.is_not(None),
                )
                .limit(1)
            )
        ) is not None

    async def has_pending_manual_revision(self, *, project_id: UUID) -> bool:
        return (
            await self._session.scalar(
                sa.select(DIFFS.c.id)
                .where(
                    DIFFS.c.project_id == project_id,
                    DIFFS.c.status == UserTwinProfileDiffStatus.PROPOSED.value,
                    owned_project_statement(
                        project_id=project_id, owner_user_id=self._owner_user_id
                    ).exists(),
                )
                .limit(1)
            )
            is not None
        )

    async def rollback(self) -> None:
        """Rollback the shared SQLAlchemy transaction."""
        await self._session.rollback()
        self._completed = True
