from __future__ import annotations

import asyncio
import os
import selectors
import sys
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import SecretStr

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

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("ORCHESTWIN_PROPOSAL_EVIDENCE_TEST_DATABASE_URL"),
        reason="explicit disposable proposal evidence database required",
    ),
]
SCHEMA = {
    "type": "object",
    "properties": {"approach": {"type": "string"}},
    "required": ["approach"],
    "additionalProperties": False,
}
FIRST_HASH = "1" * 64
SECOND_HASH = "2" * 64


def run(coroutine):
    if sys.platform == "win32":
        return asyncio.run(
            coroutine, loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
        )
    return asyncio.run(coroutine)


@pytest.fixture
def database():
    from orchestwin.persistence.config import DatabaseSettings
    from src.test.python.integration.postgres_isolation import isolated_postgres_settings

    settings = DatabaseSettings(
        url=SecretStr(os.environ["ORCHESTWIN_PROPOSAL_EVIDENCE_TEST_DATABASE_URL"]), _env_file=None
    )
    with isolated_postgres_settings(settings) as scoped:
        yield scoped


def identity():
    return ModelRuntimeIdentity(
        provider_id="anthropic",
        runtime_id="anthropic-messages",
        base_model_repository="anthropic/claude-opus-5-5",
        base_model_revision="claude-opus-5-5",
        tokenizer_revision="provider-managed",
        configuration_sha256="c" * 64,
    )


def request(project_id, context):
    schema = create_structured_json_schema(
        schema_id="proposal-design-v102", version_number=102, schema_payload=SCHEMA
    )
    return create_structured_generation_request(
        request_id=uuid4(),
        task_id="proposal-design-v1",
        expected_identity=identity(),
        output_schema=schema,
        system_instruction="Produce one JSON object.",
        input_payload={
            "context": {"project_id": str(project_id), **context},
            "output_schema": SCHEMA,
        },
        allowed_evidence_refs=(),
        prompt_version_ref="proposal-design-v102",
        temperature=1.0,
        max_output_tokens=32_000,
        timeout_seconds=1200,
    )


def provider_result(cost):
    success = create_structured_generation_success(
        payload={"approach": "Schermate per il banco."},
        actual_identity=identity(),
        usage=StructuredGenerationUsage(
            input_tokens=10, output_tokens=20, latency_milliseconds=5, cost_microusd=cost
        ),
        finish_reason=StructuredGenerationFinishReason.STOP,
        provider_request_id="msg_synthetic",
    )
    return successful_structured_generation_result(
        provider_kind=StructuredGenerationProviderKind.ANTHROPIC_HOSTED, success=success
    )


async def seed(session_factory):
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
                display_name="Synthetic generated mockup test",
                mode="GREENFIELD_GENERATION",
                current_brief_version=None,
                created_at=now,
                updated_at=now,
            )
        )
    return owner, project


async def record(store, owner, project, context, *, outcome, marker, cost=100):
    generation = request(project, context)
    await store.begin(owner_user_id=owner, project_id=project, request=generation)
    common = {"generation_id": generation.request_id, "owner_user_id": owner, "project_id": project}
    await store.append(**common, kind="HTTP_REQUEST", payload={"payload": {"model": "m"}})
    await store.append(
        **common, kind="HTTP_RESPONSE", payload={"status_code": 200}, raw_body=b'{"id":"msg"}'
    )
    await store.append(
        **common, kind="PROVIDER_RESULT", payload=provider_result(cost).to_snapshot()
    )
    if outcome == "ACCEPTED":
        await store.append(
            **common,
            kind="ADAPTER_ACCEPTED",
            payload={
                "result": {"marker": marker, "design_content_hash": context["design_content_hash"]},
                "generated_content_hashes": {"DESIGN": ["d" * 64]},
            },
        )
        await store.append(
            **common, kind="APPLICATION_RESULT", payload={"status": "MOCKUP_GENERATED"}
        )
    elif outcome == "RETIRED":
        await store.append(
            **common,
            kind="ADAPTER_REJECTED",
            payload={"code": "MOCKUP_QUALITY_REJECTED", "reason": "TABLE_TOO_SHORT SCR-002"},
        )
        await store.append(
            **common,
            kind="APPLICATION_RESULT",
            payload={"status": "MOCKUP_QUALITY_REJECTED", "role": "MOCKUP_ATTEMPT"},
        )
    return str(generation.request_id)


def context(purpose, design_hash, alternative, **extra):
    return {
        "purpose": purpose,
        "design_content_hash": design_hash,
        "alternative": {"id": str(alternative)},
        **extra,
    }


def test_the_newest_accepted_mockup_is_found_by_purpose_design_and_alternative(database):
    from orchestwin.persistence import create_database_runtime

    async def scenario():
        runtime = create_database_runtime(database)
        try:
            owner, project = await seed(runtime.session_factory)
            store = SqlAlchemyProposalEvidenceStore(runtime.session_factory)
            alternative, other = uuid4(), uuid4()
            for purpose, design_hash, target, outcome, marker in (
                ("DESIGN_MOCKUP_HTML", FIRST_HASH, alternative, "ACCEPTED", 1),
                ("DESIGN_MOCKUP_HTML", FIRST_HASH, alternative, "ACCEPTED", 2),
                ("DESIGN_MOCKUP", FIRST_HASH, alternative, "ACCEPTED", 3),
                ("DESIGN_ITERATION", SECOND_HASH, alternative, "ACCEPTED", 4),
                ("DESIGN_MOCKUP_HTML", FIRST_HASH, alternative, "RETIRED", 5),
                ("DESIGN_MOCKUP_HTML", FIRST_HASH, other, "ACCEPTED", 6),
                ("DESIGN_ALTERNATIVES_HOSTED", FIRST_HASH, alternative, "ACCEPTED", 7),
            ):
                await record(
                    store,
                    owner,
                    project,
                    context(purpose, design_hash, target),
                    outcome=outcome,
                    marker=marker,
                )

            async def latest(hashes, **options):
                result = await store.latest_design_mockup(
                    owner_user_id=options.pop("owner", owner),
                    project_id=project,
                    design_content_hashes=hashes,
                    alternative_id=options.pop("alternative", alternative),
                    **options,
                )
                return None if result is None else result["marker"]

            return (
                await latest((FIRST_HASH,)),
                await latest((FIRST_HASH,), purposes=("DESIGN_MOCKUP_HTML", "DESIGN_ITERATION")),
                await latest((SECOND_HASH,)),
                await latest((FIRST_HASH, SECOND_HASH)),
                await latest((FIRST_HASH,), alternative=other),
                await latest((FIRST_HASH,), owner=uuid4()),
                await latest(()),
                await latest(("3" * 64,)),
            )
        finally:
            await runtime.dispose()

    assert run(scenario()) == (3, 2, 4, 4, 6, None, None, None)


def test_the_generations_of_the_iterations_are_read_with_their_events(database):
    from orchestwin.persistence import create_database_runtime

    async def scenario():
        runtime = create_database_runtime(database)
        try:
            owner, project = await seed(runtime.session_factory)
            store = SqlAlchemyProposalEvidenceStore(runtime.session_factory)
            alternative = uuid4()
            iteration = context(
                "DESIGN_ITERATION",
                FIRST_HASH,
                alternative,
                command_id="c1",
                owner_request="Mostra la sede.",
            )
            retired = await record(
                store, owner, project, iteration, outcome="RETIRED", marker=1, cost=100
            )
            accepted = await record(
                store, owner, project, iteration, outcome="ACCEPTED", marker=2, cost=200
            )
            await record(
                store,
                owner,
                project,
                context("DESIGN_MOCKUP_HTML", FIRST_HASH, alternative),
                outcome="ACCEPTED",
                marker=3,
            )
            records = await store.design_iteration_generations(
                owner_user_id=owner, project_id=project
            )
            hidden = await store.design_iteration_generations(
                owner_user_id=uuid4(), project_id=project
            )
            return retired, accepted, records, hidden
        finally:
            await runtime.dispose()

    retired, accepted, records, hidden = run(scenario())
    assert [item["generation_id"] for item in records] == [accepted, retired]
    newest = records[0]
    assert newest["context"]["owner_request"] == "Mostra la sede."
    assert newest["context"]["command_id"] == "c1"
    assert set(newest["events"]) == {"PROVIDER_RESULT", "ADAPTER_ACCEPTED", "APPLICATION_RESULT"}
    assert newest["events"]["PROVIDER_RESULT"]["success"]["usage"]["cost_microusd"] == 200
    assert set(records[1]["events"]) == {
        "PROVIDER_RESULT",
        "ADAPTER_REJECTED",
        "APPLICATION_RESULT",
    }
    assert records[1]["events"]["APPLICATION_RESULT"]["role"] == "MOCKUP_ATTEMPT"
    assert records[0]["recorded_at"] > records[1]["recorded_at"]
    assert hidden == []
