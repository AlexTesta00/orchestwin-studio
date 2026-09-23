"""Owner edits retain exact generated predecessors and a separate audit trail."""

from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa

from orchestwin.api.services import ApplicationRuntime
from orchestwin.api.web_execution import (
    WebSourcePlanFileCommand,
    WebSourceProvenanceCommand,
    WebSourceRevisionCreateCommand,
)
from orchestwin.api.web_source_runtime import SqlAlchemyWebSourceApiService
from orchestwin.artifacts.web_sources import WebSourceProvenanceKind
from orchestwin.persistence import create_database_runtime
from orchestwin.persistence.migrate import downgrade_database, upgrade_database
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.web_execution.targets import WebImplementationLanguage, WebProjectLayout
from src.test.python.integration.test_model_source_generation_postgres import (
    artifacts,
    client_app,
    seed,
)
from src.test.python.integration.test_proposal_evidence_postgres import database, pytestmark, run

__all__ = ["database", "pytestmark"]


def test_owner_edit_roundtrip_is_distinct_from_generation_and_cannot_erase_original(
    database, tmp_path
):
    versions = artifacts()

    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project = await seed(db, versions)
            architecture = versions[2]
            service = SqlAlchemyWebSourceApiService(
                db.session_factory, content_root=tmp_path / "objects"
            )
            initial = await service.create_source_revision(
                owner_user_id=owner,
                project_id=project,
                command=WebSourceRevisionCreateCommand(
                    target=ExecutionTarget.WEB_STATIC,
                    frontend_language=WebImplementationLanguage.STATIC_ASSETS,
                    backend_language=None,
                    layout=WebProjectLayout.SINGLE_ROOT,
                    rationale="Explicit synthetic source fixture.",
                    files=(
                        WebSourcePlanFileCommand("index.html", "<h1>Original</h1>", "text/html"),
                    ),
                    provenance_references=(
                        WebSourceProvenanceCommand(
                            WebSourceProvenanceKind.ARCHITECTURE,
                            f"architecture:{architecture.id}",
                            architecture.version_number,
                            architecture.content_hash,
                        ),
                    ),
                ),
            )
            assert initial.status.value == "SOURCE_REVISION_CREATED"
            original = initial.snapshot
            payload = {
                "base_revision_content_hash": original["content_hash"],
                "rationale": "Correct the visible controls after owner review.",
                "files": [
                    {
                        "normalized_path": "index.html",
                        "content": "<h1>Corrected</h1>",
                        "media_type": "text/html",
                    }
                ],
            }
            runtime = ApplicationRuntime(web_source_api_service=service)
            path = f"/projects/{project}/web-source-revisions/{original['id']}/edits"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=client_app(runtime, owner)),
                base_url="http://test/api/v1",
            ) as client:
                response = await client.post(path, json=payload)
                assert response.status_code == 201, response.text
                edited = response.json()["snapshot"]
                assert edited["origin"] == "OWNER_EDIT"
                assert edited["version_number"] == 2
                assert edited["based_on"]["content_hash"] == original["content_hash"]
                assert edited["owner_edit"]["rationale"] == payload["rationale"]
                assert (await client.post(path, json=payload)).status_code == 409
                design_path = (
                    f"/projects/{project}/web-source-revisions/{edited['id']}/design-reference"
                )
                design_response = await client.get(design_path)
                assert design_response.status_code == 200, design_response.text
                ancestry = design_response.json()
                assert ancestry["source"]["origin"] == "OWNER_EDIT"
                assert ancestry["design"]["artifact_id"] == str(versions[1].id)
                assert ancestry["design"]["content_hash"] == versions[1].content_hash
                assert ancestry["architecture"]["artifact_id"] == str(architecture.id)
                assert ancestry["prototype"] == versions[1].package.prototype.to_snapshot()
                assert ancestry["design_status"] == "CURRENT"
                assert ancestry["visual_conformance"] == "NOT_ASSESSED"
                assert design_response.headers["cache-control"] == "no-store"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=client_app(runtime, uuid4())),
                base_url="http://test/api/v1",
            ) as other:
                assert (await other.post(path, json=payload)).status_code == 404
                assert (await other.get(design_path)).status_code == 404
            history = await service.source_revision_history(owner_user_id=owner, project_id=project)
            assert history == (original, edited)
            before, files = await service.source_files(
                owner_user_id=owner, project_id=project, revision_id=UUID(original["id"])
            )
            assert before == original and files[0][2] == b"<h1>Original</h1>"
            workspace = await service.prepare_workspace(
                owner_user_id=owner, project_id=project, revision_id=UUID(edited["id"])
            )
            assert (workspace.path / "index.html").read_text() == "<h1>Corrected</h1>"
            async with db.session_factory() as session:
                assert (
                    await session.scalar(sa.text("SELECT count(*) FROM model_proposal_generations"))
                    == 0
                )
                assert (
                    await session.scalar(sa.text("SELECT count(*) FROM web_source_revisions")) == 2
                )
            async with db.session_factory() as session:
                with pytest.raises(sa.exc.DBAPIError, match="immutable"):
                    await session.execute(
                        sa.text(
                            "UPDATE web_source_revisions SET origin = 'GENERATED_PLAN' WHERE version_number = 2"
                        )
                    )
        finally:
            await db.dispose()

    run(scenario())
    with pytest.raises(sa.exc.DBAPIError, match="Cannot remove owner-edit support"):
        downgrade_database(database, revision="0041_source_text_evidence")


def test_owner_edit_constraint_migration_roundtrip_without_history(database):
    downgrade_database(database, revision="0041_source_text_evidence")
    upgrade_database(database)
    engine = sa.create_engine(database.sqlalchemy_url)
    try:
        with engine.connect() as connection:
            definition = connection.scalar(
                sa.text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'ck_web_source_revisions_ck_web_source_revisions_origin' "
                    "AND conrelid = 'web_source_revisions'::regclass"
                )
            )
            assert "OWNER_EDIT" in definition
            assert (
                connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                == "0049_twin_evaluation_task"
            )
    finally:
        engine.dispose()
