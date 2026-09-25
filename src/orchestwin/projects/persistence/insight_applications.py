from __future__ import annotations

from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.projects.insight_applications import (
    InsightApplication,
    insight_application_from_snapshot,
)
from orchestwin.projects.persistence.models import ProjectRecord

APPLICATIONS = sa.table(
    "insight_applications",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("source_kind", sa.String(length=32)),
    sa.column("source_id", sa.String(length=200)),
    sa.column("source_twin_id", postgresql.UUID(as_uuid=True)),
    sa.column("text", sa.Text()),
    sa.column("target", sa.String(length=16)),
    sa.column("target_field", sa.String(length=48)),
    sa.column("target_version_id", postgresql.UUID(as_uuid=True)),
    sa.column("target_version_number", sa.Integer()),
    sa.column("target_code", sa.String(length=16)),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("content_hash", sa.String(length=64)),
)


class InsightApplicationWriteStatus(StrEnum):
    WRITTEN = "WRITTEN"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"


def _row(application: InsightApplication) -> dict[str, object]:
    return {
        "id": application.id,
        "project_id": application.project_id,
        "owner_user_id": application.owner_user_id,
        "source_kind": application.source_kind.value,
        "source_id": application.source_id,
        "source_twin_id": application.source_twin_id,
        "text": application.text,
        "target": application.target.value,
        "target_field": None
        if application.target_field is None
        else application.target_field.value,
        "target_version_id": application.target_version_id,
        "target_version_number": application.target_version_number,
        "target_code": application.target_code,
        "created_at": application.created_at,
        "content_hash": application.content_hash,
    }


def _snapshot(row) -> dict[str, object]:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "owner_user_id": str(row.owner_user_id),
        "source_kind": row.source_kind,
        "source_id": row.source_id,
        "source_twin_id": None if row.source_twin_id is None else str(row.source_twin_id),
        "text": row.text,
        "target": row.target,
        "target_field": row.target_field,
        "target_version_id": str(row.target_version_id),
        "target_version_number": row.target_version_number,
        "target_code": row.target_code,
        "created_at": row.created_at.isoformat(),
        "content_hash": row.content_hash,
    }


class SqlAlchemyInsightApplicationRepository:
    def __init__(self, session: AsyncSession, *, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id

    async def create(self, application: InsightApplication) -> InsightApplicationWriteStatus:
        owned = sa.select(ProjectRecord.id).where(
            ProjectRecord.id == application.project_id,
            ProjectRecord.owner_user_id == self._owner_user_id,
            ProjectRecord.archived_at.is_(None),
        )
        if (
            application.owner_user_id != self._owner_user_id
            or (await self._session.execute(owned)).scalar_one_or_none() is None
        ):
            return InsightApplicationWriteStatus.PROJECT_NOT_FOUND
        await self._session.execute(sa.insert(APPLICATIONS).values(**_row(application)))
        return InsightApplicationWriteStatus.WRITTEN

    async def list(self, *, project_id: UUID, limit: int = 200) -> tuple[InsightApplication, ...]:
        statement = (
            sa.select(APPLICATIONS)
            .where(
                APPLICATIONS.c.project_id == project_id,
                APPLICATIONS.c.owner_user_id == self._owner_user_id,
            )
            .order_by(APPLICATIONS.c.created_at.desc(), APPLICATIONS.c.id.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).all()
        return tuple(insight_application_from_snapshot(_snapshot(row)) for row in rows)


__all__ = [
    "APPLICATIONS",
    "InsightApplicationWriteStatus",
    "SqlAlchemyInsightApplicationRepository",
]
