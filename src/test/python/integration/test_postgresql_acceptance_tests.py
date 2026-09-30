from __future__ import annotations

import importlib
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from orchestwin.knowledge.state import ProjectStateSources
from orchestwin.persistence import create_database_runtime, load_database_settings
from orchestwin.projects.acceptance_tests import TestPlanUnknown
from orchestwin.projects.code_change_state import SqlAlchemyProjectStateQueryService
from orchestwin.projects.persistence.acceptance_tests import (
    TEST_PLANS,
    TEST_REVIEWS,
    TEST_RUNS,
    AcceptanceTestWriteStatus,
    SqlAlchemyAcceptanceTestRepository,
)
from src.test.python.integration.postgres_isolation import assert_reversible_migration
from src.test.python.integration.test_postgresql_design_loop import seed
from src.test.python.integration.test_proposal_evidence_postgres import database, run
from src.test.python.projects.test_acceptance_tests import (
    NOW,
    PLAN_ID,
    REPLAN_ID,
    RUN_ID,
    TWIN_TWO,
    sample_critique,
    sample_path,
    sample_plan,
    sample_result,
    sample_review,
    sample_run,
    step_results,
)

__all__ = ["database"]

pytestmark = pytest.mark.integration

MIGRATION = importlib.import_module(
    "orchestwin.persistence.migrations.versions.0064_acceptance_tests"
)


def plans():
    plan = sample_plan()
    replan = sample_plan(
        id=REPLAN_ID,
        created_at=NOW + timedelta(minutes=30),
        criteria=("AC-001",),
        paths=(sample_path("TP-003"),),
        not_covered=(),
        replan_of=("TP-001",),
        generation_ids=(),
        cost_microusd=190_000,
    )
    return plan, replan


def recorded_run(plan, replan):
    return sample_run(
        (plan, replan),
        results=(
            sample_result(replan.paths[0], "chrome"),
            sample_result(replan.paths[0], "firefox"),
            sample_result(plan.paths[1], "chrome", steps=step_results(2)),
        ),
    )


async def count(session, table):
    return (await session.execute(sa.select(sa.func.count()).select_from(table))).scalar_one()


def test_plans_runs_and_reviews_round_trip_into_the_project_state(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, _ = await seed(db)
            plan, replan = plans()
            stranger_id = uuid4()
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyAcceptanceTestRepository(session, owner_user_id=owner)
                assert await repository.next_path_number(project) == 1
                assert await repository.create_plan(plan) is AcceptanceTestWriteStatus.RECORDED
                assert await repository.create_plan(replan) is AcceptanceTestWriteStatus.RECORDED
                with pytest.raises(ValueError):
                    await repository.create_plan(replace(plan, id=uuid4(), snapshot_summary=None))
                stranger = SqlAlchemyAcceptanceTestRepository(session, owner_user_id=stranger_id)
                assert (
                    await stranger.create_plan(replace(plan, id=uuid4(), owner_user_id=stranger_id))
                    is AcceptanceTestWriteStatus.PROJECT_NOT_FOUND
                )
                assert await stranger.plans(project) == ()
                assert await stranger.plan(project, PLAN_ID) is None
            async with db.session_factory() as session:
                repository = SqlAlchemyAcceptanceTestRepository(session, owner_user_id=owner)
                assert await repository.project_exists(project)
                assert await repository.plans(project) == (replan, plan)
                assert await repository.plans(project, limit=1) == (replan,)
                assert await repository.plan(project, PLAN_ID) == plan
                assert await repository.plan(project, uuid4()) is None
                assert await repository.next_path_number(project) == 4
                assert await repository.counts(project) == (2, 0)

            run_value = recorded_run(plan, replan)
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyAcceptanceTestRepository(session, owner_user_id=owner)
                assert await repository.create_run(run_value) is AcceptanceTestWriteStatus.RECORDED
                with pytest.raises(TestPlanUnknown) as unknown:
                    await repository.create_run(
                        replace(run_value, id=uuid4(), replan_ids=(uuid4(),))
                    )
                assert unknown.value.plan_id != PLAN_ID
                with pytest.raises(ValueError):
                    await repository.create_run(
                        replace(run_value, id=uuid4(), review=sample_review(run_id=uuid4()))
                    )
                stranger = SqlAlchemyAcceptanceTestRepository(session, owner_user_id=stranger_id)
                assert (
                    await stranger.create_run(replace(run_value, owner_user_id=stranger_id))
                    is AcceptanceTestWriteStatus.PROJECT_NOT_FOUND
                )
            async with db.session_factory() as session:
                repository = SqlAlchemyAcceptanceTestRepository(session, owner_user_id=owner)
                assert await repository.runs(project) == (run_value,)
                assert await repository.run(project, RUN_ID) == run_value
                assert await repository.run(project, uuid4()) is None
                assert await repository.latest_review(RUN_ID) is None
                assert await repository.counts(project) == (2, 1)

            first = sample_review(id=uuid4())
            second = sample_review(
                id=uuid4(),
                reviewed_at=first.reviewed_at + timedelta(hours=1),
                critiques=(sample_critique(), sample_critique(TWIN_TWO, "Night Auditor Twin")),
                generation_ids=(),
                cost_microusd=280_000,
            )
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyAcceptanceTestRepository(session, owner_user_id=owner)
                for review in (first, second):
                    assert (
                        await repository.create_review(review) is AcceptanceTestWriteStatus.RECORDED
                    )
                assert (
                    await repository.create_review(sample_review(id=uuid4(), run_id=uuid4()))
                    is AcceptanceTestWriteStatus.RUN_NOT_FOUND
                )
                stranger = SqlAlchemyAcceptanceTestRepository(session, owner_user_id=stranger_id)
                assert (
                    await stranger.create_review(
                        sample_review(id=uuid4(), owner_user_id=stranger_id)
                    )
                    is AcceptanceTestWriteStatus.PROJECT_NOT_FOUND
                )
            async with db.session_factory() as session:
                repository = SqlAlchemyAcceptanceTestRepository(session, owner_user_id=owner)
                assert await repository.reviews(RUN_ID) == (second, first)
                assert await repository.latest_review(RUN_ID) == second
                reviewed = run_value.with_review(second)
                assert await repository.runs(project) == (reviewed,)
                assert await repository.run(project, RUN_ID) == reviewed
                folder = await repository.folder_runs(project)
                stranger = SqlAlchemyAcceptanceTestRepository(session, owner_user_id=stranger_id)
                assert await stranger.reviews(RUN_ID) == ()
                assert await stranger.runs(project) == ()

            assert folder == (reviewed.to_snapshot(),)
            document = folder[0]
            assert document["cost_microusd"] == 210_000 + 190_000 + 280_000
            assert [item["twin_name"] for item in document["critiques"]] == [
                "Receptionist Twin",
                "Night Auditor Twin",
            ]
            assert document["criteria"] == [
                {"code": "AC-001", "status": "PASSED", "paths": ["TP-003"]},
                {"code": "AC-002", "status": "PASSED", "paths": ["TP-002"]},
                {"code": "AC-003", "status": "NOT_COVERED", "paths": []},
            ]
            sources = await SqlAlchemyProjectStateQueryService(db.session_factory).current(
                owner_user_id=owner, project_id=project
            )
            assert isinstance(sources, ProjectStateSources)
            assert sources.tests == folder
            assert (sources.changes, sources.runs, sources.tasks) == ((), (), ())
            assert not sources.is_empty
            empty = await SqlAlchemyProjectStateQueryService(db.session_factory).current(
                owner_user_id=stranger_id, project_id=project
            )
            assert empty == ProjectStateSources()
        finally:
            await db.dispose()

    run(scenario())


def test_the_folder_keeps_the_newest_runs_only(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, _ = await seed(db)
            plan, replan = plans()
            runs = [
                replace(
                    recorded_run(plan, replan),
                    id=uuid4(),
                    recorded_at=NOW + timedelta(days=1, minutes=minutes),
                )
                for minutes in range(22)
            ]
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyAcceptanceTestRepository(session, owner_user_id=owner)
                await repository.create_plan(plan)
                await repository.create_plan(replan)
                for item in runs:
                    assert await repository.create_run(item) is AcceptanceTestWriteStatus.RECORDED
            async with db.session_factory() as session:
                repository = SqlAlchemyAcceptanceTestRepository(session, owner_user_id=owner)
                folder = await repository.folder_runs(project)
                listed = await repository.runs(project)
                assert await repository.runs(project, limit=None) == tuple(reversed(runs))
                assert await repository.counts(project) == (2, 22)
            assert [item["id"] for item in folder] == [str(item.id) for item in runs[::-1][:20]]
            assert listed == tuple(reversed(runs))[:20]
            sources = await SqlAlchemyProjectStateQueryService(db.session_factory).current(
                owner_user_id=owner, project_id=project
            )
            assert len(sources.tests) == 20
        finally:
            await db.dispose()

    run(scenario())


def test_the_tables_refuse_rows_outside_the_limits_and_cascade_from_the_run(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, _ = await seed(db)
            plan, replan = plans()
            run_value = recorded_run(plan, replan)
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyAcceptanceTestRepository(session, owner_user_id=owner)
                await repository.create_plan(plan)
                await repository.create_plan(replan)
                await repository.create_run(run_value)
                await repository.create_review(sample_review())
            plan_row = {
                "id": uuid4(),
                "project_id": project,
                "owner_user_id": owner,
                "created_at": NOW,
                "locale": "it-IT",
                "reference": {},
                "application": {},
                "criteria": [],
                "replan_of": [],
                "snapshot_summary": {},
                "paths": [],
                "not_covered": [],
                "generation_ids": [],
                "cost_microusd": 0,
            }
            for changes in (
                {"locale": "i"},
                {"reference": []},
                {"application": []},
                {"criteria": {}},
                {"replan_of": {}},
                {"snapshot_summary": []},
                {"paths": {}},
                {"not_covered": {}},
                {"generation_ids": {}},
                {"cost_microusd": -1},
                {"project_id": uuid4()},
                {"owner_user_id": uuid4()},
            ):
                with pytest.raises(IntegrityError):
                    async with db.session_factory() as session, session.begin():
                        await session.execute(sa.insert(TEST_PLANS).values({**plan_row, **changes}))
            run_row = {
                "id": uuid4(),
                "project_id": project,
                "owner_user_id": owner,
                "plan_id": PLAN_ID,
                "replan_ids": [],
                "started_at": NOW,
                "finished_at": NOW,
                "recorded_at": NOW,
                "application": {},
                "browsers": [],
                "reference": {},
                "results": [],
                "not_covered": [],
                "criteria": [],
                "summary": {},
                "cost_microusd": 0,
            }
            for changes in (
                {"plan_id": uuid4()},
                {"replan_ids": {}},
                {"application": []},
                {"browsers": {}},
                {"reference": []},
                {"results": {}},
                {"not_covered": {}},
                {"criteria": {}},
                {"summary": []},
                {"cost_microusd": -1},
                {"finished_at": NOW - timedelta(seconds=1)},
            ):
                with pytest.raises(IntegrityError):
                    async with db.session_factory() as session, session.begin():
                        await session.execute(sa.insert(TEST_RUNS).values({**run_row, **changes}))
            review_row = {
                "id": uuid4(),
                "run_id": RUN_ID,
                "project_id": project,
                "owner_user_id": owner,
                "reviewed_at": NOW,
                "locale": "it-IT",
                "critiques": [],
                "generation_ids": [],
                "cost_microusd": 0,
            }
            for changes in (
                {"run_id": uuid4()},
                {"locale": "i"},
                {"critiques": {}},
                {"generation_ids": {}},
                {"cost_microusd": -1},
            ):
                with pytest.raises(IntegrityError):
                    async with db.session_factory() as session, session.begin():
                        await session.execute(
                            sa.insert(TEST_REVIEWS).values({**review_row, **changes})
                        )
            with pytest.raises(IntegrityError):
                async with db.session_factory() as session, session.begin():
                    await session.execute(sa.delete(TEST_PLANS).where(TEST_PLANS.c.id == PLAN_ID))
            async with db.session_factory() as session, session.begin():
                assert (
                    await count(session, TEST_PLANS),
                    await count(session, TEST_RUNS),
                    await count(session, TEST_REVIEWS),
                ) == (2, 1, 1)
                await session.execute(sa.delete(TEST_RUNS).where(TEST_RUNS.c.id == RUN_ID))
            async with db.session_factory() as session:
                assert (await count(session, TEST_RUNS), await count(session, TEST_REVIEWS)) == (
                    0,
                    0,
                )
        finally:
            await db.dispose()

    run(scenario())


def test_downgrade_restores_the_previous_revision_schema_exactly():
    assert MIGRATION.revision == "0064_acceptance_tests"
    assert MIGRATION.down_revision == "0063_code_changes"
    assert_reversible_migration(load_database_settings(env_file=None), MIGRATION)
