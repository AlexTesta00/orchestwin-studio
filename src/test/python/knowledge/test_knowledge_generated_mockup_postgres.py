from __future__ import annotations

import asyncio
import os
import selectors
import sys
from datetime import UTC, datetime
from uuid import UUID

import pytest
import sqlalchemy as sa
from pydantic import SecretStr

from orchestwin.artifacts.design_persistence import SqlAlchemyDesignPackageRepository
from orchestwin.identity.persistence.models import UserRecord
from orchestwin.knowledge.archive import MOCKUP_LOCATION
from orchestwin.knowledge.folder import build_knowledge_folder, folder_archive
from orchestwin.knowledge.project_import import plan_documents
from orchestwin.knowledge.project_import_service import ProjectImportError, ProjectImportService
from orchestwin.knowledge.stage_documents import stage_versions
from orchestwin.persistence import create_database_runtime
from orchestwin.persistence.config import DatabaseSettings
from src.test.python.integration.postgres_isolation import isolated_postgres_settings

from .knowledge_fixtures import PUBLISHED_AT, sources_of
from .test_knowledge_generated_mockup_support import (
    ASSERTIONS,
    DASHBOARD,
    archive_of,
    design_snapshot,
    generated_folder,
    repacked,
)

OWNER = UUID("33333333-3333-4333-8333-333333333333")
IMPORTED_AT = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)
MOCKUP_FILE = "design/mockup.html"


def run(coroutine):
    if sys.platform == "win32":
        return asyncio.run(
            coroutine,
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
    return asyncio.run(coroutine)


@pytest.fixture
def database():
    url = os.environ.get("ORCHESTWIN_PROPOSAL_EVIDENCE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("explicit disposable knowledge database required")
    settings = DatabaseSettings(url=SecretStr(url), _env_file=None)
    with isolated_postgres_settings(settings) as scoped:
        yield scoped


def hostile_archive() -> bytes:
    exported = generated_folder(DASHBOARD)
    design = design_snapshot(exported)
    screen = design["package"]["generated_mockup"]["mockup"]["screens"][0]
    screen["markup"] = screen["markup"] + "<script>alert(1)</script>"
    return archive_of(repacked(exported, design))


async def seed_owner(db) -> None:
    async with db.session_factory() as session, session.begin():
        session.add(
            UserRecord(
                id=OWNER,
                email_normalized=f"{OWNER}@synthetic.invalid",
                password_hash="NO_LOGIN_SYNTHETIC",
            )
        )


async def count_projects(db) -> int:
    async with db.session_factory() as session:
        return (await session.execute(sa.text("SELECT count(*) FROM projects"))).scalar_one()


@pytest.mark.integration
def test_postgresql_imports_a_folder_with_a_generated_mockup_and_exports_it_again(database):
    exported = generated_folder(DASHBOARD)

    async def scenario():
        db = create_database_runtime(database)
        try:
            await seed_owner(db)
            service = ProjectImportService(
                session_factory=db.session_factory, clock=lambda: IMPORTED_AT
            )
            with pytest.raises(ProjectImportError) as refused:
                await service.import_archive(owner_user_id=OWNER, content=hostile_archive())
            after_refusal = await count_projects(db)
            result = await service.import_archive(
                owner_user_id=OWNER, content=folder_archive(exported).content
            )
            async with db.session_factory() as session:
                stored = await SqlAlchemyDesignPackageRepository(
                    session, owner_user_id=OWNER
                ).current(project_id=result.project.id)
        finally:
            await db.dispose()
        return refused.value, after_refusal, result, stored

    refused, after_refusal, result, stored = run(scenario())
    documents = plan_documents(result.plan, owner_user_id=OWNER, created_at=IMPORTED_AT)
    again = build_knowledge_folder(
        sources_of(stage_versions(documents), project_id=result.project.id),
        version_number=1,
        created_at=PUBLISHED_AT,
    )

    assert (refused.code, refused.detail) == (
        "FOLDER_DOCUMENT_INVALID",
        f"{MOCKUP_LOCATION}: ELEMENT_FORBIDDEN",
    )
    assert after_refusal == 0
    assert stored == result.plan.design
    assert stored.package.generated_mockup is not None
    assert stored.package.prototype == stored.package.generated_mockup.prototype()
    assert stored.package.owner_assertions == ASSERTIONS
    assert again.files[MOCKUP_FILE] == exported.files[MOCKUP_FILE]
