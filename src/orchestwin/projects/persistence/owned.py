from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.projects.persistence.models import ProjectRecord


def owned_project_query(project_id: UUID, owner_user_id: UUID) -> sa.Select:
    return sa.select(ProjectRecord.id).where(
        ProjectRecord.id == project_id,
        ProjectRecord.owner_user_id == owner_user_id,
        ProjectRecord.archived_at.is_(None),
    )


class OwnedProjectRepository:
    def __init__(self, session: AsyncSession, *, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id

    async def project_exists(self, project_id: UUID) -> bool:
        return (
            await self._session.execute(owned_project_query(project_id, self._owner_user_id))
        ).scalar_one_or_none() is not None

    async def _lock_project(self, project_id: UUID) -> bool:
        statement = owned_project_query(project_id, self._owner_user_id).with_for_update()
        return (await self._session.execute(statement)).scalar_one_or_none() is not None
