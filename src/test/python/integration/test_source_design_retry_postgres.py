"""Retain rejected HTML, enforce retry lineage, and publish only atomic accepted trees."""

import hashlib
import json
from copy import deepcopy
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa

from orchestwin.models.proposal_evidence import ProposalEvidenceError
from orchestwin.models.proposal_evidence_persistence import (
    GENERATIONS,
    SqlAlchemyProposalEvidenceBindings,
)
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
BAD_HTML = "<!doctype html><title>Unmarked original</title><h1>Original provider bytes</h1>"


def generator_for(tmp_path, *, exhausted=False):
    def mutate(ctx, output):
        if ctx.get("source_step", {}).get("file", {}).get("normalized_path") == "index.html" and (
            exhausted or "design_retry" not in ctx
        ):
            return {"content": BAD_HTML}
        return output

    return source_sequence_generator(
        tmp_path, source_output(ExecutionTarget.WEB_STATIC), mutate=mutate
    )


async def invoke(database, tmp_path, generator, versions):
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
        async with db.session_factory() as session:
            requests = (
                await session.execute(
                    sa.text("SELECT id, snapshot_json FROM model_proposal_generations")
                )
            ).all()
            events = (
                await session.execute(
                    sa.text(
                        "SELECT generation_id, kind, snapshot_json FROM model_proposal_generation_events"
                    )
                )
            ).all()
            revisions = await session.scalar(sa.text("SELECT count(*) FROM web_source_revisions"))
            links = await session.scalar(
                sa.text("SELECT count(*) FROM model_proposal_artifact_links")
            )
        return response, requests, events, revisions, links
    finally:
        await db.dispose()


@pytest.mark.parametrize("outcome", ["success", "second_failure", "publication_rollback"])
def test_design_retry_retains_failed_bytes_and_only_publishes_complete_atomic_tree(
    database, tmp_path, monkeypatch, outcome
):
    if outcome == "publication_rollback":
        monkeypatch.setattr(
            SqlAlchemyProposalEvidenceBindings,
            "bind",
            AsyncMock(side_effect=ProposalEvidenceError("ATOMIC_EVIDENCE_BINDING_FAILED")),
        )
    generator, transport = generator_for(tmp_path, exhausted=outcome == "second_failure")
    response, requests, events, revisions, links = run(
        invoke(database, tmp_path, generator, artifacts())
    )
    assert (
        response.status_code
        == {"success": 201, "second_failure": 502, "publication_rollback": 503}[outcome]
    ), response.text
    assert len(transport.calls) == len(requests) == (4 if outcome == "second_failure" else 5)
    contexts = {
        str(identifier): json.loads(json.loads(snapshot)["request"]["input_payload_json"])[
            "context"
        ]
        for identifier, snapshot in requests
    }
    retry_id, retry_ctx = next((key, ctx) for key, ctx in contexts.items() if "design_retry" in ctx)
    retry = retry_ctx["design_retry"]
    failed_id = retry["previous_generation_id"]
    retained = {
        kind: json.loads(snapshot)["payload"]
        for identifier, kind, snapshot in events
        if str(identifier) == failed_id
    }
    assert json.loads(retained["PROVIDER_RESULT"]["success"]["payload_json"])["content"] == BAD_HTML
    assert "HTTP_RESPONSE" in retained and "ADAPTER_ACCEPTED" not in retained
    assert retained["ADAPTER_REJECTED"]["design_feedback"] == retry["feedback"]
    assert retry["previous_source_sha256"] == hashlib.sha256(BAD_HTML.encode()).hexdigest()
    assert retained["APPLICATION_RESULT"]["status"] == "FAILED"
    assert revisions == links == (1 if outcome == "success" else 0)
    accepted = [
        json.loads(snapshot)["payload"]
        for _, kind, snapshot in events
        if kind == "ADAPTER_ACCEPTED"
    ]
    if outcome != "second_failure":
        parent = next(item for item in accepted if item.get("result", {}).get("generation_steps"))
        assert parent["result"]["generation_steps"][0]["generation_id"] == retry_id
    else:
        assert not any(item.get("result", {}).get("generation_steps") for item in accepted)
    with pytest.raises(sa.exc.DBAPIError, match="Cannot remove protection of retained source"):
        downgrade_database(database, revision="0043_source_syntax_retry")


@pytest.mark.parametrize(
    "tamper",
    [
        "attempt",
        "request_hash",
        "source_hash",
        "context",
        "feedback",
        "both",
        "wrong_category",
        "different_file",
    ],
)
def test_database_rejects_unbound_or_wrong_kind_html_retry_before_transport(
    database, tmp_path, monkeypatch, tamper
):
    generator, transport = generator_for(tmp_path)
    generate = generator.generate

    async def altered(**kwargs):
        ctx = deepcopy(kwargs["context"])
        if "design_retry" in ctx:
            retry = ctx["design_retry"]
            if tamper == "attempt":
                retry["attempt"] = 3
            elif tamper == "request_hash":
                retry["previous_request_hash"] = "0" * 64
            elif tamper == "source_hash":
                retry["previous_source_sha256"] = "0" * 64
            elif tamper == "context":
                ctx["completed_files"] = [{"normalized_path": "invented.js", "content": "invented"}]
            elif tamper == "feedback":
                retry["feedback"]["required_screens"] = []
            elif tamper == "both":
                ctx["syntax_retry"] = {
                    key: retry[key]
                    for key in (
                        "attempt",
                        "previous_generation_id",
                        "previous_request_hash",
                        "code",
                    )
                }
            elif tamper == "wrong_category":
                retry["code"] = "SOURCE_JAVASCRIPT_SYNTAX_INVALID"
            elif tamper == "different_file":
                ctx["source_step"]["file"]["normalized_path"] = "app.js"
            kwargs = {**kwargs, "context": ctx}
        return await generate(**kwargs)

    monkeypatch.setattr(generator, "generate", altered)
    response, requests, _events, revisions, links = run(
        invoke(database, tmp_path, generator, artifacts())
    )
    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "GENERATION_EVIDENCE_WRITE_FAILED"
    assert len(requests) == len(transport.calls) == 2
    assert revisions == links == 0


def test_empty_design_retry_migration_roundtrip(database):
    downgrade_database(database, revision="0043_source_syntax_retry")
    engine = sa.create_engine(database.sqlalchemy_url)
    try:
        with engine.connect() as connection:
            before = connection.exec_driver_sql(
                "SELECT pg_get_functiondef('validate_source_syntax_retry()'::regprocedure)"
            ).scalar_one()
        upgrade_database(database)
        downgrade_database(database, revision="0043_source_syntax_retry")
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql(
                    "SELECT pg_get_functiondef('validate_source_syntax_retry()'::regprocedure)"
                ).scalar_one()
                == before
            )
        upgrade_database(database)
    finally:
        engine.dispose()


@pytest.mark.parametrize("chain", [False, True])
def test_database_blocks_a_second_retry_slot_or_a_retry_of_a_retry(
    database, tmp_path, monkeypatch, chain
):
    generator, transport = generator_for(tmp_path)
    generate = generator.generate
    observed = []
    engine = sa.create_engine(database.sqlalchemy_url)

    async def duplicate_after_provider(**kwargs):
        result = await generate(**kwargs)
        if "design_retry" in kwargs["context"]:
            with engine.connect() as connection:
                rows = connection.execute(sa.select(GENERATIONS)).mappings().all()
            row = next(
                dict(row)
                for row in rows
                if "design_retry"
                in json.loads(json.loads(row["snapshot_json"])["request"]["input_payload_json"])[
                    "context"
                ]
            )
            original_id = row["id"]
            snapshot = json.loads(row["snapshot_json"])
            row["id"] = uuid4()
            snapshot["generation_id"] = snapshot["request"]["request_id"] = str(row["id"])
            if chain:
                payload = json.loads(snapshot["request"]["input_payload_json"])
                payload["context"]["design_retry"]["previous_generation_id"] = str(original_id)
                payload["context"]["design_retry"]["previous_request_hash"] = row[
                    "request_content_hash"
                ]
                snapshot["request"]["input_payload_json"] = json.dumps(payload)
            row["snapshot_json"] = json.dumps(snapshot)
            row["content_hash"] = hashlib.sha256(row["snapshot_json"].encode()).hexdigest()
            expected = "exact rejected first attempt" if chain else "uq_source_file_parent_ordinal"
            with pytest.raises(sa.exc.DBAPIError, match=expected), engine.begin() as connection:
                connection.execute(sa.insert(GENERATIONS).values(**row))
            observed.append(True)
        return result

    monkeypatch.setattr(generator, "generate", duplicate_after_provider)
    try:
        response, requests, _events, revisions, links = run(
            invoke(database, tmp_path, generator, artifacts())
        )
        assert response.status_code == 201, response.text
        assert observed == [True]
        assert len(requests) == len(transport.calls) == 5
        assert revisions == links == 1
    finally:
        engine.dispose()
