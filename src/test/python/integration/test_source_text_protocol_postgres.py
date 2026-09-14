"""Exact UTF-8 text, legacy rejection and retained-evidence migration boundaries."""

import hashlib

import httpx
import pytest
import sqlalchemy as sa

from orchestwin.models import source_file_generation
from orchestwin.persistence import create_database_runtime
from orchestwin.persistence.migrate import downgrade_database, upgrade_database
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from src.test.python.integration.test_model_source_generation_postgres import (
    application,
    artifacts,
    body,
    client_app,
    seed,
    source_output,
)
from src.test.python.integration.test_proposal_evidence_postgres import database, pytestmark, run
from src.test.python.models.test_source_file_generation import source_sequence_generator

__all__ = ["database", "pytestmark"]


@pytest.mark.parametrize("final_newline", [False, True])
def test_more_than_sixty_lines_preserve_exact_text_and_cannot_lose_migration_protection(
    database, tmp_path, final_newline
):
    versions = artifacts()
    output = source_output(ExecutionTarget.WEB_STATIC)
    content = "\n".join(f"// città, reserved line {number}" for number in range(72))
    content += "\n" if final_newline else ""
    output["files"][0]["content"] = content
    generator, _ = source_sequence_generator(tmp_path, output)

    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project = await seed(db, versions)
            runtime = application(db, tmp_path, generator)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=client_app(runtime, owner)),
                base_url="http://synthetic/api/v1",
            ) as client:
                response = await client.post(
                    f"/projects/{project}/source-generations/web",
                    json=body(ExecutionTarget.WEB_STATIC, versions[2]),
                )
            assert response.status_code == 201, response.text
            entry = next(
                file
                for file in response.json()["snapshot"]["files"]
                if file["normalized_path"] == "app.js"
            )
            raw = (tmp_path / "web" / entry["storage_key"]).read_bytes()
            assert raw == content.encode("utf-8")
            assert entry["sha256_digest"] == hashlib.sha256(raw).hexdigest()
            async with db.session_factory() as session:
                return await session.scalar(
                    sa.text("SELECT count(*) FROM model_proposal_generations")
                )
        finally:
            await db.dispose()

    count = run(scenario())
    assert count == 4
    with pytest.raises(sa.exc.DBAPIError, match="Cannot remove protection of retained source text"):
        downgrade_database(database, revision="0040_source_file_evidence")
    engine = sa.create_engine(database.sqlalchemy_url)
    try:
        with engine.connect() as connection:
            assert (
                connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                == "0041_source_text_evidence"
            )
            assert (
                connection.scalar(sa.text("SELECT count(*) FROM model_proposal_generations"))
                == count
            )
    finally:
        engine.dispose()


def test_text_payload_cannot_masquerade_as_historical_line_array_protocol(
    database, tmp_path, monkeypatch
):
    versions = artifacts()
    generator, _ = source_sequence_generator(tmp_path, source_output(ExecutionTarget.WEB_STATIC))
    monkeypatch.setattr(source_file_generation, "PROTOCOL", "SOURCE_FILES_V1")

    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project = await seed(db, versions)
            runtime = application(db, tmp_path, generator)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=client_app(runtime, owner)),
                base_url="http://synthetic/api/v1",
            ) as client:
                response = await client.post(
                    f"/projects/{project}/source-generations/web",
                    json=body(ExecutionTarget.WEB_STATIC, versions[2]),
                )
            assert response.status_code == 503
            assert response.json()["detail"]["code"] == "GENERATION_EVIDENCE_WRITE_FAILED"
            assert (
                await runtime.web_source_api_service.source_revision_history(
                    owner_user_id=owner, project_id=project
                )
                == ()
            )
        finally:
            await db.dispose()

    run(scenario())


def test_empty_migration_roundtrip_preserves_predecessor_guards(database):
    downgrade_database(database, revision="0040_source_file_evidence")
    engine = sa.create_engine(database.sqlalchemy_url)

    def definitions():
        with engine.connect() as connection:
            return tuple(
                connection.exec_driver_sql(
                    "SELECT pg_get_functiondef(%s::regprocedure)", (name,)
                ).scalar_one()
                for name in ("validate_source_file_request()", "validate_source_file_acceptance()")
            )

    try:
        before = definitions()
        upgrade_database(database)
        downgrade_database(database, revision="0040_source_file_evidence")
        assert definitions() == before
        upgrade_database(database)
    finally:
        engine.dispose()
