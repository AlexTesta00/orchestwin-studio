from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.artifacts.design_critique import (
    DesignCritiqueRun,
    DesignCritiqueShot,
    DesignCritiqueSource,
    DesignCritiqueSourceKind,
    design_critique_run_from_snapshot,
    page_from_document,
    shot_content,
)
from orchestwin.projects.persistence.models import ProjectRecord

SOURCES = sa.table(
    "design_critique_sources",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("kind", sa.String(length=16)),
    sa.column("title", sa.String(length=200)),
    sa.column("url", sa.Text()),
    sa.column("page_snapshot", postgresql.JSONB(none_as_null=True)),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("content_hash", sa.String(length=64)),
)

SHOTS = sa.table(
    "design_critique_shots",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("source_id", postgresql.UUID(as_uuid=True)),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("code", sa.String(length=8)),
    sa.column("media_type", sa.String(length=16)),
    sa.column("byte_size", sa.Integer()),
    sa.column("sha256", sa.String(length=64)),
    sa.column("width", sa.Integer()),
    sa.column("height", sa.Integer()),
    sa.column("viewport_width", sa.Integer()),
    sa.column("content", sa.LargeBinary()),
)

RUNS = sa.table(
    "design_critique_runs",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("source_id", postgresql.UUID(as_uuid=True)),
    sa.column("evaluator_id", sa.String(length=256)),
    sa.column("evaluator_version", sa.String(length=256)),
    sa.column("model_config_ref", sa.String(length=256)),
    sa.column("prompt_version_ref", sa.String(length=256)),
    sa.column("response_count", sa.Integer()),
    sa.column("finding_count", sa.Integer()),
    sa.column("started_at", sa.DateTime(timezone=True)),
    sa.column("completed_at", sa.DateTime(timezone=True)),
    sa.column("content_hash", sa.String(length=64)),
    sa.column("run_snapshot", postgresql.JSONB()),
)

_SHOT_COLUMNS = (
    SHOTS.c.source_id,
    SHOTS.c.code,
    SHOTS.c.media_type,
    SHOTS.c.byte_size,
    SHOTS.c.sha256,
    SHOTS.c.width,
    SHOTS.c.height,
    SHOTS.c.viewport_width,
)


class DesignCritiqueWriteStatus(StrEnum):
    WRITTEN = "WRITTEN"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    EXISTS = "EXISTS"


def _source(row, shots: Sequence) -> DesignCritiqueSource:
    return DesignCritiqueSource(
        id=row.id,
        project_id=row.project_id,
        owner_user_id=row.owner_user_id,
        kind=DesignCritiqueSourceKind(row.kind),
        title=row.title,
        url=row.url,
        page=None if row.page_snapshot is None else page_from_document(row.page_snapshot),
        shots=tuple(
            DesignCritiqueShot(
                code=shot.code,
                media_type=shot.media_type,
                byte_size=shot.byte_size,
                sha256=shot.sha256,
                width=shot.width,
                height=shot.height,
                viewport_width=shot.viewport_width,
            )
            for shot in shots
        ),
        created_at=row.created_at,
        content_hash=row.content_hash,
    )


class SqlAlchemyDesignCritiqueRepository:
    def __init__(self, session: AsyncSession, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id

    async def _owns(self, project_id: UUID) -> bool:
        statement = sa.select(ProjectRecord.id).where(
            ProjectRecord.id == project_id,
            ProjectRecord.owner_user_id == self._owner_user_id,
            ProjectRecord.archived_at.is_(None),
        )
        return (await self._session.execute(statement)).scalar_one_or_none() is not None

    async def create_source(
        self, source: DesignCritiqueSource, contents: Mapping[str, bytes]
    ) -> DesignCritiqueWriteStatus:
        if source.owner_user_id != self._owner_user_id or not await self._owns(source.project_id):
            return DesignCritiqueWriteStatus.PROJECT_NOT_FOUND
        existing = await self._session.execute(
            sa.select(SOURCES.c.id).where(SOURCES.c.id == source.id)
        )
        if existing.scalar_one_or_none() is not None:
            return DesignCritiqueWriteStatus.EXISTS
        rows = [
            {
                "id": uuid4(),
                "source_id": source.id,
                "project_id": source.project_id,
                "owner_user_id": source.owner_user_id,
                "code": shot.code,
                "media_type": shot.media_type,
                "byte_size": shot.byte_size,
                "sha256": shot.sha256,
                "width": shot.width,
                "height": shot.height,
                "viewport_width": shot.viewport_width,
                "content": shot_content(shot, contents),
            }
            for shot in source.shots
        ]
        await self._session.execute(
            sa.insert(SOURCES).values(
                id=source.id,
                project_id=source.project_id,
                owner_user_id=source.owner_user_id,
                kind=source.kind.value,
                title=source.title,
                url=source.url,
                page_snapshot=None if source.page is None else source.page.to_snapshot(),
                created_at=source.created_at,
                content_hash=source.content_hash,
            )
        )
        await self._session.execute(sa.insert(SHOTS), rows)
        return DesignCritiqueWriteStatus.WRITTEN

    def _sources(self):
        return sa.select(SOURCES).where(SOURCES.c.owner_user_id == self._owner_user_id)

    async def _shots(self, source_ids: Sequence[UUID]) -> dict[UUID, list]:
        if not source_ids:
            return {}
        statement = (
            sa.select(*_SHOT_COLUMNS)
            .where(
                SHOTS.c.owner_user_id == self._owner_user_id,
                SHOTS.c.source_id.in_(source_ids),
            )
            .order_by(SHOTS.c.source_id, SHOTS.c.code)
        )
        grouped: dict[UUID, list] = {}
        for row in (await self._session.execute(statement)).all():
            grouped.setdefault(row.source_id, []).append(row)
        return grouped

    async def source(self, project_id: UUID, source_id: UUID) -> DesignCritiqueSource | None:
        statement = self._sources().where(
            SOURCES.c.project_id == project_id, SOURCES.c.id == source_id
        )
        row = (await self._session.execute(statement)).one_or_none()
        if row is None:
            return None
        shots = await self._shots((row.id,))
        return _source(row, shots.get(row.id, ()))

    async def sources(self, project_id: UUID, limit: int = 50) -> tuple[DesignCritiqueSource, ...]:
        statement = (
            self._sources()
            .where(SOURCES.c.project_id == project_id)
            .order_by(SOURCES.c.created_at.desc(), SOURCES.c.id.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).all()
        shots = await self._shots(tuple(row.id for row in rows))
        return tuple(_source(row, shots.get(row.id, ())) for row in rows)

    async def shot(self, project_id: UUID, source_id: UUID, code: str) -> tuple[str, bytes] | None:
        statement = sa.select(SHOTS.c.media_type, SHOTS.c.content).where(
            SHOTS.c.owner_user_id == self._owner_user_id,
            SHOTS.c.project_id == project_id,
            SHOTS.c.source_id == source_id,
            SHOTS.c.code == code,
        )
        row = (await self._session.execute(statement)).one_or_none()
        return None if row is None else (row.media_type, bytes(row.content))

    async def create_run(self, run: DesignCritiqueRun) -> DesignCritiqueWriteStatus:
        if run.owner_user_id != self._owner_user_id or not await self._owns(run.project_id):
            return DesignCritiqueWriteStatus.PROJECT_NOT_FOUND
        stored = await self._session.execute(
            sa.select(SOURCES.c.content_hash).where(
                SOURCES.c.id == run.source.id,
                SOURCES.c.project_id == run.project_id,
                SOURCES.c.owner_user_id == self._owner_user_id,
            )
        )
        if stored.scalar_one_or_none() != run.source.content_hash:
            return DesignCritiqueWriteStatus.SOURCE_NOT_FOUND
        existing = await self._session.execute(sa.select(RUNS.c.id).where(RUNS.c.id == run.id))
        if existing.scalar_one_or_none() is not None:
            return DesignCritiqueWriteStatus.EXISTS
        evaluator = run.evaluator
        await self._session.execute(
            sa.insert(RUNS).values(
                id=run.id,
                project_id=run.project_id,
                owner_user_id=run.owner_user_id,
                source_id=run.source.id,
                evaluator_id=evaluator.evaluator_id,
                evaluator_version=evaluator.evaluator_version,
                model_config_ref=evaluator.model_config_ref,
                prompt_version_ref=evaluator.prompt_version_ref,
                response_count=len(run.responses),
                finding_count=len(run.findings),
                started_at=run.started_at,
                completed_at=run.completed_at,
                content_hash=run.content_hash,
                run_snapshot=run.to_snapshot(),
            )
        )
        return DesignCritiqueWriteStatus.WRITTEN

    def _runs(self):
        return sa.select(RUNS.c.run_snapshot).where(RUNS.c.owner_user_id == self._owner_user_id)

    async def runs(self, project_id: UUID, limit: int = 50) -> tuple[DesignCritiqueRun, ...]:
        statement = (
            self._runs()
            .where(RUNS.c.project_id == project_id)
            .order_by(RUNS.c.started_at.desc(), RUNS.c.id.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).scalars().all()
        return tuple(design_critique_run_from_snapshot(row) for row in rows)

    async def run(self, project_id: UUID, run_id: UUID) -> DesignCritiqueRun | None:
        statement = self._runs().where(RUNS.c.project_id == project_id, RUNS.c.id == run_id)
        row = (await self._session.execute(statement)).scalar_one_or_none()
        return None if row is None else design_critique_run_from_snapshot(row)


__all__ = [
    "RUNS",
    "SHOTS",
    "SOURCES",
    "DesignCritiqueWriteStatus",
    "SqlAlchemyDesignCritiqueRepository",
]
