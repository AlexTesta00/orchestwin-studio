"""Opt-in operation guards on an explicitly provisioned, migrated PostgreSQL DB.

Only ORCHESTWIN_JVM_OPERATION_TEST_DATABASE_URL enables these tests; application
.env files are never read. Each scenario appends independent UUID-scoped fixture
records. Every adversarial SQL probe rolls back even if a guard is missing, so
the DELETE/TRUNCATE checks cannot remove existing audit data.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestwin.artifacts.jvm_source_persistence import (
    JvmSourceRevisionAppendStatus,
    SqlAlchemyJvmSourceRevisionRepository,
)
from orchestwin.artifacts.jvm_source_plans import FileSystemJvmSourceContentStore
from orchestwin.artifacts.jvm_sources import (
    JvmSourceOrigin,
    JvmSourceProvenanceKind,
    JvmSourceProvenanceReference,
    create_jvm_source_revision,
)
from orchestwin.identity.persistence.models import UserRecord
from orchestwin.jvm_execution.operation_governance import JvmOperationError, JvmOperationState
from orchestwin.jvm_execution.operation_persistence import (
    JVM_GOVERNED_OPERATIONS,
    SqlAlchemyJvmOperationStore,
)
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.workflow.gates import HumanGateAction

DATABASE = os.environ.get("ORCHESTWIN_JVM_OPERATION_TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE, reason="explicit disposable PostgreSQL URL required"),
]


def run(scenario):
    # Psycopg's async driver requires a SelectorEventLoop on Windows.
    return asyncio.run(scenario, loop_factory=asyncio.SelectorEventLoop)


@asynccontextmanager
async def fixture_database(tmp_path):
    assert DATABASE is not None
    engine = create_async_engine(DATABASE)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner, project = uuid4(), uuid4()
    content = b"public class Main { public static void main(String[] args) {} }"
    files = FileSystemJvmSourceContentStore(tmp_path / "source-content")
    revision = create_jvm_source_revision(
        revision_id=uuid4(),
        project_id=project,
        created_by_user_id=owner,
        version_number=1,
        based_on=None,
        target=ExecutionTarget.JVM_JAVA,
        origin=JvmSourceOrigin.DETERMINISTIC_FIXTURE,
        files=(
            files.store(
                normalized_path="src/main/java/Main.java", content=content, media_type="text/plain"
            ),
        ),
        provenance_references=(
            JvmSourceProvenanceReference(
                JvmSourceProvenanceKind.SOURCE_PLAN,
                "unit7.operation.persistence.fixture",
                1,
                hashlib.sha256(content).hexdigest(),
            ),
        ),
        created_at=datetime.now(UTC),
    )
    try:
        async with sessions() as session, session.begin():
            assert await session.scalar(sa.text("SELECT to_regclass('jvm_governed_operations')"))
            await session.execute(
                sa.insert(UserRecord).values(
                    id=owner,
                    email_normalized=f"unit7-operation-{owner.hex}@example.invalid",
                    password_hash="fixture-no-login",
                )
            )
            await session.execute(
                sa.insert(ProjectRecord).values(
                    id=project,
                    owner_user_id=owner,
                    display_name="Unit7 operation persistence fixture",
                    mode="GREENFIELD_GENERATION",
                )
            )
            result = await SqlAlchemyJvmSourceRevisionRepository(
                session, owner_user_id=owner
            ).append(revision)
            assert result.status is JvmSourceRevisionAppendStatus.APPENDED
        yield engine, SqlAlchemyJvmOperationStore(sessions), owner, project, revision.id
    finally:
        await engine.dispose()


async def propose(store, owner, project, source, *, index=0):
    return await store.create(
        owner_user_id=owner,
        project_id=project,
        source_revision_id=source,
        kind="EXECUTION" if index % 2 == 0 else "REPAIR",
        payload={"schema_version": 1, "fixture_operation": index},
    )


async def approve(scope, operation):
    gate = await scope.gate(operation)
    await scope.decide(
        operation,
        expected_hash=operation.content_hash,
        expected_event_sequence=gate.event_sequence,
        action=HumanGateAction.APPROVE,
    )


async def rejected_sql(engine, statement, parameters, *, sqlstate):
    observed = None
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(sa.text("SET LOCAL lock_timeout = '3s'"))
            await connection.execute(statement, parameters)
        except DBAPIError as error:
            observed = getattr(error.orig, "sqlstate", None)
        finally:
            # A missing guard must cause a test failure, never a committed deletion.
            await transaction.rollback()
    assert observed == sqlstate


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE jvm_governed_operations SET payload_json = '{}' WHERE id = :id",
        "UPDATE jvm_governed_operations SET content_hash = repeat('0', 64) WHERE id = :id",
        "DELETE FROM jvm_governed_operations WHERE id = :id",
        "TRUNCATE TABLE jvm_governed_operations",
    ],
    ids=["payload-immutable", "identity-immutable", "delete-forbidden", "truncate-forbidden"],
)
def test_migrated_operation_audit_guards_reject_sql_and_preserve_rows(tmp_path, statement):
    async def scenario():
        async with fixture_database(tmp_path) as (engine, store, owner, project, source):
            operation = await propose(store, owner, project, source)
            await rejected_sql(engine, sa.text(statement), {"id": operation.id}, sqlstate="P0001")
            async with store.scope(owner_user_id=owner, project_id=project) as scope:
                assert await scope.get(operation.id) == operation

    run(scenario())


def test_real_claim_cas_terminal_state_and_owner_scope(tmp_path):
    async def scenario():
        async with fixture_database(tmp_path) as (engine, store, owner, project, source):
            operation = await propose(store, owner, project, source)
            async with store.scope(owner_user_id=owner, project_id=project) as scope:
                await approve(scope, operation)
                running = await scope.claim(operation, expected_hash=operation.content_hash)
            with pytest.raises(JvmOperationError, match="STATE_CONFLICT"):
                async with store.scope(owner_user_id=owner, project_id=project) as scope:
                    await scope.update(operation, running)
            async with store.scope(owner_user_id=owner, project_id=project) as scope:
                completed = await scope.finish(running, result={"observed": True}, succeeded=True)
            assert completed.content_hash == operation.content_hash
            with pytest.raises(JvmOperationError, match="ALREADY_CLAIMED"):
                async with store.scope(owner_user_id=owner, project_id=project) as scope:
                    await scope.claim(completed, expected_hash=completed.content_hash)
            with pytest.raises(JvmOperationError, match="PROJECT_NOT_FOUND"):
                async with store.scope(owner_user_id=uuid4(), project_id=project):
                    pytest.fail("foreign owner must not receive an operation scope")
            await rejected_sql(
                engine,
                sa.text("UPDATE jvm_governed_operations SET state = 'RUNNING' WHERE id = :id"),
                {"id": completed.id},
                sqlstate="P0001",
            )
            async with store.scope(owner_user_id=owner, project_id=project) as scope:
                assert await scope.get(completed.id) == completed

    run(scenario())


def test_real_cancel_accepts_exact_unstarted_result_and_rejects_invented_execution(tmp_path):
    async def scenario():
        async with fixture_database(tmp_path) as (engine, store, owner, project, source):
            operation = await propose(store, owner, project, source)
            await rejected_sql(
                engine,
                sa.text(
                    "UPDATE jvm_governed_operations SET state = 'FAILED', finished_at = now(), "
                    "result_json = :result, result_content_hash = repeat('a', 64) WHERE id = :id"
                ),
                {"id": operation.id, "result": '{"execution_started":true}'},
                sqlstate="23514",
            )
            async with store.scope(owner_user_id=owner, project_id=project) as scope:
                gate = await scope.gate(operation)
                cancelled = await scope.decide(
                    operation,
                    expected_hash=operation.content_hash,
                    expected_event_sequence=gate.event_sequence,
                    action=HumanGateAction.CANCEL,
                )
            async with store.scope(owner_user_id=owner, project_id=project) as scope:
                restored = await scope.get(operation.id)
                assert restored == cancelled
                assert restored.state is JvmOperationState.FAILED
                assert restored.started_at is None
                assert restored.result == {
                    "failure_code": "JVM_OPERATION_CANCELLED",
                    "execution_started": False,
                }

    run(scenario())


def test_real_project_allows_only_one_running_operation(tmp_path):
    async def scenario():
        async with fixture_database(tmp_path) as (engine, store, owner, project, source):
            first = await propose(store, owner, project, source)
            async with store.scope(owner_user_id=owner, project_id=project) as scope:
                await approve(scope, first)
            second = await propose(store, owner, project, source, index=1)
            async with store.scope(owner_user_id=owner, project_id=project) as scope:
                await approve(scope, second)
                running = await scope.claim(second, expected_hash=second.content_hash)
            await rejected_sql(
                engine,
                sa.update(JVM_GOVERNED_OPERATIONS)
                .where(JVM_GOVERNED_OPERATIONS.c.id == first.id)
                .values(state="RUNNING", started_at=datetime.now(UTC)),
                {},
                sqlstate="23505",
            )
            async with store.scope(owner_user_id=owner, project_id=project) as scope:
                assert await scope.get(first.id) == first
                await scope.finish(running, result={"fixture": "complete"}, succeeded=True)

    run(scenario())


def test_real_five_independent_operations_keep_current_approval_and_local_budget(tmp_path):
    async def scenario():
        async with fixture_database(tmp_path) as (_, store, owner, project, source):
            for index in range(5):
                operation = await propose(store, owner, project, source, index=index)
                async with store.scope(owner_user_id=owner, project_id=project) as scope:
                    gate = await scope.gate(operation)
                    assert gate.iteration == index + 1
                    assert gate.max_iterations - gate.iteration + 1 == 3
                    assert (await scope.latest_gate()).id == gate.id
                    await approve(scope, operation)
                    running = await scope.claim(operation, expected_hash=operation.content_hash)
                async with store.scope(owner_user_id=owner, project_id=project) as scope:
                    completed = await scope.finish(running, result={"index": index}, succeeded=True)
                    assert completed == replace(
                        running,
                        state=JvmOperationState.COMPLETED,
                        finished_at=completed.finished_at,
                        result_json=completed.result_json,
                    )
            async with store.scope(owner_user_id=owner, project_id=project) as scope:
                history = await scope.history()
                assert len(history) == 5
                assert all(item.state is JvmOperationState.COMPLETED for item in history)

    run(scenario())


def test_two_concurrent_claims_have_exactly_one_committed_winner(tmp_path):
    async def scenario():
        async with fixture_database(tmp_path) as (_, store, owner, project, source):
            operation = await propose(store, owner, project, source)
            async with store.scope(owner_user_id=owner, project_id=project) as scope:
                await approve(scope, operation)

            async def claim():
                try:
                    async with store.scope(owner_user_id=owner, project_id=project) as scope:
                        result = await scope.claim(operation, expected_hash=operation.content_hash)
                    return result
                except JvmOperationError:
                    return None

            results = await asyncio.gather(claim(), claim())
            winners = [result for result in results if result is not None]
            assert len(winners) == 1
            async with store.scope(owner_user_id=owner, project_id=project) as scope:
                assert await scope.get(operation.id) == winners[0]
                await scope.finish(winners[0], result={"test_complete": True}, succeeded=True)

    run(scenario())


def test_cancelled_claim_transaction_does_not_consume_approval(tmp_path):
    async def scenario():
        async with fixture_database(tmp_path) as (_, store, owner, project, source):
            operation = await propose(store, owner, project, source)
            async with store.scope(owner_user_id=owner, project_id=project) as scope:
                await approve(scope, operation)
            with pytest.raises(asyncio.CancelledError):
                async with store.scope(owner_user_id=owner, project_id=project) as scope:
                    await scope.claim(operation, expected_hash=operation.content_hash)
                    raise asyncio.CancelledError()
            async with store.scope(owner_user_id=owner, project_id=project) as scope:
                assert await scope.get(operation.id) == operation
                running = await scope.claim(operation, expected_hash=operation.content_hash)
                await scope.finish(running, result={"retried": True}, succeeded=True)

    run(scenario())


def test_api_decision_is_persisted_and_foreign_owner_cannot_read_it(tmp_path):
    from types import SimpleNamespace

    import httpx
    from fastapi import FastAPI

    from orchestwin.api.auth import current_user_dependency
    from orchestwin.api.jvm_operations import create_jvm_operations_router

    async def scenario():
        async with fixture_database(tmp_path) as (_, store, owner, project, source):
            operation = await propose(store, owner, project, source)
            app = FastAPI()
            app.state.jvm_operation_store = store
            app.include_router(create_jvm_operations_router())
            app.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(id=owner)
            url = f"/projects/{project}/jvm-operations/{operation.id}"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                body = {
                    "expected_content_hash": "f" * 64,
                    "expected_gate_event_sequence": 1,
                    "action": "APPROVE",
                }
                assert (await client.post(url + "/gate", json=body)).status_code == 409
                body["expected_content_hash"] = operation.content_hash
                response = await client.post(url + "/gate", json=body)
                assert response.status_code == 200
                assert response.json()["snapshot"]["gate"]["status"] == "APPROVED"
                app.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(
                    id=uuid4()
                )
                assert (await client.get(url)).status_code == 404
            async with store.scope(owner_user_id=owner, project_id=project) as scope:
                running = await scope.claim(operation, expected_hash=operation.content_hash)
                await scope.finish(running, result={"api_decision_retained": True}, succeeded=True)

    run(scenario())


def test_web_and_jvm_share_gate7_without_replacing_a_running_approval(tmp_path):
    from orchestwin.artifacts.web_source_persistence import SqlAlchemyWebSourceRevisionRepository
    from orchestwin.artifacts.web_source_plans import FileSystemWebSourceContentStore
    from orchestwin.artifacts.web_sources import (
        WebSourceOrigin,
        WebSourceProvenanceKind,
        WebSourceProvenanceReference,
        create_web_source_revision,
    )
    from orchestwin.web_execution.operation_persistence import SqlAlchemyWebOperationStore
    from orchestwin.web_execution.targets import (
        WebImplementationLanguage,
        WebLanguageConfiguration,
        WebProjectLayout,
    )

    async def scenario():
        async with fixture_database(tmp_path) as (engine, store, owner, project, source):
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            content = b"<!doctype html><title>Gate fixture</title>"
            files = FileSystemWebSourceContentStore(tmp_path / "web-source-content")
            web_revision = create_web_source_revision(
                revision_id=uuid4(),
                project_id=project,
                created_by_user_id=owner,
                version_number=1,
                based_on=None,
                target=ExecutionTarget.WEB_STATIC,
                language_configuration=WebLanguageConfiguration(
                    frontend=WebImplementationLanguage.STATIC_ASSETS, backend=None
                ),
                layout=WebProjectLayout.SINGLE_ROOT,
                origin=WebSourceOrigin.DETERMINISTIC_FIXTURE,
                files=(
                    files.store(
                        normalized_path="index.html", content=content, media_type="text/html"
                    ),
                ),
                provenance_references=(
                    WebSourceProvenanceReference(
                        WebSourceProvenanceKind.SOURCE_PLAN,
                        "cross.family.fixture",
                        1,
                        hashlib.sha256(content).hexdigest(),
                    ),
                ),
                created_at=datetime.now(UTC),
            )
            async with sessions() as session, session.begin():
                await SqlAlchemyWebSourceRevisionRepository(session, owner_user_id=owner).append(
                    web_revision
                )
            web = SqlAlchemyWebOperationStore(sessions)
            web_operation = await propose(web, owner, project, web_revision.id)
            async with web.scope(owner_user_id=owner, project_id=project) as scope:
                await approve(scope, web_operation)
                web_running = await scope.claim(
                    web_operation, expected_hash=web_operation.content_hash
                )
            with pytest.raises(JvmOperationError, match="ALREADY_RUNNING"):
                await propose(store, owner, project, source)
            async with web.scope(owner_user_id=owner, project_id=project) as scope:
                assert (await scope.gate(web_running)).status.value == "APPROVED"
                await scope.finish(web_running, result={"fixture": "done"}, succeeded=True)
            jvm_operation = await propose(store, owner, project, source)
            async with store.scope(owner_user_id=owner, project_id=project) as scope:
                await approve(scope, jvm_operation)
                running = await scope.claim(jvm_operation, expected_hash=jvm_operation.content_hash)
            with pytest.raises(DBAPIError):
                await propose(web, owner, project, web_revision.id, index=1)
            async with store.scope(owner_user_id=owner, project_id=project) as scope:
                assert (await scope.gate(running)).status.value == "APPROVED"
                assert await scope.get(running.id) == running
                await scope.finish(running, result={"fixture": "done"}, succeeded=True)
            async with web.scope(owner_user_id=owner, project_id=project) as scope:
                assert len(await scope.history()) == 1
            # Completed JVM work releases Gate 7 for a subsequent Web operation.
            next_web = await propose(web, owner, project, web_revision.id, index=1)
            assert next_web.id != web_operation.id

    run(scenario())
