from __future__ import annotations

import asyncio
import importlib
import re
import sys
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.script import ScriptDirectory

from orchestwin.models.hosted_configuration import (
    CLAUDE_CODE_PROVIDER_ID,
    CLAUDE_CODE_RUNTIME_ID,
    PROVIDER_MANAGED_TOKENIZER,
)
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
from orchestwin.persistence.migrate import create_alembic_config

MIGRATION = importlib.import_module(
    "orchestwin.persistence.migrations.versions.0067_claude_code_provider"
)
PREVIOUS = importlib.import_module(
    "orchestwin.persistence.migrations.versions.0062_hosted_model_providers"
)
OLD_CONDITION = (
    "snapshot_json::jsonb->'payload'->>'provider_kind' IN "
    "('OPENAI_COMPATIBLE_LOCAL', 'ANTHROPIC_HOSTED', 'OPENAI_COMPATIBLE_HOSTED')"
)
NEW_CONDITION = (
    "snapshot_json::jsonb->'payload'->>'provider_kind' IN "
    "('OPENAI_COMPATIBLE_LOCAL', 'ANTHROPIC_HOSTED', 'OPENAI_COMPATIBLE_HOSTED', "
    "'CLAUDE_CODE_CLI')"
)
TEST_DATABASE_URL = "postgresql+psycopg://user:synthetic-password@localhost:5432/orchestwin"
SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": False,
}
Kind = StructuredGenerationProviderKind


def record_execute(monkeypatch):
    from alembic import op

    statements = []
    monkeypatch.setattr(op, "execute", statements.append)
    return statements


def run(coroutine):
    if sys.platform == "win32":
        return asyncio.run(coroutine, loop_factory=asyncio.SelectorEventLoop)
    return asyncio.run(coroutine)


def subscription_identity():
    return ModelRuntimeIdentity(
        provider_id=CLAUDE_CODE_PROVIDER_ID,
        runtime_id=CLAUDE_CODE_RUNTIME_ID,
        base_model_repository="claude-code/claude-opus-5-5",
        base_model_revision="claude-opus-5-5",
        tokenizer_revision=PROVIDER_MANAGED_TOKENIZER,
        configuration_sha256="d" * 64,
    )


def _request(project_id, identity):
    return create_structured_generation_request(
        request_id=uuid4(),
        task_id="proposal-design-v1",
        expected_identity=identity,
        output_schema=create_structured_json_schema(
            schema_id="proposal-design-v7", version_number=7, schema_payload=SCHEMA
        ),
        system_instruction="Produce one JSON object.",
        input_payload={
            "context": {"project_id": str(project_id), "purpose": "DESIGN_MOCKUP"},
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
        provider_request_id="session-synthetic-0001",
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
                display_name="Synthetic subscription provider test",
                mode="GREENFIELD_GENERATION",
                current_brief_version=None,
                created_at=now,
                updated_at=now,
            )
        )
    return owner, project


async def _record(store, owner, project, request, result, *, accepted=False):
    await store.begin(owner_user_id=owner, project_id=project, request=request)
    common = {"generation_id": request.request_id, "owner_user_id": owner, "project_id": project}
    await store.append(**common, kind="HTTP_REQUEST", payload={"payload": {"model": "m"}})
    await store.append(
        **common, kind="HTTP_RESPONSE", payload={"status_code": 200}, raw_body=b'{"type":"result"}'
    )
    await store.append(**common, kind="PROVIDER_RESULT", payload=result.to_snapshot())
    if accepted:
        await store.append(
            **common,
            kind="ADAPTER_ACCEPTED",
            payload={"result": {}, "generated_content_hashes": {"DESIGN": ["d" * 64]}},
        )


def test_the_revision_extends_the_twin_learning_head_and_the_hosted_condition():
    assert MIGRATION.revision == "0067_claude_code_provider"
    assert MIGRATION.down_revision == "0066_twin_learning"
    assert MIGRATION.FUNCTION == PREVIOUS.FUNCTION == "validate_model_proposal_event"
    assert MIGRATION.EVENT_CHANGES == ((OLD_CONDITION, NEW_CONDITION),)
    assert PREVIOUS.EVENT_CHANGES[0][1] == OLD_CONDITION
    assert MIGRATION.replace_function is PREVIOUS.replace_function
    accepted = set(re.findall(r"'([A-Z_]+)'", NEW_CONDITION))
    assert accepted == {
        Kind.OPENAI_COMPATIBLE_LOCAL.value,
        Kind.ANTHROPIC_HOSTED.value,
        Kind.OPENAI_COMPATIBLE_HOSTED.value,
        Kind.CLAUDE_CODE_CLI.value,
    }
    scripts = ScriptDirectory.from_config(create_alembic_config(TEST_DATABASE_URL))
    script = scripts.get_revision(MIGRATION.revision)
    assert script is not None and script.down_revision == "0066_twin_learning"
    assert len(scripts.get_heads()) == 1


def test_the_upgrade_adds_only_the_subscription_kind(monkeypatch):
    statements = record_execute(monkeypatch)
    MIGRATION.upgrade()
    [statement] = statements
    assert "pg_get_functiondef('validate_model_proposal_event()'::regprocedure)" in statement
    old, new = OLD_CONDITION.replace("'", "''"), NEW_CONDITION.replace("'", "''")
    assert f"replace(definition, '{old}', '{new}')" in statement
    assert f"length(replace(definition, '{old}', ''))" in statement
    assert statement.count("replace(definition,") == 2
    assert "EXECUTE definition" in statement


def test_the_downgrade_restores_the_three_kinds_of_the_hosted_providers(monkeypatch):
    statements = record_execute(monkeypatch)
    MIGRATION.downgrade()
    [statement] = statements
    old, new = OLD_CONDITION.replace("'", "''"), NEW_CONDITION.replace("'", "''")
    assert f"replace(definition, '{new}', '{old}')" in statement
    assert f"length(replace(definition, '{new}', ''))" in statement


@pytest.mark.integration
def test_the_database_accepts_proposals_made_through_the_subscription():
    from orchestwin.persistence import create_database_runtime, load_database_settings
    from src.test.python.integration.postgres_isolation import isolated_postgres_settings

    settings = load_database_settings(env_file=None)

    async def scenario(scoped, *, subscription_accepted):
        runtime = create_database_runtime(scoped)
        try:
            owner, project = await _seed(runtime.session_factory)
            store = SqlAlchemyProposalEvidenceStore(runtime.session_factory)
            identity = subscription_identity()
            request = _request(project, identity)
            result = _result(identity, Kind.CLAUDE_CODE_CLI, input_tokens=10, output_tokens=20)
            if subscription_accepted:
                await _record(store, owner, project, request, result, accepted=True)
            else:
                with pytest.raises(ProposalEvidenceError, match="EVIDENCE_WRITE_FAILED"):
                    await _record(store, owner, project, request, result, accepted=True)
            for kind in (Kind.ANTHROPIC_HOSTED, Kind.OPENAI_COMPATIBLE_HOSTED):
                hosted = _result(identity, kind, input_tokens=1, output_tokens=1)
                await _record(
                    store, owner, project, _request(project, identity), hosted, accepted=True
                )
            fake = _result(identity, Kind.FAKE_DETERMINISTIC, input_tokens=1, output_tokens=1)
            with pytest.raises(ProposalEvidenceError, match="EVIDENCE_WRITE_FAILED"):
                await _record(
                    store, owner, project, _request(project, identity), fake, accepted=True
                )
            async with runtime.session_factory() as session:
                return await session.scalar(
                    sa.text(
                        "SELECT pg_get_functiondef('validate_model_proposal_event()'::regprocedure)"
                    )
                )
        finally:
            await runtime.dispose()

    with isolated_postgres_settings(settings, revision=MIGRATION.revision) as scoped:
        definition = run(scenario(scoped, subscription_accepted=True))
        assert NEW_CONDITION in definition and OLD_CONDITION not in definition
    with isolated_postgres_settings(settings, revision=MIGRATION.down_revision) as scoped:
        definition = run(scenario(scoped, subscription_accepted=False))
        assert OLD_CONDITION in definition and NEW_CONDITION not in definition


@pytest.mark.integration
def test_the_downgrade_restores_the_previous_revision_schema_exactly():
    from orchestwin.persistence import load_database_settings
    from src.test.python.integration.postgres_isolation import assert_reversible_migration

    assert_reversible_migration(load_database_settings(env_file=None), MIGRATION)


@pytest.mark.integration
def test_a_generation_through_the_subscription_spends_nothing_and_has_no_cost():
    from orchestwin.persistence import create_database_runtime, load_database_settings
    from src.test.python.integration.postgres_isolation import isolated_postgres_settings

    async def scenario(scoped):
        runtime = create_database_runtime(scoped)
        try:
            store = SqlAlchemyProposalEvidenceStore(runtime.session_factory)
            owner, project = await _seed(runtime.session_factory)
            identity = subscription_identity()
            request = _request(project, identity)
            result = _result(
                identity,
                Kind.CLAUDE_CODE_CLI,
                input_tokens=10_234,
                output_tokens=17_890,
                cache_read_input_tokens=5,
                cache_write_input_tokens=40,
                reasoning_tokens=6_400,
            )
            await _record(store, owner, project, request, result, accepted=True)
            spent = (
                await store.spent_microusd(project_id=project),
                await store.spent_microusd(),
            )
            usage = await store.model_usage(owner_user_id=owner, project_id=project)
            return request, spent, usage
        finally:
            await runtime.dispose()

    with isolated_postgres_settings(
        load_database_settings(env_file=None), revision=MIGRATION.revision
    ) as scoped:
        request, spent, usage = run(scenario(scoped))
    assert spent == (0, 0)
    [item] = usage["items"]
    assert item | {"recorded_at": None} == {
        "generation_id": str(request.request_id),
        "recorded_at": None,
        "task": "design",
        "purpose": "DESIGN_MOCKUP",
        "provider_kind": "CLAUDE_CODE_CLI",
        "model": "claude-opus-5-5",
        "status": "SUCCEEDED",
        "failure_code": None,
        "input_tokens": 10_234,
        "output_tokens": 17_890,
        "reasoning_tokens": 6_400,
        "cache_read_input_tokens": 5,
        "cache_write_input_tokens": 40,
        "cost_microusd": None,
        "latency_milliseconds": 184_000,
    }
    assert usage["totals"] == {
        "generations": 1,
        "input_tokens": 10_234,
        "output_tokens": 17_890,
        "reasoning_tokens": 6_400,
        "cost_microusd": 0,
    }
