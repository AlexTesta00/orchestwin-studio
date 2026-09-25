from __future__ import annotations

from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.artifacts.design_evaluation import (
    DesignEvaluationRun,
    design_evaluation_run_from_snapshot,
)
from orchestwin.projects.persistence.models import ProjectRecord

RUNS = sa.table(
    "design_evaluation_runs",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("design_version_id", postgresql.UUID(as_uuid=True)),
    sa.column("design_version_number", sa.Integer()),
    sa.column("design_content_hash", sa.String(length=64)),
    sa.column("alternative_id", postgresql.UUID(as_uuid=True)),
    sa.column("alternative_code", sa.String(length=16)),
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

FINDINGS = sa.table(
    "design_synthetic_findings",
    sa.column("evaluation_run_id", postgresql.UUID(as_uuid=True)),
    sa.column("finding_id", sa.String(length=64)),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("sequence_number", sa.Integer()),
    sa.column("twin_id", postgresql.UUID(as_uuid=True)),
    sa.column("twin_version", sa.Integer()),
    sa.column("artifact_id", postgresql.UUID(as_uuid=True)),
    sa.column("artifact_version", sa.Integer()),
    sa.column("criterion", sa.String(length=32)),
    sa.column("severity", sa.String(length=16)),
    sa.column("epistemic_status", sa.String(length=32)),
    sa.column("confidence", sa.Float()),
    sa.column("requires_human_validation", sa.Boolean()),
    sa.column("content_hash", sa.String(length=64)),
    sa.column("finding_snapshot", postgresql.JSONB()),
)


class DesignEvaluationWriteStatus(StrEnum):
    WRITTEN = "WRITTEN"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    RUN_EXISTS = "RUN_EXISTS"


class SqlAlchemyDesignEvaluationRepository:
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

    async def create(self, run: DesignEvaluationRun) -> DesignEvaluationWriteStatus:
        if run.owner_user_id != self._owner_user_id or not await self._owns(run.project_id):
            return DesignEvaluationWriteStatus.PROJECT_NOT_FOUND
        existing = await self._session.execute(sa.select(RUNS.c.id).where(RUNS.c.id == run.id))
        if existing.scalar_one_or_none() is not None:
            return DesignEvaluationWriteStatus.RUN_EXISTS
        evaluator = run.evaluator
        await self._session.execute(
            sa.insert(RUNS).values(
                id=run.id,
                project_id=run.project_id,
                owner_user_id=run.owner_user_id,
                design_version_id=run.design_version_id,
                design_version_number=run.design_version_number,
                design_content_hash=run.design_content_hash,
                alternative_id=run.alternative_id,
                alternative_code=run.alternative_code,
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
        rows = [
            {
                "evaluation_run_id": run.id,
                "finding_id": finding.finding_id,
                "project_id": run.project_id,
                "owner_user_id": run.owner_user_id,
                "sequence_number": index,
                "twin_id": finding.twin_id,
                "twin_version": finding.twin_version,
                "artifact_id": finding.artifact_id,
                "artifact_version": finding.artifact_version,
                "criterion": finding.criterion.value,
                "severity": finding.severity.value,
                "epistemic_status": finding.epistemic_status.value,
                "confidence": finding.confidence,
                "requires_human_validation": finding.requires_human_validation,
                "content_hash": finding.content_hash,
                "finding_snapshot": finding.to_snapshot(),
            }
            for index, finding in enumerate(run.findings, 1)
        ]
        if rows:
            await self._session.execute(sa.insert(FINDINGS), rows)
        return DesignEvaluationWriteStatus.WRITTEN

    def _select(self):
        return sa.select(RUNS.c.run_snapshot).where(RUNS.c.owner_user_id == self._owner_user_id)

    async def get(self, *, project_id: UUID, run_id: UUID) -> DesignEvaluationRun | None:
        statement = self._select().where(RUNS.c.project_id == project_id, RUNS.c.id == run_id)
        row = (await self._session.execute(statement)).scalar_one_or_none()
        return None if row is None else design_evaluation_run_from_snapshot(row)

    async def list(self, *, project_id: UUID, limit: int = 50) -> tuple[DesignEvaluationRun, ...]:
        statement = (
            self._select()
            .where(RUNS.c.project_id == project_id)
            .order_by(RUNS.c.started_at.desc(), RUNS.c.id.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).scalars().all()
        return tuple(design_evaluation_run_from_snapshot(row) for row in rows)

    async def latest(self, *, project_id: UUID) -> DesignEvaluationRun | None:
        runs = await self.list(project_id=project_id, limit=1)
        return runs[0] if runs else None


__all__ = [
    "FINDINGS",
    "RUNS",
    "DesignEvaluationWriteStatus",
    "SqlAlchemyDesignEvaluationRepository",
]
