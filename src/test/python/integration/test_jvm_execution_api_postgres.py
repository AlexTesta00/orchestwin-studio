"""Explicit disposable PostgreSQL: real API, gates, workflow, evidence and transactions.

Only transport observations are deterministic in these tests. They never claim
Docker validation or Level D. No application dotenv/database fallback is allowed.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.governed_jvm_execution_runtime import SqlAlchemyGovernedJvmExecutionApiService
from orchestwin.api.jvm_execution_read_runtime import SqlAlchemyJvmExecutionReadApiService
from orchestwin.api.jvm_repair_runtime import SqlAlchemyJvmRepairApiService
from orchestwin.api.jvm_source_runtime import SqlAlchemyJvmSourceApiService
from orchestwin.api.services import ApplicationRuntime
from orchestwin.artifacts.jvm_source_persistence import SqlAlchemyJvmSourceRevisionRepository
from orchestwin.artifacts.jvm_sources import JvmSourceOrigin
from orchestwin.config import ApplicationSettings
from orchestwin.identity.persistence.models import UserRecord
from orchestwin.jvm_execution import phase_executor, workspaces
from orchestwin.jvm_execution.operation_persistence import (
    SqlAlchemyJvmOperationScope,
    SqlAlchemyJvmOperationStore,
)
from orchestwin.jvm_execution.profile_loader import build_jvm_profile_catalog_loader
from orchestwin.projects.persistence.models import ProjectRecord
from src.test.python.jvm_execution.api_support import TARGETS, fixture_context
from src.test.python.jvm_execution.test_phase_executor import NETWORK, Runtime

DATABASE = os.environ.get("ORCHESTWIN_JVM_API_TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE, reason="explicit disposable PostgreSQL URL required"),
]


def run(coro):
    return asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)


@asynccontextmanager
async def api_fixture(
    tmp_path,
    monkeypatch,
    *,
    target=TARGETS[1],
    mode="pass",
    configuration=None,
    real=False,
    origin=None,
):
    assert DATABASE is not None
    backend, revision, command = fixture_context(tmp_path, target, configuration=configuration)
    if origin is not None:
        revision = replace(revision, origin=origin)
    instances = []
    if not real:
        monkeypatch.setattr(workspaces, "require_jvm_workspace_owner", lambda: None)
        monkeypatch.setattr(phase_executor, "require_jvm_workspace_owner", lambda: None)
        monkeypatch.setattr(workspaces, "seed_gradle_wrapper_cache", lambda **kwargs: None)
        monkeypatch.setattr(
            phase_executor, "verify_dependency_network", AsyncMock(return_value=NETWORK)
        )

        def transport(**kwargs):
            instance = Runtime(**kwargs)
            instance.mode = mode
            instances.append(instance)
            return instance

        backend.executor_factory = lambda **kwargs: phase_executor.GovernedJvmPhaseExecutor(
            **kwargs, runtime_factory=transport
        )
    # Pool size one also verifies catalog loads do not deadlock inside a held scope.
    engine = create_async_engine(DATABASE, pool_size=1, max_overflow=0, pool_timeout=3)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner, project = revision.created_by_user_id, revision.project_id
    operations = SqlAlchemyJvmOperationStore(sessions)
    loader = build_jvm_profile_catalog_loader(sessions)
    start = SqlAlchemyGovernedJvmExecutionApiService(
        sessions, operation_store=operations, backend=backend, catalog_loader=loader
    )
    reads = SqlAlchemyJvmExecutionReadApiService(sessions, catalog_loader=loader)
    actor = SimpleNamespace(id=owner)
    try:
        async with sessions() as session, session.begin():
            await session.execute(
                sa.insert(UserRecord).values(
                    id=owner,
                    email_normalized=f"jvm-api-{owner.hex}@example.invalid",
                    password_hash="fixture-no-login",
                )
            )
            await session.execute(
                sa.insert(ProjectRecord).values(
                    id=project,
                    owner_user_id=owner,
                    display_name="JVM API development fixture",
                    mode="GREENFIELD_GENERATION",
                )
            )
            assert (
                await SqlAlchemyJvmSourceRevisionRepository(session, owner_user_id=owner).append(
                    revision
                )
            ).status.value == "APPENDED"
        app = create_app(
            ApplicationSettings(_env_file=None),
            auth_settings=AuthApiSettings(_env_file=None),
            runtime=ApplicationRuntime(
                jvm_execution_start_api_service=start,
                jvm_execution_read_api_service=reads,
                jvm_operation_store=operations,
                jvm_source_api_service=SqlAlchemyJvmSourceApiService(
                    sessions, content_root=backend.content_root, repo_root=backend.config.repo_root
                ),
                jvm_repair_api_service=SqlAlchemyJvmRepairApiService(
                    sessions,
                    operation_store=operations,
                    content_root=backend.content_root,
                    repo_root=backend.config.repo_root,
                ),
            ),
        )
        app.dependency_overrides[current_user_dependency] = lambda: actor
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://fixture/api/v1"
        ) as client:
            from orchestwin.api.governed_jvm_context import execution_command_snapshot

            yield SimpleNamespace(
                client=client,
                start=start,
                backend=backend,
                revision=revision,
                command=command,
                body=execution_command_snapshot(command),
                owner=owner,
                project=project,
                actor=actor,
                path=f"/projects/{project}/jvm-executions",
                operations=operations,
                instances=instances,
                reads=reads,
            )
    finally:
        await engine.dispose()


async def prepared(fixture):
    response = await fixture.client.post(fixture.path + "/prepare", json=fixture.body)
    assert response.status_code == 201, response.text
    return response.json()["snapshot"]


async def approve(fixture, operation):
    response = await fixture.client.post(
        f"/projects/{fixture.project}/jvm-operations/{operation['id']}/gate",
        json={
            "expected_content_hash": operation["content_hash"],
            "expected_gate_event_sequence": operation["gate"]["event_sequence"],
            "action": "APPROVE",
        },
    )
    assert response.status_code == 200, response.text
    return {**fixture.body, "authorization_id": operation["id"]}


@pytest.mark.parametrize("target", TARGETS)
def test_api_persists_exact_gate_and_attempt_replays_without_catalog_or_transport(
    tmp_path, monkeypatch, target
):
    async def scenario():
        async with api_fixture(tmp_path, monkeypatch, target=target) as f:
            operation = await prepared(f)
            assert not f.backend.config.workspaces_root.exists() and not f.instances
            # A proposed UUID alone is not execution authority.
            denied = await f.client.post(
                f.path, json={**f.body, "authorization_id": operation["id"]}
            )
            assert denied.status_code == 409 and not f.instances
            body = await approve(f, operation)
            response = await f.client.post(f.path, json=body)
            assert response.status_code == 201, response.text
            attempt = response.json()["snapshot"]
            assert attempt["id"] == operation["id"] and attempt["report"]["status"] == "PASSED"
            assert len(f.instances) == 1 and f.instances[0].closed
            terminal = (
                await f.client.get(f"/projects/{f.project}/jvm-operations/{operation['id']}")
            ).json()["snapshot"]
            assert (
                terminal["state"] == "COMPLETED"
                and terminal["result"]["attempt_content_hash"] == attempt["content_hash"]
            )
            assert terminal["result"]["finalization_reference"]
            f.start.catalog_loader.load = AsyncMock(
                side_effect=RuntimeError("replay must not reload catalog")
            )
            assert (await f.client.post(f.path, json=body)).json()["snapshot"] == attempt
            assert len(f.instances) == 1
            assert (await f.client.get(f.path)).json()["items"] == [attempt]
            assert (await f.client.get(f"/jvm-executions/{attempt['id']}/report")).json()[
                "snapshot"
            ] == attempt["report"]
            assert (
                len(
                    (await f.client.get(f"/projects/{f.project}/jvm-source-revisions")).json()[
                        "items"
                    ]
                )
                == 1
            )
            f.actor.id = uuid4()
            assert (await f.client.get(f.path)).json()["items"] == []
            assert (await f.client.get(f"/jvm-executions/{attempt['id']}")).status_code == 404
            assert (await f.client.get(f"/projects/{f.project}/jvm-source-revisions")).json()[
                "items"
            ] == []
            assert (await f.client.post(f.path, json=body)).status_code == 404

    run(scenario())


@pytest.mark.parametrize("mode", ["failed-test", "cancel", "cleanup-failure"])
def test_failed_program_and_interruption_preserve_honest_terminal_state(
    tmp_path, monkeypatch, mode
):
    async def scenario():
        async with api_fixture(tmp_path, monkeypatch, mode=mode) as f:
            operation = await prepared(f)
            body = await approve(f, operation)
            if mode == "cancel":
                with pytest.raises(asyncio.CancelledError):
                    await f.client.post(f.path, json=body)
            else:
                response = await f.client.post(f.path, json=body)
                assert response.status_code == (201 if mode == "failed-test" else 503), (
                    response.text
                )
            terminal = (
                await f.client.get(f"/projects/{f.project}/jvm-operations/{operation['id']}")
            ).json()["snapshot"]
            attempts = (await f.client.get(f.path)).json()["items"]
            if mode == "failed-test":
                assert terminal["state"] == "COMPLETED"
                assert (
                    terminal["result"]["report_status"]
                    == attempts[0]["report"]["status"]
                    == "FAILED"
                )
            else:
                assert attempts == []
                assert terminal["state"] == ("FAILED" if mode == "cancel" else "RUNNING")
                assert (await f.client.post(f.path, json=body)).status_code == 409

    run(scenario())


def test_atomic_attempt_and_operation_rollback_on_terminal_write_failure(tmp_path, monkeypatch):
    async def scenario():
        async with api_fixture(tmp_path, monkeypatch) as f:
            operation = await prepared(f)
            body = await approve(f, operation)
            finish = SqlAlchemyJvmOperationScope.finish

            async def interrupted_finish(scope, current, *, result, succeeded):
                if succeeded:
                    raise RuntimeError("injected terminal persistence failure")
                return await finish(scope, current, result=result, succeeded=succeeded)

            monkeypatch.setattr(SqlAlchemyJvmOperationScope, "finish", interrupted_finish)
            response = await f.client.post(f.path, json=body)
            assert response.status_code == 503
            assert (await f.client.get(f.path)).json()["items"] == []
            terminal = (
                await f.client.get(f"/projects/{f.project}/jvm-operations/{operation['id']}")
            ).json()["snapshot"]
            assert terminal["state"] == "FAILED" and terminal["result"]["cleanup_confirmed"]

    run(scenario())


def test_approval_rejects_runtime_drift_and_owner_execution(tmp_path, monkeypatch):
    async def scenario():
        async with api_fixture(tmp_path, monkeypatch) as f:
            owner_body = {**f.body, "purpose": "OWNER_PROJECT", "trigger": "INITIAL"}
            assert (await f.client.post(f.path + "/prepare", json=owner_body)).status_code == 409
            operation = await prepared(f)
            body = await approve(f, operation)
            f.backend.config = f.backend.config.model_copy(
                update={"dependency_network_manifest_hash": "e" * 64}
            )
            assert (await f.client.post(f.path, json=body)).status_code == 409
            assert not f.instances
            assert (await f.client.get(f.path)).json()["items"] == []

    run(scenario())


def test_corrupt_cleanup_receipt_cannot_be_replayed(tmp_path, monkeypatch):
    async def scenario():
        async with api_fixture(tmp_path, monkeypatch) as f:
            operation = await prepared(f)
            body = await approve(f, operation)
            assert (await f.client.post(f.path, json=body)).status_code == 201
            terminal = (
                await f.client.get(f"/projects/{f.project}/jvm-operations/{operation['id']}")
            ).json()["snapshot"]
            reference = terminal["result"]["finalization_reference"]
            (f.backend.evidence_root / reference["storage_key"]).write_bytes(b"{}")
            response = await f.client.post(f.path, json=body)
            assert response.status_code == 409 and len(f.instances) == 1

    run(scenario())


def test_generated_source_cannot_bypass_capability_by_claiming_profile_validation(
    tmp_path, monkeypatch
):
    async def scenario():
        async with api_fixture(tmp_path, monkeypatch, origin=JvmSourceOrigin.GENERATED_PLAN) as f:
            response = await f.client.post(f.path + "/prepare", json=f.body)
            assert response.status_code == 422
            assert "REQUIRES_DEVELOPMENT_FIXTURE" in response.text
            assert not f.instances

    run(scenario())


@pytest.mark.parametrize("cancel", [False, True])
def test_lost_commit_response_reconciles_atomic_result_without_second_execution(
    tmp_path, monkeypatch, cancel
):
    async def scenario():
        async with api_fixture(tmp_path, monkeypatch) as f:
            operation = await prepared(f)
            body = await approve(f, operation)
            sessions = f.start.sessions

            class SessionProxy:
                def __init__(self, session):
                    self.session = session

                def __getattr__(self, name):
                    return getattr(self.session, name)

                @asynccontextmanager
                async def begin(self):
                    async with self.session.begin():
                        yield
                    # Both writes committed, but the response to COMMIT was lost.
                    if cancel:
                        raise asyncio.CancelledError()
                    raise RuntimeError("injected lost commit response")

            @asynccontextmanager
            async def uncertain_sessions():
                async with sessions() as session:
                    yield SessionProxy(session)

            f.start.sessions = uncertain_sessions
            if cancel:
                with pytest.raises(asyncio.CancelledError):
                    await f.client.post(f.path, json=body)
            else:
                assert (await f.client.post(f.path, json=body)).status_code == 201
            f.start.sessions = sessions
            replay = await f.client.post(f.path, json=body)
            assert replay.status_code == 201
            assert len(f.instances) == 1
            terminal = (
                await f.client.get(f"/projects/{f.project}/jvm-operations/{operation['id']}")
            ).json()["snapshot"]
            assert terminal["state"] == "COMPLETED"
            assert (
                terminal["result"]["attempt_content_hash"]
                == replay.json()["snapshot"]["content_hash"]
            )

    run(scenario())


def test_concurrent_request_observes_committed_claim_before_backend_allocation(
    tmp_path, monkeypatch
):
    async def scenario():
        async with api_fixture(tmp_path, monkeypatch) as f:
            operation = await prepared(f)
            body = await approve(f, operation)
            entered, release = asyncio.Event(), asyncio.Event()
            execute = f.backend.execute

            async def paused(*args, **kwargs):
                entered.set()
                await release.wait()
                return await execute(*args, **kwargs)

            f.backend.execute = paused
            task = asyncio.create_task(f.client.post(f.path, json=body))
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                current = (
                    await f.client.get(f"/projects/{f.project}/jvm-operations/{operation['id']}")
                ).json()["snapshot"]
                assert current["state"] == "RUNNING"
                assert not f.backend.config.workspaces_root.exists()
                assert (await f.client.post(f.path, json=body)).status_code == 409
            finally:
                release.set()
            assert (await task).status_code == 201
            assert len(f.instances) == 1

    run(scenario())


@pytest.mark.parametrize("boundary", ["before-commit", "after-commit", "uncertain-commit"])
def test_interrupted_claim_never_allocates_runtime_and_recovers_only_confirmed_state(
    tmp_path, monkeypatch, boundary
):
    from sqlalchemy.exc import SQLAlchemyError

    async def scenario():
        async with api_fixture(tmp_path, monkeypatch) as f:
            operation = await prepared(f)
            body = await approve(f, operation)
            scopes = f.operations.scope
            fired = False

            @asynccontextmanager
            async def interrupted_scope(**kwargs):
                nonlocal fired
                observed_claim = False
                interrupt_after = False
                async with scopes(**kwargs) as scope:
                    claim = scope.claim

                    async def observe_claim(*args, **values):
                        nonlocal observed_claim
                        result = await claim(*args, **values)
                        observed_claim = True
                        return result

                    scope.claim = observe_claim
                    yield scope
                    if observed_claim and not fired:
                        fired = True
                        if boundary == "before-commit":
                            raise asyncio.CancelledError()
                        interrupt_after = True
                if interrupt_after:
                    if boundary == "uncertain-commit":
                        raise SQLAlchemyError("injected uncertain claim response")
                    raise asyncio.CancelledError()

            f.operations.scope = interrupted_scope
            if boundary == "uncertain-commit":
                response = await f.client.post(f.path, json=body)
                assert response.status_code == 503
                assert response.json()["detail"]["code"] == "JVM_EXECUTION_CLAIM_PERSISTENCE_FAILED"
            else:
                with pytest.raises(asyncio.CancelledError):
                    await f.client.post(f.path, json=body)
            assert fired and not f.instances
            assert not f.backend.config.workspaces_root.exists()
            current = (
                await f.client.get(f"/projects/{f.project}/jvm-operations/{operation['id']}")
            ).json()["snapshot"]
            assert (
                current["state"]
                == {
                    "before-commit": "PENDING",
                    "after-commit": "FAILED",
                    "uncertain-commit": "RUNNING",
                }[boundary]
            )
            assert (await f.client.get(f.path)).json()["items"] == []

    run(scenario())
