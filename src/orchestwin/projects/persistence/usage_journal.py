from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.activity import ActivityError
from orchestwin.projects.persistence.models import ProjectRecord

USAGE_EVENTS = sa.table(
    "project_usage_events",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("session_code", sa.String(24)),
    sa.column("sequence", sa.Integer()),
    sa.column("source", sa.String(8)),
    sa.column("kind", sa.String(32)),
    sa.column("section", sa.String(16)),
    sa.column("target", sa.String(80)),
    sa.column("client_at", sa.DateTime(timezone=True)),
    sa.column("received_at", sa.DateTime(timezone=True)),
    sa.column("duration_ms", sa.Integer()),
    sa.column("status", sa.String(64)),
)
_ROW = (
    "sequence",
    "session_code",
    "source",
    "kind",
    "section",
    "target",
    "client_at",
    "received_at",
    "duration_ms",
    "status",
)


def _iso(value):
    return None if value is None else value.astimezone(UTC).isoformat()


def _instant(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value


class SqlAlchemyUsageJournalRepository:
    def __init__(self, session: AsyncSession, *, owner_user_id: UUID) -> None:
        self.session = session
        self.owner_user_id = owner_user_id

    async def owned(self, project_id: UUID, *, lock: bool = False) -> bool:
        statement = sa.select(ProjectRecord.id).where(
            ProjectRecord.id == project_id,
            ProjectRecord.owner_user_id == self.owner_user_id,
            ProjectRecord.archived_at.is_(None),
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement) is not None

    def _scoped(self, statement, project_id):
        return statement.where(
            USAGE_EVENTS.c.project_id == project_id,
            USAGE_EVENTS.c.owner_user_id == self.owner_user_id,
        )

    async def rows(self, project_id: UUID) -> list[dict]:
        statement = self._scoped(sa.select(*(USAGE_EVENTS.c[name] for name in _ROW)), project_id)
        result = await self.session.execute(statement.order_by(USAGE_EVENTS.c.sequence))
        return [
            {**row, "client_at": _iso(row["client_at"]), "received_at": _iso(row["received_at"])}
            for row in result.mappings()
        ]

    async def count(self, project_id: UUID) -> int:
        return await self.session.scalar(
            self._scoped(sa.select(sa.func.count()).select_from(USAGE_EVENTS), project_id)
        )

    async def append(
        self, project_id: UUID, rows: Sequence[Mapping], *, received_at: datetime
    ) -> int:
        if not await self.owned(project_id, lock=True):
            raise ActivityError("PROJECT_NOT_FOUND")
        last = await self.session.scalar(
            sa.select(sa.func.max(USAGE_EVENTS.c.sequence)).where(
                USAGE_EVENTS.c.project_id == project_id
            )
        )
        values = [
            {
                "id": uuid4(),
                "project_id": project_id,
                "owner_user_id": self.owner_user_id,
                "session_code": row["session_code"],
                "sequence": (last or 0) + number,
                "source": row["source"],
                "kind": row["kind"],
                "section": row.get("section"),
                "target": row.get("target"),
                "client_at": _instant(row.get("client_at")),
                "received_at": received_at,
                "duration_ms": row.get("duration_ms"),
                "status": row.get("status"),
            }
            for number, row in enumerate(rows, start=1)
        ]
        if values:
            await self.session.execute(sa.insert(USAGE_EVENTS), values)
        return len(values)


__all__ = ["USAGE_EVENTS", "SqlAlchemyUsageJournalRepository"]
