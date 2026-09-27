from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from orchestwin.artifacts.design_evaluation_persistence import (
    FINDINGS,
    RUNS,
    DesignEvaluationWriteStatus,
    SqlAlchemyDesignEvaluationRepository,
)
from orchestwin.artifacts.design_finding_validation_persistence import (
    VALIDATIONS,
    FindingValidationWriteStatus,
    SqlAlchemyFindingValidationRepository,
)
from orchestwin.artifacts.design_finding_validations import (
    FindingDecision,
    dismissed_finding_keys,
)
from orchestwin.persistence import create_database_runtime, load_database_settings
from src.test.python.artifacts.test_design_evaluation import (
    TWIN_A,
    TWIN_B,
    evaluate_async,
    template,
)
from src.test.python.integration.postgres_isolation import assert_reversible_migration
from src.test.python.integration.test_postgresql_design_loop import seed
from src.test.python.integration.test_proposal_evidence_postgres import database, run

__all__ = ["database"]

pytestmark = pytest.mark.integration

MIGRATION = importlib.import_module(
    "orchestwin.persistence.migrations.versions.0058_design_finding_validations"
)
NOW = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)


async def stored_run(db):
    owner, project, version = await seed(db)
    evaluation = await evaluate_async(
        version,
        {
            TWIN_A: (template("UTF-001", "SCR-001 Guest name", "The field lacks help."),),
            TWIN_B: (template("UTF-001", "SCR-001 Save", "The action is unclear."),),
        },
    )
    async with db.session_factory() as session, session.begin():
        status = await SqlAlchemyDesignEvaluationRepository(session, owner_user_id=owner).create(
            evaluation
        )
        assert status is DesignEvaluationWriteStatus.WRITTEN
    return owner, project, evaluation


def arguments(project, evaluation, **changes):
    return {
        "project_id": project,
        "evaluation_run_id": evaluation.id,
        "twin_id": TWIN_A,
        "finding_id": "UTF-001",
        "decision": FindingDecision.OWNER_DISMISSED,
        "note": None,
        "decided_at": NOW,
        **changes,
    }


async def count(session, table):
    return (await session.execute(sa.select(sa.func.count()).select_from(table))).scalar_one()


def test_owner_decisions_round_trip_with_per_finding_sequence_numbers(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, evaluation = await stored_run(db)
            written = []
            for twin_id, decision, note, minutes in (
                (TWIN_A, FindingDecision.OWNER_DISMISSED, "  Not   relevant ", 0),
                (TWIN_B, FindingDecision.OWNER_DISMISSED, None, 1),
                (TWIN_A, FindingDecision.OWNER_CONFIRMED, None, 2),
            ):
                async with db.session_factory() as session, session.begin():
                    result = await SqlAlchemyFindingValidationRepository(
                        session, owner_user_id=owner
                    ).append(
                        **arguments(
                            project,
                            evaluation,
                            twin_id=twin_id,
                            decision=decision,
                            note=note,
                            decided_at=NOW + timedelta(minutes=minutes),
                        )
                    )
                assert result.status is FindingValidationWriteStatus.WRITTEN
                written.append(result.validation)
            assert [item.sequence_number for item in written] == [1, 1, 2]
            assert written[0].note == "Not relevant"
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyFindingValidationRepository(session, owner_user_id=owner)
                for changes in (
                    {"finding_id": "UTF-002"},
                    {"twin_id": uuid4()},
                    {"evaluation_run_id": uuid4()},
                    {"project_id": uuid4()},
                ):
                    result = await repository.append(**arguments(project, evaluation, **changes))
                    assert result.status is FindingValidationWriteStatus.FINDING_NOT_FOUND
                    assert result.validation is None
                stranger = SqlAlchemyFindingValidationRepository(session, owner_user_id=uuid4())
                result = await stranger.append(**arguments(project, evaluation))
                assert result.status is FindingValidationWriteStatus.FINDING_NOT_FOUND
                assert await stranger.current(project_id=project) == ()
            async with db.session_factory() as session:
                current = await SqlAlchemyFindingValidationRepository(
                    session, owner_user_id=owner
                ).current(project_id=project)
                assert await count(session, VALIDATIONS) == 3
            assert current == (written[1], written[2])
            assert dismissed_finding_keys(current) == {(evaluation.id, TWIN_B, "UTF-001")}
            row = {
                "evaluation_run_id": evaluation.id,
                "twin_id": TWIN_A,
                "finding_id": "UTF-001",
                "sequence_number": 3,
                "project_id": project,
                "owner_user_id": owner,
                "decision": FindingDecision.OWNER_CONFIRMED.value,
                "note": None,
                "decided_at": NOW,
                "content_hash": "0" * 64,
                "validation_snapshot": {},
            }
            for changes in (
                {"decision": "USER_VALIDATED"},
                {"note": "x" * 1001},
                {"sequence_number": 0},
                {"finding_id": "UTF-777"},
            ):
                with pytest.raises(IntegrityError):
                    async with db.session_factory() as session, session.begin():
                        await session.execute(sa.insert(VALIDATIONS).values({**row, **changes}))
        finally:
            await db.dispose()

    run(scenario())


def test_deleting_a_run_cascades_to_its_findings_and_owner_decisions(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, evaluation = await stored_run(db)
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyFindingValidationRepository(session, owner_user_id=owner)
                for twin_id in (TWIN_A, TWIN_B, TWIN_A):
                    result = await repository.append(
                        **arguments(project, evaluation, twin_id=twin_id)
                    )
                    assert result.status is FindingValidationWriteStatus.WRITTEN
            async with db.session_factory() as session, session.begin():
                assert await count(session, VALIDATIONS) == 3
                await session.execute(sa.delete(RUNS).where(RUNS.c.id == evaluation.id))
            async with db.session_factory() as session:
                assert await count(session, FINDINGS) == 0
                assert await count(session, VALIDATIONS) == 0
                assert (
                    await SqlAlchemyFindingValidationRepository(
                        session, owner_user_id=owner
                    ).current(project_id=project)
                    == ()
                )
        finally:
            await db.dispose()

    run(scenario())


def test_downgrade_restores_the_previous_revision_schema_exactly():
    assert_reversible_migration(load_database_settings(env_file=None), MIGRATION)
