"""Isolated service tests: repositories and transitions are explicit test doubles."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from orchestwin.api import workflow_run_runtime as sut

OWNER = UUID(int=541)
PROJECT = UUID(int=542)
RUN = UUID(int=543)
COMMAND = UUID(int=544)
CHECKPOINT_ID = UUID(int=1000)
NOW = datetime(2026, 9, 8, 10, 0, tzinfo=UTC)


@dataclass(frozen=True)
class RunDouble:
    id: UUID = RUN
    project_id: UUID = PROJECT
    owner_user_id: UUID = OWNER
    status: sut.WorkflowRunStatus = sut.WorkflowRunStatus.RUNNING
    pending_gate_id: UUID | None = None

    def to_snapshot(self):
        return {"id": str(self.id), "project_id": str(self.project_id), "status": self.status.value}


class TransactionDouble:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        self.session.transaction_entered += 1
        return self

    async def __aexit__(self, exc_type, _value, _tb):
        if exc_type is None:
            self.session.committed += 1
        else:
            self.session.rolled_back += 1


class SessionDouble:
    def __init__(self):
        self.scalar = AsyncMock(return_value=object())
        self.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: ()))
        self.closed = 0
        self.transaction_entered = 0
        self.committed = 0
        self.rolled_back = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        self.closed += 1

    def begin(self):
        return TransactionDouble(self)


@pytest.fixture
def environment(monkeypatch):
    session = SessionDouble()
    run = RunDouble()
    project = SimpleNamespace(mode="GREENFIELD_GENERATION", created_at=NOW - timedelta(days=1))
    projects = SimpleNamespace(get_owned=AsyncMock(return_value=project))
    runs = SimpleNamespace(
        get_owned=AsyncMock(return_value=run),
        create=AsyncMock(
            return_value=SimpleNamespace(status=sut.WorkflowRunStoreStatus.CREATED, run=run)
        ),
        list_checkpoints=AsyncMock(return_value=()),
    )
    events = SimpleNamespace(
        list_after=AsyncMock(return_value=()),
        append=AsyncMock(
            return_value=SimpleNamespace(status=sut.WorkflowEventAppendStatus.APPENDED)
        ),
    )
    transitions = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(
                status=sut.WorkflowLifecycleCommandStatus.APPLIED,
                run=replace(run, status=sut.WorkflowRunStatus.PAUSED),
            )
        )
    )
    owners = []
    monkeypatch.setattr(sut, "SqlAlchemyProjectRepository", lambda _session: projects)

    def run_repository(received_session, *, owner_user_id):
        assert received_session is session
        owners.append(owner_user_id)
        return runs

    monkeypatch.setattr(sut, "SqlAlchemyWorkflowRunRepository", run_repository)
    monkeypatch.setattr(sut, "SqlAlchemyWorkflowEventRepository", lambda _s, **_kw: events)
    monkeypatch.setattr(sut, "WorkflowLifecycleCommandService", lambda repository: transitions)
    created = []
    monkeypatch.setattr(sut, "create_workflow_run", lambda **kw: created.append(kw) or run)
    service = sut.SqlAlchemyWorkflowRunApiService(lambda: session)
    return SimpleNamespace(
        service=service,
        session=session,
        run=run,
        project=project,
        projects=projects,
        runs=runs,
        events=events,
        transitions=transitions,
        owners=owners,
        created=created,
    )


def create_command(**overrides):
    return sut.WorkflowRunCreateCommand(
        **{
            "run_id": RUN,
            "created_at": NOW,
            "project_mode": "GREENFIELD_GENERATION",
            **overrides,
        }
    )


def lifecycle_command(**overrides):
    return sut.WorkflowRunLifecycleCommand(
        **{
            "command_id": COMMAND,
            "project_id": PROJECT,
            "kind": sut.WorkflowLifecycleCommandKind.PAUSE,
            "expected_state_version": 1,
            "expected_checkpoint_sequence": 0,
            "occurred_at": NOW,
            "reason": None,
            "authorization_reference": None,
            **overrides,
        }
    )


def create(env, command=None):
    return asyncio.run(
        env.service.create_run(
            owner_user_id=OWNER,
            project_id=PROJECT,
            command=command or create_command(),
        )
    )


def apply(env, command=None):
    return asyncio.run(
        env.service.apply_lifecycle_command(
            owner_user_id=OWNER,
            run_id=RUN,
            command=command or lifecycle_command(),
        )
    )


def test_creation_delegates_exact_identity_and_does_not_emit_a_started_event(environment):
    env = environment
    result = create(env)
    assert result.status is sut.WorkflowRunApiStatus.RUN_CREATED
    assert env.created == [
        {
            "project_id": PROJECT,
            "owner_user_id": OWNER,
            "project_mode": env.project.mode,
            "run_id": RUN,
            "created_at": NOW,
        }
    ]
    assert env.owners == [OWNER]
    assert env.session.committed == env.session.closed == 1
    env.events.append.assert_not_awaited()
    env.transitions.execute.assert_not_awaited()


def test_identical_creation_uses_existing_repository_result(environment):
    env = environment
    env.runs.create.return_value = SimpleNamespace(
        status=sut.WorkflowRunStoreStatus.ALREADY_PRESENT,
        run=env.run,
    )
    assert create(env).status is sut.WorkflowRunApiStatus.COMMAND_ALREADY_APPLIED
    env.events.append.assert_not_awaited()


@pytest.mark.parametrize("missing_at", ["lock", "project", "repository"])
def test_creation_hides_missing_or_unowned_project(environment, missing_at):
    env = environment
    if missing_at == "lock":
        env.session.scalar.return_value = None
    elif missing_at == "project":
        env.projects.get_owned.return_value = None
    else:
        env.runs.create.return_value = SimpleNamespace(
            status=sut.WorkflowRunStoreStatus.PROJECT_NOT_FOUND,
            run=None,
        )
    result = create(env)
    assert result.status is sut.WorkflowRunApiStatus.NOT_FOUND
    assert result.snapshot is None
    assert env.session.closed == 1


@pytest.mark.parametrize("change", ["mode", "collision", "timestamp"])
def test_creation_rejects_invalid_or_conflicting_input(environment, change):
    env = environment
    command = create_command()
    if change == "mode":
        command = create_command(project_mode="BROWNFIELD_ASSESSMENT")
    elif change == "collision":
        env.runs.create.return_value = SimpleNamespace(
            status=sut.WorkflowRunStoreStatus.STATE_CONFLICT,
            run=None,
        )
    else:
        command = create_command(created_at=NOW - timedelta(days=2))
    with pytest.raises(HTTPException) as error:
        create(env, command)
    assert error.value.status_code == (422 if change == "timestamp" else 409)
    assert env.session.rolled_back == 1
    assert env.session.closed == 1


def test_naive_creation_timestamp_never_opens_a_transaction(environment):
    with pytest.raises(HTTPException) as error:
        create(environment, create_command(created_at=NOW.replace(tzinfo=None)))
    assert error.value.status_code == 422
    assert environment.session.transaction_entered == 0


def test_run_read_delegates_authenticated_owner(environment):
    env = environment
    result = asyncio.run(env.service.run(owner_user_id=OWNER, run_id=RUN))
    assert result == env.run.to_snapshot()
    assert env.owners == [OWNER]
    env.runs.get_owned.assert_awaited_once_with(run_id=RUN)
    assert env.session.closed == 1


@pytest.mark.parametrize("operation", ["run", "checkpoints", "events"])
def test_missing_or_archived_run_never_reads_child_evidence(environment, operation):
    env = environment
    env.runs.get_owned.return_value = None
    kwargs = {"owner_user_id": OWNER, "run_id": RUN}
    if operation == "events":
        kwargs.update(after_sequence=0, limit=500)
    result = asyncio.run(getattr(env.service, operation)(**kwargs))
    assert result is None if operation == "run" else result == ()
    env.events.list_after.assert_not_awaited()
    env.runs.list_checkpoints.assert_not_awaited()
    assert env.session.closed == 1


def test_list_runs_has_owner_project_archive_filters_and_stable_order(environment, monkeypatch):
    env = environment
    env.session.scalars.return_value = SimpleNamespace(all=lambda: (env.run,))
    monkeypatch.setattr(sut, "workflow_run_record_to_domain", lambda row: row)
    assert asyncio.run(env.service.list_runs(owner_user_id=OWNER, project_id=PROJECT)) == (
        env.run.to_snapshot(),
    )
    statement = env.session.scalars.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "workflow_runs.owner_user_id =" in sql
    assert "projects.owner_user_id =" in sql
    assert "projects.archived_at IS NULL" in sql
    assert "workflow_runs.project_id =" in sql
    assert "ORDER BY workflow_runs.created_at, workflow_runs.id" in sql
    assert PROJECT in statement.compile().params.values()
    assert env.session.closed == 1


def test_events_preserve_cursor_and_minimal_payload(environment):
    env = environment
    event = SimpleNamespace(
        id=UUID(int=900),
        run_id=RUN,
        project_id=PROJECT,
        owner_user_id=OWNER,
        sequence_number=3,
        event_type=sut.WorkflowEventType.PAUSED,
        occurred_at=NOW,
        payload=SimpleNamespace(to_snapshot=lambda: {"decision_id": str(COMMAND)}),
        payload_hash="a" * 64,
    )
    env.events.list_after.return_value = (event,)
    results = asyncio.run(
        env.service.events(
            owner_user_id=OWNER,
            run_id=RUN,
            after_sequence=2,
            limit=10,
        )
    )
    assert results[0]["event_type"] == "workflow.paused"
    assert results[0]["sequence_number"] == 3
    assert results[0]["payload"] == {"decision_id": str(COMMAND)}
    env.events.list_after.assert_awaited_once_with(run_id=RUN, after_sequence=2, limit=10)


@pytest.mark.parametrize(("cursor", "limit"), [(-1, 1), (True, 1), (0, 0), (0, 501), (0, True)])
def test_invalid_event_cursors_are_rejected_before_database_use(environment, cursor, limit):
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            environment.service.events(
                owner_user_id=OWNER,
                run_id=RUN,
                after_sequence=cursor,
                limit=limit,
            )
        )
    assert error.value.status_code == 422
    assert environment.session.closed == 0


@pytest.mark.parametrize("missing_at", ["lock", "repository", "project_scope"])
def test_lifecycle_rejects_unowned_or_mismatched_run(environment, missing_at):
    env = environment
    if missing_at == "lock":
        env.session.scalar.return_value = None
    elif missing_at == "repository":
        env.runs.get_owned.return_value = None
    else:
        env.runs.get_owned.return_value = replace(env.run, project_id=UUID(int=999))
    result = apply(env)
    assert result.status is sut.WorkflowRunApiStatus.NOT_FOUND
    assert result.snapshot is None
    env.transitions.execute.assert_not_awaited()
    env.events.append.assert_not_awaited()


@pytest.mark.parametrize(
    "status",
    [
        sut.WorkflowLifecycleCommandStatus.ALREADY_APPLIED,
        sut.WorkflowLifecycleCommandStatus.STATE_CONFLICT,
        sut.WorkflowLifecycleCommandStatus.ILLEGAL_STATE,
        sut.WorkflowLifecycleCommandStatus.AUTHORIZATION_REQUIRED,
    ],
)
def test_non_applied_domain_results_do_not_add_events(environment, status):
    env = environment
    env.transitions.execute.return_value = SimpleNamespace(status=status, run=env.run)
    assert apply(env).status is sut._COMMAND_STATUSES[status]
    env.events.append.assert_not_awaited()
    assert env.session.committed == 1


@pytest.mark.parametrize(
    ("status", "reference"),
    [
        (sut.WorkflowRunStatus.PAUSED_NEEDS_HUMAN, None),
        (sut.WorkflowRunStatus.PAUSED_NEEDS_HUMAN, UUID(int=999)),
        (sut.WorkflowRunStatus.PAUSED, UUID(int=999)),
    ],
)
def test_resume_never_accepts_an_unverified_authorization(environment, status, reference):
    env = environment
    env.runs.get_owned.return_value = replace(env.run, status=status)
    result = apply(
        env,
        lifecycle_command(
            kind=sut.WorkflowLifecycleCommandKind.RESUME, authorization_reference=reference
        ),
    )
    assert result.status is sut.WorkflowRunApiStatus.AUTHORIZATION_REQUIRED
    env.transitions.execute.assert_not_awaited()
    env.events.append.assert_not_awaited()


@pytest.mark.parametrize(
    "bad",
    [
        {"occurred_at": NOW.replace(tzinfo=None)},
        {"expected_state_version": True},
        {"expected_state_version": 0},
        {"expected_checkpoint_sequence": -1},
        {"expected_checkpoint_sequence": True},
        {"reason": " leading whitespace"},
        {"authorization_reference": UUID(int=999)},
    ],
)
def test_invalid_lifecycle_input_is_not_persisted(environment, bad):
    with pytest.raises(HTTPException) as error:
        apply(environment, lifecycle_command(**bad))
    assert error.value.status_code == 422
    assert environment.session.transaction_entered == 0


@pytest.mark.parametrize("rejected_append", [0, 1])
def test_event_failure_rolls_back_whole_transaction(environment, monkeypatch, rejected_append):
    env = environment
    env.session.scalar.side_effect = [object(), 4]
    monkeypatch.setattr(sut, "create_workflow_event", lambda *args, **kwargs: kwargs)
    statuses = [sut.WorkflowEventAppendStatus.APPENDED] * 2
    statuses[rejected_append] = sut.WorkflowEventAppendStatus.SEQUENCE_CONFLICT
    env.events.append.side_effect = [SimpleNamespace(status=status) for status in statuses]
    with pytest.raises(HTTPException) as error:
        apply(env)
    assert error.value.status_code == 409
    assert error.value.detail == {"code": "WORKFLOW_EVENT_WRITE_CONFLICT"}
    assert env.session.committed == 0
    assert env.session.rolled_back == 1
    assert env.session.closed == 1


def test_applied_command_adds_ordered_events_under_lock(environment, monkeypatch):
    env = environment
    env.session.scalar.side_effect = [object(), 8]
    monkeypatch.setattr(sut, "create_workflow_event", lambda *args, **kwargs: kwargs)
    assert apply(env).status is sut.WorkflowRunApiStatus.COMMAND_APPLIED
    lock = env.session.scalar.await_args_list[0].args[0]
    assert "FOR UPDATE" in str(lock.compile(dialect=postgresql.dialect()))
    calls = env.events.append.await_args_list
    assert [call.args[0]["sequence_number"] for call in calls] == [9, 10]
    assert [call.kwargs["expected_previous_sequence"] for call in calls] == [8, 9]
    assert all(call.args[0]["decision_id"] == COMMAND for call in calls)
    assert env.session.committed == env.session.closed == 1
    domain = env.transitions.execute.await_args.args[0]
    assert domain.run_id == RUN and domain.owner_user_id == OWNER


def test_resume_to_waiting_preserves_gate_event_semantics():
    run = RunDouble(status=sut.WorkflowRunStatus.WAITING_FOR_HUMAN, pending_gate_id=UUID(int=901))
    assert sut._transition_event_type(sut.WorkflowLifecycleCommandKind.RESUME, run) is (
        sut.WorkflowEventType.WAITING_FOR_HUMAN
    )


def test_corrupt_checkpoint_is_not_returned(environment, monkeypatch):
    env = environment
    env.runs.list_checkpoints.return_value = (object(),)
    monkeypatch.setattr(
        sut,
        "restore_workflow_checkpoint",
        lambda *_a, **_k: SimpleNamespace(
            status=sut.WorkflowCheckpointRestoreStatus.CORRUPTED,
        ),
    )
    with pytest.raises(sut.WorkflowRunPersistenceConflict, match="INTEGRITY"):
        asyncio.run(env.service.checkpoints(owner_user_id=OWNER, run_id=RUN))
    assert env.session.closed == 1


def test_checkpoint_envelope_is_json_safe(environment, monkeypatch):
    env = environment

    @dataclass(frozen=True)
    class CheckpointDouble:
        id: UUID = CHECKPOINT_ID
        created_at: datetime = NOW
        payload_json: str = "{}"

    env.runs.list_checkpoints.return_value = (CheckpointDouble(),)
    received = []
    monkeypatch.setattr(
        sut,
        "restore_workflow_checkpoint",
        lambda *a, **kw: (
            received.append(kw)
            or SimpleNamespace(status=sut.WorkflowCheckpointRestoreStatus.RESTORED)
        ),
    )
    result = asyncio.run(env.service.checkpoints(owner_user_id=OWNER, run_id=RUN))
    assert result[0]["id"] == str(UUID(int=1000))
    assert isinstance(result[0]["created_at"], str)
    assert received == [
        {"expected_run_id": RUN, "expected_project_id": PROJECT, "expected_owner_user_id": OWNER}
    ]
