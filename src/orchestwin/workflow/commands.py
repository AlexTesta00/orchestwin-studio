"""Idempotent owner-scoped pause, resume, and cancel workflow commands."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from orchestwin.projects.requirements_primitives import normalize_optional_text
from orchestwin.workflow.checkpoints import create_workflow_checkpoint
from orchestwin.workflow.run_persistence import (
    WorkflowRunRepository,
    WorkflowRunStoreStatus,
)
from orchestwin.workflow.runs import WorkflowRun, WorkflowRunStatus


class WorkflowLifecycleCommandKind(StrEnum):
    """Public lifecycle operations accepted by the workflow application layer."""

    PAUSE = "PAUSE"
    RESUME = "RESUME"
    CANCEL = "CANCEL"


class WorkflowLifecycleCommandStatus(StrEnum):
    """Owner-safe deterministic result of one lifecycle command."""

    APPLIED = "APPLIED"
    ALREADY_APPLIED = "ALREADY_APPLIED"
    RUN_NOT_FOUND = "RUN_NOT_FOUND"
    STATE_CONFLICT = "STATE_CONFLICT"
    ILLEGAL_STATE = "ILLEGAL_STATE"
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"


@dataclass(frozen=True, slots=True)
class WorkflowLifecycleCommand:
    """One explicit lifecycle command bound to exact expected run state."""

    command_id: UUID
    run_id: UUID
    project_id: UUID
    owner_user_id: UUID
    kind: WorkflowLifecycleCommandKind
    expected_state_version: int
    expected_checkpoint_sequence: int
    occurred_at: datetime
    reason: str | None = None
    authorization_reference: UUID | None = None

    def __post_init__(self) -> None:
        if self.expected_state_version < 1:
            raise ValueError("workflow command expected state version must be positive")
        if self.expected_checkpoint_sequence < 0:
            raise ValueError("workflow command checkpoint sequence must not be negative")
        if self.occurred_at.tzinfo is None:
            raise ValueError("workflow command timestamp must be timezone-aware")
        normalized_reason = normalize_optional_text(
            self.reason,
            label="workflow command reason",
            maximum_length=2000,
        )
        if normalized_reason != self.reason:
            raise ValueError("workflow command reason must be normalized")
        if self.kind is not WorkflowLifecycleCommandKind.RESUME and (
            self.authorization_reference is not None
        ):
            raise ValueError("only resume commands may include an authorization reference")


@dataclass(frozen=True, slots=True)
class WorkflowLifecycleCommandResult:
    """Command result containing state only when it remains owner-visible."""

    status: WorkflowLifecycleCommandStatus
    run: WorkflowRun | None
    command_id: UUID

    def __post_init__(self) -> None:
        visible = self.status in {
            WorkflowLifecycleCommandStatus.APPLIED,
            WorkflowLifecycleCommandStatus.ALREADY_APPLIED,
            WorkflowLifecycleCommandStatus.STATE_CONFLICT,
            WorkflowLifecycleCommandStatus.ILLEGAL_STATE,
            WorkflowLifecycleCommandStatus.AUTHORIZATION_REQUIRED,
        }
        if visible != (self.run is not None):
            raise ValueError("workflow command result shape is inconsistent")


def apply_workflow_lifecycle_command(
    run: WorkflowRun,
    command: WorkflowLifecycleCommand,
) -> WorkflowLifecycleCommandResult:
    """Apply a lifecycle transition without persistence or hidden retries."""
    if (
        command.run_id != run.id
        or command.project_id != run.project_id
        or command.owner_user_id != run.owner_user_id
    ):
        return _result(WorkflowLifecycleCommandStatus.RUN_NOT_FOUND, None, command)

    idempotent = _idempotent_result(run, command)
    if idempotent is not None:
        return idempotent

    if (
        command.expected_state_version != run.state_version
        or command.expected_checkpoint_sequence != run.checkpoint_sequence
    ):
        return _result(WorkflowLifecycleCommandStatus.STATE_CONFLICT, run, command)
    if command.occurred_at < run.updated_at:
        return _result(WorkflowLifecycleCommandStatus.STATE_CONFLICT, run, command)

    if command.kind is WorkflowLifecycleCommandKind.PAUSE:
        return _pause(run, command)
    if command.kind is WorkflowLifecycleCommandKind.RESUME:
        return _resume(run, command)
    if command.kind is WorkflowLifecycleCommandKind.CANCEL:
        return _cancel(run, command)
    raise ValueError("unsupported workflow lifecycle command")


class WorkflowLifecycleCommandService:
    """Persist lifecycle commands through checkpointed compare-and-set updates."""

    def __init__(self, repository: WorkflowRunRepository) -> None:
        self._repository = repository

    async def execute(
        self,
        command: WorkflowLifecycleCommand,
    ) -> WorkflowLifecycleCommandResult:
        """Load, transition, checkpoint, and save exactly once."""
        current = await self._repository.get_owned(run_id=command.run_id)
        if current is None or (
            current.project_id != command.project_id
            or current.owner_user_id != command.owner_user_id
        ):
            return _result(WorkflowLifecycleCommandStatus.RUN_NOT_FOUND, None, command)

        transition = apply_workflow_lifecycle_command(current, command)
        if transition.status is not WorkflowLifecycleCommandStatus.APPLIED:
            return transition
        if transition.run is None:
            raise AssertionError("applied workflow command must contain updated state")

        history = await self._repository.list_checkpoints(run_id=current.id)
        previous_checkpoint = None if not history else history[-1]
        creation = create_workflow_checkpoint(
            transition.run,
            created_at=command.occurred_at,
            previous_checkpoint=previous_checkpoint,
        )
        stored = await self._repository.save_checkpoint(
            previous_run=current,
            creation=creation,
        )
        if stored.status is not WorkflowRunStoreStatus.UPDATED or stored.run is None:
            return _result(WorkflowLifecycleCommandStatus.STATE_CONFLICT, current, command)
        return _result(WorkflowLifecycleCommandStatus.APPLIED, stored.run, command)


def _idempotent_result(
    run: WorkflowRun,
    command: WorkflowLifecycleCommand,
) -> WorkflowLifecycleCommandResult | None:
    desired_states = {
        WorkflowLifecycleCommandKind.PAUSE: {
            WorkflowRunStatus.PAUSED,
            WorkflowRunStatus.PAUSED_NEEDS_HUMAN,
        },
        WorkflowLifecycleCommandKind.RESUME: {
            WorkflowRunStatus.RUNNING,
            WorkflowRunStatus.WAITING_FOR_HUMAN,
        },
        WorkflowLifecycleCommandKind.CANCEL: {WorkflowRunStatus.CANCELLED},
    }
    if run.status in desired_states[command.kind]:
        return _result(WorkflowLifecycleCommandStatus.ALREADY_APPLIED, run, command)
    return None


def _pause(
    run: WorkflowRun,
    command: WorkflowLifecycleCommand,
) -> WorkflowLifecycleCommandResult:
    if run.status not in {
        WorkflowRunStatus.RUNNING,
        WorkflowRunStatus.WAITING_FOR_HUMAN,
    }:
        return _result(WorkflowLifecycleCommandStatus.ILLEGAL_STATE, run, command)
    paused = replace(
        run,
        status=WorkflowRunStatus.PAUSED,
        resume_status=run.status,
        state_version=run.state_version + 1,
        updated_at=command.occurred_at,
    )
    return _result(WorkflowLifecycleCommandStatus.APPLIED, paused, command)


def _resume(
    run: WorkflowRun,
    command: WorkflowLifecycleCommand,
) -> WorkflowLifecycleCommandResult:
    if run.status not in {
        WorkflowRunStatus.PAUSED,
        WorkflowRunStatus.PAUSED_NEEDS_HUMAN,
    }:
        return _result(WorkflowLifecycleCommandStatus.ILLEGAL_STATE, run, command)
    if run.status is WorkflowRunStatus.PAUSED_NEEDS_HUMAN and (
        command.authorization_reference is None
    ):
        return _result(
            WorkflowLifecycleCommandStatus.AUTHORIZATION_REQUIRED,
            run,
            command,
        )
    if run.resume_status is None:
        raise ValueError("paused workflow run is missing its resume status")
    resumed = replace(
        run,
        status=run.resume_status,
        resume_status=None,
        blocking_issues=(),
        state_version=run.state_version + 1,
        updated_at=command.occurred_at,
    )
    return _result(WorkflowLifecycleCommandStatus.APPLIED, resumed, command)


def _cancel(
    run: WorkflowRun,
    command: WorkflowLifecycleCommand,
) -> WorkflowLifecycleCommandResult:
    if run.status in {
        WorkflowRunStatus.FAILED,
        WorkflowRunStatus.APPROVED,
    }:
        return _result(WorkflowLifecycleCommandStatus.ILLEGAL_STATE, run, command)
    cancelled = replace(
        run,
        status=WorkflowRunStatus.CANCELLED,
        resume_status=None,
        pending_gate_id=None,
        blocking_issues=(),
        completed_at=command.occurred_at,
        started_at=run.started_at or command.occurred_at,
        state_version=run.state_version + 1,
        updated_at=command.occurred_at,
    )
    return _result(WorkflowLifecycleCommandStatus.APPLIED, cancelled, command)


def _result(
    status: WorkflowLifecycleCommandStatus,
    run: WorkflowRun | None,
    command: WorkflowLifecycleCommand,
) -> WorkflowLifecycleCommandResult:
    return WorkflowLifecycleCommandResult(
        status=status,
        run=run,
        command_id=command.command_id,
    )
