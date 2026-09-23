import json

import httpx
import pytest
import sqlalchemy as sa

from orchestwin.models.source_assembly import assemble_static_module
from orchestwin.models.source_proposals import ModelSourceProposalAdapter
from orchestwin.persistence import create_database_runtime
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from src.test.python.integration.test_model_source_generation_postgres import (
    application,
    artifacts,
    body,
    client_app,
    failed_attempt,
    seed,
    source_output,
)
from src.test.python.integration.test_proposal_evidence_postgres import database, run
from src.test.python.models.test_proposal_evidence import audited_generator
from src.test.python.models.test_source_file_generation import source_sequence_generator

__all__ = ["database"]

pytestmark = pytest.mark.integration


def module(body):
    return assemble_static_module(
        {
            "shared_state": [],
            "private_helpers": "",
            "functions": [{"name": "value", "parameters": "", "body": body}],
            "browser_setup": "  document.title = String(value());",
        }
    )


BROKEN = module("  document.title = 'Repaired';\n  return 'Repaired';")
FIXED = module("  return 'Repaired';")


def repair_payload(content):
    return {
        "rationale": "Repair the recorded synthetic failure.",
        "changes": [
            {
                "normalized_path": "app.js",
                "operation": "REPLACE",
                "content": content,
                "media_type": "text/javascript",
            }
        ],
    }


def contexts_by_generation(rows):
    return {
        str(identifier): json.loads(json.loads(snapshot)["request"]["input_payload_json"])[
            "context"
        ]
        for identifier, snapshot in rows
    }


@pytest.mark.parametrize("tamper", [None, "hash", "context"])
def test_repair_retry_is_audited_and_bound_to_the_accepted_attempt(
    database, tmp_path, monkeypatch, tamper
):
    versions = artifacts()
    generator, _ = source_sequence_generator(tmp_path, source_output(ExecutionTarget.WEB_STATIC))

    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project = await seed(db, versions)
            runtime = application(db, tmp_path, generator)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=client_app(runtime, owner)),
                base_url="http://synthetic/api/v1",
            ) as client:
                initial = await client.post(
                    f"/projects/{project}/source-generations/web",
                    json=body(ExecutionTarget.WEB_STATIC, versions[2]),
                )
                assert initial.status_code == 201, initial.text
                attempt, request_body = await failed_attempt(
                    db, owner, project, ExecutionTarget.WEB_STATIC
                )
                repair_directory = tmp_path / "repair"
                repair_directory.mkdir()
                repair_generator, transport = audited_generator(
                    repair_directory, repair_payload(BROKEN)
                )
                post = transport.post_json

                async def sequential(**kwargs):
                    transport.output = repair_payload(FIXED if transport.calls else BROKEN)
                    return await post(**kwargs)

                transport.post_json = sequential
                if tamper:
                    generate = repair_generator.generate

                    async def tampered(**kwargs):
                        ctx = kwargs["context"]
                        if "repair_retry" in ctx:
                            ctx = {**ctx, "repair_retry": {**ctx["repair_retry"]}}
                            if tamper == "hash":
                                ctx["repair_retry"]["previous_request_hash"] = "0" * 64
                            else:
                                ctx["failure_signature"] = {**ctx["failure_signature"], "x": 1}
                            kwargs = {**kwargs, "context": ctx}
                        return await generate(**kwargs)

                    monkeypatch.setattr(repair_generator, "generate", tampered)
                runtime.real_model_runtime.sources = ModelSourceProposalAdapter(repair_generator)
                response = await client.post(
                    f"/projects/{project}/repair-generations/web/{attempt.id}",
                    json=request_body,
                )
            assert len(transport.calls) == (1 if tamper else 2)
            async with db.session_factory() as session:
                rows = (
                    await session.execute(
                        sa.text(
                            "SELECT id, snapshot_json FROM model_proposal_generations "
                            "WHERE task_id = 'proposal-web-repair-v1'"
                        )
                    )
                ).all()
                contexts = contexts_by_generation(rows)
                events = (
                    await session.execute(
                        sa.text(
                            "SELECT generation_id, kind, snapshot_json "
                            "FROM model_proposal_generation_events"
                        )
                    )
                ).all()
                payloads = {}
                for identifier, kind, snapshot in events:
                    payloads.setdefault(str(identifier), {})[kind] = json.loads(snapshot)["payload"]
                links = (
                    await session.execute(
                        sa.text(
                            "SELECT generation_id FROM model_proposal_artifact_links "
                            "WHERE artifact_kind = 'WEB_REPAIR'"
                        )
                    )
                ).all()
                repairs = await session.scalar(
                    sa.text("SELECT count(*) FROM web_governed_operations WHERE kind = 'REPAIR'")
                )
            if tamper:
                assert response.status_code == 503, response.text
                assert response.json()["detail"]["code"] == "GENERATION_EVIDENCE_WRITE_FAILED"
                assert len(contexts) == 1
                assert not links and repairs == 0
                (rejected_id,) = contexts
                assert payloads[rejected_id]["ADAPTER_REJECTED"]["code"] == (
                    "SOURCE_JAVASCRIPT_SYNTAX_INVALID"
                )
                return
            assert response.status_code == 201, response.text
            retries = {
                identifier: ctx for identifier, ctx in contexts.items() if "repair_retry" in ctx
            }
            assert len(contexts) == 2 and len(retries) == 1
            retry_id, retry_ctx = next(iter(retries.items()))
            retry = retry_ctx.pop("repair_retry")
            rejected_id = retry["previous_generation_id"]
            assert retry == {
                "attempt": 2,
                "previous_generation_id": rejected_id,
                "previous_request_hash": next(
                    json.loads(snapshot)["request"]["content_hash"]
                    for identifier, snapshot in rows
                    if str(identifier) == rejected_id
                ),
                "code": "SOURCE_JAVASCRIPT_SYNTAX_INVALID",
            }
            assert retry_ctx == contexts[rejected_id]
            rejected = payloads[rejected_id]
            assert rejected["ADAPTER_REJECTED"]["code"] == "SOURCE_JAVASCRIPT_SYNTAX_INVALID"
            assert rejected["APPLICATION_RESULT"] == {
                "status": "FAILED",
                "code": "SOURCE_JAVASCRIPT_SYNTAX_INVALID",
            }
            assert "ADAPTER_ACCEPTED" not in rejected
            accepted = payloads[retry_id]
            assert accepted["ADAPTER_ACCEPTED"]["related_generations"] == [
                {
                    "role": "REJECTED_REPAIR_ATTEMPT",
                    "generation_id": rejected_id,
                    "request_hash": retry["previous_request_hash"],
                    "code": "SOURCE_JAVASCRIPT_SYNTAX_INVALID",
                }
            ]
            assert accepted["APPLICATION_RESULT"]["status"] != "FAILED"
            assert [str(identifier) for (identifier,) in links] == [retry_id]
            assert repairs == 1
            assert response.json()["snapshot"]["model_generation_id"] == retry_id
        finally:
            await db.dispose()

    run(scenario())
