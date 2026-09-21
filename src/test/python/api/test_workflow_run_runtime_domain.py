"""Real lifecycle/checkpoint/event contracts with in-memory repositories, no external DB."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import HTTPException

from orchestwin.api import workflow_run_runtime as sut
from orchestwin.api.workflow_runs import WorkflowRunCreateCommand, WorkflowRunLifecycleCommand
from orchestwin.projects.domain import ProjectMode
from orchestwin.workflow.commands import WorkflowLifecycleCommandKind
from orchestwin.workflow.event_persistence import (
    InMemoryWorkflowEventRepository,
    WorkflowEventAppendResult,
    WorkflowEventAppendStatus,
)
from orchestwin.workflow.run_persistence import InMemoryWorkflowRunRepository
from orchestwin.workflow.runs import WorkflowRunStatus

OWNER = UUID(int=54101)
PROJECT = UUID(int=54102)
RUN = UUID(int=54103)
DEFAULT_COMMAND_ID = UUID(int=54110)
NOW = datetime(2026, 9, 8, 10, 0, tzinfo=UTC)


class Transaction:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        self.before = deepcopy(
            (self.session.runs._runs, self.session.runs._checkpoints, self.session.events._events)
        )
        return self

    async def __aexit__(self, exc_type, *_args):
        if exc_type is not None:
            self.session.runs._runs, self.session.runs._checkpoints, self.session.events._events = (
                self.before
            )


class Session:
    """Only transaction and locking transport are doubled, not domain transitions."""

    def __init__(self, runs, events):
        self.runs, self.events = runs, events
        self.scalar = AsyncMock(return_value=True)
        self.closed = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        self.closed += 1

    def begin(self):
        return Transaction(self)


@pytest.fixture
def environment(monkeypatch):
    runs = InMemoryWorkflowRunRepository(owner_user_id=OWNER, project_ids=frozenset({PROJECT}))
    events = InMemoryWorkflowEventRepository(owner_user_id=OWNER, run_projects={RUN: PROJECT})
    session = Session(runs, events)
    monkeypatch.setattr(sut, "SqlAlchemyWorkflowRunRepository", lambda *_a, **_k: runs)
    monkeypatch.setattr(sut, "SqlAlchemyWorkflowEventRepository", lambda *_a, **_k: events)
    project = SimpleNamespace(
        mode=ProjectMode.GREENFIELD_GENERATION, created_at=NOW - timedelta(days=1)
    )
    monkeypatch.setattr(
        sut,
        "SqlAlchemyProjectRepository",
        lambda _s: SimpleNamespace(
            get_owned=AsyncMock(return_value=project),
        ),
    )
    return SimpleNamespace(
        runs=runs,
        events=events,
        session=session,
        service=sut.SqlAlchemyWorkflowRunApiService(lambda: session),
    )


async def create(env):
    result = await env.service.create_run(
        owner_user_id=OWNER,
        project_id=PROJECT,
        command=WorkflowRunCreateCommand(RUN, ProjectMode.GREENFIELD_GENERATION, NOW),
    )
    assert result.status is sut.WorkflowRunApiStatus.RUN_CREATED
    return await env.runs.get_owned(run_id=RUN)


def command(
    kind,
    *,
    version=1,
    sequence=0,
    seconds=1,
    command_id=DEFAULT_COMMAND_ID,
    **extra,
):
    return WorkflowRunLifecycleCommand(
        command_id=command_id,
        project_id=PROJECT,
        kind=kind,
        expected_state_version=version,
        expected_checkpoint_sequence=sequence,
        occurred_at=NOW + timedelta(seconds=seconds),
        reason=None,
        authorization_reference=extra.get("authorization_reference"),
    )


async def apply(env, cmd):
    # Lock result, then latest event sequence; an unchanged command never queries sequence.
    count = len(await env.events.list_after(run_id=RUN, limit=500))
    env.session.scalar.side_effect = [True, count]
    try:
        return await env.service.apply_lifecycle_command(
            owner_user_id=OWNER, run_id=RUN, command=cmd
        )
    finally:
        env.session.scalar.side_effect = None


def test_draft_creation_cancellation_checkpoint_and_event_replay(environment):
    async def scenario():
        env = environment
        draft = await create(env)
        assert draft.status is WorkflowRunStatus.DRAFT
        assert draft.started_at is None and draft.checkpoint_sequence == 0
        cancel = command(WorkflowLifecycleCommandKind.CANCEL)
        result = await apply(env, cancel)
        assert result.status is sut.WorkflowRunApiStatus.COMMAND_APPLIED
        assert result.snapshot["status"] == "CANCELLED"
        assert result.snapshot["checkpoint_sequence"] == 1
        replay = await apply(env, cancel)
        assert replay.status is sut.WorkflowRunApiStatus.COMMAND_ALREADY_APPLIED
        history = await env.service.checkpoints(owner_user_id=OWNER, run_id=RUN)
        assert len(history) == 1
        items = await env.service.events(
            owner_user_id=OWNER, run_id=RUN, after_sequence=0, limit=500
        )
        assert [item["event_type"] for item in items] == [
            "workflow.cancelled",
            "workflow.checkpoint.created",
        ]
        assert all(item["payload"]["decision_id"] == str(cancel.command_id) for item in items)
        tail = await env.service.events(
            owner_user_id=OWNER, run_id=RUN, after_sequence=1, limit=500
        )
        assert [item["sequence_number"] for item in tail] == [2]

    asyncio.run(scenario())


def test_pause_and_resume_preserve_a_pending_human_gate(environment):
    async def scenario():
        env = environment
        draft = await create(env)
        gate_id = UUID(int=54199)
        env.runs._runs[RUN] = replace(
            draft,
            status=WorkflowRunStatus.WAITING_FOR_HUMAN,
            pending_gate_id=gate_id,
            started_at=NOW,
        )
        paused = await apply(env, command(WorkflowLifecycleCommandKind.PAUSE))
        assert paused.snapshot["status"] == "PAUSED"
        resumed = await apply(
            env,
            command(
                WorkflowLifecycleCommandKind.RESUME,
                version=2,
                sequence=1,
                seconds=2,
                command_id=UUID(int=54111),
            ),
        )
        assert resumed.snapshot["status"] == "WAITING_FOR_HUMAN"
        assert resumed.snapshot["pending_gate_id"] == str(gate_id)
        events = await env.events.list_after(run_id=RUN, limit=500)
        assert events[2].event_type is sut.WorkflowEventType.WAITING_FOR_HUMAN
        assert len(await env.service.checkpoints(owner_user_id=OWNER, run_id=RUN)) == 2

    asyncio.run(scenario())


def test_stale_active_transition_and_unverified_limit_resume_are_not_applied(environment):
    async def scenario():
        env = environment
        draft = await create(env)
        env.runs._runs[RUN] = replace(draft, status=WorkflowRunStatus.RUNNING, started_at=NOW)
        result = await apply(env, command(WorkflowLifecycleCommandKind.PAUSE, version=99))
        assert result.status is sut.WorkflowRunApiStatus.STATE_CONFLICT
        env.runs._runs[RUN] = replace(
            env.runs._runs[RUN],
            status=WorkflowRunStatus.PAUSED_NEEDS_HUMAN,
            resume_status=WorkflowRunStatus.RUNNING,
        )
        result = await apply(
            env,
            command(
                WorkflowLifecycleCommandKind.RESUME,
                authorization_reference=UUID(int=54999),
            ),
        )
        assert result.status is sut.WorkflowRunApiStatus.AUTHORIZATION_REQUIRED
        assert await env.runs.list_checkpoints(run_id=RUN) == ()
        assert await env.events.list_after(run_id=RUN) == ()

    asyncio.run(scenario())


def test_event_append_conflict_restores_state_and_checkpoint_in_transaction(
    environment, monkeypatch
):
    async def scenario():
        env = environment
        before = await create(env)
        monkeypatch.setattr(
            env.events,
            "append",
            AsyncMock(
                return_value=WorkflowEventAppendResult(
                    WorkflowEventAppendStatus.SEQUENCE_CONFLICT,
                    None,
                )
            ),
        )
        with pytest.raises(HTTPException) as error:
            await apply(env, command(WorkflowLifecycleCommandKind.CANCEL))
        assert error.value.status_code == 409
        assert await env.runs.get_owned(run_id=RUN) == before
        assert await env.runs.list_checkpoints(run_id=RUN) == ()
        assert await env.events.list_after(run_id=RUN) == ()

    asyncio.run(scenario())
