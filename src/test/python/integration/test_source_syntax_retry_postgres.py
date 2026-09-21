"""A rejected source invocation remains evidence when its one retry succeeds."""

import json

import httpx
import pytest
import sqlalchemy as sa

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
from src.test.python.models.test_source_file_generation import broken, source_sequence_generator

__all__ = ["database", "pytestmark"]


@pytest.mark.parametrize("exhausted", [False, True])
def test_syntax_retry_preserves_failed_child_and_publishes_only_complete_accepted_tree(
    database, tmp_path, exhausted
):
    versions = artifacts()

    def mutate(ctx, output):
        if ctx.get("source_step", {}).get("ordinal") == 2 and (
            exhausted or "syntax_retry" not in ctx
        ):
            return broken(output, "assert.equal(result, (")
        return output

    generator, _ = source_sequence_generator(
        tmp_path, source_output(ExecutionTarget.WEB_STATIC), mutate=mutate
    )

    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project = await seed(db, versions)
            runtime = application(db, tmp_path, generator)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=client_app(runtime, owner)),
                base_url="http://test/api/v1",
            ) as client:
                response = await client.post(
                    f"/projects/{project}/source-generations/web",
                    json=body(ExecutionTarget.WEB_STATIC, versions[2]),
                )
            assert response.status_code == (502 if exhausted else 201), response.text
            async with db.session_factory() as session:
                requests = (
                    await session.execute(
                        sa.text("SELECT id, snapshot_json FROM model_proposal_generations")
                    )
                ).all()
                assert len(requests) == (4 if exhausted else 5)
                retries = [
                    (
                        identifier,
                        json.loads(json.loads(snapshot)["request"]["input_payload_json"])[
                            "context"
                        ],
                    )
                    for identifier, snapshot in requests
                    if "syntax_retry"
                    in json.loads(json.loads(snapshot)["request"]["input_payload_json"])["context"]
                ]
                assert len(retries) == 1
                retry_id, retry_ctx = retries[0]
                failed_id = retry_ctx["syntax_retry"]["previous_generation_id"]
                events = (
                    await session.execute(
                        sa.text(
                            "SELECT generation_id, kind, snapshot_json FROM model_proposal_generation_events"
                        )
                    )
                ).all()
                failed = {
                    kind: json.loads(snapshot)["payload"]
                    for identifier, kind, snapshot in events
                    if str(identifier) == failed_id
                }
                assert "HTTP_RESPONSE" in failed and "PROVIDER_RESULT" in failed
                assert failed["ADAPTER_REJECTED"]["code"] == "SOURCE_JAVASCRIPT_SYNTAX_INVALID"
                assert failed["APPLICATION_RESULT"]["status"] == "FAILED"
                assert "ADAPTER_ACCEPTED" not in failed
                if not exhausted:
                    parent_accepted = next(
                        json.loads(snapshot)["payload"]
                        for identifier, kind, snapshot in events
                        if kind == "ADAPTER_ACCEPTED"
                        and json.loads(snapshot)["payload"]
                        .get("result", {})
                        .get("generation_steps")
                    )
                    selected = parent_accepted["result"]["generation_steps"][1]
                    assert selected["generation_id"] == str(retry_id)
                assert await session.scalar(
                    sa.text("SELECT count(*) FROM web_source_revisions")
                ) == (0 if exhausted else 1)
        finally:
            await db.dispose()

    run(scenario())
    with pytest.raises(sa.exc.DBAPIError, match="Cannot remove protection of retained source"):
        downgrade_database(database, revision="0042_web_source_owner_edits")


@pytest.mark.parametrize("tamper", ["attempt", "hash", "context"])
def test_database_refuses_unbound_or_unbounded_syntax_retry(
    database, tmp_path, monkeypatch, tamper
):
    versions = artifacts()

    def invalid_first(ctx, output):
        # The first file is now HTML; inject an actual inline JavaScript parse
        # error so this test still exercises syntax lineage, not missing design.
        return (
            {"content": "<script>const unfinished = (</script>"}
            if ctx.get("source_step")
            else output
        )

    generator, transport = source_sequence_generator(
        tmp_path, source_output(ExecutionTarget.WEB_STATIC), mutate=invalid_first
    )
    generate = generator.generate

    async def tampered_generate(**kwargs):
        ctx = kwargs["context"]
        if "syntax_retry" in ctx:
            ctx = {**ctx, "syntax_retry": {**ctx["syntax_retry"]}}
            if tamper == "attempt":
                ctx["syntax_retry"]["attempt"] = 3
            elif tamper == "hash":
                ctx["syntax_retry"]["previous_request_hash"] = "0" * 64
            else:
                ctx["completed_files"] = [{"normalized_path": "extra.js", "content": "modified"}]
            kwargs = {**kwargs, "context": ctx}
        return await generate(**kwargs)

    monkeypatch.setattr(generator, "generate", tampered_generate)

    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project = await seed(db, versions)
            runtime = application(db, tmp_path, generator)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=client_app(runtime, owner)),
                base_url="http://test/api/v1",
            ) as client:
                response = await client.post(
                    f"/projects/{project}/source-generations/web",
                    json=body(ExecutionTarget.WEB_STATIC, versions[2]),
                )
            assert response.status_code == 503
            assert response.json()["detail"]["code"] == "GENERATION_EVIDENCE_WRITE_FAILED"
            assert len(transport.calls) == 2
            assert (
                await runtime.web_source_api_service.source_revision_history(
                    owner_user_id=owner, project_id=project
                )
                == ()
            )
        finally:
            await db.dispose()

    run(scenario())


def test_empty_syntax_retry_migration_roundtrip(database):
    downgrade_database(database, revision="0042_web_source_owner_edits")
    upgrade_database(database)
