from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.projects.code_changes import (
    AlignedPoint,
    ChangeDecision,
    ChangeReviewRun,
    ChangeReviewSummary,
    CodeChange,
    CodeChangeAmbiguous,
    CodeTask,
    DecisionKind,
    TaskOrigin,
    TaskSource,
    TaskStatus,
    alignment_verdict_from_snapshot,
    changed_file_from_snapshot,
    commit_prefix,
    twin_critique_from_snapshot,
)
from orchestwin.projects.persistence.acceptance_tests import TEST_RUNS
from orchestwin.projects.persistence.models import ProjectRecord

DEFAULT_LIST_LIMIT: Final = 200
UNIQUE_COMMIT: Final = "uq_project_code_changes_commit"

CHANGES = sa.table(
    "project_code_changes",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("commit", sa.String(length=64)),
    sa.column("parent", sa.String(length=64)),
    sa.column("committed_at", sa.DateTime(timezone=True)),
    sa.column("author", sa.String(length=200)),
    sa.column("message", sa.Text()),
    sa.column("files", postgresql.JSONB()),
    sa.column("diff", sa.Text()),
    sa.column("recorded_at", sa.DateTime(timezone=True)),
    sa.column("decision_kind", sa.String(length=32)),
    sa.column("decision_note", sa.Text()),
    sa.column("decided_at", sa.DateTime(timezone=True)),
    sa.column("aligned_requirements_version", sa.Integer()),
    sa.column("aligned_design_version", sa.Integer()),
)

REVIEWS = sa.table(
    "code_change_reviews",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("change_id", postgresql.UUID(as_uuid=True)),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("reviewed_at", sa.DateTime(timezone=True)),
    sa.column("locale", sa.String(length=20)),
    sa.column("reference", postgresql.JSONB()),
    sa.column("critiques", postgresql.JSONB()),
    sa.column("alignment", postgresql.JSONB()),
    sa.column("generation_ids", postgresql.JSONB()),
    sa.column("cost_microusd", sa.BigInteger()),
)

TASKS = sa.table(
    "code_tasks",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("number", sa.Integer()),
    sa.column("code", sa.String(length=12)),
    sa.column("text", sa.String(length=300)),
    sa.column("about", postgresql.JSONB()),
    sa.column("from_change_id", postgresql.UUID(as_uuid=True)),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("status", sa.String(length=8)),
    sa.column("closed_at", sa.DateTime(timezone=True)),
    sa.column("origin", sa.String(length=16)),
    sa.column("test_run_id", postgresql.UUID(as_uuid=True)),
    sa.column("twin_id", postgresql.UUID(as_uuid=True)),
    sa.column("twin_name", sa.String(length=200)),
    sa.column("finding_text", sa.String(length=400)),
    sa.column("note", sa.String(length=300)),
)

_SUMMARY_COLUMNS: Final = tuple(column for column in CHANGES.c if column.name != "diff")
_ORDER: Final = (CHANGES.c.recorded_at, CHANGES.c.committed_at, CHANGES.c.commit)
_NEWEST_FIRST: Final = tuple(column.desc() for column in _ORDER)
_CREATED_ORIGINS: Final = (TaskOrigin.TEST_RUN.value, TaskOrigin.OWNER.value)


class CodeChangeWriteStatus(StrEnum):
    RECORDED = "RECORDED"
    ALREADY_RECORDED = "ALREADY_RECORDED"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    CHANGE_NOT_FOUND = "CHANGE_NOT_FOUND"


@dataclass(frozen=True, slots=True)
class CodeChangeWriteResult:
    status: CodeChangeWriteStatus
    change: CodeChange | None = None


@dataclass(frozen=True, slots=True)
class CreatedTasks:
    tasks: tuple[CodeTask, ...]
    created: int


def _violated_constraint(error: sa.exc.IntegrityError) -> str | None:
    diagnostic = getattr(getattr(error, "orig", None), "diag", None)
    return getattr(diagnostic, "constraint_name", None)


def _utc(value: datetime | None) -> datetime | None:
    return None if value is None else value.astimezone(UTC)


def _position(row: Mapping[str, object]):
    return sa.tuple_(
        sa.literal(row["recorded_at"], sa.DateTime(timezone=True)),
        sa.literal(row["committed_at"], sa.DateTime(timezone=True)),
        sa.literal(row["commit"], sa.String(length=64)),
    )


def _decision(row: Mapping[str, object]) -> ChangeDecision | None:
    if row["decision_kind"] is None:
        return None
    return ChangeDecision(
        kind=DecisionKind(row["decision_kind"]),
        decided_at=_utc(row["decided_at"]),
        note=row["decision_note"],
    )


def _change(
    row: Mapping[str, object], review: ChangeReviewSummary | None, *, with_diff: bool
) -> CodeChange:
    return CodeChange(
        id=row["id"],
        project_id=row["project_id"],
        owner_user_id=row["owner_user_id"],
        commit=row["commit"],
        parent=row["parent"],
        committed_at=_utc(row["committed_at"]),
        author=row["author"],
        message=row["message"],
        files=tuple(changed_file_from_snapshot(item) for item in row["files"]),
        recorded_at=_utc(row["recorded_at"]),
        diff=row["diff"] if with_diff else None,
        decision=_decision(row),
        aligned_requirements_version=row["aligned_requirements_version"],
        aligned_design_version=row["aligned_design_version"],
        review=review,
    )


def _summary(row: Mapping[str, object]) -> ChangeReviewSummary:
    alignment = row["alignment"]
    reference = row["reference"]
    return ChangeReviewSummary(
        run_id=row["id"],
        reviewed_at=_utc(row["reviewed_at"]),
        verdict=alignment_verdict_from_snapshot(alignment).status,
        summary=alignment["summary"],
        requirements_version_number=reference["requirements_version_number"],
        design_version_number=reference["design_version_number"],
        alternative_code=reference["alternative_code"],
    )


def _run(row: Mapping[str, object]) -> ChangeReviewRun:
    reference = row["reference"]
    return ChangeReviewRun(
        id=row["id"],
        change_id=row["change_id"],
        project_id=row["project_id"],
        owner_user_id=row["owner_user_id"],
        commit=row["commit"],
        reviewed_at=_utc(row["reviewed_at"]),
        locale=row["locale"],
        requirements_version_number=reference["requirements_version_number"],
        design_version_number=reference["design_version_number"],
        alternative_code=reference["alternative_code"],
        critiques=tuple(twin_critique_from_snapshot(item) for item in row["critiques"]),
        alignment=alignment_verdict_from_snapshot(row["alignment"]),
        generation_ids=tuple(UUID(str(item)) for item in row["generation_ids"]),
        cost_microusd=row["cost_microusd"],
    )


def _task(row: Mapping[str, object]) -> CodeTask:
    about = row["about"]
    task = CodeTask(
        id=row["id"],
        project_id=row["project_id"],
        owner_user_id=row["owner_user_id"],
        number=row["number"],
        text=row["text"],
        created_at=_utc(row["created_at"]),
        origin=TaskOrigin(row["origin"]),
        from_change_id=row["from_change_id"],
        from_commit=row["from_commit"],
        test_run_id=row["test_run_id"],
        twin_id=row["twin_id"],
        twin_name=row["twin_name"],
        finding=row["finding_text"],
        status=TaskStatus(row["status"]),
        requirements=tuple(about.get("requirements", ())),
        screens=tuple(about.get("screens", ())),
        criteria=tuple(about.get("criteria", ())),
        closed_at=_utc(row["closed_at"]),
        note=row["note"],
    )
    if task.code != row["code"]:
        raise ValueError("stored code task code does not match its number")
    return task


def _task_values(task: CodeTask) -> dict[str, object]:
    return {
        "id": task.id,
        "project_id": task.project_id,
        "owner_user_id": task.owner_user_id,
        "number": task.number,
        "code": task.code,
        "text": task.text,
        "about": task.about_snapshot(),
        "from_change_id": task.from_change_id,
        "created_at": task.created_at,
        "status": task.status.value,
        "closed_at": task.closed_at,
        "origin": task.origin.value,
        "test_run_id": task.test_run_id,
        "twin_id": task.twin_id,
        "twin_name": task.twin_name,
        "finding_text": task.finding,
        "note": task.note,
    }


class SqlAlchemyCodeChangeRepository:
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

    def _owned_changes(self, project_id: UUID, *columns):
        return sa.select(*(columns or _SUMMARY_COLUMNS)).where(
            CHANGES.c.project_id == project_id,
            CHANGES.c.owner_user_id == self._owner_user_id,
        )

    async def _summaries(self, change_ids: Sequence[UUID]) -> dict[UUID, ChangeReviewSummary]:
        if not change_ids:
            return {}
        statement = (
            sa.select(
                REVIEWS.c.change_id,
                REVIEWS.c.id,
                REVIEWS.c.reviewed_at,
                REVIEWS.c.reference,
                REVIEWS.c.alignment,
            )
            .where(
                REVIEWS.c.change_id.in_(list(change_ids)),
                REVIEWS.c.owner_user_id == self._owner_user_id,
            )
            .distinct(REVIEWS.c.change_id)
            .order_by(REVIEWS.c.change_id, REVIEWS.c.reviewed_at.desc(), REVIEWS.c.id.desc())
        )
        rows = (await self._session.execute(statement)).mappings().all()
        return {row["change_id"]: _summary(row) for row in rows}

    async def _assemble(
        self, rows: Sequence[Mapping[str, object]], *, with_diff: bool = False
    ) -> tuple[CodeChange, ...]:
        summaries = await self._summaries([row["id"] for row in rows])
        return tuple(_change(row, summaries.get(row["id"]), with_diff=with_diff) for row in rows)

    async def _aligned_row(self, project_id: UUID):
        statement = (
            self._owned_changes(project_id)
            .where(CHANGES.c.decision_kind == DecisionKind.ALIGNED.value)
            .order_by(*_NEWEST_FIRST)
            .limit(1)
        )
        return (await self._session.execute(statement)).mappings().first()

    async def _pending_filter(self, project_id: UUID, statement):
        aligned = await self._aligned_row(project_id)
        if aligned is None:
            return statement
        return statement.where(sa.tuple_(*_ORDER) > _position(aligned))

    async def _exact(self, project_id: UUID, commit: str) -> CodeChange | None:
        statement = self._owned_changes(project_id, *CHANGES.c).where(CHANGES.c.commit == commit)
        row = (await self._session.execute(statement)).mappings().one_or_none()
        if row is None:
            return None
        [change] = await self._assemble((row,), with_diff=True)
        return change

    async def record(self, change: CodeChange) -> CodeChangeWriteResult:
        if change.owner_user_id != self._owner_user_id or not await self.project_exists(
            change.project_id
        ):
            return CodeChangeWriteResult(CodeChangeWriteStatus.PROJECT_NOT_FOUND)
        if change.diff is None or change.decision is not None or change.review is not None:
            raise ValueError("a new code change carries its diff and no decision or review")
        stored = await self._exact(change.project_id, change.commit)
        if stored is not None:
            return CodeChangeWriteResult(CodeChangeWriteStatus.ALREADY_RECORDED, stored)
        try:
            async with self._session.begin_nested():
                await self._session.execute(
                    sa.insert(CHANGES).values(
                        id=change.id,
                        project_id=change.project_id,
                        owner_user_id=change.owner_user_id,
                        commit=change.commit,
                        parent=change.parent,
                        committed_at=change.committed_at,
                        author=change.author,
                        message=change.message,
                        files=[item.to_snapshot() for item in change.files],
                        diff=change.diff,
                        recorded_at=change.recorded_at,
                    )
                )
        except sa.exc.IntegrityError as error:
            if _violated_constraint(error) != UNIQUE_COMMIT:
                raise
            stored = await self._exact(change.project_id, change.commit)
            return CodeChangeWriteResult(CodeChangeWriteStatus.ALREADY_RECORDED, stored)
        return CodeChangeWriteResult(CodeChangeWriteStatus.RECORDED, change)

    async def list(
        self,
        project_id: UUID,
        *,
        pending_only: bool = False,
        limit: int | None = DEFAULT_LIST_LIMIT,
    ) -> tuple[CodeChange, ...]:
        statement = self._owned_changes(project_id)
        if pending_only:
            statement = await self._pending_filter(project_id, statement)
        statement = statement.order_by(*_NEWEST_FIRST)
        if limit is not None:
            statement = statement.limit(limit)
        rows = (await self._session.execute(statement)).mappings().all()
        return await self._assemble(rows)

    async def count(self, project_id: UUID, *, pending_only: bool = False) -> int:
        statement = self._owned_changes(project_id, CHANGES.c.id)
        if pending_only:
            statement = await self._pending_filter(project_id, statement)
        counted = sa.select(sa.func.count()).select_from(statement.subquery())
        return (await self._session.execute(counted)).scalar_one()

    async def get(self, project_id: UUID, commit_or_prefix: str) -> CodeChange | None:
        prefix = commit_prefix(commit_or_prefix)
        if prefix is None:
            return None
        exact = await self._exact(project_id, prefix)
        if exact is not None:
            return exact
        statement = (
            self._owned_changes(project_id, *CHANGES.c)
            .where(CHANGES.c.commit.startswith(prefix, autoescape=True))
            .order_by(CHANGES.c.commit)
            .limit(2)
        )
        rows = (await self._session.execute(statement)).mappings().all()
        if len(rows) > 1:
            raise CodeChangeAmbiguous(prefix)
        if not rows:
            return None
        [change] = await self._assemble(rows, with_diff=True)
        return change

    def _runs(self):
        return (
            sa.select(*REVIEWS.c, CHANGES.c.commit)
            .join(CHANGES, CHANGES.c.id == REVIEWS.c.change_id)
            .where(REVIEWS.c.owner_user_id == self._owner_user_id)
            .order_by(REVIEWS.c.reviewed_at.desc(), REVIEWS.c.id.desc())
        )

    async def runs(self, change_id: UUID) -> tuple[ChangeReviewRun, ...]:
        statement = self._runs().where(REVIEWS.c.change_id == change_id)
        rows = (await self._session.execute(statement)).mappings().all()
        return tuple(_run(row) for row in rows)

    async def latest_run(self, change_id: UUID) -> ChangeReviewRun | None:
        statement = self._runs().where(REVIEWS.c.change_id == change_id).limit(1)
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return None if row is None else _run(row)

    async def project_runs(
        self, project_id: UUID, *, limit: int | None = None
    ) -> tuple[ChangeReviewRun, ...]:
        statement = self._runs().where(REVIEWS.c.project_id == project_id)
        if limit is not None:
            statement = statement.limit(limit)
        rows = (await self._session.execute(statement)).mappings().all()
        return tuple(_run(row) for row in rows)

    async def create_run(self, run: ChangeReviewRun) -> CodeChangeWriteStatus:
        if run.owner_user_id != self._owner_user_id or not await self.project_exists(
            run.project_id
        ):
            return CodeChangeWriteStatus.PROJECT_NOT_FOUND
        statement = self._owned_changes(run.project_id, CHANGES.c.id).where(
            CHANGES.c.id == run.change_id, CHANGES.c.commit == run.commit
        )
        if (await self._session.execute(statement)).scalar_one_or_none() is None:
            return CodeChangeWriteStatus.CHANGE_NOT_FOUND
        await self._session.execute(
            sa.insert(REVIEWS).values(
                id=run.id,
                change_id=run.change_id,
                project_id=run.project_id,
                owner_user_id=run.owner_user_id,
                reviewed_at=run.reviewed_at,
                locale=run.locale,
                reference=run.reference_snapshot(),
                critiques=[item.to_snapshot() for item in run.critiques],
                alignment=run.alignment.to_snapshot(),
                generation_ids=[str(item) for item in run.generation_ids],
                cost_microusd=run.cost_microusd,
            )
        )
        return CodeChangeWriteStatus.RECORDED

    async def decide(
        self,
        change_id: UUID,
        decision: ChangeDecision,
        *,
        aligned_versions: tuple[int | None, int | None] = (None, None),
    ) -> CodeChange | None:
        statement = (
            sa.select(*CHANGES.c)
            .where(CHANGES.c.id == change_id, CHANGES.c.owner_user_id == self._owner_user_id)
            .with_for_update()
        )
        row = (await self._session.execute(statement)).mappings().one_or_none()
        if row is None:
            return None
        [current] = await self._assemble((row,), with_diff=True)
        requirements_version, design_version = aligned_versions
        decided = current.with_decision(
            decision, requirements_version=requirements_version, design_version=design_version
        )
        await self._session.execute(
            sa.update(CHANGES)
            .where(CHANGES.c.id == change_id)
            .values(
                decision_kind=decision.kind.value,
                decision_note=decision.note,
                decided_at=decision.decided_at,
                aligned_requirements_version=decided.aligned_requirements_version,
                aligned_design_version=decided.aligned_design_version,
            )
        )
        return decided

    async def aligned_point(self, project_id: UUID) -> AlignedPoint | None:
        row = await self._aligned_row(project_id)
        if row is None:
            return None
        return _change(row, None, with_diff=False).aligned_point()

    def _tasks(self, project_id: UUID):
        return (
            sa.select(*TASKS.c, CHANGES.c.commit.label("from_commit"))
            .select_from(TASKS.outerjoin(CHANGES, CHANGES.c.id == TASKS.c.from_change_id))
            .where(
                TASKS.c.project_id == project_id,
                TASKS.c.owner_user_id == self._owner_user_id,
            )
            .order_by(TASKS.c.number)
        )

    async def tasks(self, project_id: UUID, *, open_only: bool = False) -> tuple[CodeTask, ...]:
        statement = self._tasks(project_id)
        if open_only:
            statement = statement.where(TASKS.c.status == TaskStatus.OPEN.value)
        rows = (await self._session.execute(statement)).mappings().all()
        return tuple(_task(row) for row in rows)

    async def task(self, project_id: UUID, number: int) -> CodeTask | None:
        statement = self._tasks(project_id).where(TASKS.c.number == number)
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return None if row is None else _task(row)

    async def _check_subject(self, project_id: UUID, source: TaskSource) -> None:
        if source.origin is TaskOrigin.CODE_CHANGE:
            statement = self._owned_changes(project_id, CHANGES.c.id).where(
                CHANGES.c.id == source.change_id, CHANGES.c.commit == source.commit
            )
        elif source.origin is TaskOrigin.TEST_RUN:
            statement = sa.select(TEST_RUNS.c.id).where(
                TEST_RUNS.c.id == source.test_run_id,
                TEST_RUNS.c.project_id == project_id,
                TEST_RUNS.c.owner_user_id == self._owner_user_id,
            )
        else:
            return
        if (await self._session.execute(statement)).scalar_one_or_none() is None:
            raise ValueError("a code task names a change or a test run of its project")

    async def create_tasks(
        self, project_id: UUID, sources: Sequence[TaskSource], *, created_at: datetime
    ) -> CreatedTasks:
        if not await self._lock_project(project_id):
            raise ValueError("code tasks need an owned active project")
        for source in sources:
            await self._check_subject(project_id, source)
        known = {
            task.source_key: task
            for task in await self.tasks(project_id, open_only=True)
            if task.source_key is not None
        }
        latest = (
            await self._session.execute(
                sa.select(sa.func.max(TASKS.c.number)).where(TASKS.c.project_id == project_id)
            )
        ).scalar_one()
        number = latest or 0
        tasks = []
        created = 0
        for source in sources:
            existing = None if source.key is None else known.get(source.key)
            if existing is not None:
                tasks.append(existing)
                continue
            number += 1
            task = CodeTask.from_source(
                source,
                task_id=uuid4(),
                project_id=project_id,
                owner_user_id=self._owner_user_id,
                number=number,
                created_at=created_at,
            )
            await self._session.execute(sa.insert(TASKS).values(**_task_values(task)))
            if task.source_key is not None:
                known[task.source_key] = task
            tasks.append(task)
            created += 1
        return CreatedTasks(tasks=tuple(tasks), created=created)

    async def set_task_status(
        self,
        project_id: UUID,
        number: int,
        status: TaskStatus,
        *,
        at: datetime,
        note: str | None = None,
    ) -> CodeTask | None:
        if not await self._lock_project(project_id):
            return None
        task = await self.task(project_id, number)
        if task is None:
            return None
        changed = task.with_status(status, at=at, note=note)
        await self._session.execute(
            sa.update(TASKS)
            .where(TASKS.c.id == task.id)
            .values(status=changed.status.value, closed_at=changed.closed_at, note=changed.note)
        )
        return changed

    async def close_open_tasks(
        self, project_id: UUID, aligned_change_id: UUID, closed_at: datetime
    ) -> int:
        statement = self._owned_changes(project_id).where(CHANGES.c.id == aligned_change_id)
        aligned = (await self._session.execute(statement)).mappings().one_or_none()
        if aligned is None:
            return 0
        covered = self._owned_changes(project_id, CHANGES.c.id).where(
            sa.tuple_(*_ORDER) <= _position(aligned)
        )
        result = await self._session.execute(
            sa.update(TASKS)
            .where(
                TASKS.c.project_id == project_id,
                TASKS.c.owner_user_id == self._owner_user_id,
                TASKS.c.status == TaskStatus.OPEN.value,
                sa.or_(
                    sa.and_(
                        TASKS.c.origin == TaskOrigin.CODE_CHANGE.value,
                        TASKS.c.from_change_id.in_(covered),
                    ),
                    sa.and_(
                        TASKS.c.origin.in_(_CREATED_ORIGINS),
                        TASKS.c.created_at <= aligned["recorded_at"],
                    ),
                ),
            )
            .values(status=TaskStatus.DONE.value, closed_at=closed_at, note=None)
        )
        return result.rowcount


__all__ = [
    "CHANGES",
    "DEFAULT_LIST_LIMIT",
    "REVIEWS",
    "TASKS",
    "UNIQUE_COMMIT",
    "CodeChangeWriteResult",
    "CodeChangeWriteStatus",
    "CreatedTasks",
    "SqlAlchemyCodeChangeRepository",
]
