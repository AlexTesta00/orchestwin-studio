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
from orchestwin.projects.code_change_state import SqlAlchemyProjectStateQueryService
from orchestwin.projects.code_changes import (
    AlignedPoint,
    AlignmentStatus,
    ChangeDecision,
    CodeChangeAmbiguous,
    DecisionKind,
    TaskStatus,
)
from orchestwin.projects.persistence.code_changes import (
    CHANGES,
    REVIEWS,
    TASKS,
    CodeChangeWriteStatus,
    SqlAlchemyCodeChangeRepository,
)
from src.test.python.integration.postgres_isolation import assert_reversible_migration
from src.test.python.integration.test_postgresql_design_loop import seed
from src.test.python.integration.test_proposal_evidence_postgres import database, run
from src.test.python.projects.test_code_changes import (
    FIRST,
    NOW,
    SECOND,
    THIRD,
    TWIN_TWO,
    code_change,
    critique,
    review_run,
    verdict,
)

__all__ = ["database"]

pytestmark = pytest.mark.integration

MIGRATION = importlib.import_module("orchestwin.persistence.migrations.versions.0063_code_changes")


def changes():
    first = code_change(FIRST, number=1)
    second = code_change(SECOND, minutes=5, number=2, parent=FIRST)
    third = code_change(THIRD, minutes=10, number=3, parent=SECOND, author=None)
    return first, second, third


def decision(kind, minutes=120, note=None):
    return ChangeDecision(kind=kind, decided_at=NOW + timedelta(minutes=minutes), note=note)


async def count(session, table):
    return (await session.execute(sa.select(sa.func.count()).select_from(table))).scalar_one()


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
                    first.id,
                    ["Ripristinare  il pulsante.", "Aggiungere la data."],
                    created_at=NOW + timedelta(hours=3),
                    requirements=("REQ-001",),
                    screens=("SCR-001",),
                )
                assert [item.code for item in created] == ["TSK-001", "TSK-002"]
                assert created[0].text == "Ripristinare il pulsante."
                later = await repository.create_tasks(
                    project, third.id, ["Terzo compito."], created_at=NOW + timedelta(hours=3)
                )
                assert [item.code for item in later] == ["TSK-003"]
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
                    await repository.create_tasks(project, uuid4(), ["Nessuno."], created_at=NOW)
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
                assert tasks[0].done_at == NOW + timedelta(hours=4)
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
            assert sources.changes[2]["review"] == two.summary().to_snapshot()
            assert sources.changes[1]["decision"]["kind"] == "ALIGNED"
            assert sources.runs == (two.to_snapshot(), one.to_snapshot())
            assert sources.tasks == tuple(item.to_snapshot() for item in tasks)
            assert (sources.pending_changes, sources.open_tasks) == (1, 1)
            empty = await SqlAlchemyProjectStateQueryService(db.session_factory).current(
                owner_user_id=stranger_id, project_id=project
            )
            assert empty == ProjectStateSources()
            assert empty.is_empty
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
                await repository.create_tasks(project, first.id, ["Un compito."], created_at=NOW)
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
                "about": {"requirements": [], "screens": []},
                "from_change_id": first.id,
                "created_at": NOW,
                "status": "OPEN",
                "done_at": None,
            }
            for changes_to_row in (
                {"number": 1, "code": "TSK-001"},
                {"number": 0},
                {"code": "TASK-2"},
                {"text": ""},
                {"about": []},
                {"status": "LATER"},
                {"status": "DONE"},
                {"done_at": NOW},
                {"from_change_id": uuid4()},
            ):
                with pytest.raises(IntegrityError):
                    async with db.session_factory() as session, session.begin():
                        await session.execute(
                            sa.insert(TASKS).values({**task_row, **changes_to_row})
                        )
            async with db.session_factory() as session, session.begin():
                assert (await count(session, REVIEWS), await count(session, TASKS)) == (1, 1)
                await session.execute(sa.delete(CHANGES).where(CHANGES.c.id == first.id))
            async with db.session_factory() as session:
                assert (
                    await count(session, CHANGES),
                    await count(session, REVIEWS),
                    await count(session, TASKS),
                ) == (0, 0, 0)
        finally:
            await db.dispose()

    run(scenario())


def test_downgrade_restores_the_previous_revision_schema_exactly():
    assert MIGRATION.down_revision == "0062_hosted_model_providers"
    assert_reversible_migration(load_database_settings(env_file=None), MIGRATION)
