"""Tests for idempotent pause, resume, and cancel workflow commands."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from orchestwin.projects.domain import ProjectMode
from orchestwin.workflow.commands import (
    WorkflowLifecycleCommand,
    WorkflowLifecycleCommandKind,
    WorkflowLifecycleCommandService,
    WorkflowLifecycleCommandStatus,
    apply_workflow_lifecycle_command,
)
from orchestwin.workflow.routing import start_workflow_run
from orchestwin.workflow.run_persistence import InMemoryWorkflowRunRepository
from orchestwin.workflow.runs import (
    WorkflowBlockingIssue,
    WorkflowBlockingIssueSource,
    WorkflowRunStatus,
    create_workflow_run,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000010501")
OWNER_ID = UUID("00000000-0000-4000-8000-000000010502")
RUN_ID = UUID("00000000-0000-4000-8000-000000010503")
COMMAND_ID = UUID("00000000-0000-4000-8000-000000010504")
NOW = datetime(2026, 8, 28, 22, 50, tzinfo=UTC)


def running_run():
    draft = create_workflow_run(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        run_id=RUN_ID,
        created_at=NOW,
    )
    return start_workflow_run(draft, occurred_at=NOW + timedelta(seconds=1)).run


def command(
    run,
    *,
    kind: WorkflowLifecycleCommandKind,
    offset: int,
    authorization_reference: UUID | None = None,
):
    return WorkflowLifecycleCommand(
        command_id=COMMAND_ID,
        run_id=run.id,
        project_id=run.project_id,
        owner_user_id=run.owner_user_id,
        kind=kind,
        expected_state_version=run.state_version,
        expected_checkpoint_sequence=run.checkpoint_sequence,
        occurred_at=NOW + timedelta(seconds=offset),
        reason="Owner lifecycle command.",
        authorization_reference=authorization_reference,
    )


def test_pause_and_cancel_transitions_preserve_run_invariants() -> None:
    run = running_run()
    paused = apply_workflow_lifecycle_command(
        run,
        command(run, kind=WorkflowLifecycleCommandKind.PAUSE, offset=2),
    )
    cancelled = apply_workflow_lifecycle_command(
        paused.run,
        command(paused.run, kind=WorkflowLifecycleCommandKind.CANCEL, offset=3),
    )

    assert paused.status is WorkflowLifecycleCommandStatus.APPLIED
    assert paused.run.status is WorkflowRunStatus.PAUSED
    assert paused.run.resume_status is WorkflowRunStatus.RUNNING
    assert cancelled.run.status is WorkflowRunStatus.CANCELLED
    assert cancelled.run.completed_at == NOW + timedelta(seconds=3)


def test_repeated_command_is_idempotent_before_stale_version_rejection() -> None:
    run = running_run()
    pause_command = command(run, kind=WorkflowLifecycleCommandKind.PAUSE, offset=2)
    paused = apply_workflow_lifecycle_command(run, pause_command)
    repeated = apply_workflow_lifecycle_command(paused.run, pause_command)

    assert repeated.status is WorkflowLifecycleCommandStatus.ALREADY_APPLIED
    assert repeated.run == paused.run


def test_operational_limit_resume_requires_explicit_authorization() -> None:
    run = running_run()
    blocked = replace(
        run,
        status=WorkflowRunStatus.PAUSED_NEEDS_HUMAN,
        resume_status=WorkflowRunStatus.RUNNING,
        blocking_issues=(
            WorkflowBlockingIssue(
                code="BUDGET_LIMIT",
                source=WorkflowBlockingIssueSource.OPERATIONAL_LIMIT,
                summary="The project budget is exhausted.",
                recoverable=True,
            ),
        ),
    )
    denied = apply_workflow_lifecycle_command(
        blocked,
        command(blocked, kind=WorkflowLifecycleCommandKind.RESUME, offset=2),
    )
    allowed = apply_workflow_lifecycle_command(
        blocked,
        command(
            blocked,
            kind=WorkflowLifecycleCommandKind.RESUME,
            offset=2,
            authorization_reference=UUID("00000000-0000-4000-8000-000000010505"),
        ),
    )

    assert denied.status is WorkflowLifecycleCommandStatus.AUTHORIZATION_REQUIRED
    assert allowed.status is WorkflowLifecycleCommandStatus.APPLIED
    assert allowed.run.status is WorkflowRunStatus.RUNNING
    assert allowed.run.blocking_issues == ()


def test_service_checkpoints_commands_and_rejects_stale_concurrency() -> None:
    async def scenario() -> None:
        run = running_run()
        repository = InMemoryWorkflowRunRepository(
            owner_user_id=OWNER_ID,
            project_ids=frozenset({PROJECT_ID}),
        )
        assert (await repository.create(run)).run == run
        service = WorkflowLifecycleCommandService(repository)

        pause_command = command(run, kind=WorkflowLifecycleCommandKind.PAUSE, offset=2)
        paused = await service.execute(pause_command)
        repeated = await service.execute(pause_command)
        current = await repository.get_owned(run_id=RUN_ID)
        resume_command = command(
            current,
            kind=WorkflowLifecycleCommandKind.RESUME,
            offset=3,
        )
        resumed = await service.execute(resume_command)

        assert paused.status is WorkflowLifecycleCommandStatus.APPLIED
        assert repeated.status is WorkflowLifecycleCommandStatus.ALREADY_APPLIED
        assert resumed.status is WorkflowLifecycleCommandStatus.APPLIED
        assert len(await repository.list_checkpoints(run_id=RUN_ID)) == 2

    asyncio.run(scenario())


def test_cross_owner_command_is_not_disclosed() -> None:
    run = running_run()
    foreign = replace(
        command(run, kind=WorkflowLifecycleCommandKind.CANCEL, offset=2),
        owner_user_id=UUID("00000000-0000-4000-8000-000000010599"),
    )

    result = apply_workflow_lifecycle_command(run, foreign)

    assert result.status is WorkflowLifecycleCommandStatus.RUN_NOT_FOUND
    assert result.run is None
