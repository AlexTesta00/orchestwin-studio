"""Recovery assessment for application and LangGraph workflow checkpoints."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import CheckpointTuple

from orchestwin.workflow.checkpoints import (
    WorkflowCheckpointRestoreStatus,
    restore_workflow_checkpoint,
    workflow_run_content_hash,
)
from orchestwin.workflow.langgraph_checkpointer import (
    reconcile_checkpoint_with_authoritative_run,
)
from orchestwin.workflow.run_persistence import WorkflowRunRepository
from orchestwin.workflow.runs import WorkflowRun


class AsyncCheckpointReader(Protocol):
    """Minimal graph-checkpointer surface required by recovery assessment."""

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None: ...


class WorkflowRecoveryStatus(StrEnum):
    """Inspectable result of reconciling durable workflow recovery state."""

    READY = "READY"
    RUN_NOT_FOUND = "RUN_NOT_FOUND"
    APPLICATION_CHECKPOINT_MISSING = "APPLICATION_CHECKPOINT_MISSING"
    APPLICATION_CHECKPOINT_INVALID = "APPLICATION_CHECKPOINT_INVALID"
    GRAPH_CHECKPOINT_MISSING = "GRAPH_CHECKPOINT_MISSING"
    GRAPH_CHECKPOINT_SCOPE_MISMATCH = "GRAPH_CHECKPOINT_SCOPE_MISMATCH"
    GRAPH_CHECKPOINT_STATE_MISMATCH = "GRAPH_CHECKPOINT_STATE_MISMATCH"


@dataclass(frozen=True, slots=True)
class WorkflowRecoveryResult:
    """Recovery result exposing state only after every durable check succeeds."""

    status: WorkflowRecoveryStatus
    run: WorkflowRun | None = None
    graph_config: RunnableConfig | None = None
    issue: str | None = None

    def __post_init__(self) -> None:
        ready = self.status is WorkflowRecoveryStatus.READY
        if ready != (self.run is not None and self.graph_config is not None):
            raise ValueError("workflow recovery result shape is inconsistent")
        if ready == (self.issue is not None):
            raise ValueError("workflow recovery issue is inconsistent with status")


class WorkflowRecoveryService:
    """Validate application and graph checkpoints before process restart recovery."""

    def __init__(
        self,
        repository: WorkflowRunRepository,
        graph_checkpointer: AsyncCheckpointReader,
    ) -> None:
        self._repository = repository
        self._graph_checkpointer = graph_checkpointer

    async def assess(self, *, run_id: UUID) -> WorkflowRecoveryResult:
        current = await self._repository.get_owned(run_id=run_id)
        if current is None:
            return _recovery_failure(
                WorkflowRecoveryStatus.RUN_NOT_FOUND,
                "workflow run is not visible to the authenticated owner",
            )

        checkpoints = await self._repository.list_checkpoints(run_id=run_id)
        if not checkpoints:
            return _recovery_failure(
                WorkflowRecoveryStatus.APPLICATION_CHECKPOINT_MISSING,
                "workflow run has no application checkpoint",
            )
        latest = max(checkpoints, key=lambda item: item.sequence_number)
        restored = restore_workflow_checkpoint(
            latest,
            expected_run_id=current.id,
            expected_project_id=current.project_id,
            expected_owner_user_id=current.owner_user_id,
            minimum_state_version=current.state_version,
        )
        if (
            restored.status is not WorkflowCheckpointRestoreStatus.RESTORED
            or restored.run is None
            or workflow_run_content_hash(restored.run) != workflow_run_content_hash(current)
        ):
            return _recovery_failure(
                WorkflowRecoveryStatus.APPLICATION_CHECKPOINT_INVALID,
                f"application checkpoint cannot restore current state: {restored.status.value}",
            )

        requested_config: RunnableConfig = {
            "configurable": {
                "thread_id": str(current.id),
                "checkpoint_ns": "",
            }
        }
        try:
            graph_checkpoint = await self._graph_checkpointer.aget_tuple(requested_config)
        except ValueError:
            return _recovery_failure(
                WorkflowRecoveryStatus.GRAPH_CHECKPOINT_SCOPE_MISMATCH,
                "LangGraph checkpoint is not bound to the owned workflow run",
            )
        if graph_checkpoint is None:
            return _recovery_failure(
                WorkflowRecoveryStatus.GRAPH_CHECKPOINT_MISSING,
                "workflow run has no LangGraph checkpoint",
            )

        configurable = graph_checkpoint.config.get("configurable", {})
        if configurable.get("thread_id") != str(current.id):
            return _recovery_failure(
                WorkflowRecoveryStatus.GRAPH_CHECKPOINT_SCOPE_MISMATCH,
                "LangGraph checkpoint thread does not match workflow run",
            )
        try:
            reconcile_checkpoint_with_authoritative_run(
                graph_checkpoint.checkpoint,
                authoritative_run=current,
            )
        except ValueError:
            return _recovery_failure(
                WorkflowRecoveryStatus.GRAPH_CHECKPOINT_STATE_MISMATCH,
                "LangGraph checkpoint state does not match application state",
            )
        return WorkflowRecoveryResult(
            status=WorkflowRecoveryStatus.READY,
            run=current,
            graph_config=graph_checkpoint.config,
        )


def _recovery_failure(
    status: WorkflowRecoveryStatus,
    issue: str,
) -> WorkflowRecoveryResult:
    return WorkflowRecoveryResult(status=status, issue=issue)
