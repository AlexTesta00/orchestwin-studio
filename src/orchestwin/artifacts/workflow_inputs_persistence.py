from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.artifacts.provided_prototypes import provided_prototype_from_snapshot
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.workflow_inputs import WorkflowInputError, workflow_records


def _table(name, *, prototype=False):
    return sa.table(
        name,
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("project_id", postgresql.UUID(as_uuid=True)),
        sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
        *(
            [sa.column("version_number", sa.Integer()), sa.column("code", sa.String(12))]
            if prototype
            else [sa.column("sequence", sa.Integer())]
        ),
        sa.column("content_hash", sa.String(64)),
        sa.column("created_at" if prototype else "recorded_at", sa.DateTime(timezone=True)),
        sa.column("snapshot", postgresql.JSONB()),
    )


DECISIONS = _table("project_workflow_decisions")
PROTOTYPES = _table("project_provided_prototypes", prototype=True)


class SqlAlchemyWorkflowInputsRepository:
    def __init__(self, session: AsyncSession, *, owner_user_id: UUID) -> None:
        self.session = session
        self.owner_user_id = owner_user_id

    async def owned(self, project_id: UUID, *, lock=False) -> bool:
        query = sa.select(ProjectRecord.id).where(
            ProjectRecord.id == project_id,
            ProjectRecord.owner_user_id == self.owner_user_id,
            ProjectRecord.archived_at.is_(None),
        )
        if lock:
            query = query.with_for_update()
        return await self.session.scalar(query) is not None

    async def records(self, project_id: UUID) -> dict:
        if not await self.owned(project_id):
            raise WorkflowInputError("PROJECT_NOT_FOUND")
        values = []
        for table, order in (
            (DECISIONS, (DECISIONS.c.sequence,)),
            (PROTOTYPES, (PROTOTYPES.c.code, PROTOTYPES.c.version_number)),
        ):
            rows = (
                await self.session.scalars(
                    sa.select(table.c.snapshot)
                    .where(
                        table.c.project_id == project_id,
                        table.c.owner_user_id == self.owner_user_id,
                    )
                    .order_by(*order)
                )
            ).all()
            if table is PROTOTYPES:
                rows = [provided_prototype_from_snapshot(row).to_snapshot() for row in rows]
            values.append(rows)
        return workflow_records(project_id, *values)

    async def current(self, project_id: UUID):
        row = await self.session.scalar(
            sa.select(PROTOTYPES.c.snapshot)
            .where(
                PROTOTYPES.c.project_id == project_id,
                PROTOTYPES.c.owner_user_id == self.owner_user_id,
            )
            .order_by(PROTOTYPES.c.created_at.desc(), PROTOTYPES.c.version_number.desc())
            .limit(1)
        )
        return None if row is None else provided_prototype_from_snapshot(row)

    async def append_decision(self, payload: Mapping) -> None:
        project_id = UUID(payload["project_id"])
        workflow_records(project_id, [payload])
        if not await self.owned(project_id):
            raise WorkflowInputError("PROJECT_NOT_FOUND")
        await self.session.execute(
            sa.insert(DECISIONS).values(
                id=UUID(payload["id"]),
                project_id=project_id,
                owner_user_id=self.owner_user_id,
                sequence=payload["sequence"],
                content_hash=payload["content_hash"],
                recorded_at=datetime.fromisoformat(payload["recorded_at"]),
                snapshot=dict(payload),
            )
        )

    async def append_prototype(self, prototype) -> None:
        if not await self.owned(prototype.project_id):
            raise WorkflowInputError("PROJECT_NOT_FOUND")
        payload = prototype.to_snapshot()
        await self.session.execute(
            sa.insert(PROTOTYPES).values(
                id=prototype.id,
                version_number=prototype.version_number,
                project_id=prototype.project_id,
                owner_user_id=self.owner_user_id,
                code=prototype.code,
                content_hash=prototype.content_hash,
                created_at=prototype.created_at,
                snapshot=payload,
            )
        )

    async def import_records(self, *, project_id: UUID, records: Mapping) -> dict:
        if not await self.owned(project_id, lock=True):
            raise WorkflowInputError("PROJECT_NOT_FOUND")
        checked = workflow_records(project_id, records["decisions"], records["prototypes"])
        for record in checked["decisions"]:
            await self.append_decision(record)
        for record in checked["prototypes"]:
            await self.append_prototype(provided_prototype_from_snapshot(record))
        await self.session.flush()
        return await self.records(project_id)
