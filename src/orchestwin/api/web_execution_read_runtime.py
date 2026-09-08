"""Read persisted Web execution attempts without configuring an executor.

Empty history is not successful execution. Hydration uses the existing hash
and projection validators; raw JSON rows are never returned as trusted evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast
from uuid import UUID

from fastapi import HTTPException
from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _schema():
    # Use the authoritative tables, not a parallel schema or metadata registry.
    from orchestwin.projects.persistence.models import ProjectRecord
    from orchestwin.web_execution.attempt_persistence import WEB_EXECUTION_ATTEMPTS

    return WEB_EXECUTION_ATTEMPTS, ProjectRecord.__table__


def _decode_attempt(row: Mapping[str, object]):
    from orchestwin.web_execution.attempt_persistence import web_execution_attempt_from_record

    return web_execution_attempt_from_record(row)


def _owned_attempts(owner_user_id: UUID):
    attempts, projects = _schema()
    return (
        select(attempts)
        .join(projects, projects.c.id == attempts.c.project_id)
        .where(
            projects.c.owner_user_id == owner_user_id,
            projects.c.archived_at.is_(None),
            attempts.c.created_by_user_id == owner_user_id,
        )
    )


def _snapshot(row: Mapping[str, object]) -> dict[str, JsonValue]:
    try:
        return cast(dict[str, JsonValue], _decode_attempt(row).to_snapshot())
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=409, detail={"code": "WEB_EXECUTION_EVIDENCE_INTEGRITY_FAILED"}
        ) from None


class SqlAlchemyWebExecutionReadApiService:
    """Owner-scoped SELECT-only adapter for history, attempts and normalized reports."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def execution_history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]:
        attempts, _ = _schema()
        async with self._session_factory() as session:
            result = await session.execute(
                _owned_attempts(owner_user_id)
                .where(attempts.c.project_id == project_id)
                .order_by(attempts.c.attempt_number.asc())
            )
            return tuple(_snapshot(row) for row in result.mappings().all())

    async def execution(
        self,
        *,
        owner_user_id: UUID,
        execution_id: UUID,
    ) -> dict[str, JsonValue] | None:
        attempts, _ = _schema()
        async with self._session_factory() as session:
            result = await session.execute(
                _owned_attempts(owner_user_id).where(attempts.c.id == execution_id)
            )
            row = result.mappings().one_or_none()
            return None if row is None else _snapshot(row)

    async def execution_report(
        self,
        *,
        owner_user_id: UUID,
        execution_id: UUID,
    ) -> dict[str, JsonValue] | None:
        snapshot = await self.execution(owner_user_id=owner_user_id, execution_id=execution_id)
        if snapshot is None:
            return None
        return cast(dict[str, JsonValue], snapshot["report"])
