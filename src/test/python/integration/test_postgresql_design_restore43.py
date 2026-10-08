from __future__ import annotations

import importlib
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.design_persistence import (
    SqlAlchemyDesignDiffRepository,
    SqlAlchemyDesignPackageRepository,
)
from orchestwin.artifacts.design_revision_application import (
    DESIGN_RESTORE_CURRENT,
    DesignRestoreFailure,
    DesignRevisionStatus,
    LocalDesignRevisionService,
)
from orchestwin.artifacts.design_revisions import DesignPackageDiffStatus
from orchestwin.identity.persistence.models import UserRecord
from orchestwin.persistence import create_database_runtime
from orchestwin.projects.briefs import create_project_brief
from orchestwin.projects.design_application import DesignVersionAppendStatus
from orchestwin.projects.design_runtime import ManagedDesignUnitOfWorkFactory
from orchestwin.projects.persistence.models import ProjectBriefVersionRecord, ProjectRecord
from src.test.python.artifacts import design_fixtures
from src.test.python.integration.postgres_isolation import assert_reversible_migration
from src.test.python.integration.test_proposal_evidence_postgres import database, run

__all__ = ["database"]

pytestmark = pytest.mark.integration

MIGRATION = importlib.import_module(
    "orchestwin.persistence.migrations.versions.0074_design_version_restore"
)
NOW = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)
NOTE = "Ripristino della versione 1"
QUESTION = "Should the night shift see the same list?"
SECOND_ID = UUID("00000000-0000-4000-8000-000000004311")
THIRD_ID = UUID("00000000-0000-4000-8000-000000004312")
APPENDED = DesignVersionAppendStatus.APPENDED
CONFLICT = DesignVersionAppendStatus.CONTENT_CONFLICT


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
                display_name="Synthetic design restore",
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
    return owner, project


def two_versions():
    first = design_fixtures.design_version()
    package = replace(first.package, open_questions=(QUESTION,))
    second = DesignPackageVersion(
        id=SECOND_ID,
        project_id=first.project_id,
        version_number=2,
        based_on_version_number=1,
        package=package,
        content_hash=package.content_hash,
        created_by_user_id=first.created_by_user_id,
        created_at=first.created_at,
    )
    return first, second


async def append_versions(db, owner, *versions):
    async with db.session_factory() as session, session.begin():
        repository = SqlAlchemyDesignPackageRepository(session, owner_user_id=owner)
        return [await repository.append(version) for version in versions]


async def stored_history(db, owner, project):
    async with db.session_factory() as session:
        packages = SqlAlchemyDesignPackageRepository(session, owner_user_id=owner)
        diffs = SqlAlchemyDesignDiffRepository(session, owner_user_id=owner)
        return (
            await packages.history(project_id=project),
            await diffs.history(project_id=project),
        )


def restore_service(db):
    return LocalDesignRevisionService(
        uow_factory=ManagedDesignUnitOfWorkFactory(db.session_factory), clock=lambda: NOW
    )


def test_the_restore_migration_is_reversible(database):
    assert_reversible_migration(database, MIGRATION)


def test_a_past_version_comes_back_on_postgresql(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project = await seed(db)
            first, second = two_versions()
            assert await append_versions(db, owner, first, second) == [APPENDED, APPENDED]
            result = await restore_service(db).restore_version(
                owner_user_id=owner, project_id=project, version_number=1, note=NOTE
            )
            version = result.version
            assert result.status is DesignRevisionStatus.APPLIED
            assert version is not None
            assert (version.version_number, version.based_on_version_number) == (3, 2)
            assert (version.content_hash, version.package) == (first.content_hash, first.package)
            with pytest.raises(DesignRestoreFailure) as refused:
                await restore_service(db).restore_version(
                    owner_user_id=owner, project_id=project, version_number=1, note=NOTE
                )
            assert refused.value.code == DESIGN_RESTORE_CURRENT
            versions, diffs = await stored_history(db, owner, project)
            assert versions == (first, second, version)
            assert [item.content_hash for item in versions] == [
                first.content_hash,
                second.content_hash,
                first.content_hash,
            ]
            assert diffs == (result.diff,)
            saved = diffs[0]
            assert saved.status is DesignPackageDiffStatus.APPROVED
            assert saved.decision_reason == NOTE
            assert saved.applied_version_id == version.id
        finally:
            await db.dispose()

    run(scenario())


def test_a_version_equal_to_the_current_one_is_still_refused(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project = await seed(db)
            first, second = two_versions()
            assert await append_versions(db, owner, first, second) == [APPENDED, APPENDED]
            third = replace(second, id=THIRD_ID, version_number=3, based_on_version_number=2)
            assert await append_versions(db, owner, third) == [CONFLICT]
            with pytest.raises(DesignRestoreFailure) as refused:
                await restore_service(db).restore_version(
                    owner_user_id=owner,
                    project_id=project,
                    version_number=2,
                    note="Ripristino della versione 2",
                )
            assert refused.value.code == DESIGN_RESTORE_CURRENT
            assert await stored_history(db, owner, project) == ((first, second), ())
        finally:
            await db.dispose()

    run(scenario())
