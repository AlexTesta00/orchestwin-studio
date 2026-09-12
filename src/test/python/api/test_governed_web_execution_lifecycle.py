"""Commit/cancellation boundaries never invent absent or duplicate executions."""

from __future__ import annotations

import asyncio
import hashlib
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from test_governed_web_context import context_fixture

from orchestwin.api.governed_web_execution_runtime import SqlAlchemyGovernedWebExecutionApiService
from orchestwin.api.web_execution import WebApiCommandStatus
from orchestwin.web_execution.attempt_persistence import web_execution_attempt_to_record
from orchestwin.web_execution.attempts import WebExecutionAttemptTrigger
from orchestwin.web_execution.operation_governance import (
    WebGovernedOperation,
    WebOperationError,
    WebOperationState,
)
from orchestwin.web_execution.profile_registry import create_sprint08_web_profile_registry
from orchestwin.web_execution.reports import (
    WebEvidenceReference,
    WebFailureCategory,
    WebPhaseResultStatus,
)
from orchestwin.workflow.web_execution import WebExecutionServiceStatus
from src.test.python.web_execution.test_attempt_persistence import create_attempt


class BoundaryState:
    def __init__(self, operation, attempt):
        self.operation, self.attempt = operation, attempt
        self.persisted_attempt = None
        self.claim_exit = self.attempt_exit = self.finish_exit = None
        self.backend_cancel = False
        self.backend_calls = 0
        self.finishes = []
        self.read_error = None
        self.read_entered = asyncio.Event()
        self.release_read = asyncio.Event()
        self.release_read.set()
        self.scope_connections = 0
        self.catalog_loads = 0


class Scope:
    def __init__(self, state):
        self.state = state
        self.current = state.operation
        self.claimed = self.finished = False
        self.session = self

    async def execute(self, query):
        compiled = query.compile()
        assert self.state.operation.id in compiled.params.values()
        assert self.state.operation.owner_user_id in compiled.params.values()
        assert self.state.operation.project_id in compiled.params.values()
        self.state.read_entered.set()
        await self.state.release_read.wait()
        if self.state.read_error is not None:
            raise self.state.read_error
        row = (
            None
            if self.state.persisted_attempt is None
            else web_execution_attempt_to_record(self.state.persisted_attempt)
        )
        return SimpleNamespace(mappings=lambda: SimpleNamespace(one_or_none=lambda: row))

    async def get(self, identifier):
        assert identifier == self.current.id
        return self.current

    async def claim(self, operation, *, expected_hash):
        assert operation == self.current and operation.content_hash == expected_hash
        assert operation.state is WebOperationState.PENDING
        self.current = replace(
            operation, state=WebOperationState.RUNNING, started_at=datetime.now(UTC)
        )
        self.claimed = True
        return self.current

    async def finish(self, operation, *, result, succeeded):
        assert operation == self.current
        if operation.state is not WebOperationState.RUNNING:
            raise WebOperationError("WEB_OPERATION_STATE_CONFLICT")
        if self.state.finish_exit == "error_before":
            self.state.finish_exit = None
            raise OSError("commit boundary unavailable")
        from orchestwin.web_execution.operation_governance import operation_json

        self.current = replace(
            operation,
            state=WebOperationState.COMPLETED if succeeded else WebOperationState.FAILED,
            result_json=operation_json(result),
            finished_at=datetime.now(UTC),
        )
        self.state.finishes.append((result, succeeded))
        self.finished = True
        return self.current


class Store:
    def __init__(self, state):
        self.state = state

    @asynccontextmanager
    async def scope(self, **kwargs):
        assert kwargs == {
            "owner_user_id": self.state.operation.owner_user_id,
            "project_id": self.state.operation.project_id,
        }
        local = Scope(self.state)
        self.state.scope_connections += 1
        try:
            yield local
        finally:
            self.state.scope_connections -= 1
        if local.claimed and self.state.claim_exit == "cancel_rollback":
            self.state.claim_exit = None
            raise asyncio.CancelledError
        self.state.operation = local.current
        if local.claimed and self.state.claim_exit == "cancel_commit":
            self.state.claim_exit = None
            raise asyncio.CancelledError
        if local.finished and self.state.finish_exit == "error_after":
            self.state.finish_exit = None
            raise OSError("commit acknowledgment lost")


class Sessions:
    def __init__(self, state):
        self.state = state

    def __call__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    @asynccontextmanager
    async def begin(self):
        yield
        if self.state.attempt_exit == "cancel_rollback":
            raise asyncio.CancelledError
        self.state.persisted_attempt = self.state.attempt
        if self.state.attempt_exit == "cancel_commit":
            raise asyncio.CancelledError


def setup_lifecycle(tmp_path, monkeypatch):
    backend, revision, command = context_fixture(tmp_path, monkeypatch)
    command = replace(command, trigger=WebExecutionAttemptTrigger.PROFILE_VALIDATION)
    context = backend.prepare(
        revision, command=command, registry=create_sprint08_web_profile_registry(), previous=None
    )
    operation = WebGovernedOperation.create(
        project_id=revision.project_id,
        owner_user_id=revision.created_by_user_id,
        source_revision_id=revision.id,
        kind="EXECUTION",
        payload=context.payload,
    )
    base = create_attempt(attempt_id=operation.id)
    failure_log = b"development failure"
    digest = hashlib.sha256(failure_log).hexdigest()
    failed = replace(
        base.report.phase_results[0],
        status=WebPhaseResultStatus.RUNTIME_ERROR,
        failure_category=WebFailureCategory.RUNTIME,
        failure_code="DEVELOPMENT_FAILURE",
        normalized_summary="An actual development command failed.",
        stderr_refs=(
            WebEvidenceReference(
                f"sha256/{digest[:2]}/{digest}", digest, len(failure_log), "text/plain"
            ),
        ),
    )
    attempt = replace(
        base,
        project_id=revision.project_id,
        created_by_user_id=revision.created_by_user_id,
        source_revision=revision.reference,
        profile_validation_content_hash=context.contract.validation.content_hash,
        execution_plan_content_hash=context.contract.execution_plan.content_hash,
        trigger=command.trigger,
        report=replace(
            base.report,
            source_revision_content_hash=revision.content_hash,
            source_tree_hash=revision.source_tree_hash,
            runner_image_digest=command.execution_runner_image_digest,
            policy_content_hash=command.policy_content_hash,
            phase_results=(failed, *base.report.phase_results[1:]),
        ),
    )
    state = BoundaryState(operation, attempt)

    async def execute(*args, **kwargs):
        state.backend_calls += 1
        if state.backend_cancel:
            raise asyncio.CancelledError
        return SimpleNamespace(status=WebExecutionServiceStatus.RECORDED, attempt=state.attempt)

    async def read(*, owner_user_id, execution_id):
        assert state.scope_connections == 0, (
            "reader requested a second connection from a size-one pool"
        )
        assert owner_user_id == operation.owner_user_id and execution_id == operation.id
        state.read_entered.set()
        await state.release_read.wait()
        if state.read_error is not None:
            raise state.read_error
        return None if state.persisted_attempt is None else state.persisted_attempt.to_snapshot()

    backend.execute = execute

    async def load_catalog():
        assert state.scope_connections == 0, (
            "catalog loader requested a second connection from a size-one pool"
        )
        state.catalog_loads += 1
        return SimpleNamespace(registry=create_sprint08_web_profile_registry())

    service = SqlAlchemyGovernedWebExecutionApiService(
        Sessions(state),
        operation_store=Store(state),
        backend=backend,
        catalog_loader=SimpleNamespace(load=load_catalog),
    )
    service._context = AsyncMock(return_value=context)
    service.reads = SimpleNamespace(execution=read)
    return state, service, replace(command, authorization_id=operation.id)


async def start(state, service, command):
    return await service.start_execution(
        owner_user_id=state.operation.owner_user_id,
        project_id=state.operation.project_id,
        command=command,
    )


@pytest.mark.parametrize("boundary", ["cancel_commit", "cancel_rollback"])
def test_cancel_on_claim_exit_reconciles_committed_state_without_executing(
    tmp_path, monkeypatch, boundary
):
    state, service, command = setup_lifecycle(tmp_path, monkeypatch)
    state.claim_exit = boundary
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(start(state, service, command))
    assert state.backend_calls == 0
    if boundary == "cancel_commit":
        assert state.operation.state is WebOperationState.FAILED
        assert state.operation.result["attempt_recorded"] is False
        assert state.operation.result["execution_started"] is False
    else:
        assert state.operation.state is WebOperationState.PENDING
        assert state.operation.result is None and state.finishes == []


@pytest.mark.parametrize("boundary", ["cancel_commit", "cancel_rollback"])
def test_cancel_on_attempt_commit_preserves_only_real_persisted_attempt(
    tmp_path, monkeypatch, boundary
):
    state, service, command = setup_lifecycle(tmp_path, monkeypatch)
    state.attempt_exit = boundary
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(start(state, service, command))
    assert state.backend_calls == 1
    if boundary == "cancel_commit":
        assert state.operation.state is WebOperationState.COMPLETED
        assert state.operation.result == {
            "execution_id": str(state.attempt.id),
            "attempt_content_hash": state.attempt.content_hash,
            "report_status": "FAILED",
        }
    else:
        assert state.operation.state is WebOperationState.FAILED
        assert state.operation.result["attempt_recorded"] is False
        assert "execution_started" not in state.operation.result


@pytest.mark.parametrize("boundary", ["error_before", "error_after"])
def test_finish_acknowledgment_failure_reconciles_attempt_and_is_idempotent(
    tmp_path, monkeypatch, boundary
):
    state, service, command = setup_lifecycle(tmp_path, monkeypatch)
    state.finish_exit = boundary
    result = asyncio.run(start(state, service, command))
    assert result.status is WebApiCommandStatus.EXECUTION_RECORDED
    assert result.snapshot == state.attempt.to_snapshot()
    assert state.operation.state is WebOperationState.COMPLETED
    assert state.operation.result["report_status"] == "FAILED"
    assert len(state.finishes) == 1 and state.finishes[0][1] is True
    assert state.backend_calls == 1


@pytest.mark.parametrize("repeat", [False, True])
def test_cancel_during_backend_drains_reconciliation_across_repeated_cancel(
    tmp_path, monkeypatch, repeat
):
    async def scenario():
        state, service, command = setup_lifecycle(tmp_path, monkeypatch)
        state.backend_cancel = True
        state.release_read.clear()
        task = asyncio.create_task(start(state, service, command))
        await asyncio.wait_for(state.read_entered.wait(), timeout=1)
        if repeat:
            task.cancel()
        state.release_read.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        assert state.operation.state is WebOperationState.FAILED
        assert state.operation.result["attempt_recorded"] is False
        assert state.backend_calls == 1 and len(state.finishes) == 1

    asyncio.run(scenario())


def test_unavailable_reconciliation_does_not_invent_absence(tmp_path, monkeypatch):
    state, service, command = setup_lifecycle(tmp_path, monkeypatch)
    state.backend_cancel = True
    state.read_error = OSError("database unavailable")
    with pytest.raises(OSError, match="database unavailable"):
        asyncio.run(start(state, service, command))
    assert state.operation.state is WebOperationState.RUNNING
    assert state.operation.result is None and state.finishes == []


def test_reconciliation_rejects_an_attempt_bound_to_another_source(tmp_path, monkeypatch):
    state, service, command = setup_lifecycle(tmp_path, monkeypatch)
    state.finish_exit = "error_before"
    other_source = replace(state.attempt.source_revision, revision_id=uuid4())
    state.attempt = replace(state.attempt, source_revision=other_source)
    with pytest.raises(WebOperationError, match="WEB_EXECUTION_RECORDED_ATTEMPT_MISMATCH"):
        asyncio.run(start(state, service, command))
    assert state.operation.state is WebOperationState.RUNNING
    assert state.finishes == []


def test_completed_replay_uses_existing_session_without_loading_catalog(tmp_path, monkeypatch):
    async def scenario():
        state, service, command = setup_lifecycle(tmp_path, monkeypatch)
        first = await start(state, service, command)
        assert first.status is WebApiCommandStatus.EXECUTION_RECORDED
        loads = state.catalog_loads
        replay = await start(state, service, command)
        assert replay.snapshot == first.snapshot
        assert state.backend_calls == 1 and state.catalog_loads == loads

    asyncio.run(scenario())
