from __future__ import annotations

import hashlib
import importlib
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from functools import cache
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from orchestwin.agents.persistence.repositories import SqlAlchemyTeamProposalVersionRepository
from orchestwin.artifacts.design_persistence import (
    PACKAGE_VERSIONS,
    SqlAlchemyDesignPackageRepository,
    design_package_version_to_record,
)
from orchestwin.identity.persistence.models import UserRecord
from orchestwin.knowledge.folder import build_knowledge_folder, folder_archive, json_text
from orchestwin.knowledge.layout import KNOWLEDGE_MANIFEST, STAGES
from orchestwin.knowledge.project_import_persistence import SqlAlchemyProjectImportRepository
from orchestwin.knowledge.project_import_service import ProjectImportError, ProjectImportService
from orchestwin.persistence import create_database_runtime, load_database_settings
from orchestwin.projects.design_application import DesignVersionAppendStatus
from orchestwin.projects.domain import ProjectMode, create_project
from orchestwin.projects.persistence.briefs import SqlAlchemyProjectBriefRepository
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.projects.persistence.repositories import SqlAlchemyProjectRepository
from orchestwin.projects.requirements_persistence import (
    SqlAlchemyRequirementsSpecificationRepository,
)
from orchestwin.twins.persistence.repositories import (
    SqlAlchemyPersonaVersionRepository,
    SqlAlchemyUserModelingSnapshotRepository,
    SqlAlchemyUserTwinVersionRepository,
)
from src.test.python.integration.postgres_isolation import assert_reversible_migration
from src.test.python.integration.test_proposal_evidence_postgres import database, run
from src.test.python.knowledge.knowledge_fixtures import PUBLISHED_AT, REAL_PROJECT_ID, real_sources

__all__ = ["database"]

pytestmark = pytest.mark.integration

MIGRATION = importlib.import_module(
    "orchestwin.persistence.migrations.versions.0061_project_imports"
)
OWNER = UUID("33333333-3333-4333-8333-333333333333")
STRANGER = UUID("66666666-6666-4666-8666-666666666666")
IMPORTED_AT = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)
TABLES = (
    "projects",
    "project_brief_versions",
    "team_proposals",
    "persona_profile_versions",
    "user_twin_profile_versions",
    "user_modeling_snapshot_versions",
    "requirements_specification_versions",
    "design_package_versions",
    "project_imports",
    "human_gates",
)
INSERT = sa.text(
    "INSERT INTO project_imports (id, project_id, owner_user_id, source_project_id,"
    " source_project_name, package_version, package_content_hash, schema_version, archive_hash,"
    " archive_size, stage_versions, imported_at) VALUES (:id, :project_id, :owner_user_id,"
    " :source_project_id, :source_project_name, :package_version, :package_content_hash,"
    " :schema_version, :archive_hash, :archive_size, CAST(:stage_versions AS JSONB), :imported_at)"
)


@cache
def archive_content() -> bytes:
    folder = build_knowledge_folder(real_sources(), version_number=1, created_at=PUBLISHED_AT)
    return folder_archive(folder).content


def tampered_manifest() -> bytes:
    with zipfile.ZipFile(io.BytesIO(archive_content())) as source:
        files = {name: source.read(name).decode("utf-8") for name in source.namelist()}
    manifest = json.loads(files[KNOWLEDGE_MANIFEST])
    manifest["files"]["brief/brief.md"] = "0" * 64
    files[KNOWLEDGE_MANIFEST] = json_text(manifest)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for name, text in files.items():
            target.writestr(name, text)
    return buffer.getvalue()


def importer(db, *moments: datetime) -> ProjectImportService:
    remaining = iter(moments or (IMPORTED_AT,))
    return ProjectImportService(session_factory=db.session_factory, clock=lambda: next(remaining))


async def seed_users(db, *users: UUID) -> None:
    async with db.session_factory() as session, session.begin():
        for identity in users:
            session.add(
                UserRecord(
                    id=identity,
                    email_normalized=f"{identity}@synthetic.invalid",
                    password_hash="NO_LOGIN_SYNTHETIC",
                )
            )


async def row_counts(db) -> dict[str, int]:
    async with db.session_factory() as session:
        return {
            table: (await session.execute(sa.text(f"SELECT count(*) FROM {table}"))).scalar_one()
            for table in TABLES
        }


def test_import_creates_every_stage_as_version_one_of_a_new_unapproved_project(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            await seed_users(db, OWNER)
            imports = importer(db)
            content = archive_content()
            result = await imports.import_archive(owner_user_id=OWNER, content=content)
            project_id = result.project.id
            async with db.session_factory() as session:
                project = await SqlAlchemyProjectRepository(session).get_owned(
                    project_id=project_id, owner_user_id=OWNER
                )
                brief = await SqlAlchemyProjectBriefRepository(session).get_current_owned(
                    project_id=project_id, owner_user_id=OWNER
                )
                team = await SqlAlchemyTeamProposalVersionRepository(session).get_current_owned(
                    project_id=project_id, owner_user_id=OWNER
                )
                modeling = await SqlAlchemyUserModelingSnapshotRepository(
                    session, owner_user_id=OWNER
                ).current(project_id=project_id)
                personas = await SqlAlchemyPersonaVersionRepository(
                    session, owner_user_id=OWNER
                ).list_current(project_id=project_id)
                twins = await SqlAlchemyUserTwinVersionRepository(
                    session, owner_user_id=OWNER
                ).list_current(project_id=project_id)
                requirements = await SqlAlchemyRequirementsSpecificationRepository(
                    session, owner_user_id=OWNER
                ).current(project_id=project_id)
                design = await SqlAlchemyDesignPackageRepository(
                    session, owner_user_id=OWNER
                ).current(project_id=project_id)
            counts = await row_counts(db)
            origin = await imports.origin(owner_user_id=OWNER, project_id=project_id)
        finally:
            await db.dispose()

        plan = result.plan
        assert project == result.project
        assert project.owner_user_id == OWNER
        assert project.display_name == "Lista ospiti workshop"
        assert project.mode is ProjectMode.GREENFIELD_GENERATION
        assert project.current_brief_version == 1
        assert project.created_at == IMPORTED_AT
        assert brief == result.brief_version
        assert (brief.id, brief.content_hash) == (plan.brief_version_id, plan.brief.content_hash)
        assert (team.id, team.content_hash) == (plan.team.id, plan.team.content_hash)
        assert (modeling.id, modeling.content_hash) == (
            plan.modeling.id,
            plan.modeling.content_hash,
        )
        assert modeling.snapshot.twin_count == 2
        assert {version.id for version in personas} == {version.id for version in plan.personas}
        assert {version.id for version in twins} == {version.id for version in plan.twins}
        assert {version.content_hash for version in twins} == {
            version.content_hash for version in plan.twins
        }
        assert (requirements.id, requirements.content_hash) == (
            plan.requirements.id,
            plan.requirements.content_hash,
        )
        assert (design.id, design.content_hash) == (plan.design.id, plan.design.content_hash)
        for version in (brief, team, modeling, *personas, *twins, requirements, design):
            assert version.project_id == project_id
            assert version.version_number == 1
            assert version.created_by_user_id == OWNER
            assert version.created_at == IMPORTED_AT
        assert counts == {
            **dict.fromkeys(TABLES, 1),
            "persona_profile_versions": 2,
            "user_twin_profile_versions": 2,
            "human_gates": 0,
        }
        assert origin == result.record
        assert origin.origin == plan.origin
        assert origin.source_project_id == REAL_PROJECT_ID
        assert origin.archive_hash == hashlib.sha256(content).hexdigest()
        assert origin.archive_size == len(content)
        assert origin.stage_versions["design"] == {
            "version_id": str(plan.design.id),
            "version_number": 1,
            "content_hash": plan.design.content_hash,
        }

    run(scenario())


def test_importing_the_same_archive_twice_creates_two_independent_projects(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            await seed_users(db, OWNER)
            imports = importer(db, IMPORTED_AT, IMPORTED_AT + timedelta(minutes=5))
            first = await imports.import_archive(
                owner_user_id=OWNER, content=archive_content(), display_name="Prima copia"
            )
            second = await imports.import_archive(
                owner_user_id=OWNER, content=archive_content(), display_name="Seconda copia"
            )
            async with db.session_factory() as session:
                listed = await SqlAlchemyProjectImportRepository(
                    session, owner_user_id=OWNER
                ).list()
                projects = await SqlAlchemyProjectRepository(session).list_active_owned(
                    owner_user_id=OWNER
                )
            counts = await row_counts(db)
        finally:
            await db.dispose()

        assert first.project.id != second.project.id
        assert [project.display_name for project in projects] == ["Seconda copia", "Prima copia"]
        assert listed == (second.record, first.record)
        for stage in STAGES:
            assert (
                first.record.stage_versions[stage]["version_id"]
                != second.record.stage_versions[stage]["version_id"]
            )
        for stage in ("team", "twins", "requirements", "design"):
            assert (
                first.record.stage_versions[stage]["content_hash"]
                != second.record.stage_versions[stage]["content_hash"]
            )
        assert first.plan.brief.content_hash == second.plan.brief.content_hash
        assert not {twin.twin_id for twin in first.plan.twins} & {
            twin.twin_id for twin in second.plan.twins
        }
        assert first.record.origin == second.record.origin
        assert first.record.archive_hash == second.record.archive_hash
        assert counts == {
            **dict.fromkeys(TABLES, 2),
            "persona_profile_versions": 4,
            "user_twin_profile_versions": 4,
            "human_gates": 0,
        }

    run(scenario())


def test_archive_with_a_tampered_manifest_is_rejected_and_leaves_no_row(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            await seed_users(db, OWNER)
            with pytest.raises(ProjectImportError) as rejected:
                await importer(db).import_archive(owner_user_id=OWNER, content=tampered_manifest())
            counts = await row_counts(db)
        finally:
            await db.dispose()

        assert (rejected.value.code, rejected.value.detail) == ("FOLDER_TAMPERED", "brief/brief.md")
        assert counts == dict.fromkeys(TABLES, 0)

    run(scenario())


@pytest.mark.parametrize("failure", ["status", "integrity"])
def test_failure_while_writing_the_design_leaves_nothing_of_the_import(
    database, monkeypatch: pytest.MonkeyPatch, failure: str
):
    original = SqlAlchemyDesignPackageRepository.append

    async def refused(self, version):
        return DesignVersionAppendStatus.CONTENT_CONFLICT

    async def duplicated(self, version):
        assert await original(self, version) is DesignVersionAppendStatus.APPENDED
        await self._session.execute(
            sa.insert(PACKAGE_VERSIONS).values(**design_package_version_to_record(version))
        )
        return DesignVersionAppendStatus.APPENDED

    monkeypatch.setattr(
        SqlAlchemyDesignPackageRepository, "append", refused if failure == "status" else duplicated
    )

    async def scenario():
        db = create_database_runtime(database)
        try:
            await seed_users(db, OWNER)
            with pytest.raises(ProjectImportError) as rejected:
                await importer(db).import_archive(owner_user_id=OWNER, content=archive_content())
            counts = await row_counts(db)
            monkeypatch.undo()
            retried = await importer(db).import_archive(
                owner_user_id=OWNER, content=archive_content()
            )
            after_retry = await row_counts(db)
        finally:
            await db.dispose()

        assert (rejected.value.code, rejected.value.detail) == ("PROJECT_IMPORT_REJECTED", "design")
        assert isinstance(rejected.value.__cause__, IntegrityError) is (failure == "integrity")
        assert counts == dict.fromkeys(TABLES, 0)
        assert retried.project.current_brief_version == 1
        assert after_retry["projects"] == after_retry["design_package_versions"] == 1

    run(scenario())


def test_origin_is_owner_scoped_and_hidden_once_the_project_is_archived(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            await seed_users(db, OWNER, STRANGER)
            imports = importer(db)
            result = await imports.import_archive(owner_user_id=OWNER, content=archive_content())
            project_id = result.project.id
            owned = await imports.origin(owner_user_id=OWNER, project_id=project_id)
            foreign = await imports.origin(owner_user_id=STRANGER, project_id=project_id)
            unknown = await imports.origin(owner_user_id=OWNER, project_id=uuid4())
            async with db.session_factory() as session:
                owner_list = await SqlAlchemyProjectImportRepository(
                    session, owner_user_id=OWNER
                ).list()
                stranger_list = await SqlAlchemyProjectImportRepository(
                    session, owner_user_id=STRANGER
                ).list()
            async with db.session_factory() as session, session.begin():
                await session.execute(
                    sa.update(ProjectRecord)
                    .where(ProjectRecord.id == project_id)
                    .values(archived_at=IMPORTED_AT + timedelta(hours=1))
                )
            archived = await imports.origin(owner_user_id=OWNER, project_id=project_id)
            async with db.session_factory() as session:
                archived_list = await SqlAlchemyProjectImportRepository(
                    session, owner_user_id=OWNER
                ).list()
        finally:
            await db.dispose()

        assert owned == result.record
        assert foreign is None
        assert unknown is None
        assert owner_list == (result.record,)
        assert stranger_list == ()
        assert archived is None
        assert archived_list == ()

    run(scenario())


def test_the_database_keeps_imports_immutable_and_consistent(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            await seed_users(db, OWNER)
            result = await importer(db).import_archive(
                owner_user_id=OWNER, content=archive_content()
            )
            for statement in (
                sa.text("UPDATE project_imports SET source_project_name = 'Altro nome'"),
                sa.text("DELETE FROM project_imports"),
            ):
                with pytest.raises(sa.exc.DBAPIError, match="immutable"):
                    async with db.session_factory() as session, session.begin():
                        await session.execute(statement)
            bare = create_project(
                owner_user_id=OWNER,
                display_name="Progetto senza import",
                mode=ProjectMode.GREENFIELD_GENERATION,
                created_at=IMPORTED_AT,
            )
            async with db.session_factory() as session, session.begin():
                await SqlAlchemyProjectRepository(session).add(bare)
            record = result.record
            row = {
                "id": uuid4(),
                "project_id": bare.id,
                "owner_user_id": OWNER,
                "source_project_id": record.source_project_id,
                "source_project_name": record.source_project_name,
                "package_version": record.package_version,
                "package_content_hash": record.package_content_hash,
                "schema_version": record.schema_version,
                "archive_hash": record.archive_hash,
                "archive_size": record.archive_size,
                "stage_versions": json.dumps(record.to_snapshot()["stage_versions"]),
                "imported_at": record.imported_at,
            }
            for changes, constraint in (
                ({"package_version": 0}, "ck_project_imports_package_version"),
                ({"schema_version": 0}, "ck_project_imports_schema_version"),
                ({"archive_size": 0}, "ck_project_imports_archive_size"),
                ({"package_content_hash": "A" * 64}, "ck_project_imports_package_content_hash"),
                ({"archive_hash": "a" * 63}, "ck_project_imports_archive_hash"),
                ({"source_project_name": ""}, "ck_project_imports_source_project_name"),
                ({"project_id": result.project.id}, "uq_project_imports_project"),
                ({"project_id": uuid4()}, "fk_project_imports_project"),
                ({"owner_user_id": uuid4()}, "fk_project_imports_owner"),
            ):
                with pytest.raises(IntegrityError) as rejected:
                    async with db.session_factory() as session, session.begin():
                        await session.execute(INSERT, {**row, **changes})
                assert rejected.value.orig.diag.constraint_name == constraint
            async with db.session_factory() as session, session.begin():
                await session.execute(INSERT, row)
            async with db.session_factory() as session:
                stored = await SqlAlchemyProjectImportRepository(
                    session, owner_user_id=OWNER
                ).for_project(bare.id)
        finally:
            await db.dispose()

        assert stored is not None
        assert stored.project_id == bare.id
        assert stored.stage_versions == record.stage_versions

    run(scenario())


def test_downgrade_restores_the_previous_revision_schema_exactly():
    assert_reversible_migration(load_database_settings(env_file=None), MIGRATION)
