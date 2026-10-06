from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.projects.knowledge_alignment import (
    AlignmentProposal,
    KnowledgeAlignmentRun,
    ProposalAlreadyDecided,
    ProposalSection,
    ProposalStatus,
    proposal_number,
    proposal_origin_from_snapshot,
    proposal_subjects_from_snapshot,
)
from orchestwin.projects.persistence.models import ProjectRecord

RUNS = sa.table(
    "knowledge_alignment_runs",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("from_commit", sa.String(length=64)),
    sa.column("to_commit", sa.String(length=64)),
    sa.column("commits", postgresql.JSONB()),
    sa.column("locale", sa.String(length=20)),
    sa.column("requirements_version_number", sa.Integer()),
    sa.column("design_version_number", sa.Integer()),
    sa.column("alternative_code", sa.String(length=16)),
    sa.column("summary", sa.Text()),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("cost_microusd", sa.Integer()),
    sa.column("generation_ids", postgresql.JSONB()),
)

PROPOSALS = sa.table(
    "knowledge_alignment_proposals",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("run_id", postgresql.UUID(as_uuid=True)),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("number", sa.Integer()),
    sa.column("section", sa.String(length=16)),
    sa.column("title", sa.String(length=200)),
    sa.column("request", sa.Text()),
    sa.column("rationale", sa.Text()),
    sa.column("subjects", postgresql.JSONB()),
    sa.column("origin", postgresql.JSONB()),
    sa.column("status", sa.String(length=16)),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("decided_at", sa.DateTime(timezone=True)),
    sa.column("decision_note", sa.Text()),
    sa.column("applied_text", sa.Text()),
    sa.column("applied_diff_id", postgresql.UUID(as_uuid=True)),
)

_RUNS_NEWEST_FIRST: Final = (RUNS.c.created_at.desc(), RUNS.c.id.desc())
_PROPOSALS_NEWEST_FIRST: Final = (PROPOSALS.c.created_at.desc(), PROPOSALS.c.number.desc())


def _utc(value: datetime | None) -> datetime | None:
    return None if value is None else value.astimezone(UTC)


def _proposal(row: Mapping[str, object]) -> AlignmentProposal:
    return AlignmentProposal(
        id=row["id"],
        run_id=row["run_id"],
        project_id=row["project_id"],
        owner_user_id=row["owner_user_id"],
        number=row["number"],
        section=ProposalSection(row["section"]),
        title=row["title"],
        request=row["request"],
        rationale=row["rationale"],
        subjects=proposal_subjects_from_snapshot(row["subjects"]),
        origin=proposal_origin_from_snapshot(row["origin"]),
        status=ProposalStatus(row["status"]),
        created_at=_utc(row["created_at"]),
        decided_at=_utc(row["decided_at"]),
        decision_note=row["decision_note"],
        applied_text=row["applied_text"],
        applied_diff_id=row["applied_diff_id"],
    )


def _run(
    row: Mapping[str, object], proposals: tuple[AlignmentProposal, ...]
) -> KnowledgeAlignmentRun:
    return KnowledgeAlignmentRun(
        id=row["id"],
        project_id=row["project_id"],
        owner_user_id=row["owner_user_id"],
        from_commit=row["from_commit"],
        to_commit=row["to_commit"],
        commits=tuple(row["commits"]),
        locale=row["locale"],
        requirements_version_number=row["requirements_version_number"],
        design_version_number=row["design_version_number"],
        alternative_code=row["alternative_code"],
        summary=row["summary"],
        created_at=_utc(row["created_at"]),
        cost_microusd=row["cost_microusd"],
        generation_ids=tuple(UUID(str(item)) for item in row["generation_ids"]),
        proposals=proposals,
    )


def _run_values(run: KnowledgeAlignmentRun) -> dict[str, object]:
    return {
        "id": run.id,
        "project_id": run.project_id,
        "owner_user_id": run.owner_user_id,
        "from_commit": run.from_commit,
        "to_commit": run.to_commit,
        "commits": list(run.commits),
        "locale": run.locale,
        "requirements_version_number": run.requirements_version_number,
        "design_version_number": run.design_version_number,
        "alternative_code": run.alternative_code,
        "summary": run.summary,
        "created_at": run.created_at,
        "cost_microusd": run.cost_microusd,
        "generation_ids": [str(item) for item in run.generation_ids],
    }


def _proposal_values(proposal: AlignmentProposal) -> dict[str, object]:
    return {
        "id": proposal.id,
        "run_id": proposal.run_id,
        "project_id": proposal.project_id,
        "owner_user_id": proposal.owner_user_id,
        "number": proposal.number,
        "section": proposal.section.value,
        "title": proposal.title,
        "request": proposal.request,
        "rationale": proposal.rationale,
        "subjects": proposal.subjects.to_snapshot(),
        "origin": proposal.origin.to_snapshot(),
        "status": proposal.status.value,
        "created_at": proposal.created_at,
        "decided_at": proposal.decided_at,
        "decision_note": proposal.decision_note,
        "applied_text": proposal.applied_text,
        "applied_diff_id": proposal.applied_diff_id,
    }


class SqlAlchemyKnowledgeAlignmentRepository:
    def __init__(self, session: AsyncSession, *, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id

    def _owned_project(self, project_id: UUID):
        return sa.select(ProjectRecord.id).where(
            ProjectRecord.id == project_id,
            ProjectRecord.owner_user_id == self._owner_user_id,
            ProjectRecord.archived_at.is_(None),
        )

    async def project_exists(self, project_id: UUID) -> bool:
        return (
            await self._session.execute(self._owned_project(project_id))
        ).scalar_one_or_none() is not None

    async def _lock_project(self, project_id: UUID) -> bool:
        statement = self._owned_project(project_id).with_for_update()
        return (await self._session.execute(statement)).scalar_one_or_none() is not None

    def _owned_runs(self, project_id: UUID):
        return sa.select(*RUNS.c).where(
            RUNS.c.project_id == project_id, RUNS.c.owner_user_id == self._owner_user_id
        )

    def _owned_proposals(self, project_id: UUID):
        return sa.select(*PROPOSALS.c).where(
            PROPOSALS.c.project_id == project_id,
            PROPOSALS.c.owner_user_id == self._owner_user_id,
        )

    async def _proposals_of(
        self, run_ids: Sequence[UUID]
    ) -> dict[UUID, tuple[AlignmentProposal, ...]]:
        grouped: dict[UUID, list[AlignmentProposal]] = {run_id: [] for run_id in run_ids}
        if not run_ids:
            return {}
        statement = (
            sa.select(*PROPOSALS.c)
            .where(
                PROPOSALS.c.run_id.in_(list(run_ids)),
                PROPOSALS.c.owner_user_id == self._owner_user_id,
            )
            .order_by(PROPOSALS.c.number)
        )
        for row in (await self._session.execute(statement)).mappings().all():
            grouped[row["run_id"]].append(_proposal(row))
        return {run_id: tuple(items) for run_id, items in grouped.items()}

    async def _assemble(
        self, rows: Sequence[Mapping[str, object]]
    ) -> tuple[KnowledgeAlignmentRun, ...]:
        proposals = await self._proposals_of([row["id"] for row in rows])
        return tuple(_run(row, proposals.get(row["id"], ())) for row in rows)

    async def next_number(self, project_id: UUID) -> int:
        latest = (
            await self._session.execute(
                sa.select(sa.func.max(PROPOSALS.c.number)).where(
                    PROPOSALS.c.project_id == project_id
                )
            )
        ).scalar_one()
        return (latest or 0) + 1

    async def create_run(self, run: KnowledgeAlignmentRun) -> KnowledgeAlignmentRun:
        if run.owner_user_id != self._owner_user_id or not await self._lock_project(run.project_id):
            raise ValueError("knowledge alignment runs need an owned active project")
        stored = run.renumbered(await self.next_number(run.project_id))
        await self._session.execute(sa.insert(RUNS).values(**_run_values(stored)))
        if stored.proposals:
            await self._session.execute(
                sa.insert(PROPOSALS), [_proposal_values(item) for item in stored.proposals]
            )
        return stored

    async def runs(self, project_id: UUID) -> tuple[KnowledgeAlignmentRun, ...]:
        statement = self._owned_runs(project_id).order_by(*_RUNS_NEWEST_FIRST)
        rows = (await self._session.execute(statement)).mappings().all()
        return await self._assemble(rows)

    async def latest_run(self, project_id: UUID) -> KnowledgeAlignmentRun | None:
        statement = self._owned_runs(project_id).order_by(*_RUNS_NEWEST_FIRST).limit(1)
        row = (await self._session.execute(statement)).mappings().one_or_none()
        if row is None:
            return None
        [run] = await self._assemble((row,))
        return run

    async def run(self, project_id: UUID, run_id: UUID) -> KnowledgeAlignmentRun | None:
        statement = self._owned_runs(project_id).where(RUNS.c.id == run_id)
        row = (await self._session.execute(statement)).mappings().one_or_none()
        if row is None:
            return None
        [run] = await self._assemble((row,))
        return run

    async def proposals(
        self, project_id: UUID, *, waiting_only: bool = False
    ) -> tuple[AlignmentProposal, ...]:
        statement = self._owned_proposals(project_id)
        if waiting_only:
            statement = statement.where(PROPOSALS.c.status == ProposalStatus.PROPOSED.value)
        statement = statement.order_by(*_PROPOSALS_NEWEST_FIRST)
        rows = (await self._session.execute(statement)).mappings().all()
        return tuple(_proposal(row) for row in rows)

    async def proposal(self, project_id: UUID, code: str) -> AlignmentProposal | None:
        number = proposal_number(code)
        if number is None:
            return None
        statement = self._owned_proposals(project_id).where(PROPOSALS.c.number == number)
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return None if row is None else _proposal(row)

    async def decide(
        self,
        project_id: UUID,
        code: str,
        *,
        status: ProposalStatus,
        decided_at: datetime,
        note: str | None = None,
        applied_text: str | None = None,
        applied_diff_id: UUID | None = None,
    ) -> AlignmentProposal | None:
        number = proposal_number(code)
        if number is None or not await self._lock_project(project_id):
            return None
        statement = (
            self._owned_proposals(project_id).where(PROPOSALS.c.number == number).with_for_update()
        )
        row = (await self._session.execute(statement)).mappings().one_or_none()
        if row is None:
            return None
        decided = _proposal(row).with_decision(
            status=status,
            decided_at=decided_at,
            note=note,
            applied_text=applied_text,
            applied_diff_id=applied_diff_id,
        )
        await self._session.execute(
            sa.update(PROPOSALS)
            .where(PROPOSALS.c.id == decided.id)
            .values(
                status=decided.status.value,
                decided_at=decided.decided_at,
                decision_note=decided.decision_note,
                applied_text=decided.applied_text,
                applied_diff_id=decided.applied_diff_id,
            )
        )
        return decided


__all__ = [
    "PROPOSALS",
    "RUNS",
    "ProposalAlreadyDecided",
    "SqlAlchemyKnowledgeAlignmentRepository",
]
