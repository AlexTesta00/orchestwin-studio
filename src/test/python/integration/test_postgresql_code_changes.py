from __future__ import annotations

import importlib
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from orchestwin.knowledge.state import ProjectStateSources
from orchestwin.persistence import create_database_runtime, load_database_settings
from orchestwin.persistence.migrate import downgrade_database, upgrade_database
from orchestwin.projects.code_change_state import SqlAlchemyProjectStateQueryService
from orchestwin.projects.code_changes import (
    AlignedPoint,
    AlignmentStatus,
    ChangeDecision,
    CodeChangeAmbiguous,
    DecisionKind,
    TaskOrigin,
    TaskSource,
    TaskStatus,
)
from orchestwin.projects.persistence.acceptance_tests import (
    TEST_RUNS,
    AcceptanceTestWriteStatus,
    SqlAlchemyAcceptanceTestRepository,
)
from orchestwin.projects.persistence.code_changes import (
    CHANGES,
    REVIEWS,
    TASKS,
    CodeChangeWriteStatus,
    SqlAlchemyCodeChangeRepository,
)
from src.test.python.integration.postgres_isolation import (
    assert_reversible_migration,
    isolated_postgres_settings,
)
from src.test.python.integration.test_postgresql_design_loop import seed
from src.test.python.integration.test_proposal_evidence_postgres import database, run
from src.test.python.projects.test_acceptance_tests import RUN_ID as TEST_RUN_ID
from src.test.python.projects.test_acceptance_tests import sample_plan, sample_review, sample_run
from src.test.python.projects.test_code_changes import (
    FIRST,
    NOW,
    SECOND,
    THIRD,
    TWIN_ONE,
    TWIN_TWO,
    code_change,
    critique,
    review_run,
    verdict,
)

__all__ = ["database"]

pytestmark = pytest.mark.integration

MIGRATION = importlib.import_module("orchestwin.persistence.migrations.versions.0063_code_changes")
SOURCES_MIGRATION = importlib.import_module(
    "orchestwin.persistence.migrations.versions.0065_code_task_sources"
)
OLD_TASKS = sa.table(
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
    sa.column("done_at", sa.DateTime(timezone=True)),
)
DATE_FINDING = "Il modulo non chiede la data di arrivo."
CURRENCY_FINDING = "Il totale non mostra la valuta che uso."


def changes():
    first = code_change(FIRST, number=1)
    second = code_change(SECOND, minutes=5, number=2, parent=FIRST)
    third = code_change(THIRD, minutes=10, number=3, parent=SECOND, author=None)
    return first, second, third


def decision(kind, minutes=120, note=None):
    return ChangeDecision(kind=kind, decided_at=NOW + timedelta(minutes=minutes), note=note)


def verdict_sources(change, *texts, requirements=(), screens=()):
    return [
        TaskSource(
            origin=TaskOrigin.CODE_CHANGE,
            text=text,
            change_id=change.id,
            commit=change.commit,
            requirements=tuple(requirements),
            screens=tuple(screens),
        )
        for text in texts
    ]


def change_finding(change, text=DATE_FINDING, twin_id=TWIN_ONE):
    return TaskSource(
        origin=TaskOrigin.CODE_CHANGE,
        text="Aggiungere il campo della data di arrivo.",
        change_id=change.id,
        commit=change.commit,
        twin_id=twin_id,
        twin_name="Receptionist Twin",
        finding=text,
        requirements=("REQ-001",),
        screens=("SCR-001",),
    )


def run_finding(text=CURRENCY_FINDING, run_id=TEST_RUN_ID):
    return TaskSource(
        origin=TaskOrigin.TEST_RUN,
        text="Mostrare la valuta accanto al totale.",
        test_run_id=run_id,
        twin_id=TWIN_ONE,
        twin_name="Receptionist Twin",
        finding=text,
        requirements=("REQ-001",),
        screens=("SCR-001",),
        criteria=("AC-001",),
    )


def owner_source(text="Scrivere la guida per la reception."):
    return TaskSource(origin=TaskOrigin.OWNER, text=text)


async def count(session, table):
    return (await session.execute(sa.select(sa.func.count()).select_from(table))).scalar_one()


async def record_run(db, owner):
    plan = sample_plan()
    run_value = sample_run((plan,))
    async with db.session_factory() as session, session.begin():
        tests = SqlAlchemyAcceptanceTestRepository(session, owner_user_id=owner)
        assert await tests.create_plan(plan) is AcceptanceTestWriteStatus.RECORDED
        assert await tests.create_run(run_value) is AcceptanceTestWriteStatus.RECORDED
        assert await tests.create_review(sample_review()) is AcceptanceTestWriteStatus.RECORDED
    return run_value


def test_changes_runs_decisions_and_tasks_round_trip_into_the_project_state(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, _ = await seed(db)
            first, second, third = changes()
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyCodeChangeRepository(session, owner_user_id=owner)
                assert await repository.aligned_point(project) is None
                for change in (first, second, third):
                    result = await repository.record(change)
                    assert result.status is CodeChangeWriteStatus.RECORDED
                    assert result.change == change
                again = await repository.record(replace(first, id=uuid4(), message="Altro"))
                assert again.status is CodeChangeWriteStatus.ALREADY_RECORDED
                assert again.change == first
            stranger_id = uuid4()
            async with db.session_factory() as session, session.begin():
                stranger = SqlAlchemyCodeChangeRepository(session, owner_user_id=stranger_id)
                assert not await stranger.project_exists(project)
                refused = await stranger.record(
                    replace(first, id=uuid4(), owner_user_id=stranger_id)
                )
                assert refused.status is CodeChangeWriteStatus.PROJECT_NOT_FOUND
                assert await stranger.list(project) == ()
                assert await stranger.get(project, FIRST) is None
            async with db.session_factory() as session:
                repository = SqlAlchemyCodeChangeRepository(session, owner_user_id=owner)
                assert await repository.project_exists(project)
                listed = await repository.list(project)
                assert listed == tuple(replace(item, diff=None) for item in (third, second, first))
                assert await repository.list(project, limit=1) == (replace(third, diff=None),)
                assert await repository.count(project) == 3
                assert await repository.get(project, FIRST[:7].upper()) == first
                assert await repository.get(project, "9" * 40) is None
                assert await repository.get(project, "abc") is None

            one = review_run(
                first,
                id=uuid4(),
                critiques=(critique(), critique(TWIN_TWO, "Night Auditor Twin")),
                alignment=verdict(AlignmentStatus.CODE_DRIFT),
            )
            two = review_run(
                first,
                id=uuid4(),
                reviewed_at=one.reviewed_at + timedelta(hours=1),
                alignment=verdict(AlignmentStatus.DESIGN_OUTDATED),
                design_version_number=2,
                generation_ids=(),
                cost_microusd=0,
            )
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyCodeChangeRepository(session, owner_user_id=owner)
                for item in (one, two):
                    assert await repository.create_run(item) is CodeChangeWriteStatus.RECORDED
                assert (
                    await repository.create_run(replace(one, id=uuid4(), change_id=uuid4()))
                    is CodeChangeWriteStatus.CHANGE_NOT_FOUND
                )
                assert (
                    await repository.create_run(replace(one, id=uuid4(), commit=SECOND))
                    is CodeChangeWriteStatus.CHANGE_NOT_FOUND
                )
            async with db.session_factory() as session:
                repository = SqlAlchemyCodeChangeRepository(session, owner_user_id=owner)
                assert await repository.runs(first.id) == (two, one)
                assert await repository.latest_run(first.id) == two
                assert await repository.latest_run(second.id) is None
                assert await repository.project_runs(project) == (two, one)
                assert (await repository.get(project, FIRST)).review == two.summary()
                assert [item.review for item in await repository.list(project)] == [
                    None,
                    None,
                    two.summary(),
                ]

            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyCodeChangeRepository(session, owner_user_id=owner)
                tasked = await repository.decide(
                    first.id, decision(DecisionKind.CODE_TASKS, note="Da fare.")
                )
                assert tasked.decision.kind is DecisionKind.CODE_TASKS
                assert tasked.review == two.summary()
                created = await repository.create_tasks(
                    project,
                    verdict_sources(
                        first,
                        "Ripristinare il pulsante.",
                        "Aggiungere la data.",
                        requirements=("REQ-001",),
                        screens=("SCR-001",),
                    ),
                    created_at=NOW + timedelta(hours=3),
                )
                assert [item.code for item in created.tasks] == ["TSK-001", "TSK-002"]
                assert created.created == 2
                later = await repository.create_tasks(
                    project,
                    verdict_sources(third, "Terzo compito."),
                    created_at=NOW + timedelta(hours=3),
                )
                assert [item.code for item in later.tasks] == ["TSK-003"]
                aligned = await repository.decide(
                    second.id, decision(DecisionKind.ALIGNED), aligned_versions=(2, 3)
                )
                assert (aligned.aligned_requirements_version, aligned.aligned_design_version) == (
                    2,
                    3,
                )
                closing = NOW + timedelta(hours=4)
                assert await repository.close_open_tasks(project, uuid4(), closing) == 0
                stranger = SqlAlchemyCodeChangeRepository(session, owner_user_id=stranger_id)
                assert await stranger.close_open_tasks(project, third.id, closing) == 0
                assert await repository.close_open_tasks(project, second.id, closing) == 2
                assert await repository.close_open_tasks(project, first.id, closing) == 0
                assert await repository.decide(uuid4(), decision(DecisionKind.DISMISSED)) is None
                with pytest.raises(ValueError):
                    await repository.create_tasks(
                        project,
                        verdict_sources(replace(first, id=uuid4()), "Nessuno."),
                        created_at=NOW,
                    )
            async with db.session_factory() as session:
                repository = SqlAlchemyCodeChangeRepository(session, owner_user_id=owner)
                point = await repository.aligned_point(project)
                assert point == AlignedPoint(
                    commit=SECOND,
                    decided_at=NOW + timedelta(minutes=120),
                    requirements_version_number=2,
                    design_version_number=3,
                )
                assert [
                    item.commit for item in await repository.list(project, pending_only=True)
                ] == [THIRD]
                assert await repository.count(project, pending_only=True) == 1
                tasks = await repository.tasks(project)
                assert [(item.code, item.status) for item in tasks] == [
                    ("TSK-001", TaskStatus.DONE),
                    ("TSK-002", TaskStatus.DONE),
                    ("TSK-003", TaskStatus.OPEN),
                ]
                assert tasks[0].requirements == ("REQ-001",)
                assert tasks[0].from_commit == FIRST
                assert tasks[0].closed_at == NOW + timedelta(hours=4)
                assert await repository.tasks(project, open_only=True) == (tasks[2],)
                newest_first = await repository.list(project)

            sources = await SqlAlchemyProjectStateQueryService(db.session_factory).current(
                owner_user_id=owner, project_id=project
            )
            assert isinstance(sources, ProjectStateSources)
            assert sources.aligned == point.to_snapshot()
            assert sources.changes == tuple(item.to_snapshot() for item in newest_first)
            assert [item["commit"] for item in sources.changes] == [THIRD, SECOND, FIRST]
            assert all("diff" not in item for item in sources.changes)
            review = sources.changes[2]["review"]
            assert review == two.summary().to_snapshot()
            assert review["reference"] == {
                "requirements_version_number": 1,
                "design_version_number": 2,
                "alternative_code": "DES-001",
            }
            assert "stale" not in review
            assert sources.changes[1]["decision"]["kind"] == "ALIGNED"
            assert sources.runs == (two.to_snapshot(), one.to_snapshot())
            assert sources.tasks == tuple(item.to_snapshot() for item in tasks)
            assert sources.tasks[0]["origin"]["kind"] == "CODE_CHANGE"
            assert (sources.pending_changes, sources.open_tasks) == (1, 1)
            assert sources.learning == ()
            empty = await SqlAlchemyProjectStateQueryService(db.session_factory).current(
                owner_user_id=stranger_id, project_id=project
            )
            assert empty == ProjectStateSources()
            assert empty.is_empty
        finally:
            await db.dispose()

    run(scenario())


def test_tasks_of_every_origin_round_trip_and_close_with_the_aligned_change(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, _ = await seed(db)
            first, second, third = changes()
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyCodeChangeRepository(session, owner_user_id=owner)
                for change in (first, second, third):
                    assert (await repository.record(change)).status is (
                        CodeChangeWriteStatus.RECORDED
                    )
            recorded_run = await record_run(db, owner)

            async def created(source, minutes):
                async with db.session_factory() as session, session.begin():
                    repository = SqlAlchemyCodeChangeRepository(session, owner_user_id=owner)
                    return await repository.create_tasks(
                        project, [source], created_at=NOW + timedelta(minutes=minutes)
                    )

            owner_early = await created(owner_source(), 1)
            run_early = await created(run_finding(), 5.5)
            from_first = await created(change_finding(first), 60)
            owner_late = await created(owner_source("Aggiornare il manuale."), 8)
            run_late = await created(run_finding("Il pulsante Calcola non risponde."), 20)
            from_third = await created(verdict_sources(third, "Terzo compito.")[0], 2)
            again = await created(change_finding(first), 90)
            other_text = await created(change_finding(first, "Manca il pulsante di stampa."), 91)
            assert [item.created for item in (again, other_text)] == [0, 1]
            assert again.tasks == from_first.tasks
            assert [
                item.tasks[0].code
                for item in (owner_early, run_early, from_first, owner_late, run_late, from_third)
            ] == ["TSK-001", "TSK-002", "TSK-003", "TSK-004", "TSK-005", "TSK-006"]
            assert other_text.tasks[0].code == "TSK-007"
            with pytest.raises(ValueError):
                await created(run_finding(run_id=uuid4()), 3)
            with pytest.raises(ValueError):
                await created(replace(change_finding(first), commit=SECOND), 3)
            async with db.session_factory() as session:
                repository = SqlAlchemyCodeChangeRepository(session, owner_user_id=owner)
                tasks = await repository.tasks(project)
                assert await repository.task(project, 2) == tasks[1]
                assert await repository.task(project, 99) is None
                stranger = SqlAlchemyCodeChangeRepository(session, owner_user_id=uuid4())
                assert await stranger.tasks(project) == ()
                assert await stranger.task(project, 1) is None
            assert [task.origin for task in tasks] == [
                TaskOrigin.OWNER,
                TaskOrigin.TEST_RUN,
                TaskOrigin.CODE_CHANGE,
                TaskOrigin.OWNER,
                TaskOrigin.TEST_RUN,
                TaskOrigin.CODE_CHANGE,
                TaskOrigin.CODE_CHANGE,
            ]
            assert tasks == (
                *owner_early.tasks,
                *run_early.tasks,
                *from_first.tasks,
                *owner_late.tasks,
                *run_late.tasks,
                *from_third.tasks,
                *other_text.tasks,
            )
            assert tasks[1].test_run_id == recorded_run.id
            assert tasks[1].criteria == ("AC-001",)
            assert tasks[2].to_snapshot()["origin"] == {
                "kind": "CODE_CHANGE",
                "commit": FIRST,
                "test_run_id": None,
                "twin_id": str(TWIN_ONE),
                "twin_name": "Receptionist Twin",
                "finding": DATE_FINDING,
            }
            assert tasks[0].to_snapshot()["from_commit"] is None

            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyCodeChangeRepository(session, owner_user_id=owner)
                await repository.decide(second.id, decision(DecisionKind.ALIGNED))
                assert (
                    await repository.close_open_tasks(project, second.id, NOW + timedelta(hours=2))
                    == 4
                )
                dropped = await repository.set_task_status(
                    project,
                    5,
                    TaskStatus.DROPPED,
                    at=NOW + timedelta(hours=3),
                    note="Non serve.",
                )
                assert (dropped.status, dropped.closed_at, dropped.note) == (
                    TaskStatus.DROPPED,
                    NOW + timedelta(hours=3),
                    "Non serve.",
                )
                reopened = await repository.set_task_status(
                    project, 5, TaskStatus.OPEN, at=NOW + timedelta(hours=4), note="Serve."
                )
                assert (reopened.status, reopened.closed_at, reopened.note) == (
                    TaskStatus.OPEN,
                    None,
                    "Serve.",
                )
                assert (
                    await repository.set_task_status(project, 99, TaskStatus.DONE, at=NOW) is None
                )
                stranger = SqlAlchemyCodeChangeRepository(session, owner_user_id=uuid4())
                assert await stranger.set_task_status(project, 5, TaskStatus.DONE, at=NOW) is None
            async with db.session_factory() as session:
                repository = SqlAlchemyCodeChangeRepository(session, owner_user_id=owner)
                middle = await repository.tasks(project)
            assert [(task.code, task.status) for task in middle] == [
                ("TSK-001", TaskStatus.DONE),
                ("TSK-002", TaskStatus.DONE),
                ("TSK-003", TaskStatus.DONE),
                ("TSK-004", TaskStatus.OPEN),
                ("TSK-005", TaskStatus.OPEN),
                ("TSK-006", TaskStatus.OPEN),
                ("TSK-007", TaskStatus.DONE),
            ]
            assert middle[4].note == "Serve."
            assert all(
                task.closed_at == NOW + timedelta(hours=2) and task.note is None
                for task in middle
                if not task.open
            )
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyCodeChangeRepository(session, owner_user_id=owner)
                again_done = await repository.set_task_status(
                    project, 1, TaskStatus.DONE, at=NOW + timedelta(days=1), note="Visto."
                )
                assert (again_done.closed_at, again_done.note) == (
                    NOW + timedelta(hours=2),
                    "Visto.",
                )
                await repository.decide(third.id, decision(DecisionKind.ALIGNED, minutes=180))
                assert (
                    await repository.close_open_tasks(project, third.id, NOW + timedelta(hours=5))
                    == 2
                )
            async with db.session_factory() as session:
                repository = SqlAlchemyCodeChangeRepository(session, owner_user_id=owner)
                final = await repository.tasks(project)
            assert [task.code for task in final if task.open] == ["TSK-005"]
            sources = await SqlAlchemyProjectStateQueryService(db.session_factory).current(
                owner_user_id=owner, project_id=project
            )
            assert sources.tasks == tuple(task.to_snapshot() for task in final)
            assert sources.open_tasks == 1
            assert [item["status"] for item in sources.tasks] == [
                "DONE",
                "DONE",
                "DONE",
                "DONE",
                "OPEN",
                "DONE",
                "DONE",
            ]
            assert sources.tasks[0]["note"] == "Visto."
        finally:
            await db.dispose()

    run(scenario())


def test_a_prefix_shared_by_two_commits_is_ambiguous_and_the_same_commit_is_unique(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, _ = await seed(db)
            left = code_change("abcdef1" + "0" * 33, number=1)
            right = code_change("abcdef1" + "f" * 33, minutes=1, number=2)
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyCodeChangeRepository(session, owner_user_id=owner)
                for item in (left, right):
                    assert (await repository.record(item)).status is CodeChangeWriteStatus.RECORDED
            async with db.session_factory() as session:
                repository = SqlAlchemyCodeChangeRepository(session, owner_user_id=owner)
                with pytest.raises(CodeChangeAmbiguous):
                    await repository.get(project, "ABCDEF1")
                assert await repository.get(project, "abcdef10") == left
                assert await repository.get(project, left.commit) == left
            with pytest.raises(IntegrityError):
                async with db.session_factory() as session, session.begin():
                    await session.execute(
                        sa.insert(CHANGES).values(
                            id=uuid4(),
                            project_id=project,
                            owner_user_id=owner,
                            commit=left.commit,
                            committed_at=NOW,
                            message="Doppio",
                            files=[],
                            diff="",
                            recorded_at=NOW,
                        )
                    )
        finally:
            await db.dispose()

    run(scenario())


def test_the_tables_refuse_rows_outside_the_limits_and_cascade_from_the_change(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, _ = await seed(db)
            first = code_change(FIRST)
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyCodeChangeRepository(session, owner_user_id=owner)
                assert (await repository.record(first)).status is CodeChangeWriteStatus.RECORDED
                assert await repository.create_run(review_run(first)) is (
                    CodeChangeWriteStatus.RECORDED
                )
                await repository.create_tasks(
                    project, verdict_sources(first, "Un compito."), created_at=NOW
                )
            recorded_run = await record_run(db, owner)
            change_row = {
                "id": uuid4(),
                "project_id": project,
                "owner_user_id": owner,
                "commit": SECOND,
                "parent": None,
                "committed_at": NOW,
                "author": None,
                "message": "Un messaggio",
                "files": [],
                "diff": "",
                "recorded_at": NOW,
                "decision_kind": None,
                "decision_note": None,
                "decided_at": None,
                "aligned_requirements_version": None,
                "aligned_design_version": None,
            }
            for changes_to_row in (
                {"commit": "ABCDEF1"},
                {"commit": "abcdef"},
                {"parent": SECOND},
                {"parent": "xyz"},
                {"message": ""},
                {"message": "x" * 2001},
                {"author": ""},
                {"files": {}},
                {"diff": "x" * 65537},
                {"decision_kind": "LATER", "decided_at": NOW},
                {"decision_kind": "DISMISSED"},
                {"decided_at": NOW},
                {"decision_note": "Una nota"},
                {"aligned_requirements_version": 1},
                {"decision_kind": "DISMISSED", "decided_at": NOW, "aligned_design_version": 2},
                {"decision_kind": "ALIGNED", "decided_at": NOW, "aligned_design_version": 0},
            ):
                with pytest.raises(IntegrityError):
                    async with db.session_factory() as session, session.begin():
                        await session.execute(
                            sa.insert(CHANGES).values({**change_row, **changes_to_row})
                        )
            run_row = {
                "id": uuid4(),
                "change_id": first.id,
                "project_id": project,
                "owner_user_id": owner,
                "reviewed_at": NOW,
                "locale": "it-IT",
                "reference": {},
                "critiques": [],
                "alignment": {"status": "ALIGNED"},
                "generation_ids": [],
                "cost_microusd": 0,
            }
            for changes_to_row in (
                {"alignment": {"status": "LATER"}},
                {"alignment": {}},
                {"critiques": {}},
                {"reference": []},
                {"generation_ids": {}},
                {"cost_microusd": -1},
                {"locale": "i"},
                {"change_id": uuid4()},
            ):
                with pytest.raises(IntegrityError):
                    async with db.session_factory() as session, session.begin():
                        await session.execute(
                            sa.insert(REVIEWS).values({**run_row, **changes_to_row})
                        )
            task_row = {
                "id": uuid4(),
                "project_id": project,
                "owner_user_id": owner,
                "number": 2,
                "code": "TSK-002",
                "text": "Un altro compito.",
                "about": {"requirements": [], "screens": [], "criteria": []},
                "from_change_id": first.id,
                "created_at": NOW,
                "status": "OPEN",
                "closed_at": None,
                "origin": "CODE_CHANGE",
                "test_run_id": None,
                "twin_id": None,
                "twin_name": None,
                "finding_text": None,
                "note": None,
            }
            twin = {"twin_id": uuid4(), "twin_name": "Receptionist Twin", "finding_text": "Uno."}
            from_run = {
                "origin": "TEST_RUN",
                "from_change_id": None,
                "test_run_id": recorded_run.id,
                **twin,
            }
            owner_row = {"origin": "OWNER", "from_change_id": None}
            for changes_to_row in (
                {"number": 1, "code": "TSK-001"},
                {"number": 0},
                {"code": "TASK-2"},
                {"text": ""},
                {"about": []},
                {"status": "LATER"},
                {"status": "DONE"},
                {"status": "DROPPED"},
                {"closed_at": NOW},
                {"from_change_id": uuid4()},
                {"from_change_id": None},
                {"origin": "MODEL"},
                {"origin": "TEST_RUN"},
                {"origin": "OWNER"},
                {"test_run_id": recorded_run.id},
                {**from_run, "test_run_id": uuid4()},
                {**from_run, "test_run_id": None},
                {**from_run, "from_change_id": first.id},
                {**from_run, "twin_id": None, "twin_name": None, "finding_text": None},
                {**owner_row, "test_run_id": recorded_run.id},
                {**owner_row, **twin},
                {"twin_id": uuid4()},
                {**twin, "twin_name": None},
                {**twin, "finding_text": None},
                {**twin, "twin_name": ""},
                {**twin, "finding_text": ""},
                {"note": ""},
            ):
                with pytest.raises(IntegrityError):
                    async with db.session_factory() as session, session.begin():
                        await session.execute(
                            sa.insert(TASKS).values({**task_row, **changes_to_row})
                        )
            accepted = (
                {"id": uuid4(), "number": 3, "code": "TSK-003", **from_run},
                {"id": uuid4(), "number": 4, "code": "TSK-004", **owner_row, "note": "Scritta."},
                {
                    "id": uuid4(),
                    "number": 5,
                    "code": "TSK-005",
                    "status": "DROPPED",
                    "closed_at": NOW,
                    **twin,
                },
            )
            async with db.session_factory() as session, session.begin():
                for values in accepted:
                    await session.execute(sa.insert(TASKS).values({**task_row, **values}))
            async with db.session_factory() as session, session.begin():
                assert (await count(session, REVIEWS), await count(session, TASKS)) == (1, 4)
                await session.execute(sa.delete(TEST_RUNS).where(TEST_RUNS.c.id == recorded_run.id))
            async with db.session_factory() as session, session.begin():
                assert await count(session, TASKS) == 3
                await session.execute(sa.delete(CHANGES).where(CHANGES.c.id == first.id))
            async with db.session_factory() as session:
                assert (
                    await count(session, CHANGES),
                    await count(session, REVIEWS),
                    await count(session, TASKS),
                ) == (0, 0, 1)
        finally:
            await db.dispose()

    run(scenario())


def test_a_task_stored_before_the_origins_reads_as_a_task_of_a_code_change():
    settings = load_database_settings(env_file=None)
    first = code_change(FIRST)
    identifiers = (UUID(int=0xD001), UUID(int=0xD002))
    with isolated_postgres_settings(settings, revision=SOURCES_MIGRATION.down_revision) as scoped:

        async def before():
            db = create_database_runtime(scoped)
            try:
                owner, project, _ = await seed(db)
                async with db.session_factory() as session, session.begin():
                    repository = SqlAlchemyCodeChangeRepository(session, owner_user_id=owner)
                    assert (await repository.record(first)).status is (
                        CodeChangeWriteStatus.RECORDED
                    )
                    for number, identifier in enumerate(identifiers, 1):
                        await session.execute(
                            sa.insert(OLD_TASKS).values(
                                id=identifier,
                                project_id=project,
                                owner_user_id=owner,
                                number=number,
                                code=f"TSK-{number:03d}",
                                text=f"Compito numero {number}.",
                                about={"requirements": ["REQ-001"], "screens": []},
                                from_change_id=first.id,
                                created_at=NOW,
                                status="OPEN" if number == 1 else "DONE",
                                done_at=None if number == 1 else NOW + timedelta(hours=1),
                            )
                        )
                return owner, project
            finally:
                await db.dispose()

        owner, project = run(before())
        upgrade_database(scoped, revision=SOURCES_MIGRATION.revision)

        async def after():
            db = create_database_runtime(scoped)
            try:
                async with db.session_factory() as session:
                    repository = SqlAlchemyCodeChangeRepository(session, owner_user_id=owner)
                    return await repository.tasks(project)
            finally:
                await db.dispose()

        opened, done = run(after())
    assert [task.id for task in (opened, done)] == list(identifiers)
    for task in (opened, done):
        assert task.origin is TaskOrigin.CODE_CHANGE
        assert (task.from_change_id, task.from_commit) == (first.id, FIRST)
        assert (task.test_run_id, task.twin_id, task.twin_name, task.finding) == (
            None,
            None,
            None,
            None,
        )
        assert (task.criteria, task.note) == ((), None)
    assert (opened.status, opened.closed_at) == (TaskStatus.OPEN, None)
    assert (done.status, done.closed_at) == (TaskStatus.DONE, NOW + timedelta(hours=1))
    assert done.to_snapshot() == {
        "code": "TSK-002",
        "text": "Compito numero 2.",
        "about": {"requirements": ["REQ-001"], "screens": [], "criteria": []},
        "origin": {
            "kind": "CODE_CHANGE",
            "commit": FIRST,
            "test_run_id": None,
            "twin_id": None,
            "twin_name": None,
            "finding": None,
        },
        "from_commit": FIRST,
        "created_at": "2026-09-29T10:00:00+00:00",
        "status": "DONE",
        "closed_at": "2026-09-29T11:00:00+00:00",
        "note": None,
    }


def test_the_downgrade_keeps_the_tasks_the_old_table_can_hold():
    settings = load_database_settings(env_file=None)
    first = code_change(FIRST)
    with isolated_postgres_settings(settings, revision=SOURCES_MIGRATION.revision) as scoped:

        async def before():
            db = create_database_runtime(scoped)
            try:
                owner, project, _ = await seed(db)
                async with db.session_factory() as session, session.begin():
                    repository = SqlAlchemyCodeChangeRepository(session, owner_user_id=owner)
                    assert (await repository.record(first)).status is (
                        CodeChangeWriteStatus.RECORDED
                    )
                recorded = await record_run(db, owner)
                async with db.session_factory() as session, session.begin():
                    repository = SqlAlchemyCodeChangeRepository(session, owner_user_id=owner)
                    await repository.create_tasks(
                        project,
                        [
                            *verdict_sources(first, "Dal verdetto.", "Da lasciare."),
                            change_finding(first),
                            run_finding(run_id=recorded.id),
                            owner_source(),
                        ],
                        created_at=NOW,
                    )
                    await repository.set_task_status(
                        project, 2, TaskStatus.DROPPED, at=NOW + timedelta(hours=1), note="No."
                    )
            finally:
                await db.dispose()

        run(before())
        downgrade_database(scoped, revision=SOURCES_MIGRATION.down_revision)

        async def after():
            db = create_database_runtime(scoped)
            try:
                async with db.session_factory() as session:
                    statement = sa.select(
                        OLD_TASKS.c.code, OLD_TASKS.c.status, OLD_TASKS.c.done_at
                    ).order_by(OLD_TASKS.c.number)
                    return (await session.execute(statement)).all()
            finally:
                await db.dispose()

        rows = run(after())
    assert [tuple(row) for row in rows] == [
        ("TSK-001", "OPEN", None),
        ("TSK-002", "DONE", NOW + timedelta(hours=1)),
        ("TSK-003", "OPEN", None),
    ]


def test_downgrade_restores_the_previous_revision_schema_exactly():
    assert MIGRATION.down_revision == "0062_hosted_model_providers"
    assert_reversible_migration(load_database_settings(env_file=None), MIGRATION)


def test_the_downgrade_of_the_task_sources_restores_the_previous_schema_exactly():
    assert SOURCES_MIGRATION.revision == "0065_code_task_sources"
    assert SOURCES_MIGRATION.down_revision == "0064_acceptance_tests"
    assert_reversible_migration(load_database_settings(env_file=None), SOURCES_MIGRATION)
