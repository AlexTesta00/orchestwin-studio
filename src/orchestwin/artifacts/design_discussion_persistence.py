from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.artifacts.design_discussion import (
    MAX_DISCUSSION_ROUNDS,
    DesignDiscussion,
    DiscussionRound,
    DiscussionStatus,
    design_discussion_from_snapshot,
)
from orchestwin.projects.persistence.models import ProjectRecord

OPEN_DISCUSSION_INDEX: Final = "uq_design_discussions_open_version"

DISCUSSIONS = sa.table(
    "design_discussions",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("design_version_id", postgresql.UUID(as_uuid=True)),
    sa.column("design_version_number", sa.Integer()),
    sa.column("design_content_hash", sa.String(length=64)),
    sa.column("alternative_id", postgresql.UUID(as_uuid=True)),
    sa.column("alternative_code", sa.String(length=16)),
    sa.column("locale", sa.String(length=20)),
    sa.column("status", sa.String(length=16)),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("decided_at", sa.DateTime(timezone=True)),
)

ROUNDS = sa.table(
    "design_discussion_rounds",
    sa.column("discussion_id", postgresql.UUID(as_uuid=True)),
    sa.column("ordinal", sa.Integer()),
    sa.column("owner_note", sa.Text()),
    sa.column("content_hash", sa.String(length=64)),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("round_snapshot", postgresql.JSONB()),
)


class DiscussionWriteStatus(StrEnum):
    WRITTEN = "WRITTEN"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    DISCUSSION_NOT_FOUND = "DISCUSSION_NOT_FOUND"
    DISCUSSION_OPEN = "DISCUSSION_OPEN"
    DISCUSSION_CLOSED = "DISCUSSION_CLOSED"
    DISCUSSION_CHANGED = "DISCUSSION_CHANGED"
    DISCUSSION_FULL = "DISCUSSION_FULL"


def _round_row(discussion_id: UUID, round_: DiscussionRound) -> dict[str, object]:
    return {
        "discussion_id": discussion_id,
        "ordinal": round_.ordinal,
        "owner_note": round_.owner_note,
        "content_hash": round_.content_hash,
        "created_at": round_.created_at,
        "round_snapshot": round_.to_snapshot(),
    }


def _violated_constraint(error: sa.exc.IntegrityError) -> str | None:
    diagnostic = getattr(getattr(error, "orig", None), "diag", None)
    return getattr(diagnostic, "constraint_name", None)


def _timestamp(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


class SqlAlchemyDesignDiscussionRepository:
    def __init__(self, session: AsyncSession, *, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id

    async def _owns(self, project_id: UUID) -> bool:
        statement = sa.select(ProjectRecord.id).where(
            ProjectRecord.id == project_id,
            ProjectRecord.owner_user_id == self._owner_user_id,
            ProjectRecord.archived_at.is_(None),
        )
        return (await self._session.execute(statement)).scalar_one_or_none() is not None

    def _headers(self, project_id: UUID):
        return sa.select(DISCUSSIONS).where(
            DISCUSSIONS.c.project_id == project_id,
            DISCUSSIONS.c.owner_user_id == self._owner_user_id,
        )

    async def _open_discussion_id(self, project_id: UUID, design_version_id: UUID) -> UUID | None:
        statement = sa.select(DISCUSSIONS.c.id).where(
            DISCUSSIONS.c.project_id == project_id,
            DISCUSSIONS.c.design_version_id == design_version_id,
            DISCUSSIONS.c.status == DiscussionStatus.OPEN.value,
        )
        return (await self._session.execute(statement)).scalars().first()

    async def _locked(self, project_id: UUID, discussion_id: UUID):
        if not await self._owns(project_id):
            return None
        statement = (
            self._headers(project_id).where(DISCUSSIONS.c.id == discussion_id).with_for_update()
        )
        return (await self._session.execute(statement)).mappings().one_or_none()

    async def _assemble(self, headers) -> tuple[DesignDiscussion, ...]:
        if not headers:
            return ()
        rows = (
            (
                await self._session.execute(
                    sa.select(ROUNDS)
                    .where(ROUNDS.c.discussion_id.in_([header["id"] for header in headers]))
                    .order_by(ROUNDS.c.discussion_id, ROUNDS.c.ordinal)
                )
            )
            .mappings()
            .all()
        )
        rounds: dict[UUID, list[dict[str, object]]] = {}
        for row in rows:
            snapshot = row["round_snapshot"]
            if (
                snapshot.get("ordinal") != row["ordinal"]
                or snapshot.get("content_hash") != row["content_hash"]
                or snapshot.get("owner_note") != row["owner_note"]
            ):
                raise ValueError("stored discussion round does not match its columns")
            rounds.setdefault(row["discussion_id"], []).append(snapshot)
        return tuple(
            design_discussion_from_snapshot(
                {
                    "id": str(header["id"]),
                    "project_id": str(header["project_id"]),
                    "owner_user_id": str(header["owner_user_id"]),
                    "design_version_id": str(header["design_version_id"]),
                    "design_version_number": header["design_version_number"],
                    "design_content_hash": header["design_content_hash"],
                    "alternative_id": str(header["alternative_id"]),
                    "alternative_code": header["alternative_code"],
                    "status": header["status"],
                    "created_at": _timestamp(header["created_at"]),
                    "decided_at": _timestamp(header["decided_at"]),
                    "max_rounds": MAX_DISCUSSION_ROUNDS,
                    "rounds": rounds.get(header["id"], []),
                },
                locale=header["locale"],
            )
            for header in headers
        )

    async def create(self, discussion: DesignDiscussion) -> DiscussionWriteStatus:
        if discussion.status is not DiscussionStatus.OPEN or len(discussion.rounds) != 1:
            raise ValueError("a new discussion is open and holds its first round only")
        if discussion.owner_user_id != self._owner_user_id or not await self._owns(
            discussion.project_id
        ):
            return DiscussionWriteStatus.PROJECT_NOT_FOUND
        if (
            await self._open_discussion_id(discussion.project_id, discussion.design_version_id)
            is not None
        ):
            return DiscussionWriteStatus.DISCUSSION_OPEN
        try:
            async with self._session.begin_nested():
                await self._session.execute(
                    sa.insert(DISCUSSIONS).values(
                        id=discussion.id,
                        project_id=discussion.project_id,
                        owner_user_id=discussion.owner_user_id,
                        design_version_id=discussion.design_version_id,
                        design_version_number=discussion.design_version_number,
                        design_content_hash=discussion.design_content_hash,
                        alternative_id=discussion.alternative_id,
                        alternative_code=discussion.alternative_code,
                        locale=discussion.locale,
                        status=discussion.status.value,
                        created_at=discussion.created_at,
                        decided_at=discussion.decided_at,
                    )
                )
                await self._session.execute(
                    sa.insert(ROUNDS).values(**_round_row(discussion.id, discussion.rounds[0]))
                )
        except sa.exc.IntegrityError as error:
            if _violated_constraint(error) == OPEN_DISCUSSION_INDEX:
                return DiscussionWriteStatus.DISCUSSION_OPEN
            raise
        return DiscussionWriteStatus.WRITTEN

    async def append_round(
        self,
        *,
        project_id: UUID,
        discussion_id: UUID,
        round: DiscussionRound,
        expected_round_count: int,
    ) -> DiscussionWriteStatus:
        header = await self._locked(project_id, discussion_id)
        if header is None:
            return DiscussionWriteStatus.DISCUSSION_NOT_FOUND
        if header["status"] != DiscussionStatus.OPEN.value:
            return DiscussionWriteStatus.DISCUSSION_CLOSED
        [current] = await self._assemble((header,))
        recorded = len(current.rounds)
        if recorded != expected_round_count:
            return DiscussionWriteStatus.DISCUSSION_CHANGED
        if recorded >= MAX_DISCUSSION_ROUNDS:
            return DiscussionWriteStatus.DISCUSSION_FULL
        if round.ordinal != recorded + 1:
            return DiscussionWriteStatus.DISCUSSION_CHANGED
        extended = current.with_round(round)
        await self._session.execute(
            sa.insert(ROUNDS).values(**_round_row(discussion_id, extended.rounds[-1]))
        )
        return DiscussionWriteStatus.WRITTEN

    async def decide(
        self,
        *,
        project_id: UUID,
        discussion_id: UUID,
        status: DiscussionStatus,
        decided_at: datetime,
    ) -> DiscussionWriteStatus:
        header = await self._locked(project_id, discussion_id)
        if header is None:
            return DiscussionWriteStatus.DISCUSSION_NOT_FOUND
        if header["status"] != DiscussionStatus.OPEN.value:
            return DiscussionWriteStatus.DISCUSSION_CLOSED
        [current] = await self._assemble((header,))
        decided = current.decided(status, decided_at)
        await self._session.execute(
            sa.update(DISCUSSIONS)
            .where(DISCUSSIONS.c.id == discussion_id)
            .values(status=decided.status.value, decided_at=decided.decided_at)
        )
        return DiscussionWriteStatus.WRITTEN

    async def get(self, *, project_id: UUID, discussion_id: UUID) -> DesignDiscussion | None:
        statement = self._headers(project_id).where(DISCUSSIONS.c.id == discussion_id)
        header = (await self._session.execute(statement)).mappings().one_or_none()
        if header is None:
            return None
        [discussion] = await self._assemble((header,))
        return discussion

    async def list(self, *, project_id: UUID, limit: int = 50) -> tuple[DesignDiscussion, ...]:
        statement = (
            self._headers(project_id)
            .order_by(DISCUSSIONS.c.created_at.desc(), DISCUSSIONS.c.id.desc())
            .limit(limit)
        )
        headers = (await self._session.execute(statement)).mappings().all()
        return await self._assemble(tuple(headers))

    async def open_for_version(
        self, *, project_id: UUID, design_version_id: UUID
    ) -> DesignDiscussion | None:
        statement = self._headers(project_id).where(
            DISCUSSIONS.c.design_version_id == design_version_id,
            DISCUSSIONS.c.status == DiscussionStatus.OPEN.value,
        )
        header = (await self._session.execute(statement)).mappings().first()
        if header is None:
            return None
        [discussion] = await self._assemble((header,))
        return discussion


__all__ = [
    "DISCUSSIONS",
    "OPEN_DISCUSSION_INDEX",
    "ROUNDS",
    "DiscussionWriteStatus",
    "SqlAlchemyDesignDiscussionRepository",
]
