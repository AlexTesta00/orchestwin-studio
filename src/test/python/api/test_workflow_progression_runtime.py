"""Runtime tests for persisted start, advance, and approved-gate resume commands."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from orchestwin.api import workflow_run_runtime as sut
from orchestwin.api.workflow_runs import (
    WorkflowRunAdvanceCommand,
    WorkflowRunCreateCommand,
    WorkflowRunGateResumeCommand,
    WorkflowRunStartCommand,
)
from orchestwin.projects.domain import ProjectMode
from orchestwin.workflow.event_persistence import InMemoryWorkflowEventRepository
from orchestwin.workflow.langgraph_checkpointer import InMemoryLangGraphCheckpointStore
from orchestwin.workflow.progression_graph import DurableWorkflowGraphProgression
from orchestwin.workflow.run_persistence import InMemoryWorkflowRunRepository
from orchestwin.workflow.runs import WorkflowRunStatus, WorkflowStage

OWNER = UUID("00000000-0000-4000-8000-000000013001")
PROJECT = UUID("00000000-0000-4000-8000-000000013002")
RUN = UUID("00000000-0000-4000-8000-000000013003")
GATE_1 = UUID("00000000-0000-4000-8000-000000013004")
GATE_2 = UUID("00000000-0000-4000-8000-000000013005")
DECISION_1 = UUID("00000000-0000-4000-8000-000000013006")
DECISION_2 = UUID("00000000-0000-4000-8000-000000013007")
NOW = datetime(2026, 9, 10, 20, 30, tzinfo=UTC)


class MutableClock:
    def __init__(self) -> None:
        self.current = NOW

    def at(self, seconds: int) -> None:
        self.current = NOW + timedelta(seconds=seconds)

    def __call__(self) -> datetime:
        return self.current


class Transaction:
    def __init__(self, session) -> None:
        self.session = session

    async def __aenter__(self):
        self.before = deepcopy(
            (
                self.session.runs._runs,
                self.session.runs._checkpoints,
                self.session.events._events,
            )
        )
        return self

    async def __aexit__(self, exc_type, *_args):
        if exc_type is not None:
            (
                self.session.runs._runs,
                self.session.runs._checkpoints,
                self.session.events._events,
            ) = self.before


class Session:
    def __init__(self, runs, events) -> None:
        self.runs = runs
        self.events = events
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
    runs = InMemoryWorkflowRunRepository(
        owner_user_id=OWNER,
        project_ids=frozenset({PROJECT}),
    )
    events = InMemoryWorkflowEventRepository(
        owner_user_id=OWNER,
        run_projects={RUN: PROJECT},
    )
    session = Session(runs, events)
    clock = MutableClock()

    monkeypatch.setattr(
        sut,
        "SqlAlchemyWorkflowRunRepository",
        lambda *_args, **_kwargs: runs,
    )
    monkeypatch.setattr(
        sut,
        "SqlAlchemyWorkflowEventRepository",
        lambda *_args, **_kwargs: events,
    )
    monkeypatch.setattr(
        sut,
        "SqlAlchemyProjectRepository",
        lambda _session: SimpleNamespace(
            get_owned=AsyncMock(
                return_value=SimpleNamespace(
                    mode=ProjectMode.GREENFIELD_GENERATION,
                    created_at=NOW - timedelta(days=1),
                )
            )
        ),
    )

    enterable = AsyncMock(return_value=True)
    approved = AsyncMock(return_value=True)
    monkeypatch.setattr(sut, "_gate_is_enterable", enterable)
    monkeypatch.setattr(sut, "_approved_gate_decision_exists", approved)

    return SimpleNamespace(
        runs=runs,
        events=events,
        session=session,
        clock=clock,
        enterable=enterable,
        approved=approved,
        service=sut.SqlAlchemyWorkflowRunApiService(
            lambda: session,
            clock=clock,
            graph_runtime=DurableWorkflowGraphProgression(InMemoryLangGraphCheckpointStore()),
        ),
    )


async def create_draft(env):
    env.session.scalar.return_value = True
    result = await env.service.create_run(
        owner_user_id=OWNER,
        project_id=PROJECT,
        command=WorkflowRunCreateCommand(
            run_id=RUN,
            project_mode=ProjectMode.GREENFIELD_GENERATION,
            created_at=NOW,
        ),
    )
    assert result.status is sut.WorkflowRunApiStatus.RUN_CREATED
    return await env.runs.get_owned(run_id=RUN)


async def event_count(env) -> int:
    return len(await env.events.list_after(run_id=RUN, limit=500))


async def apply_with_event_sequence(env, operation):
    count = await event_count(env)
    env.session.scalar.side_effect = [True, count]
    try:
        return await operation
    finally:
        env.session.scalar.side_effect = None
        env.session.scalar.return_value = True


def start_command(*, version: int, sequence: int, command_id: int) -> WorkflowRunStartCommand:
    return WorkflowRunStartCommand(
        command_id=UUID(int=command_id),
        project_id=PROJECT,
        expected_state_version=version,
        expected_checkpoint_sequence=sequence,
    )


def advance_command(
    *,
    version: int,
    sequence: int,
    command_id: int,
    stage: WorkflowStage,
    gate_id: UUID | None = None,
) -> WorkflowRunAdvanceCommand:
    return WorkflowRunAdvanceCommand(
        command_id=UUID(int=command_id),
        project_id=PROJECT,
        expected_state_version=version,
        expected_checkpoint_sequence=sequence,
        next_stage=stage,
        pending_gate_id=gate_id,
    )


def resume_command(
    *,
    version: int,
    sequence: int,
    gate_id: UUID,
    decision_id: UUID,
) -> WorkflowRunGateResumeCommand:
    return WorkflowRunGateResumeCommand(
        project_id=PROJECT,
        expected_state_version=version,
        expected_checkpoint_sequence=sequence,
        gate_id=gate_id,
        decision_id=decision_id,
    )


def test_formal_pre_main_path_is_checkpointed_and_cannot_skip_owner_gates(environment):
    async def scenario() -> None:
        env = environment
        draft = await create_draft(env)
        assert draft is not None
        assert draft.status is WorkflowRunStatus.DRAFT
        assert draft.current_stage is WorkflowStage.INTAKE

        env.clock.at(1)
        started = await apply_with_event_sequence(
            env,
            env.service.start_run(
                owner_user_id=OWNER,
                run_id=RUN,
                command=start_command(version=1, sequence=0, command_id=13010),
            ),
        )
        assert started.status is sut.WorkflowRunApiStatus.COMMAND_APPLIED
        assert started.snapshot["status"] == "RUNNING"
        assert started.snapshot["current_stage"] == "INTAKE"
        assert started.snapshot["state_version"] == 2
        assert started.snapshot["checkpoint_sequence"] == 1

        env.clock.at(2)
        brief_wait = await apply_with_event_sequence(
            env,
            env.service.advance_run(
                owner_user_id=OWNER,
                run_id=RUN,
                command=advance_command(
                    version=2,
                    sequence=1,
                    command_id=13011,
                    stage=WorkflowStage.BRIEF_APPROVAL,
                    gate_id=GATE_1,
                ),
            ),
        )
        assert brief_wait.snapshot["status"] == "WAITING_FOR_HUMAN"
        assert brief_wait.snapshot["pending_gate_id"] == str(GATE_1)

        env.clock.at(3)
        brief_resumed = await apply_with_event_sequence(
            env,
            env.service.resume_after_gate(
                owner_user_id=OWNER,
                run_id=RUN,
                command=resume_command(
                    version=3,
                    sequence=2,
                    gate_id=GATE_1,
                    decision_id=DECISION_1,
                ),
            ),
        )
        assert brief_resumed.snapshot["status"] == "RUNNING"
        assert brief_resumed.snapshot["pending_gate_id"] is None
        assert brief_resumed.snapshot["current_stage"] == "BRIEF_APPROVAL"

        env.clock.at(4)
        selection = await apply_with_event_sequence(
            env,
            env.service.advance_run(
                owner_user_id=OWNER,
                run_id=RUN,
                command=advance_command(
                    version=4,
                    sequence=3,
                    command_id=13012,
                    stage=WorkflowStage.TEAM_SELECTION,
                ),
            ),
        )
        assert selection.snapshot["current_stage"] == "TEAM_SELECTION"
        assert selection.snapshot["status"] == "RUNNING"

        env.clock.at(5)
        team_wait = await apply_with_event_sequence(
            env,
            env.service.advance_run(
                owner_user_id=OWNER,
                run_id=RUN,
                command=advance_command(
                    version=5,
                    sequence=4,
                    command_id=13013,
                    stage=WorkflowStage.TEAM_APPROVAL,
                    gate_id=GATE_2,
                ),
            ),
        )
        assert team_wait.snapshot["status"] == "WAITING_FOR_HUMAN"
        assert team_wait.snapshot["pending_gate_id"] == str(GATE_2)

        env.clock.at(6)
        team_resumed = await apply_with_event_sequence(
            env,
            env.service.resume_after_gate(
                owner_user_id=OWNER,
                run_id=RUN,
                command=resume_command(
                    version=6,
                    sequence=5,
                    gate_id=GATE_2,
                    decision_id=DECISION_2,
                ),
            ),
        )
        assert team_resumed.snapshot["status"] == "RUNNING"
        assert team_resumed.snapshot["current_stage"] == "TEAM_APPROVAL"

        env.clock.at(7)
        user_modeling = await apply_with_event_sequence(
            env,
            env.service.advance_run(
                owner_user_id=OWNER,
                run_id=RUN,
                command=advance_command(
                    version=7,
                    sequence=6,
                    command_id=13014,
                    stage=WorkflowStage.USER_MODELING,
                ),
            ),
        )
        assert user_modeling.snapshot["status"] == "RUNNING"
        assert user_modeling.snapshot["current_stage"] == "USER_MODELING"
        assert user_modeling.snapshot["state_version"] == 8
        assert user_modeling.snapshot["checkpoint_sequence"] == 7

        checkpoints = await env.runs.list_checkpoints(run_id=RUN)
        assert len(checkpoints) == 7

        events = await env.events.list_after(run_id=RUN, limit=500)
        assert [event.event_type.value for event in events] == [
            "workflow.run.started",
            "workflow.checkpoint.created",
            "workflow.stage.changed",
            "workflow.waiting_for_human",
            "workflow.checkpoint.created",
            "workflow.resumed",
            "workflow.checkpoint.created",
            "workflow.stage.changed",
            "workflow.checkpoint.created",
            "workflow.stage.changed",
            "workflow.waiting_for_human",
            "workflow.checkpoint.created",
            "workflow.resumed",
            "workflow.checkpoint.created",
            "workflow.stage.changed",
            "workflow.checkpoint.created",
        ]
        assert events[5].payload.decision_id == DECISION_1
        assert events[12].payload.decision_id == DECISION_2

        assert env.enterable.await_count == 2
        assert env.approved.await_count == 2

    asyncio.run(scenario())


def test_human_gate_entry_and_resume_fail_closed_without_verified_authority(environment):
    async def scenario() -> None:
        env = environment
        await create_draft(env)

        env.clock.at(1)
        await apply_with_event_sequence(
            env,
            env.service.start_run(
                owner_user_id=OWNER,
                run_id=RUN,
                command=start_command(version=1, sequence=0, command_id=13100),
            ),
        )

        env.enterable.return_value = False
        env.clock.at(2)
        denied_entry = await apply_with_event_sequence(
            env,
            env.service.advance_run(
                owner_user_id=OWNER,
                run_id=RUN,
                command=advance_command(
                    version=2,
                    sequence=1,
                    command_id=13101,
                    stage=WorkflowStage.BRIEF_APPROVAL,
                    gate_id=GATE_1,
                ),
            ),
        )
        assert denied_entry.status is sut.WorkflowRunApiStatus.AUTHORIZATION_REQUIRED
        current = await env.runs.get_owned(run_id=RUN)
        assert current is not None
        assert current.current_stage is WorkflowStage.INTAKE
        assert current.checkpoint_sequence == 1

        env.enterable.return_value = True
        env.clock.at(3)
        waiting = await apply_with_event_sequence(
            env,
            env.service.advance_run(
                owner_user_id=OWNER,
                run_id=RUN,
                command=advance_command(
                    version=2,
                    sequence=1,
                    command_id=13102,
                    stage=WorkflowStage.BRIEF_APPROVAL,
                    gate_id=GATE_1,
                ),
            ),
        )
        assert waiting.snapshot["status"] == "WAITING_FOR_HUMAN"

        env.approved.return_value = False
        env.clock.at(4)
        denied_resume = await apply_with_event_sequence(
            env,
            env.service.resume_after_gate(
                owner_user_id=OWNER,
                run_id=RUN,
                command=resume_command(
                    version=3,
                    sequence=2,
                    gate_id=GATE_1,
                    decision_id=DECISION_1,
                ),
            ),
        )
        assert denied_resume.status is sut.WorkflowRunApiStatus.AUTHORIZATION_REQUIRED
        current = await env.runs.get_owned(run_id=RUN)
        assert current is not None
        assert current.status is WorkflowRunStatus.WAITING_FOR_HUMAN
        assert current.pending_gate_id == GATE_1
        assert current.checkpoint_sequence == 2

    asyncio.run(scenario())


def test_progression_rejects_stale_state_and_illegal_stage_without_persistence(environment):
    async def scenario() -> None:
        env = environment
        await create_draft(env)

        env.clock.at(1)
        stale = await apply_with_event_sequence(
            env,
            env.service.start_run(
                owner_user_id=OWNER,
                run_id=RUN,
                command=start_command(version=99, sequence=0, command_id=13200),
            ),
        )
        assert stale.status is sut.WorkflowRunApiStatus.STATE_CONFLICT
        assert await env.runs.list_checkpoints(run_id=RUN) == ()
        assert await env.events.list_after(run_id=RUN) == ()

        valid = await apply_with_event_sequence(
            env,
            env.service.start_run(
                owner_user_id=OWNER,
                run_id=RUN,
                command=start_command(version=1, sequence=0, command_id=13201),
            ),
        )
        assert valid.status is sut.WorkflowRunApiStatus.COMMAND_APPLIED

        env.clock.at(2)
        illegal = await apply_with_event_sequence(
            env,
            env.service.advance_run(
                owner_user_id=OWNER,
                run_id=RUN,
                command=advance_command(
                    version=2,
                    sequence=1,
                    command_id=13202,
                    stage=WorkflowStage.REQUIREMENTS,
                ),
            ),
        )
        assert illegal.status is sut.WorkflowRunApiStatus.ILLEGAL_STATE
        current = await env.runs.get_owned(run_id=RUN)
        assert current is not None
        assert current.current_stage is WorkflowStage.INTAKE
        assert current.checkpoint_sequence == 1

    asyncio.run(scenario())
