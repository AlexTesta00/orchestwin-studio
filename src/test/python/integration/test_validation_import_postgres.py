from __future__ import annotations

import json
from dataclasses import replace
from uuid import uuid4

import pytest
import sqlalchemy as sa

from orchestwin.agents.persistence.repositories import SqlAlchemyTeamProposalVersionRepository
from orchestwin.artifacts.design_gate import design_artifact_reference
from orchestwin.artifacts.design_persistence import SqlAlchemyDesignPackageRepository
from orchestwin.artifacts.human_validation_persistence import (
    HYPOTHESES,
    OUTCOMES,
    SqlAlchemyHumanValidationRepository,
)
from orchestwin.artifacts.human_validation_runtime import SqlAlchemyHumanValidationService
from orchestwin.knowledge import project_import_service
from orchestwin.knowledge.feedback_runtime import SqlAlchemyKnowledgeFeedbackQueryService
from orchestwin.knowledge.folder import build_knowledge_folder, folder_archive
from orchestwin.knowledge.project_import_persistence import SqlAlchemyProjectImportRepository
from orchestwin.knowledge.project_import_service import ProjectImportError, ProjectImportService
from orchestwin.knowledge.validation_records import VALIDATION_DOCUMENT
from orchestwin.persistence import create_database_runtime
from orchestwin.projects.persistence.briefs import SqlAlchemyProjectBriefRepository
from orchestwin.projects.requirements_persistence import (
    SqlAlchemyRequirementsSpecificationRepository,
)
from orchestwin.twins.persistence.repositories import SqlAlchemyUserModelingSnapshotRepository
from orchestwin.workflow.gates import HumanGateType
from src.test.python.integration.test_postgresql_project_import import row_counts, seed_users
from src.test.python.integration.test_proposal_evidence_postgres import database, run
from src.test.python.knowledge.knowledge_fixtures import PUBLISHED_AT, approved_gate, sources_of
from src.test.python.knowledge.test_export import loader
from src.test.python.knowledge.validation_fixtures import validation_sources
from src.test.python.knowledge.why_fixtures import current_feedback_sources

__all__ = ["database"]
pytestmark = pytest.mark.integration


@pytest.mark.parametrize("retired", [False, True])
def test_import_rechecks_stored_validation_and_preserves_exact_lineage_citation_and_metadata(
    database, retired
):
    sources = validation_sources(human=True, version=2, retired=retired)
    content = folder_archive(
        build_knowledge_folder(sources, version_number=1, created_at=PUBLISHED_AT)
    ).content

    async def scenario():
        db = create_database_runtime(database)
        owner, stranger = uuid4(), uuid4()
        try:
            await seed_users(db, owner, stranger)
            result = await ProjectImportService(session_factory=db.session_factory).import_archive(
                owner_user_id=owner, content=content
            )
            async with db.session_factory() as session:
                repository = SqlAlchemyHumanValidationRepository(session, owner_user_id=owner)
                stored = await repository.records(project_id=result.project.id)
                imported = await SqlAlchemyProjectImportRepository(
                    session, owner_user_id=owner
                ).for_project(result.project.id)
                assert imported.import_limits == result.import_limits
                assert "HYPOTHESIS_HISTORY_PARTIAL" in imported.import_limits
                assert imported.omitted_sections == result.omitted_sections
                assert (
                    await SqlAlchemyProjectImportRepository(
                        session, owner_user_id=stranger
                    ).for_project(result.project.id)
                    is None
                )
            assert result.why_verified is True
            assert stored["hypotheses"] == result.plan.validation_records["hypotheses"]
            assert stored["outcomes"] == result.plan.validation_records["outcomes"]
            hypothesis, outcome = stored["hypotheses"][0], stored["outcomes"][0]
            assert hypothesis["version_number"] == 2
            assert hypothesis["based_on_version_number"] == 1
            original = sources.validation_records["outcomes"][0]
            assert outcome["hypothesis_content_hash"] == hypothesis["content_hash"]
            assert outcome["citation"]["quote"] == original["citation"]["quote"]
            assert outcome["citation"]["content_hash"] == original["citation"]["content_hash"]
            assert outcome["citation"]["source_version"] == original["citation"]["source_version"]
            projection = await SqlAlchemyHumanValidationService(db.session_factory).current(
                owner_user_id=owner, project_id=result.project.id
            )
            assert projection["hypotheses"][0]["state"] == ("TO_VERIFY" if retired else "CONFIRMED")
            assert projection["outcomes"][0]["effective_status"] == (
                "RETIRED" if retired else "ACTIVE"
            )
        finally:
            await db.dispose()

    run(scenario())


def test_post_write_validation_reread_mismatch_rolls_back_all_imported_rows(database, monkeypatch):
    sources = validation_sources(human=True)
    content = folder_archive(
        build_knowledge_folder(sources, version_number=1, created_at=PUBLISHED_AT)
    ).content
    original_verification = project_import_service.verify_imported_why
    original_records = SqlAlchemyHumanValidationRepository.records
    checking = False
    observed = []

    async def inconsistent_reread(repository, *, project_id):
        records = await original_records(repository, project_id=project_id)
        if checking:
            observed.append(
                (
                    repository.session.in_transaction(),
                    len(records["hypotheses"]),
                    len(records["outcomes"]),
                )
            )
            return {**records, "outcomes": []}
        return records

    async def verification(session, **values):
        nonlocal checking
        checking = True
        try:
            return await original_verification(session, **values)
        finally:
            checking = False

    monkeypatch.setattr(SqlAlchemyHumanValidationRepository, "records", inconsistent_reread)
    monkeypatch.setattr(project_import_service, "verify_imported_why", verification)

    async def scenario():
        db = create_database_runtime(database)
        owner = uuid4()
        try:
            await seed_users(db, owner)
            before = await row_counts(db)
            with pytest.raises(ProjectImportError, match="FOLDER_VALIDATION_MISMATCH"):
                await ProjectImportService(session_factory=db.session_factory).import_archive(
                    owner_user_id=owner, content=content
                )
            assert observed == [(True, 1, 1)]
            assert await row_counts(db) == before
            async with db.session_factory() as session:
                for table in (HYPOTHESES, OUTCOMES):
                    assert await session.scalar(sa.select(sa.func.count()).select_from(table)) == 0
        finally:
            await db.dispose()

    run(scenario())


def test_secondary_export_and_import_keep_stored_omissions_with_original_provenance(database):
    original = current_feedback_sources()
    design = replace(original.design, id=uuid4())
    original = replace(
        original,
        design=design,
        design_gate=approved_gate(
            design, HumanGateType.DESIGN, design_artifact_reference(design), 9980
        ),
    )
    folder = build_knowledge_folder(original, version_number=1, created_at=PUBLISHED_AT)

    async def scenario():
        db = create_database_runtime(database)
        owner, stranger = uuid4(), uuid4()
        try:
            await seed_users(db, owner, stranger)
            imports = ProjectImportService(session_factory=db.session_factory)
            result = await imports.import_archive(
                owner_user_id=owner, content=folder_archive(folder).content
            )
            project_id = result.project.id
            async with db.session_factory() as session:
                versions = {
                    "brief": await SqlAlchemyProjectBriefRepository(session).get_current_owned(
                        project_id=project_id, owner_user_id=owner
                    ),
                    "team": await SqlAlchemyTeamProposalVersionRepository(
                        session
                    ).get_current_owned(project_id=project_id, owner_user_id=owner),
                    "twins": await SqlAlchemyUserModelingSnapshotRepository(
                        session, owner_user_id=owner
                    ).current(project_id=project_id),
                    "requirements": await SqlAlchemyRequirementsSpecificationRepository(
                        session, owner_user_id=owner
                    ).current(project_id=project_id),
                    "design": await SqlAlchemyDesignPackageRepository(
                        session, owner_user_id=owner
                    ).current(project_id=project_id),
                }
            loaded = await loader(
                sources_of(versions, project_id=project_id),
                feedback_query_service=SqlAlchemyKnowledgeFeedbackQueryService(db.session_factory),
                validation_query_service=SqlAlchemyHumanValidationService(db.session_factory),
                import_origin_query_service=imports,
            ).load(owner_user_id=owner, project_id=project_id)
            assert loaded.feedback.runs == ()
            exported = build_knowledge_folder(loaded, version_number=1, created_at=PUBLISHED_AT)
            document = json.loads(exported.files[VALIDATION_DOCUMENT])
            omission = document["omitted_sections"][0]
            assert document["hypotheses"] == document["outcomes"] == []
            assert omission["historical"] is True
            assert omission["origin"] == {
                "project_id": str(original.project_id),
                "package_version": 1,
                "package_content_hash": folder.content_hash,
            }
            assert omission["evaluation_run_id"] == str(original.feedback.runs[0].id)
            assert omission["references"] == result.omitted_sections[0]["references"]
            second = await imports.import_archive(
                owner_user_id=owner, content=folder_archive(exported).content
            )
            assert second.why_verified is True
            assert second.plan.evaluations == second.plan.finding_decisions == ()
            second_origin = await imports.origin(owner_user_id=owner, project_id=second.project.id)
            assert second_origin.omitted_sections == tuple(document["omitted_sections"])
            assert "FEEDBACK_CONTEXT_NOT_RESTORED" in second_origin.import_limits
            assert (
                await imports.origin(owner_user_id=stranger, project_id=second.project.id) is None
            )
        finally:
            await db.dispose()

    run(scenario())
