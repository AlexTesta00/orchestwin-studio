from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa

from orchestwin.artifacts.design_evaluation_persistence import (
    RUNS,
    SqlAlchemyDesignEvaluationRepository,
)
from orchestwin.artifacts.design_finding_validation_persistence import (
    SqlAlchemyFindingValidationRepository,
)
from orchestwin.artifacts.design_gate import design_artifact_reference
from orchestwin.knowledge import project_import_service
from orchestwin.knowledge.folder import build_knowledge_folder, folder_archive
from orchestwin.knowledge.project_import_service import ProjectImportError, ProjectImportService
from orchestwin.persistence import create_database_runtime
from orchestwin.workflow.gates import HumanGateType
from src.test.python.integration.test_postgresql_project_import import row_counts, seed_users
from src.test.python.integration.test_proposal_evidence_postgres import database, run
from src.test.python.knowledge.knowledge_fixtures import PUBLISHED_AT, approved_gate
from src.test.python.knowledge.why_fixtures import current_feedback_sources

__all__ = ["database"]
pytestmark = pytest.mark.integration


def content_with_feedback():
    sources = current_feedback_sources(claim_reference=True)
    return folder_archive(
        build_knowledge_folder(sources, version_number=1, created_at=PUBLISHED_AT)
    ).content


def test_import_verifies_real_stored_feedback_and_keeps_it_synthetic(database):
    content = content_with_feedback()

    async def scenario():
        db = create_database_runtime(database)
        owner = uuid4()
        try:
            await seed_users(db, owner)
            result = await ProjectImportService(
                session_factory=db.session_factory, clock=lambda: datetime.now(UTC)
            ).import_archive(owner_user_id=owner, content=content)
            async with db.session_factory() as session:
                runs = await SqlAlchemyDesignEvaluationRepository(
                    session, owner_user_id=owner
                ).list(project_id=result.project.id)
                decisions = await SqlAlchemyFindingValidationRepository(
                    session, owner_user_id=owner
                ).current(project_id=result.project.id)
                why_tables = (
                    (
                        await session.execute(
                            sa.text(
                                "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE '%why%'"
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            assert result.why_verified is True
            assert "LEARNED_PROJECTION_NOT_RESTORED" in result.import_limits
            assert len(runs) == 1
            assert runs[0] == result.plan.evaluations[0]
            assert runs[0].findings[0].requires_human_validation is True
            assert runs[0].findings[0].is_simulated_feedback is True
            assert decisions[0].decision.value == "OWNER_CONFIRMED"
            assert why_tables == []
        finally:
            await db.dispose()

    run(scenario())


def test_post_write_derivation_mismatch_rolls_back_every_imported_row(database, monkeypatch):
    content = content_with_feedback()
    original = project_import_service.verify_imported_why

    async def changed_storage(session, **values):
        await session.execute(sa.delete(RUNS).where(RUNS.c.project_id == values["plan"].project_id))
        await original(session, **values)

    monkeypatch.setattr(project_import_service, "verify_imported_why", changed_storage)

    async def scenario():
        db = create_database_runtime(database)
        owner = uuid4()
        try:
            await seed_users(db, owner)
            before = await row_counts(db)
            with pytest.raises(ProjectImportError, match="FOLDER_WHY_MISMATCH"):
                await ProjectImportService(session_factory=db.session_factory).import_archive(
                    owner_user_id=owner, content=content
                )
            assert await row_counts(db) == before
            async with db.session_factory() as session:
                assert (
                    await session.execute(sa.select(sa.func.count()).select_from(RUNS))
                ).scalar_one() == 0
        finally:
            await db.dispose()

    run(scenario())


def test_missing_historical_design_context_imports_no_rows(database):
    sources = current_feedback_sources()
    design = replace(sources.design, id=uuid4())
    sources = replace(
        sources,
        design=design,
        design_gate=approved_gate(
            design, HumanGateType.DESIGN, design_artifact_reference(design), 9970
        ),
    )
    content = folder_archive(
        build_knowledge_folder(sources, version_number=1, created_at=PUBLISHED_AT)
    ).content

    async def scenario():
        db = create_database_runtime(database)
        owner = uuid4()
        try:
            await seed_users(db, owner)
            before = await row_counts(db)
            with pytest.raises(ProjectImportError, match="FOLDER_FEEDBACK_CONTEXT_MISSING"):
                await ProjectImportService(session_factory=db.session_factory).import_archive(
                    owner_user_id=owner, content=content
                )
            assert await row_counts(db) == before
        finally:
            await db.dispose()

    run(scenario())


def test_tampered_feedback_imports_no_rows_even_with_an_updated_file_digest(database):
    sources = current_feedback_sources(claim_reference=True)
    folder = build_knowledge_folder(sources, version_number=1, created_at=PUBLISHED_AT)
    files = dict(folder.files)
    document = json.loads(files["twins/feedback/reviews.json"])
    document["runs"][0]["responses"][0]["findings"][0]["summary"] = "Tampered synthetic finding."
    files["twins/feedback/reviews.json"] = json.dumps(document)
    manifest = json.loads(files["orchestwin.json"])
    manifest["files"]["twins/feedback/reviews.json"] = hashlib.sha256(
        files["twins/feedback/reviews.json"].encode("utf-8")
    ).hexdigest()
    files["orchestwin.json"] = json.dumps(manifest)
    content = folder_archive(replace(folder, files=files)).content

    async def scenario():
        db = create_database_runtime(database)
        owner = uuid4()
        try:
            await seed_users(db, owner)
            before = await row_counts(db)
            with pytest.raises(ProjectImportError, match="FOLDER_TAMPERED"):
                await ProjectImportService(session_factory=db.session_factory).import_archive(
                    owner_user_id=owner, content=content
                )
            assert await row_counts(db) == before
        finally:
            await db.dispose()

    run(scenario())
