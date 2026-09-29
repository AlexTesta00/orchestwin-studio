from __future__ import annotations

import asyncio
import importlib
import inspect
import selectors
import sys
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa

from orchestwin.models.hosted_configuration import ANTHROPIC_RUNTIME_ID
from orchestwin.models.proposal_evidence import ProposalEvidenceError
from orchestwin.models.proposal_evidence_persistence import SqlAlchemyProposalEvidenceStore
from orchestwin.models.structured_generation import (
    ModelRuntimeIdentity,
    StructuredGenerationFinishReason,
    StructuredGenerationProviderKind,
    StructuredGenerationUsage,
    create_structured_generation_request,
    create_structured_generation_success,
    create_structured_json_schema,
    successful_structured_generation_result,
)

MIGRATION = importlib.import_module(
    "orchestwin.persistence.migrations.versions.0062_hosted_model_providers"
)
PREVIOUS = importlib.import_module(
    "orchestwin.persistence.migrations.versions.0038_proposal_generation_evidence"
)
OLD_CONDITION = "snapshot_json::jsonb->'payload'->>'provider_kind' = 'OPENAI_COMPATIBLE_LOCAL'"
NEW_CONDITION = (
    "snapshot_json::jsonb->'payload'->>'provider_kind' IN "
    "('OPENAI_COMPATIBLE_LOCAL', 'ANTHROPIC_HOSTED', 'OPENAI_COMPATIBLE_HOSTED')"
)
SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": False,
}


def record_execute(monkeypatch):
    from alembic import op

    statements = []
    monkeypatch.setattr(op, "execute", statements.append)
    return statements


def test_the_revision_follows_the_project_imports():
    assert MIGRATION.revision == "0062_hosted_model_providers"
    assert MIGRATION.down_revision == "0061_project_imports"
    assert MIGRATION.FUNCTION == "validate_model_proposal_event"
    assert MIGRATION.EVENT_CHANGES == ((OLD_CONDITION, NEW_CONDITION),)
    source = inspect.getsource(PREVIOUS)
    assert source.count(OLD_CONDITION) == 1
    assert source.count("CREATE FUNCTION validate_model_proposal_event()") == 1


def test_the_upgrade_changes_only_the_provider_kind_condition(monkeypatch):
    statements = record_execute(monkeypatch)
    MIGRATION.upgrade()
    [statement] = statements
    assert "pg_get_functiondef('validate_model_proposal_event()'::regprocedure)" in statement
    old, new = OLD_CONDITION.replace("'", "''"), NEW_CONDITION.replace("'", "''")
    assert f"replace(definition, '{old}', '{new}')" in statement
    assert f"length(replace(definition, '{old}', ''))" in statement
    assert statement.count("replace(definition,") == 2
    assert "EXECUTE definition" in statement


def test_the_downgrade_restores_the_local_only_condition(monkeypatch):
    statements = record_execute(monkeypatch)
    MIGRATION.downgrade()
    [statement] = statements
    old, new = OLD_CONDITION.replace("'", "''"), NEW_CONDITION.replace("'", "''")
    assert f"replace(definition, '{new}', '{old}')" in statement


def run(coroutine):
    if sys.platform == "win32":
        return asyncio.run(
            coroutine, loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
        )
    return asyncio.run(coroutine)


def _identity(runtime_id="anthropic-messages", repository="anthropic/claude-opus-5-5"):
    return ModelRuntimeIdentity(
        provider_id="anthropic",
        runtime_id=runtime_id,
        base_model_repository=repository,
        base_model_revision="claude-opus-5-5",
        tokenizer_revision="provider-managed",
        configuration_sha256="c" * 64,
    )


def _request(project_id, identity, purpose="DESIGN_MOCKUP"):
    return create_structured_generation_request(
        request_id=uuid4(),
        task_id="proposal-design-v1",
        expected_identity=identity,
        output_schema=create_structured_json_schema(
            schema_id="proposal-design-v7", version_number=7, schema_payload=SCHEMA
        ),
        system_instruction="Produce one JSON object.",
        input_payload={
            "context": {"project_id": str(project_id), "purpose": purpose},
            "output_schema": SCHEMA,
        },
        allowed_evidence_refs=(),
        prompt_version_ref="proposal-design-v7",
        temperature=1.0,
        max_output_tokens=4096,
        timeout_seconds=600,
    )


def _result(identity, kind, **usage):
    success = create_structured_generation_success(
        payload={"summary": "A generated mockup."},
        actual_identity=identity,
        usage=StructuredGenerationUsage(latency_milliseconds=184_000, **usage),
        finish_reason=StructuredGenerationFinishReason.STOP,
        provider_request_id="msg_synthetic_0001",
    )
    return successful_structured_generation_result(provider_kind=kind, success=success)


async def _seed(session_factory):
    from orchestwin.identity.persistence.models import UserRecord
    from orchestwin.projects.persistence.models import ProjectRecord

    owner, project, now = uuid4(), uuid4(), datetime.now(UTC)
    async with session_factory() as session, session.begin():
        session.add(
            UserRecord(
                id=owner,
                email_normalized=f"{owner}@synthetic.example",
                password_hash="UNUSABLE_SYNTHETIC_TEST_ACCOUNT",
            )
        )
        await session.flush()
        session.add(
            ProjectRecord(
                id=project,
                owner_user_id=owner,
                display_name="Synthetic hosted provider test",
                mode="GREENFIELD_GENERATION",
                current_brief_version=None,
                created_at=now,
                updated_at=now,
            )
        )
    return owner, project


async def _record(store, owner, project, request, result=None, *, accepted=False):
    await store.begin(owner_user_id=owner, project_id=project, request=request)
    if result is None:
        return
    common = {"generation_id": request.request_id, "owner_user_id": owner, "project_id": project}
    await store.append(**common, kind="HTTP_REQUEST", payload={"payload": {"model": "m"}})
    await store.append(
        **common, kind="HTTP_RESPONSE", payload={"status_code": 200}, raw_body=b'{"id":"msg"}'
    )
    await store.append(**common, kind="PROVIDER_RESULT", payload=result.to_snapshot())
    if accepted:
        await store.append(
            **common,
            kind="ADAPTER_ACCEPTED",
            payload={"result": {}, "generated_content_hashes": {"DESIGN": ["d" * 64]}},
        )


@pytest.mark.integration
def test_the_database_accepts_hosted_proposals_and_still_rejects_unknown_kinds():
    from orchestwin.persistence import create_database_runtime, load_database_settings
    from src.test.python.integration.postgres_isolation import isolated_postgres_settings

    settings = load_database_settings(env_file=None)

    async def scenario(scoped, *, hosted_accepted):
        runtime = create_database_runtime(scoped)
        try:
            owner, project = await _seed(runtime.session_factory)
            store = SqlAlchemyProposalEvidenceStore(runtime.session_factory)
            identity = _identity()
            for kind in (
                StructuredGenerationProviderKind.ANTHROPIC_HOSTED,
                StructuredGenerationProviderKind.OPENAI_COMPATIBLE_HOSTED,
            ):
                request = _request(project, identity)
                result = _result(identity, kind, input_tokens=10, output_tokens=20)
                if hosted_accepted:
                    await _record(store, owner, project, request, result, accepted=True)
                else:
                    with pytest.raises(ProposalEvidenceError, match="EVIDENCE_WRITE_FAILED"):
                        await _record(store, owner, project, request, result, accepted=True)
            request = _request(project, identity)
            fake = _result(
                identity,
                StructuredGenerationProviderKind.FAKE_DETERMINISTIC,
                input_tokens=1,
                output_tokens=1,
            )
            with pytest.raises(ProposalEvidenceError, match="EVIDENCE_WRITE_FAILED"):
                await _record(store, owner, project, request, fake, accepted=True)
            async with runtime.session_factory() as session:
                definition = await session.scalar(
                    sa.text(
                        "SELECT pg_get_functiondef('validate_model_proposal_event()'::regprocedure)"
                    )
                )
            return definition
        finally:
            await runtime.dispose()

    with isolated_postgres_settings(settings, revision=MIGRATION.revision) as scoped:
        definition = run(scenario(scoped, hosted_accepted=True))
        assert NEW_CONDITION in definition and OLD_CONDITION not in definition
    with isolated_postgres_settings(settings, revision=MIGRATION.down_revision) as scoped:
        definition = run(scenario(scoped, hosted_accepted=False))
        assert OLD_CONDITION in definition and NEW_CONDITION not in definition


@pytest.mark.integration
def test_the_downgrade_restores_the_previous_revision_schema_exactly():
    from orchestwin.persistence import load_database_settings
    from src.test.python.integration.postgres_isolation import assert_reversible_migration

    assert_reversible_migration(load_database_settings(env_file=None), MIGRATION)


@pytest.mark.integration
def test_spending_and_usage_are_read_from_verified_provider_results():
    from orchestwin.persistence import create_database_runtime, load_database_settings
    from src.test.python.integration.postgres_isolation import isolated_postgres_settings

    async def scenario(scoped):
        runtime = create_database_runtime(scoped)
        try:
            store = SqlAlchemyProposalEvidenceStore(runtime.session_factory)
            owner, project = await _seed(runtime.session_factory)
            other_owner, other_project = await _seed(runtime.session_factory)
            hosted = _identity()
            local = _identity(runtime_id="contract-test", repository="test/base")
            hosted_request = _request(project, hosted)
            await _record(
                store,
                owner,
                project,
                hosted_request,
                _result(
                    hosted,
                    StructuredGenerationProviderKind.ANTHROPIC_HOSTED,
                    input_tokens=10_234,
                    output_tokens=17_890,
                    cache_read_input_tokens=5,
                    cost_microusd=398_736,
                    reasoning_tokens=6_400,
                ),
                accepted=True,
            )
            local_request = _request(project, local, purpose="TWIN_CHAT")
            await _record(
                store,
                owner,
                project,
                local_request,
                _result(
                    local,
                    StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL,
                    input_tokens=100,
                    output_tokens=50,
                ),
            )
            pending = _request(project, hosted)
            await _record(store, owner, project, pending)
            await _record(
                store,
                other_owner,
                other_project,
                _request(other_project, hosted),
                _result(
                    hosted,
                    StructuredGenerationProviderKind.ANTHROPIC_HOSTED,
                    input_tokens=1,
                    output_tokens=1,
                    cost_microusd=1_000,
                ),
            )
            tomorrow = date.today() + timedelta(days=1)
            spent = {
                "project": await store.spent_microusd(project_id=project),
                "other": await store.spent_microusd(project_id=other_project),
                "total": await store.spent_microusd(),
                "since_past": await store.spent_microusd(since=date(2000, 1, 1)),
                "since_future": await store.spent_microusd(since=tomorrow),
            }
            usage = await store.model_usage(owner_user_id=owner, project_id=project)
            foreign = await store.model_usage(owner_user_id=other_owner, project_id=project)
            limited = await store.model_usage(owner_user_id=owner, project_id=project, limit=1)
            with pytest.raises(ValueError):
                await store.model_usage(owner_user_id=owner, project_id=project, limit=201)
            return spent, usage, foreign, limited, hosted_request, local_request, pending
        finally:
            await runtime.dispose()

    with isolated_postgres_settings(
        load_database_settings(env_file=None), revision=MIGRATION.revision
    ) as scoped:
        spent, usage, foreign, limited, hosted_request, local_request, pending = run(
            scenario(scoped)
        )
    assert spent == {
        "project": 398_736,
        "other": 1_000,
        "total": 399_736,
        "since_past": 399_736,
        "since_future": 0,
    }
    assert foreign is None
    assert usage["totals"] == {
        "generations": 3,
        "input_tokens": 10_334,
        "output_tokens": 17_940,
        "reasoning_tokens": 6_400,
        "cost_microusd": 398_736,
    }
    items = {item["generation_id"]: item for item in usage["items"]}
    assert usage["items"][0]["generation_id"] == str(pending.request_id)
    assert items[str(hosted_request.request_id)] | {"recorded_at": None} == {
        "generation_id": str(hosted_request.request_id),
        "recorded_at": None,
        "task": "design",
        "purpose": "DESIGN_MOCKUP",
        "provider_kind": "ANTHROPIC_HOSTED",
        "model": "claude-opus-5-5",
        "status": "SUCCEEDED",
        "failure_code": None,
        "input_tokens": 10_234,
        "output_tokens": 17_890,
        "reasoning_tokens": 6_400,
        "cache_read_input_tokens": 5,
        "cache_write_input_tokens": 0,
        "cost_microusd": 398_736,
        "latency_milliseconds": 184_000,
    }
    local_item = items[str(local_request.request_id)]
    assert (local_item["model"], local_item["cost_microusd"], local_item["purpose"]) == (
        "test/base",
        None,
        "TWIN_CHAT",
    )
    assert items[str(pending.request_id)]["status"] is None
    assert datetime.fromisoformat(items[str(pending.request_id)]["recorded_at"]).tzinfo is not None
    assert len(limited["items"]) == 1 and limited["totals"]["generations"] == 3
    assert ANTHROPIC_RUNTIME_ID == "anthropic-messages"
