from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.artifacts.human_validation import (
    HypothesisVersion,
    ValidationOutcome,
    hypothesis_from_snapshot,
    outcome_from_snapshot,
    validate_session_source,
)
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.projects.persistence.research_evidence import VERSIONS
from orchestwin.validation import ValidationError

HYPOTHESES = sa.table(
    "project_validation_hypotheses",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("version_number", sa.Integer()),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("code", sa.String(12)),
    sa.column("content_hash", sa.String(64)),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("snapshot", postgresql.JSONB()),
)
OUTCOMES = sa.table(
    "project_validation_outcomes",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("code", sa.String(12)),
    sa.column("hypothesis_id", postgresql.UUID(as_uuid=True)),
    sa.column("hypothesis_version_number", sa.Integer()),
    sa.column("hypothesis_content_hash", sa.String(64)),
    sa.column("evidence_id", postgresql.UUID(as_uuid=True)),
    sa.column("evidence_version", sa.Integer()),
    sa.column("content_hash", sa.String(64)),
    sa.column("recorded_at", sa.DateTime(timezone=True)),
    sa.column("snapshot", postgresql.JSONB()),
)


class SqlAlchemyHumanValidationRepository:
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

    async def records(self, *, project_id: UUID) -> dict:
        if not await self.owned(project_id):
            return {"hypotheses": [], "outcomes": []}
        result = {}
        for key, table, restore, order in (
            (
                "hypotheses",
                HYPOTHESES,
                hypothesis_from_snapshot,
                (HYPOTHESES.c.code, HYPOTHESES.c.version_number),
            ),
            ("outcomes", OUTCOMES, outcome_from_snapshot, (OUTCOMES.c.code, OUTCOMES.c.id)),
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
            result[key] = [restore(row).to_snapshot() for row in rows]
        return result

    async def hypothesis(
        self, *, project_id: UUID, hypothesis_id: UUID
    ) -> HypothesisVersion | None:
        row = await self.session.scalar(
            sa.select(HYPOTHESES.c.snapshot)
            .where(
                HYPOTHESES.c.project_id == project_id,
                HYPOTHESES.c.owner_user_id == self.owner_user_id,
                HYPOTHESES.c.id == hypothesis_id,
            )
            .order_by(HYPOTHESES.c.version_number.desc())
            .limit(1)
        )
        return None if row is None else hypothesis_from_snapshot(row)

    async def next_code(self, *, project_id: UUID, outcome: bool = False) -> str:
        table = OUTCOMES if outcome else HYPOTHESES
        rows = (
            await self.session.scalars(
                sa.select(table.c.code).where(
                    table.c.project_id == project_id, table.c.owner_user_id == self.owner_user_id
                )
            )
        ).all()
        number = max((int(value.split("-")[1]) for value in rows), default=0) + 1
        if number > 999999:
            raise ValidationError("VALIDATION_INPUT_INVALID")
        return f"{'HVO' if outcome else 'HYP'}-{number:03}"

    def _scope(self, payload):
        if payload["owner_user_id"] != str(self.owner_user_id):
            raise ValidationError("PROJECT_NOT_FOUND")

    async def append_hypothesis(self, record: HypothesisVersion) -> None:
        payload = record.to_snapshot()
        self._scope(payload)
        if not await self.owned(UUID(payload["project_id"])):
            raise ValidationError("PROJECT_NOT_FOUND")
        await self.session.execute(
            sa.insert(HYPOTHESES).values(
                id=record.id,
                version_number=record.version_number,
                project_id=UUID(payload["project_id"]),
                owner_user_id=self.owner_user_id,
                code=payload["code"],
                content_hash=record.content_hash,
                created_at=datetime.fromisoformat(payload["created_at"]),
                snapshot=payload,
            )
        )

    async def append_outcome(self, record: ValidationOutcome) -> None:
        payload = record.to_snapshot()
        self._scope(payload)
        project_id = UUID(payload["project_id"])
        if not await self.owned(project_id):
            raise ValidationError("PROJECT_NOT_FOUND")
        hypothesis = await self.session.scalar(
            sa.select(HYPOTHESES.c.id).where(
                HYPOTHESES.c.id == UUID(payload["hypothesis_id"]),
                HYPOTHESES.c.version_number == payload["hypothesis_version_number"],
                HYPOTHESES.c.content_hash == payload["hypothesis_content_hash"],
                HYPOTHESES.c.project_id == project_id,
                HYPOTHESES.c.owner_user_id == self.owner_user_id,
            )
        )
        source = await self.session.scalar(
            sa.select(VERSIONS.c.metadata).where(
                VERSIONS.c.id == UUID(payload["evidence_id"]),
                VERSIONS.c.version == payload["evidence_version"],
                VERSIONS.c.project_id == project_id,
                VERSIONS.c.owner_user_id == self.owner_user_id,
                VERSIONS.c.metadata["content_hash"].astext == payload["evidence_content_hash"],
            )
        )
        if hypothesis is None or source is None:
            raise ValidationError("VALIDATION_CONTEXT_CHANGED")
        validate_session_source(payload["session_kind"], source)
        await self.session.execute(
            sa.insert(OUTCOMES).values(
                id=record.id,
                project_id=UUID(payload["project_id"]),
                owner_user_id=self.owner_user_id,
                code=payload["code"],
                hypothesis_id=UUID(payload["hypothesis_id"]),
                hypothesis_version_number=payload["hypothesis_version_number"],
                hypothesis_content_hash=payload["hypothesis_content_hash"],
                evidence_id=UUID(payload["evidence_id"]),
                evidence_version=payload["evidence_version"],
                content_hash=record.content_hash,
                recorded_at=datetime.fromisoformat(payload["recorded_at"]),
                snapshot=payload,
            )
        )

    async def import_records(self, *, project_id: UUID, records: Mapping) -> dict:
        if not await self.owned(project_id, lock=True):
            raise ValidationError("PROJECT_NOT_FOUND")
        for payload in records.get("hypotheses", ()):
            if payload.get("project_id") != str(project_id):
                raise ValidationError("VALIDATION_CONTEXT_CHANGED")
            await self.append_hypothesis(hypothesis_from_snapshot(payload))
        for payload in records.get("outcomes", ()):
            if payload.get("project_id") != str(project_id):
                raise ValidationError("VALIDATION_CONTEXT_CHANGED")
            await self.append_outcome(outcome_from_snapshot(payload))
        await self.session.flush()
        return await self.records(project_id=project_id)


__all__ = ["HYPOTHESES", "OUTCOMES", "SqlAlchemyHumanValidationRepository"]
