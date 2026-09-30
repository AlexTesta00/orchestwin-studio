from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.knowledge.state import MAX_FOLDER_TEST_RUNS
from orchestwin.projects.acceptance_tests import (
    TestPlan,
    TestPlanUnknown,
    TestReview,
    TestRun,
    application_from_snapshot,
    browser_from_snapshot,
    critique_from_snapshot,
    not_covered_from_snapshot,
    outcome_from_snapshot,
    path_from_snapshot,
    path_number,
    path_result_from_snapshot,
    run_summary_from_snapshot,
    snapshot_summary_from_snapshot,
)
from orchestwin.projects.persistence.models import ProjectRecord

DEFAULT_LIST_LIMIT: Final = 20

TEST_PLANS = sa.table(
    "acceptance_test_plans",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("locale", sa.String(length=20)),
    sa.column("reference", postgresql.JSONB()),
    sa.column("application", postgresql.JSONB()),
    sa.column("criteria", postgresql.JSONB()),
    sa.column("replan_of", postgresql.JSONB()),
    sa.column("snapshot_summary", postgresql.JSONB()),
    sa.column("paths", postgresql.JSONB()),
    sa.column("not_covered", postgresql.JSONB()),
    sa.column("generation_ids", postgresql.JSONB()),
    sa.column("cost_microusd", sa.BigInteger()),
)

TEST_RUNS = sa.table(
    "acceptance_test_runs",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("plan_id", postgresql.UUID(as_uuid=True)),
    sa.column("replan_ids", postgresql.JSONB()),
    sa.column("started_at", sa.DateTime(timezone=True)),
    sa.column("finished_at", sa.DateTime(timezone=True)),
    sa.column("recorded_at", sa.DateTime(timezone=True)),
    sa.column("application", postgresql.JSONB()),
    sa.column("browsers", postgresql.JSONB()),
    sa.column("reference", postgresql.JSONB()),
    sa.column("results", postgresql.JSONB()),
    sa.column("not_covered", postgresql.JSONB()),
    sa.column("criteria", postgresql.JSONB()),
    sa.column("summary", postgresql.JSONB()),
    sa.column("cost_microusd", sa.BigInteger()),
)

TEST_REVIEWS = sa.table(
    "acceptance_test_reviews",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("run_id", postgresql.UUID(as_uuid=True)),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("reviewed_at", sa.DateTime(timezone=True)),
    sa.column("locale", sa.String(length=20)),
    sa.column("critiques", postgresql.JSONB()),
    sa.column("generation_ids", postgresql.JSONB()),
    sa.column("cost_microusd", sa.BigInteger()),
)


class AcceptanceTestWriteStatus(StrEnum):
    RECORDED = "RECORDED"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    RUN_NOT_FOUND = "RUN_NOT_FOUND"


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _identifiers(values: Sequence[object]) -> tuple[UUID, ...]:
    return tuple(UUID(str(item)) for item in values)


def _plan(row: Mapping[str, object]) -> TestPlan:
    reference = row["reference"]
    return TestPlan(
        id=row["id"],
        project_id=row["project_id"],
        owner_user_id=row["owner_user_id"],
        created_at=_utc(row["created_at"]),
        locale=row["locale"],
        requirements_version_number=reference["requirements_version_number"],
        design_version_number=reference["design_version_number"],
        alternative_code=reference["alternative_code"],
        application=application_from_snapshot(row["application"]),
        criteria=tuple(row["criteria"]),
        paths=tuple(path_from_snapshot(item) for item in row["paths"]),
        not_covered=tuple(not_covered_from_snapshot(item) for item in row["not_covered"]),
        replan_of=tuple(row["replan_of"]),
        snapshot_summary=snapshot_summary_from_snapshot(row["snapshot_summary"]),
        generation_ids=_identifiers(row["generation_ids"]),
        cost_microusd=row["cost_microusd"],
    )


def _review(row: Mapping[str, object]) -> TestReview:
    return TestReview(
        id=row["id"],
        run_id=row["run_id"],
        project_id=row["project_id"],
        owner_user_id=row["owner_user_id"],
        reviewed_at=_utc(row["reviewed_at"]),
        locale=row["locale"],
        critiques=tuple(critique_from_snapshot(item) for item in row["critiques"]),
        generation_ids=_identifiers(row["generation_ids"]),
        cost_microusd=row["cost_microusd"],
    )


def _run(row: Mapping[str, object], review: TestReview | None) -> TestRun:
    reference = row["reference"]
    return TestRun(
        id=row["id"],
        project_id=row["project_id"],
        owner_user_id=row["owner_user_id"],
        plan_id=row["plan_id"],
        started_at=_utc(row["started_at"]),
        finished_at=_utc(row["finished_at"]),
        recorded_at=_utc(row["recorded_at"]),
        application=application_from_snapshot(row["application"]),
        browsers=tuple(browser_from_snapshot(item) for item in row["browsers"]),
        requirements_version_number=reference["requirements_version_number"],
        design_version_number=reference["design_version_number"],
        alternative_code=reference["alternative_code"],
        results=tuple(path_result_from_snapshot(item) for item in row["results"]),
        not_covered=tuple(not_covered_from_snapshot(item) for item in row["not_covered"]),
        criteria=tuple(outcome_from_snapshot(item) for item in row["criteria"]),
        summary=run_summary_from_snapshot(row["summary"]),
        replan_ids=_identifiers(row["replan_ids"]),
        cost_microusd=row["cost_microusd"],
        review=review,
    )


class SqlAlchemyAcceptanceTestRepository:
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

    def _owned(self, table, project_id: UUID, *columns):
        return sa.select(*(columns or table.c)).where(
            table.c.project_id == project_id,
            table.c.owner_user_id == self._owner_user_id,
        )

    async def create_plan(self, plan: TestPlan) -> AcceptanceTestWriteStatus:
        if plan.owner_user_id != self._owner_user_id or not await self.project_exists(
            plan.project_id
        ):
            return AcceptanceTestWriteStatus.PROJECT_NOT_FOUND
        if plan.snapshot_summary is None:
            raise ValueError("a stored test plan carries the summary of its snapshot")
        await self._session.execute(
            sa.insert(TEST_PLANS).values(
                id=plan.id,
                project_id=plan.project_id,
                owner_user_id=plan.owner_user_id,
                created_at=plan.created_at,
                locale=plan.locale,
                reference=plan.reference_snapshot(),
                application=plan.application.to_snapshot(),
                criteria=list(plan.criteria),
                replan_of=list(plan.replan_of),
                snapshot_summary=plan.snapshot_summary.to_snapshot(),
                paths=[item.to_snapshot() for item in plan.paths],
                not_covered=[item.to_snapshot() for item in plan.not_covered],
                generation_ids=[str(item) for item in plan.generation_ids],
                cost_microusd=plan.cost_microusd,
            )
        )
        return AcceptanceTestWriteStatus.RECORDED

    async def plans(
        self, project_id: UUID, *, limit: int | None = DEFAULT_LIST_LIMIT
    ) -> tuple[TestPlan, ...]:
        statement = self._owned(TEST_PLANS, project_id).order_by(
            TEST_PLANS.c.created_at.desc(), TEST_PLANS.c.id.desc()
        )
        if limit is not None:
            statement = statement.limit(limit)
        rows = (await self._session.execute(statement)).mappings().all()
        return tuple(_plan(row) for row in rows)

    async def plan(self, project_id: UUID, plan_id: UUID) -> TestPlan | None:
        statement = self._owned(TEST_PLANS, project_id).where(TEST_PLANS.c.id == plan_id)
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return None if row is None else _plan(row)

    async def next_path_number(self, project_id: UUID) -> int:
        statement = self._owned(TEST_PLANS, project_id, TEST_PLANS.c.paths)
        stored = (await self._session.execute(statement)).scalars().all()
        highest = max(
            (path_number(item["code"]) for paths in stored for item in paths),
            default=0,
        )
        return highest + 1

    async def create_run(self, run: TestRun) -> AcceptanceTestWriteStatus:
        if run.owner_user_id != self._owner_user_id or not await self.project_exists(
            run.project_id
        ):
            return AcceptanceTestWriteStatus.PROJECT_NOT_FOUND
        if run.review is not None:
            raise ValueError("a new test run carries no review")
        wanted = (run.plan_id, *run.replan_ids)
        statement = self._owned(TEST_PLANS, run.project_id, TEST_PLANS.c.id).where(
            TEST_PLANS.c.id.in_(list(wanted))
        )
        found = set((await self._session.execute(statement)).scalars().all())
        missing = next((item for item in wanted if item not in found), None)
        if missing is not None:
            raise TestPlanUnknown(missing)
        await self._session.execute(
            sa.insert(TEST_RUNS).values(
                id=run.id,
                project_id=run.project_id,
                owner_user_id=run.owner_user_id,
                plan_id=run.plan_id,
                replan_ids=[str(item) for item in run.replan_ids],
                started_at=run.started_at,
                finished_at=run.finished_at,
                recorded_at=run.recorded_at,
                application=run.application.to_snapshot(),
                browsers=[item.to_snapshot() for item in run.browsers],
                reference=run.reference_snapshot(),
                results=[item.to_snapshot() for item in run.results],
                not_covered=[item.to_snapshot() for item in run.not_covered],
                criteria=[item.to_snapshot() for item in run.criteria],
                summary=run.summary.to_snapshot(),
                cost_microusd=run.cost_microusd,
            )
        )
        return AcceptanceTestWriteStatus.RECORDED

    async def _latest_reviews(self, run_ids: Sequence[UUID]) -> dict[UUID, TestReview]:
        if not run_ids:
            return {}
        statement = (
            sa.select(*TEST_REVIEWS.c)
            .where(
                TEST_REVIEWS.c.run_id.in_(list(run_ids)),
                TEST_REVIEWS.c.owner_user_id == self._owner_user_id,
            )
            .distinct(TEST_REVIEWS.c.run_id)
            .order_by(
                TEST_REVIEWS.c.run_id,
                TEST_REVIEWS.c.reviewed_at.desc(),
                TEST_REVIEWS.c.id.desc(),
            )
        )
        rows = (await self._session.execute(statement)).mappings().all()
        return {row["run_id"]: _review(row) for row in rows}

    async def _assemble(self, rows: Sequence[Mapping[str, object]]) -> tuple[TestRun, ...]:
        reviews = await self._latest_reviews([row["id"] for row in rows])
        return tuple(_run(row, reviews.get(row["id"])) for row in rows)

    async def runs(
        self, project_id: UUID, *, limit: int | None = DEFAULT_LIST_LIMIT
    ) -> tuple[TestRun, ...]:
        statement = self._owned(TEST_RUNS, project_id).order_by(
            TEST_RUNS.c.recorded_at.desc(), TEST_RUNS.c.id.desc()
        )
        if limit is not None:
            statement = statement.limit(limit)
        rows = (await self._session.execute(statement)).mappings().all()
        return await self._assemble(rows)

    async def run(self, project_id: UUID, run_id: UUID) -> TestRun | None:
        statement = self._owned(TEST_RUNS, project_id).where(TEST_RUNS.c.id == run_id)
        row = (await self._session.execute(statement)).mappings().one_or_none()
        if row is None:
            return None
        [run] = await self._assemble((row,))
        return run

    def _reviews(self, run_id: UUID):
        return (
            sa.select(*TEST_REVIEWS.c)
            .where(
                TEST_REVIEWS.c.run_id == run_id,
                TEST_REVIEWS.c.owner_user_id == self._owner_user_id,
            )
            .order_by(TEST_REVIEWS.c.reviewed_at.desc(), TEST_REVIEWS.c.id.desc())
        )

    async def reviews(self, run_id: UUID) -> tuple[TestReview, ...]:
        rows = (await self._session.execute(self._reviews(run_id))).mappings().all()
        return tuple(_review(row) for row in rows)

    async def latest_review(self, run_id: UUID) -> TestReview | None:
        statement = self._reviews(run_id).limit(1)
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return None if row is None else _review(row)

    async def create_review(self, review: TestReview) -> AcceptanceTestWriteStatus:
        if review.owner_user_id != self._owner_user_id or not await self.project_exists(
            review.project_id
        ):
            return AcceptanceTestWriteStatus.PROJECT_NOT_FOUND
        statement = self._owned(TEST_RUNS, review.project_id, TEST_RUNS.c.id).where(
            TEST_RUNS.c.id == review.run_id
        )
        if (await self._session.execute(statement)).scalar_one_or_none() is None:
            return AcceptanceTestWriteStatus.RUN_NOT_FOUND
        await self._session.execute(
            sa.insert(TEST_REVIEWS).values(
                id=review.id,
                run_id=review.run_id,
                project_id=review.project_id,
                owner_user_id=review.owner_user_id,
                reviewed_at=review.reviewed_at,
                locale=review.locale,
                critiques=[item.to_snapshot() for item in review.critiques],
                generation_ids=[str(item) for item in review.generation_ids],
                cost_microusd=review.cost_microusd,
            )
        )
        return AcceptanceTestWriteStatus.RECORDED

    async def counts(self, project_id: UUID) -> tuple[int, int]:
        totals = []
        for table in (TEST_PLANS, TEST_RUNS):
            owned = self._owned(table, project_id, table.c.id).subquery()
            statement = sa.select(sa.func.count()).select_from(owned)
            totals.append((await self._session.execute(statement)).scalar_one())
        plans, runs = totals
        return plans, runs

    async def folder_runs(
        self, project_id: UUID, *, limit: int = MAX_FOLDER_TEST_RUNS
    ) -> tuple[dict[str, object], ...]:
        return tuple(run.to_snapshot() for run in await self.runs(project_id, limit=limit))


__all__ = [
    "DEFAULT_LIST_LIMIT",
    "TEST_PLANS",
    "TEST_REVIEWS",
    "TEST_RUNS",
    "AcceptanceTestWriteStatus",
    "SqlAlchemyAcceptanceTestRepository",
]
