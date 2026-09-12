"""Production execution never claims an unapproved or mismatched Web operation."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from test_governed_web_context import context_fixture

from orchestwin.api.governed_web_execution_runtime import SqlAlchemyGovernedWebExecutionApiService
from orchestwin.api.web_execution import WebApiCommandStatus
from orchestwin.web_execution.profile_registry import create_sprint08_web_profile_registry
from orchestwin.workflow.web_execution import WebExecutionPurpose


class Scope:
    def __init__(self, revision, operation=None):
        self.session = object()
        self.revision = revision
        self.operation = operation
        self.claim = AsyncMock(side_effect=RuntimeError("claim must not occur"))
        self.propose = AsyncMock()

    async def get(self, identifier):
        return self.operation


class Store:
    def __init__(self, scope):
        self.value = scope
        self.active = False

    @asynccontextmanager
    async def scope(self, **kwargs):
        self.active = True
        try:
            yield self.value
        finally:
            self.active = False


def runtime(tmp_path, monkeypatch):
    backend, revision, command = context_fixture(tmp_path, monkeypatch)
    scope = Scope(revision)
    service = SqlAlchemyGovernedWebExecutionApiService(
        None,
        operation_store=Store(scope),
        backend=backend,
        catalog_loader=SimpleNamespace(
            load=AsyncMock(
                return_value=SimpleNamespace(registry=create_sprint08_web_profile_registry())
            )
        ),
    )
    monkeypatch.setattr(service, "_source_and_previous", AsyncMock(return_value=(revision, None)))
    return service, scope, revision, command


def test_owner_execution_cannot_bypass_unvalidated_profile(tmp_path, monkeypatch):
    service, scope, revision, command = runtime(tmp_path, monkeypatch)
    result = asyncio.run(
        service.prepare_execution(
            owner_user_id=revision.created_by_user_id,
            project_id=revision.project_id,
            command=replace(command, purpose=WebExecutionPurpose.OWNER_PROJECT),
        )
    )
    assert result.status is WebApiCommandStatus.CAPABILITY_BLOCKED
    scope.propose.assert_not_awaited()


@pytest.mark.parametrize("action", ["prepare", "start"])
def test_catalog_load_does_not_wait_for_a_second_pool_connection(tmp_path, monkeypatch, action):
    from orchestwin.web_execution.operation_governance import WebGovernedOperation

    service, scope, revision, command = runtime(tmp_path, monkeypatch)
    command = replace(command, purpose=WebExecutionPurpose.OWNER_PROJECT)
    if action == "start":
        from orchestwin.api.governed_web_context import execution_command_snapshot

        scope.operation = WebGovernedOperation.create(
            project_id=revision.project_id,
            owner_user_id=revision.created_by_user_id,
            source_revision_id=revision.id,
            kind="EXECUTION",
            payload={"command": execution_command_snapshot(command)},
        )
        command = replace(command, authorization_id=scope.operation.id)

    async def load():
        assert not service.operations.active, (
            "catalog load acquired a second connection under the project lock"
        )
        return SimpleNamespace(registry=create_sprint08_web_profile_registry())

    service.catalog_loader.load = load
    method = service.prepare_execution if action == "prepare" else service.start_execution
    result = asyncio.run(
        method(
            owner_user_id=revision.created_by_user_id,
            project_id=revision.project_id,
            command=command,
        )
    )
    assert result.status is WebApiCommandStatus.CAPABILITY_BLOCKED
    scope.claim.assert_not_awaited()


def test_start_requires_persisted_authorization_before_source_or_docker(tmp_path, monkeypatch):
    service, scope, revision, command = runtime(tmp_path, monkeypatch)
    result = asyncio.run(
        service.start_execution(
            owner_user_id=revision.created_by_user_id,
            project_id=revision.project_id,
            command=command,
        )
    )
    assert result.status is WebApiCommandStatus.APPROVAL_REQUIRED
    scope.claim.assert_not_awaited()


@pytest.mark.parametrize("case", ["missing", "changed", "wrong-kind"])
def test_start_rejects_operation_binding_before_claim(tmp_path, monkeypatch, case):
    service, scope, revision, command = runtime(tmp_path, monkeypatch)
    context = service.backend.prepare(
        revision, command=command, registry=create_sprint08_web_profile_registry(), previous=None
    )
    operation_id = uuid4()
    scope.operation = (
        None
        if case == "missing"
        else SimpleNamespace(
            id=operation_id,
            kind="REPAIR" if case == "wrong-kind" else "EXECUTION",
            state="PENDING",
            payload={**context.payload, "source_tree_hash": "f" * 64},
            source_revision_id=revision.id,
            owner_user_id=revision.created_by_user_id,
            project_id=revision.project_id,
        )
    )
    result = asyncio.run(
        service.start_execution(
            owner_user_id=revision.created_by_user_id,
            project_id=revision.project_id,
            command=replace(command, authorization_id=operation_id),
        )
    )
    assert result.status in {WebApiCommandStatus.NOT_FOUND, WebApiCommandStatus.CONFLICT}
    scope.claim.assert_not_awaited()
