from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from orchestwin.knowledge.package_persistence import (
    PACKAGE_VERSIONS,
    KnowledgePackageWriteStatus,
    SqlAlchemyKnowledgePackageRepository,
)
from orchestwin.knowledge.packages import KnowledgePackageVersion
from orchestwin.persistence import create_database_runtime, load_database_settings
from orchestwin.projects.persistence.models import ProjectRecord
from src.test.python.integration.postgres_isolation import assert_reversible_migration
from src.test.python.integration.test_postgresql_design_loop import seed
from src.test.python.integration.test_proposal_evidence_postgres import database, run

__all__ = ["database"]

pytestmark = pytest.mark.integration

MIGRATION = importlib.import_module(
    "orchestwin.persistence.migrations.versions.0060_knowledge_package_versions"
)
NOW = datetime(2026, 9, 27, 21, 0, tzinfo=UTC)
MANIFEST = {
    "schema_version": 2,
    "manifest": "orchestwin.json",
    "index": "ORCHESTWIN.md",
    "files": {"brief/brief.md": "0" * 64},
}
WRITTEN = KnowledgePackageWriteStatus.WRITTEN
INSERT = sa.text(
    "INSERT INTO knowledge_package_versions (id, project_id, owner_user_id, version_number,"
    " schema_version, content_hash, archive_hash, file_name, file_count, archive_size, manifest,"
    " archive, created_at) VALUES (:id, :project_id, :owner_user_id, :version_number,"
    " :schema_version, :content_hash, :archive_hash, :file_name, :file_count, :archive_size,"
    " CAST(:manifest AS JSONB), :archive, :created_at)"
)


def package(owner: UUID, project: UUID, archive: bytes, number: int = 1) -> KnowledgePackageVersion:
    return KnowledgePackageVersion(
        id=uuid4(),
        project_id=project,
        owner_user_id=owner,
        version_number=number,
        schema_version=2,
        content_hash=hashlib.sha256(b"content" + archive).hexdigest(),
        archive_hash=hashlib.sha256(archive).hexdigest(),
        file_name=f"orchestwin-knowledge-v{number}.zip",
        file_count=3,
        archive_size=len(archive),
        manifest=MANIFEST,
        created_at=NOW + timedelta(minutes=number),
    )


def repository(session, owner: UUID) -> SqlAlchemyKnowledgePackageRepository:
    return SqlAlchemyKnowledgePackageRepository(session, owner_user_id=owner)


async def count(session) -> int:
    statement = sa.select(sa.func.count()).select_from(PACKAGE_VERSIONS)
    return (await session.execute(statement)).scalar_one()


def test_versions_round_trip_newest_first_with_identical_archives(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, _ = await seed(db)
            first_archive = b"PK\x03\x04first knowledge folder\x00\xff"
            second_archive = b"PK\x03\x04second knowledge folder" * 7
            first = package(owner, project, first_archive)
            second = package(owner, project, second_archive, number=2)
            async with db.session_factory() as session, session.begin():
                packages = repository(session, owner)
                assert await packages.latest(project_id=project) is None
                assert await packages.list(project_id=project) == ()
                assert await packages.lock_project(project_id=project) is True
                assert await packages.create(first, first_archive) is WRITTEN
                assert await packages.create(second, second_archive) is WRITTEN
            async with db.session_factory() as session:
                packages = repository(session, owner)
                assert await packages.latest(project_id=project) == second
                assert await packages.list(project_id=project) == (second, first)
                assert await packages.list(project_id=project, limit=1) == (second,)
                assert await packages.get(project_id=project, version_number=1) == first
                assert await packages.get(project_id=project, version_number=2) == second
                assert await packages.get(project_id=project, version_number=3) is None
                stored_first = await packages.archive(project_id=project, version_number=1)
                stored_second = await packages.archive(project_id=project, version_number=2)
                assert await packages.archive(project_id=project, version_number=3) is None
            assert stored_first == first_archive
            assert stored_second == second_archive
            assert first.matches(stored_first)
            assert second.matches(stored_second)
        finally:
            await db.dispose()

    run(scenario())


def test_a_stranger_or_an_archived_project_sees_nothing_and_cannot_publish(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, _ = await seed(db)
            archive = b"PK\x03\x04owner knowledge folder"
            async with db.session_factory() as session, session.begin():
                assert (
                    await repository(session, owner).create(
                        package(owner, project, archive), archive
                    )
                    is WRITTEN
                )
            stranger = uuid4()
            async with db.session_factory() as session, session.begin():
                packages = repository(session, stranger)
                assert await packages.lock_project(project_id=project) is False
                assert await packages.latest(project_id=project) is None
                assert await packages.list(project_id=project) == ()
                assert await packages.get(project_id=project, version_number=1) is None
                assert await packages.archive(project_id=project, version_number=1) is None
                assert (
                    await packages.create(package(stranger, project, archive, 2), archive)
                    is KnowledgePackageWriteStatus.PROJECT_NOT_FOUND
                )
                assert await repository(session, owner).lock_project(project_id=uuid4()) is False
            async with db.session_factory() as session, session.begin():
                assert await count(session) == 1
                await session.execute(
                    sa.update(ProjectRecord)
                    .where(ProjectRecord.id == project)
                    .values(archived_at=NOW)
                )
            async with db.session_factory() as session, session.begin():
                packages = repository(session, owner)
                assert await packages.lock_project(project_id=project) is False
                assert await packages.latest(project_id=project) is None
                assert await packages.archive(project_id=project, version_number=1) is None
                assert (
                    await packages.create(package(owner, project, archive, 2), archive)
                    is KnowledgePackageWriteStatus.PROJECT_NOT_FOUND
                )
                assert await count(session) == 1
        finally:
            await db.dispose()

    run(scenario())


def test_lock_project_holds_the_owned_project_row_until_the_transaction_ends(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, _ = await seed(db)
            async with db.session_factory() as holder, holder.begin():
                assert await repository(holder, owner).lock_project(project_id=project) is True
                with pytest.raises(sa.exc.OperationalError, match="lock timeout"):
                    async with db.session_factory() as waiter, waiter.begin():
                        await waiter.execute(sa.text("SET LOCAL lock_timeout = '200ms'"))
                        await repository(waiter, owner).lock_project(project_id=project)
            async with db.session_factory() as session, session.begin():
                assert await repository(session, owner).lock_project(project_id=project) is True
        finally:
            await db.dispose()

    run(scenario())


def test_a_taken_version_number_is_a_conflict_that_keeps_the_transaction_usable(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, _ = await seed(db)
            first_archive = b"PK\x03\x04first"
            other_archive = b"PK\x03\x04concurrent"
            first = package(owner, project, first_archive)
            async with db.session_factory() as session, session.begin():
                assert await repository(session, owner).create(first, first_archive) is WRITTEN
            second = package(owner, project, other_archive, 2)
            async with db.session_factory() as session, session.begin():
                packages = repository(session, owner)
                assert await packages.lock_project(project_id=project) is True
                assert (
                    await packages.create(package(owner, project, other_archive), other_archive)
                    is KnowledgePackageWriteStatus.VERSION_CONFLICT
                )
                assert await packages.create(second, other_archive) is WRITTEN
            with pytest.raises(IntegrityError) as rejected:
                async with db.session_factory() as session, session.begin():
                    await repository(session, owner).create(
                        replace(first, version_number=3), first_archive
                    )
            assert rejected.value.orig.diag.constraint_name == "pk_knowledge_package_versions"
            async with db.session_factory() as session:
                assert await count(session) == 2
                assert await repository(session, owner).list(project_id=project) == (
                    second,
                    first,
                )
                assert (
                    await repository(session, owner).archive(project_id=project, version_number=1)
                    == first_archive
                )
        finally:
            await db.dispose()

    run(scenario())


def test_create_refuses_an_archive_or_an_owner_that_does_not_match_the_version(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, _ = await seed(db)
            archive = b"PK\x03\x04declared knowledge folder"
            version = package(owner, project, archive)
            async with db.session_factory() as session, session.begin():
                packages = repository(session, owner)
                for candidate in (archive + b"!", archive[:-1] + b"?", archive[:-1]):
                    with pytest.raises(ValueError, match="archive does not match"):
                        await packages.create(version, candidate)
                with pytest.raises(ValueError, match="owner does not match"):
                    await packages.create(replace(version, owner_user_id=uuid4()), archive)
                assert await count(session) == 0
                assert await packages.create(version, archive) is WRITTEN
                assert await count(session) == 1
        finally:
            await db.dispose()

    run(scenario())


def test_the_database_keeps_package_versions_immutable_and_consistent(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, _ = await seed(db)
            archive = b"PK\x03\x04immutable knowledge folder"
            first = package(owner, project, archive)
            async with db.session_factory() as session, session.begin():
                assert await repository(session, owner).create(first, archive) is WRITTEN
            for statement in (
                sa.text("UPDATE knowledge_package_versions SET file_name = 'edited.zip'"),
                sa.text("DELETE FROM knowledge_package_versions"),
            ):
                with pytest.raises(sa.exc.DBAPIError, match="immutable"):
                    async with db.session_factory() as session, session.begin():
                        await session.execute(statement)
            second = package(owner, project, archive, 2)
            row = {
                "id": second.id,
                "project_id": project,
                "owner_user_id": owner,
                "version_number": second.version_number,
                "schema_version": second.schema_version,
                "content_hash": second.content_hash,
                "archive_hash": second.archive_hash,
                "file_name": second.file_name,
                "file_count": second.file_count,
                "archive_size": second.archive_size,
                "manifest": json.dumps(MANIFEST),
                "archive": archive,
                "created_at": second.created_at,
            }
            for changes, constraint in (
                ({"archive_size": len(archive) + 1}, "archive_length"),
                ({"archive": b"", "archive_size": 0}, "archive_size"),
                ({"version_number": 0}, "version_number"),
                ({"schema_version": 0}, "schema_version"),
                ({"file_count": 0}, "file_count"),
                ({"content_hash": "A" * 64}, "content_hash"),
                ({"archive_hash": "a" * 63}, "archive_hash"),
                ({"file_name": ""}, "file_name"),
            ):
                with pytest.raises(IntegrityError) as rejected:
                    async with db.session_factory() as session, session.begin():
                        await session.execute(INSERT, {**row, **changes})
                assert (
                    rejected.value.orig.diag.constraint_name
                    == f"ck_knowledge_package_versions_{constraint}"
                )
            async with db.session_factory() as session, session.begin():
                await session.execute(INSERT, row)
            async with db.session_factory() as session:
                assert await repository(session, owner).list(project_id=project) == (
                    second,
                    first,
                )
        finally:
            await db.dispose()

    run(scenario())


def test_downgrade_restores_the_previous_revision_schema_exactly():
    assert_reversible_migration(load_database_settings(env_file=None), MIGRATION)
