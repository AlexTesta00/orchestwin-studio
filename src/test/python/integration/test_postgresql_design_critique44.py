from __future__ import annotations

import importlib
from datetime import timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa

from orchestwin.artifacts.design_critique_persistence import (
    DesignCritiqueWriteStatus,
    SqlAlchemyDesignCritiqueRepository,
)
from orchestwin.identity.persistence.models import UserRecord
from orchestwin.persistence import create_database_runtime
from orchestwin.projects.briefs import create_project_brief
from orchestwin.projects.persistence.models import ProjectBriefVersionRecord, ProjectRecord
from src.test.python.artifacts.test_design_critique44 import (
    NOW,
    OWNER_ID,
    PROJECT_ID,
    critique_run,
    image_source,
    page_source,
)
from src.test.python.integration.postgres_isolation import assert_reversible_migration
from src.test.python.integration.test_proposal_evidence_postgres import database, run

__all__ = ["database"]

pytestmark = pytest.mark.integration

MIGRATION = importlib.import_module(
    "orchestwin.persistence.migrations.versions.0075_design_critiques"
)
WRITTEN = DesignCritiqueWriteStatus.WRITTEN
EXISTS = DesignCritiqueWriteStatus.EXISTS
PROJECT_NOT_FOUND = DesignCritiqueWriteStatus.PROJECT_NOT_FOUND
SOURCE_NOT_FOUND = DesignCritiqueWriteStatus.SOURCE_NOT_FOUND
PAGES = sa.text(
    "SELECT id, page_snapshot IS NULL FROM design_critique_sources ORDER BY created_at, id"
)


async def seed(db):
    brief = create_project_brief(description="Una prenotazione al ristorante.")
    async with db.session_factory() as session, session.begin():
        session.add(
            UserRecord(
                id=OWNER_ID,
                email_normalized=f"{OWNER_ID}@synthetic.invalid",
                password_hash="NO_LOGIN_SYNTHETIC",
            )
        )
        await session.flush()
        session.add(
            ProjectRecord(
                id=PROJECT_ID,
                owner_user_id=OWNER_ID,
                display_name="Synthetic design critique",
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
                project_id=PROJECT_ID,
                version_number=1,
                schema_version=brief.SCHEMA_VERSION,
                content=brief.to_snapshot(),
                content_hash=brief.content_hash,
                created_by_user_id=OWNER_ID,
                created_at=NOW,
            )
        )


def test_the_critique_migration_is_reversible(database):
    assert_reversible_migration(database, MIGRATION)


def test_sources_shots_and_runs_round_trip_on_postgresql(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            await seed(db)
            page, page_contents = page_source()
            image, image_contents = image_source(created_at=NOW + timedelta(minutes=5))
            critique = critique_run(page, page_contents)
            async with db.session_factory() as session, session.begin():
                owned = SqlAlchemyDesignCritiqueRepository(session, owner_user_id=OWNER_ID)
                assert await owned.create_run(critique) is SOURCE_NOT_FOUND
                assert await owned.create_source(page, page_contents) is WRITTEN
                assert await owned.create_source(page, page_contents) is EXISTS
                assert await owned.create_source(image, image_contents) is WRITTEN
                assert await owned.create_run(critique) is WRITTEN
                assert await owned.create_run(critique) is EXISTS
            stranger_id = uuid4()
            async with db.session_factory() as session, session.begin():
                stranger = SqlAlchemyDesignCritiqueRepository(session, owner_user_id=stranger_id)
                assert await stranger.create_source(page, page_contents) is PROJECT_NOT_FOUND
                assert await stranger.create_run(critique) is PROJECT_NOT_FOUND
                assert await stranger.sources(PROJECT_ID) == ()
                assert await stranger.source(PROJECT_ID, page.id) is None
                assert await stranger.shot(PROJECT_ID, page.id, "SCR-001") is None
                assert await stranger.runs(PROJECT_ID) == ()
                assert await stranger.run(PROJECT_ID, critique.id) is None
            async with db.session_factory() as session:
                owned = SqlAlchemyDesignCritiqueRepository(session, owner_user_id=OWNER_ID)
                assert await owned.source(PROJECT_ID, page.id) == page
                assert await owned.source(PROJECT_ID, image.id) == image
                assert await owned.source(uuid4(), page.id) is None
                assert await owned.sources(PROJECT_ID) == (image, page)
                assert await owned.sources(PROJECT_ID, limit=1) == (image,)
                for shot in page.shots:
                    assert await owned.shot(PROJECT_ID, page.id, shot.code) == (
                        shot.media_type,
                        page_contents[shot.code],
                    )
                assert await owned.shot(PROJECT_ID, image.id, "SCR-001") == (
                    "image/png",
                    image_contents["SCR-001"],
                )
                assert await owned.shot(PROJECT_ID, image.id, "SCR-002") is None
                stored = await owned.run(PROJECT_ID, critique.id)
                assert stored == critique
                assert stored.to_snapshot() == critique.to_snapshot()
                assert stored.verdicts() == critique.verdicts()
                assert await owned.runs(PROJECT_ID) == (critique,)
                assert await owned.runs(uuid4()) == ()
                rows = (await session.execute(PAGES)).all()
                assert [tuple(row) for row in rows] == [(page.id, False), (image.id, True)]
        finally:
            await db.dispose()

    run(scenario())
