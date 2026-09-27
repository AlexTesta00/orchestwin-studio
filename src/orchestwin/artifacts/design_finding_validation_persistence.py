from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.artifacts.design_evaluation_persistence import FINDINGS, RUNS
from orchestwin.artifacts.design_finding_validations import (
    FindingDecision,
    FindingValidation,
    create_finding_validation,
    finding_validation_from_snapshot,
)
from orchestwin.projects.persistence.models import ProjectRecord

VALIDATIONS = sa.table(
    "design_finding_validations",
    sa.column("evaluation_run_id", postgresql.UUID(as_uuid=True)),
    sa.column("twin_id", postgresql.UUID(as_uuid=True)),
    sa.column("finding_id", sa.String(length=64)),
    sa.column("sequence_number", sa.Integer()),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("decision", sa.String(length=24)),
    sa.column("note", sa.Text()),
    sa.column("decided_at", sa.DateTime(timezone=True)),
    sa.column("content_hash", sa.String(length=64)),
    sa.column("validation_snapshot", postgresql.JSONB()),
)


class FindingValidationWriteStatus(StrEnum):
    WRITTEN = "WRITTEN"
    FINDING_NOT_FOUND = "FINDING_NOT_FOUND"


@dataclass(frozen=True, slots=True)
class FindingValidationWriteResult:
    status: FindingValidationWriteStatus
    validation: FindingValidation | None = None


class SqlAlchemyFindingValidationRepository:
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

    async def _lock_finding(
        self, *, project_id: UUID, evaluation_run_id: UUID, twin_id: UUID, finding_id: str
    ) -> bool:
        statement = (
            sa.select(FINDINGS.c.finding_id)
            .join(RUNS, RUNS.c.id == FINDINGS.c.evaluation_run_id)
            .where(
                FINDINGS.c.evaluation_run_id == evaluation_run_id,
                FINDINGS.c.twin_id == twin_id,
                FINDINGS.c.finding_id == finding_id,
                RUNS.c.project_id == project_id,
                RUNS.c.owner_user_id == self._owner_user_id,
            )
            .with_for_update(of=FINDINGS)
        )
        return (await self._session.execute(statement)).scalar_one_or_none() is not None

    async def append(
        self,
        *,
        project_id: UUID,
        evaluation_run_id: UUID,
        twin_id: UUID,
        finding_id: str,
        decision: FindingDecision,
        note: str | None,
        decided_at: datetime,
    ) -> FindingValidationWriteResult:
        if not await self._owns(project_id) or not await self._lock_finding(
            project_id=project_id,
            evaluation_run_id=evaluation_run_id,
            twin_id=twin_id,
            finding_id=finding_id,
        ):
            return FindingValidationWriteResult(FindingValidationWriteStatus.FINDING_NOT_FOUND)
        previous = sa.select(sa.func.max(VALIDATIONS.c.sequence_number)).where(
            VALIDATIONS.c.evaluation_run_id == evaluation_run_id,
            VALIDATIONS.c.twin_id == twin_id,
            VALIDATIONS.c.finding_id == finding_id,
        )
        latest = (await self._session.execute(previous)).scalar_one()
        validation = create_finding_validation(
            evaluation_run_id=evaluation_run_id,
            twin_id=twin_id,
            finding_id=finding_id,
            sequence_number=(latest or 0) + 1,
            project_id=project_id,
            owner_user_id=self._owner_user_id,
            decision=decision,
            note=note,
            decided_at=decided_at,
        )
        await self._session.execute(
            sa.insert(VALIDATIONS).values(
                evaluation_run_id=validation.evaluation_run_id,
                twin_id=validation.twin_id,
                finding_id=validation.finding_id,
                sequence_number=validation.sequence_number,
                project_id=validation.project_id,
                owner_user_id=validation.owner_user_id,
                decision=validation.decision.value,
                note=validation.note,
                decided_at=validation.decided_at,
                content_hash=validation.content_hash,
                validation_snapshot=validation.to_snapshot(),
            )
        )
        return FindingValidationWriteResult(FindingValidationWriteStatus.WRITTEN, validation)

    async def current(self, *, project_id: UUID) -> tuple[FindingValidation, ...]:
        identity = (
            VALIDATIONS.c.evaluation_run_id,
            VALIDATIONS.c.twin_id,
            VALIDATIONS.c.finding_id,
        )
        latest = (
            sa.select(*identity, sa.func.max(VALIDATIONS.c.sequence_number).label("latest"))
            .where(
                VALIDATIONS.c.project_id == project_id,
                VALIDATIONS.c.owner_user_id == self._owner_user_id,
            )
            .group_by(*identity)
            .subquery()
        )
        statement = (
            sa.select(VALIDATIONS.c.validation_snapshot)
            .join(
                latest,
                sa.and_(
                    VALIDATIONS.c.evaluation_run_id == latest.c.evaluation_run_id,
                    VALIDATIONS.c.twin_id == latest.c.twin_id,
                    VALIDATIONS.c.finding_id == latest.c.finding_id,
                    VALIDATIONS.c.sequence_number == latest.c.latest,
                ),
            )
            .order_by(VALIDATIONS.c.decided_at, *identity)
        )
        rows = (await self._session.execute(statement)).scalars().all()
        return tuple(finding_validation_from_snapshot(row) for row in rows)


__all__ = [
    "VALIDATIONS",
    "FindingValidationWriteResult",
    "FindingValidationWriteStatus",
    "SqlAlchemyFindingValidationRepository",
]
