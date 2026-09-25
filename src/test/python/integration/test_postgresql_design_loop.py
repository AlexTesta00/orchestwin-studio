from __future__ import annotations

import importlib
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa

from orchestwin.artifacts.design_evaluation_persistence import (
    DesignEvaluationWriteStatus,
    SqlAlchemyDesignEvaluationRepository,
)
from orchestwin.artifacts.design_persistence import SqlAlchemyDesignPackageRepository
from orchestwin.identity.persistence.models import UserRecord
from orchestwin.persistence import create_database_runtime, load_database_settings
from orchestwin.projects.briefs import create_project_brief
from orchestwin.projects.insight_applications import (
    InsightSourceKind,
    InsightTarget,
    create_insight_application,
)
from orchestwin.projects.persistence.insight_applications import (
    InsightApplicationWriteStatus,
    SqlAlchemyInsightApplicationRepository,
)
from orchestwin.projects.persistence.models import ProjectBriefVersionRecord, ProjectRecord
from src.test.python.artifacts import design_fixtures
from src.test.python.artifacts.test_design_evaluation import (
    TWIN_A,
    TWIN_B,
    evaluate_async,
    template,
)
from src.test.python.integration.postgres_isolation import assert_reversible_migration
from src.test.python.integration.test_proposal_evidence_postgres import database, run

__all__ = ["database"]

pytestmark = pytest.mark.integration

MIGRATION = importlib.import_module(
    "orchestwin.persistence.migrations.versions.0057_design_evaluation_loop"
)
NOW = datetime(2026, 9, 25, 21, 0, tzinfo=UTC)


async def seed(db):
    owner, project = design_fixtures.OWNER_ID, design_fixtures.PROJECT_ID
    brief = create_project_brief(description="Una reception per le prenotazioni.")
    async with db.session_factory() as session, session.begin():
        session.add(
            UserRecord(
                id=owner,
                email_normalized=f"{owner}@synthetic.invalid",
                password_hash="NO_LOGIN_SYNTHETIC",
            )
        )
        await session.flush()
        session.add(
            ProjectRecord(
                id=project,
                owner_user_id=owner,
                display_name="Synthetic design loop",
                mode="GREENFIELD_GENERATION",
                current_brief_version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.flush()
        session.add(
            ProjectBriefVersionRecord(
                id=uuid4(),
                project_id=project,
                version_number=1,
                schema_version=brief.SCHEMA_VERSION,
                content=brief.to_snapshot(),
                content_hash=brief.content_hash,
                created_by_user_id=owner,
                created_at=NOW,
            )
        )
    version = design_fixtures.design_version()
    async with db.session_factory() as session, session.begin():
        status = await SqlAlchemyDesignPackageRepository(session, owner_user_id=owner).append(
            version
        )
        assert status.value == "APPENDED"
    return owner, project, version


def test_evaluation_runs_and_insight_applications_round_trip(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, version = await seed(db)
            first = await evaluate_async(
                version,
                {
                    TWIN_A: (template("UTF-001", "SCR-001 Guest name", "The field lacks help."),),
                    TWIN_B: (template("UTF-001", "SCR-001 Save", "The action is unclear."),),
                },
            )
            async with db.engine.connect() as connection:
                primary_key = await connection.run_sync(
                    lambda sync: sa.inspect(sync).get_pk_constraint("design_synthetic_findings")
                )
            assert primary_key["constrained_columns"] == [
                "evaluation_run_id",
                "twin_id",
                "finding_id",
            ]
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyDesignEvaluationRepository(session, owner_user_id=owner)
                assert await repository.latest(project_id=project) is None
                assert await repository.create(first) is DesignEvaluationWriteStatus.WRITTEN
                assert await repository.create(first) is DesignEvaluationWriteStatus.RUN_EXISTS
            foreign = uuid4()
            async with db.session_factory() as session, session.begin():
                stranger = SqlAlchemyDesignEvaluationRepository(session, owner_user_id=foreign)
                assert await stranger.create(first) is DesignEvaluationWriteStatus.PROJECT_NOT_FOUND
                assert await stranger.list(project_id=project) == ()
            async with db.session_factory() as session:
                repository = SqlAlchemyDesignEvaluationRepository(session, owner_user_id=owner)
                assert await repository.get(project_id=project, run_id=first.id) == first
                assert await repository.latest(project_id=project) == first
                listed = await repository.list(project_id=project)
                assert listed == (first,)
                assert [item.finding_id for item in listed[0].findings] == ["UTF-001", "UTF-001"]
                assert [item.twin_id for item in listed[0].findings] == [TWIN_A, TWIN_B]
            application = create_insight_application(
                application_id=uuid4(),
                project_id=project,
                owner_user_id=owner,
                source_kind=InsightSourceKind.SYNTHETIC_FINDING,
                source_id=f"run:{first.id}:UTF-001",
                source_twin_id=TWIN_A,
                text="The field lacks help.",
                target=InsightTarget.DESIGN,
                target_field=None,
                target_version_id=version.id,
                target_version_number=version.version_number,
                target_code="DRK-002",
                created_at=NOW,
            )
            async with db.session_factory() as session, session.begin():
                applications = SqlAlchemyInsightApplicationRepository(session, owner_user_id=owner)
                assert (
                    await applications.create(application) is InsightApplicationWriteStatus.WRITTEN
                )
                assert (
                    await SqlAlchemyInsightApplicationRepository(
                        session, owner_user_id=foreign
                    ).create(application)
                    is InsightApplicationWriteStatus.PROJECT_NOT_FOUND
                )
            async with db.session_factory() as session:
                applications = SqlAlchemyInsightApplicationRepository(session, owner_user_id=owner)
                assert await applications.list(project_id=project) == (application,)
        finally:
            await db.dispose()

    run(scenario())


def test_downgrade_restores_the_previous_revision_schema_exactly():
    assert_reversible_migration(load_database_settings(env_file=None), MIGRATION)
