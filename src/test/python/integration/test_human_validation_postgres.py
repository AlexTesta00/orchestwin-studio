from __future__ import annotations

import asyncio
import importlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from orchestwin.artifacts.human_validation_runtime import SqlAlchemyHumanValidationService
from orchestwin.artifacts.why_runtime import SqlAlchemyWhyQueryService
from orchestwin.knowledge.project_import_service import ProjectImportService
from orchestwin.persistence import create_database_runtime
from orchestwin.persistence.migrate import downgrade_database, upgrade_database
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.projects.persistence.research_evidence import SqlAlchemyResearchEvidenceRepository
from orchestwin.validation import ValidationError
from orchestwin.why import explain_why
from src.test.python.integration.postgres_isolation import (
    assert_reversible_migration,
    isolated_postgres_settings,
)
from src.test.python.integration.test_postgresql_project_import import seed_users
from src.test.python.integration.test_proposal_evidence_postgres import database, run
from src.test.python.integration.test_research_evidence_import_postgres import (
    synthetic_evidence_archive,
)

__all__ = ["database"]
pytestmark = pytest.mark.integration
MIGRATION = importlib.import_module(
    "orchestwin.persistence.migrations.versions.0069_human_validation"
)
NOW = datetime(2026, 10, 3, 10, tzinfo=UTC)
TEXT = "Synthetic contract fixture; no participants.\nè exact synthetic observation"


async def seed_validation_project(db, *, owner_user_id=None):
    owner_user_id = owner_user_id or uuid4()
    await seed_users(db, owner_user_id)
    archive, _, _ = synthetic_evidence_archive()
    imported = await ProjectImportService(session_factory=db.session_factory).import_archive(
        owner_user_id=owner_user_id, content=archive
    )
    project = imported.project.id
    why = SqlAlchemyWhyQueryService(db.session_factory)
    original = await why.current(owner_user_id=owner_user_id, project_id=project)
    scenario_node = next(
        node for node in original["nodes"] if node["kind"] == "SCENARIO" and node["current"]
    )
    twin_key = next(
        link["target"]
        for link in original["links"]
        if link["source"] == scenario_node["key"] and link["kind"] == "ACTOR"
    )
    claim_key = next(
        link["source"]
        for link in original["links"]
        if link["target"] == twin_key
        and link["kind"] == "CLAIM_OF"
        and next(node for node in original["nodes"] if node["key"] == link["source"])[
            "validation_required"
        ]
    )
    design_node = next(
        node
        for node in original["nodes"]
        if node["kind"] == "DESIGN_ALTERNATIVE" and node["current"]
    )
    runtime = SqlAlchemyHumanValidationService(db.session_factory, clock=lambda: NOW)
    saved = await runtime.save_hypothesis(
        owner_user_id=owner_user_id,
        project_id=project,
        request={
            "candidate_key": claim_key,
            "twin_key": twin_key,
            "scenario_key": scenario_node["key"],
            "design_key": design_node["key"],
            "question": "Can this synthetic task be completed?",
            "observe": ["Synthetic completion"],
            "limitations": "No participants; isolated contract fixture.",
        },
    )
    hypothesis = saved["hypothesis"]
    async with db.session_factory() as session, session.begin():
        repository = SqlAlchemyResearchEvidenceRepository(session, owner_user_id=owner_user_id)
        evidence = await repository.insert(
            project,
            text=TEXT,
            metadata={
                "title": "Synthetic human-session contract fixture",
                "source_kind": "EMPIRICAL_RESEARCH",
                "source_ref": "synthetic.invalid/SES-001",
                "context": "Synthetic contract metadata, no actual session.",
                "method": "Synthetic isolated fixture; no participants.",
                "collected_at": None,
                "limitations": "No empirical research or actual participants.",
                "empirical": True,
            },
        )
    return {
        "owner_user_id": owner_user_id,
        "project_id": project,
        "hypothesis": hypothesis,
        "evidence": evidence,
        "why": why,
        "runtime": runtime,
    }


def test_isolated_human_validation_migration_is_reversible(database):
    assert_reversible_migration(database, MIGRATION)


def test_migration_roundtrip_preserves_existing_project_and_evidence_hash(database):
    with isolated_postgres_settings(database, revision=MIGRATION.down_revision) as scoped:

        async def scenario():
            db = create_database_runtime(scoped)
            owner, project = uuid4(), uuid4()
            try:
                await seed_users(db, owner)
                async with db.session_factory() as session, session.begin():
                    session.add(
                        ProjectRecord(
                            id=project,
                            owner_user_id=owner,
                            display_name="Synthetic pre-0069 project",
                            mode="GREENFIELD_GENERATION",
                            created_at=NOW,
                            updated_at=NOW,
                        )
                    )
                    await session.flush()
                    evidence = await SqlAlchemyResearchEvidenceRepository(
                        session, owner_user_id=owner
                    ).insert(
                        project,
                        text=TEXT,
                        metadata={
                            "title": "Synthetic pre-0069 source",
                            "source_kind": "OWNER_INPUT",
                            "source_ref": "synthetic.invalid",
                            "context": "Synthetic software fixture.",
                            "method": "Synthetic fixture.",
                            "collected_at": None,
                            "limitations": "No participants or empirical results.",
                            "empirical": False,
                        },
                    )
                original = evidence.to_snapshot()
                await asyncio.to_thread(upgrade_database, scoped, revision=MIGRATION.revision)
                async with db.session_factory() as session:
                    after = await SqlAlchemyResearchEvidenceRepository(
                        session, owner_user_id=owner
                    ).get(project, evidence.id)
                    assert after.to_snapshot() == original
                    assert (
                        await session.scalar(
                            sa.select(ProjectRecord.display_name).where(ProjectRecord.id == project)
                        )
                        == "Synthetic pre-0069 project"
                    )
                await asyncio.to_thread(
                    downgrade_database, scoped, revision=MIGRATION.down_revision
                )
                async with db.session_factory() as session:
                    final = await SqlAlchemyResearchEvidenceRepository(
                        session, owner_user_id=owner
                    ).get(project, evidence.id)
                    assert final.to_snapshot() == original
            finally:
                await db.dispose()

        run(scenario())


def test_hypothesis_outcome_retirement_deletion_history_and_owner_scope(database):
    async def scenario():
        db = create_database_runtime(database)
        owner, stranger = uuid4(), uuid4()
        try:
            seeded = await seed_validation_project(db, owner_user_id=owner)
            await seed_users(db, stranger)
            project, hypothesis, evidence = (
                seeded["project_id"],
                seeded["hypothesis"],
                seeded["evidence"],
            )
            runtime, why = seeded["runtime"], seeded["why"]
            outcome = await runtime.record_outcome(
                owner_user_id=owner,
                project_id=project,
                request={
                    "hypothesis_id": hypothesis["id"],
                    "hypothesis_version_number": 1,
                    "hypothesis_content_hash": hypothesis["content_hash"],
                    "session_ref": "SES-001",
                    "session_kind": "HUMAN_SESSION",
                    "outcome": "CONFIRMED",
                    "coverage": "COMPLETE",
                    "limitations": "Synthetic fixture only.",
                    "evidence_id": str(evidence.id),
                    "evidence_version": 1,
                    "quote": "è exact synthetic observation",
                    "line": 2,
                },
            )
            assert (await runtime.current(owner_user_id=owner, project_id=project))["hypotheses"][
                0
            ]["state"] == "CONFIRMED"
            assert await runtime.current(owner_user_id=stranger, project_id=project) is None
            with pytest.raises(ValidationError, match="PROJECT_NOT_FOUND"):
                await runtime.save_hypothesis(
                    owner_user_id=stranger, project_id=project, request={}
                )
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyResearchEvidenceRepository(session, owner_user_id=owner)
                assert await repository.owned(project, lock=True)
                await repository.retire(
                    project, evidence.id, reason="Synthetic withdrawal", occurred_at=NOW
                )
            retired = await runtime.current(owner_user_id=owner, project_id=project)
            assert retired["hypotheses"][0]["state"] == "TO_VERIFY"
            assert retired["outcomes"][0]["effective_status"] == "RETIRED"
            assert retired["outcomes"][0]["content_hash"] == outcome["outcome"]["content_hash"]
            async with db.session_factory() as session, session.begin():
                await SqlAlchemyResearchEvidenceRepository(
                    session, owner_user_id=owner
                ).delete_text(project, evidence.id)
            deleted = await runtime.current(owner_user_id=owner, project_id=project)
            assert deleted["outcomes"][0]["citation"] == outcome["outcome"]["citation"]
            assert deleted["hypotheses"][0]["state"] == "TO_VERIFY"
            answer = explain_why(
                await why.current(owner_user_id=owner, project_id=project), "HVO-001"
            )
            assert "SOURCE_RETIRED" in answer["limits"]
            assert "SOURCE_TEXT_UNAVAILABLE" in answer["limits"]
            with pytest.raises(DBAPIError):
                async with db.session_factory() as session, session.begin():
                    await session.execute(
                        sa.text("DELETE FROM project_validation_outcomes WHERE id=:id"),
                        {"id": UUID(outcome["outcome"]["id"])},
                    )
            with pytest.raises(RuntimeError, match="must be preserved"):
                await asyncio.to_thread(
                    downgrade_database, database, revision=MIGRATION.down_revision
                )
        finally:
            await db.dispose()

    run(scenario())
