"""Durable LangGraph driver for explicit workflow progression commands.

The public API owns application-level optimistic concurrency, human-gate
authorization, application checkpoints, and workflow events. This module owns
only the LangGraph execution/checkpoint side of start, advance, and exact gate
resume operations.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from orchestwin.workflow.langgraph_checkpointer import (
    LangGraphCheckpointStore,
    RunScopedLangGraphCheckpointer,
    reconcile_checkpoint_with_authoritative_run,
)
from orchestwin.workflow.langgraph_graph import (
    GovernedWorkflowState,
    WorkflowGraphStep,
    WorkflowGraphStepKind,
    build_governed_workflow_graph,
    create_workflow_gate_resume_command,
)
from orchestwin.workflow.runs import WorkflowRun, WorkflowStage


class WorkflowGraphStateConflict(RuntimeError):
    """The persisted LangGraph state cannot be reconciled with the application run."""


class WorkflowGraphExecutionConflict(RuntimeError):
    """LangGraph produced a result inconsistent with the requested governed command."""


@dataclass(frozen=True, slots=True)
class WorkflowGraphProgressionResult:
    """Observed result of one durable LangGraph progression invocation."""

    run: WorkflowRun
    transition_status: str
    transition_issue: str | None
    interrupt_id: str | None = None
    applied_decision_id: UUID | None = None


class DurableWorkflowGraphProgression:
    """Run the governed graph against one owner-scoped durable checkpoint store."""

    def __init__(self, store: LangGraphCheckpointStore) -> None:
        self._store = store

    async def start(
        self,
        *,
        run: WorkflowRun,
        occurred_at: datetime,
    ) -> WorkflowGraphProgressionResult:
        """Start a draft run through the LangGraph START node exactly once."""
        checkpointer = self._checkpointer(run)
        config = self._thread_config(run.id)
        if await checkpointer.aget_tuple(config) is not None:
            raise WorkflowGraphStateConflict(
                "draft workflow already has LangGraph checkpoint state"
            )

        graph = build_governed_workflow_graph(checkpointer=checkpointer)
        output = await graph.ainvoke(
            {
                "run": run,
                "step": WorkflowGraphStep(
                    kind=WorkflowGraphStepKind.START,
                    occurred_at=occurred_at,
                ),
                "trace": (),
            },
            config=config,
        )
        return self._result(output)

    async def advance(
        self,
        *,
        run: WorkflowRun,
        next_stage: WorkflowStage,
        pending_gate_id: UUID | None,
        occurred_at: datetime,
    ) -> WorkflowGraphProgressionResult:
        """Advance one legal edge through the recovered durable LangGraph state."""
        graph, config, _checkpointer = await self._recovered_graph(run)
        output = await graph.ainvoke(
            {
                "run": run,
                "step": WorkflowGraphStep(
                    kind=WorkflowGraphStepKind.ADVANCE,
                    occurred_at=occurred_at,
                    next_stage=next_stage,
                    pending_gate_id=pending_gate_id,
                ),
                "trace": (),
            },
            config=config,
        )
        interrupt_id = None
        if pending_gate_id is not None:
            interrupt_id = self._interrupt_id_from_output(
                output,
                gate_id=pending_gate_id,
            )
            if interrupt_id is None:
                raise WorkflowGraphExecutionConflict(
                    "human-gate advance did not create the expected LangGraph interrupt"
                )
        elif self._all_interrupts(output):
            raise WorkflowGraphExecutionConflict(
                "non-gate advance unexpectedly created a LangGraph interrupt"
            )

        result = self._result(output)
        return WorkflowGraphProgressionResult(
            run=result.run,
            transition_status=result.transition_status,
            transition_issue=result.transition_issue,
            interrupt_id=interrupt_id,
            applied_decision_id=result.applied_decision_id,
        )

    async def resume_gate(
        self,
        *,
        run: WorkflowRun,
        gate_id: UUID,
        decision_id: UUID,
        occurred_at: datetime,
    ) -> WorkflowGraphProgressionResult:
        """Resume the one persisted interrupt bound to an approved human gate."""
        graph, config, checkpointer = await self._recovered_graph(run)
        checkpoint = await checkpointer.aget_tuple(config)
        if checkpoint is None:
            raise WorkflowGraphStateConflict(
                "workflow human-gate resume has no durable graph checkpoint"
            )
        interrupt_id = self._interrupt_id_from_pending_writes(
            checkpoint.pending_writes,
            gate_id=gate_id,
        )
        if interrupt_id is None:
            raise WorkflowGraphStateConflict(
                "workflow human-gate resume has no matching durable interrupt"
            )

        output = await graph.ainvoke(
            create_workflow_gate_resume_command(
                interrupt_id=interrupt_id,
                gate_id=gate_id,
                decision_id=decision_id,
                decision_applied=True,
                occurred_at=occurred_at,
            ),
            config=config,
        )
        result = self._result(output)
        if result.applied_decision_id != decision_id:
            raise WorkflowGraphExecutionConflict(
                "LangGraph resume did not preserve the approved decision identity"
            )
        if self._all_interrupts(output):
            raise WorkflowGraphExecutionConflict(
                "approved human-gate resume left an unexpected interrupt"
            )
        return result

    async def _recovered_graph(
        self,
        run: WorkflowRun,
    ) -> tuple[
        CompiledStateGraph[
            GovernedWorkflowState,
            None,
            GovernedWorkflowState,
            GovernedWorkflowState,
        ],
        RunnableConfig,
        RunScopedLangGraphCheckpointer,
    ]:
        raw = self._checkpointer(run)
        requested = self._thread_config(run.id)
        checkpoint = await raw.aget_tuple(requested)
        if checkpoint is None:
            raise WorkflowGraphStateConflict(
                "application workflow checkpoint has no LangGraph counterpart"
            )
        try:
            reconcile_checkpoint_with_authoritative_run(
                checkpoint.checkpoint,
                authoritative_run=run,
            )
        except ValueError as error:
            raise WorkflowGraphStateConflict(
                "application and LangGraph workflow state diverged"
            ) from error

        configurable = checkpoint.config.get("configurable")
        if not isinstance(configurable, Mapping):
            raise WorkflowGraphStateConflict(
                "LangGraph checkpoint does not expose configurable identity"
            )
        checkpoint_id = configurable.get("checkpoint_id")
        if not isinstance(checkpoint_id, str) or not checkpoint_id:
            raise WorkflowGraphStateConflict("LangGraph checkpoint identity is missing")

        authoritative = self._checkpointer(
            run,
            authoritative_run=run,
            authoritative_checkpoint_id=checkpoint_id,
        )
        graph = build_governed_workflow_graph(checkpointer=authoritative)
        return graph, checkpoint.config, authoritative

    def _checkpointer(
        self,
        run: WorkflowRun,
        *,
        authoritative_run: WorkflowRun | None = None,
        authoritative_checkpoint_id: str | None = None,
    ) -> RunScopedLangGraphCheckpointer:
        return RunScopedLangGraphCheckpointer(
            self._store,
            run_id=run.id,
            project_id=run.project_id,
            owner_user_id=run.owner_user_id,
            authoritative_run=authoritative_run,
            authoritative_checkpoint_id=authoritative_checkpoint_id,
        )

    @staticmethod
    def _thread_config(run_id: UUID) -> RunnableConfig:
        return {
            "configurable": {
                "thread_id": str(run_id),
                "checkpoint_ns": "",
            }
        }

    @classmethod
    def _result(cls, output: Mapping[str, Any]) -> WorkflowGraphProgressionResult:
        run = output.get("run")
        transition_status = output.get("transition_status")
        transition_issue = output.get("transition_issue")
        if not isinstance(run, WorkflowRun):
            raise WorkflowGraphExecutionConflict(
                "LangGraph progression did not return a typed workflow run"
            )
        if not isinstance(transition_status, str) or not transition_status:
            raise WorkflowGraphExecutionConflict(
                "LangGraph progression did not return a transition status"
            )
        if transition_issue is not None and not isinstance(transition_issue, str):
            raise WorkflowGraphExecutionConflict(
                "LangGraph progression returned an invalid transition issue"
            )

        raw_decision = output.get("applied_decision_id")
        applied_decision_id = None
        if raw_decision is not None:
            try:
                applied_decision_id = UUID(str(raw_decision))
            except ValueError as error:
                raise WorkflowGraphExecutionConflict(
                    "LangGraph progression returned an invalid decision identity"
                ) from error

        return WorkflowGraphProgressionResult(
            run=run,
            transition_status=transition_status,
            transition_issue=transition_issue,
            applied_decision_id=applied_decision_id,
        )

    @classmethod
    def _interrupt_id_from_output(
        cls,
        output: Mapping[str, Any],
        *,
        gate_id: UUID,
    ) -> str | None:
        matches = [
            interrupt_id
            for interrupt_id, value in cls._all_interrupts(output)
            if cls._interrupt_matches_gate(value, gate_id)
        ]
        return matches[0] if len(matches) == 1 else None

    @classmethod
    def _interrupt_id_from_pending_writes(
        cls,
        pending_writes: list[tuple[str, str, Any]],
        *,
        gate_id: UUID,
    ) -> str | None:
        matches: list[str] = []
        for _task_id, channel, value in pending_writes:
            if channel != "__interrupt__":
                continue
            for interrupt in cls._flatten_interrupt_values(value):
                interrupt_id = getattr(interrupt, "id", None)
                interrupt_value = getattr(interrupt, "value", None)
                if (
                    isinstance(interrupt_id, str)
                    and interrupt_id
                    and cls._interrupt_matches_gate(interrupt_value, gate_id)
                ):
                    matches.append(interrupt_id)
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _flatten_interrupt_values(value: Any) -> tuple[Any, ...]:
        if isinstance(value, (tuple, list)):
            return tuple(value)
        return (value,)

    @classmethod
    def _all_interrupts(
        cls,
        output: Mapping[str, Any],
    ) -> tuple[tuple[str, Any], ...]:
        raw = output.get("__interrupt__", ())
        interrupts: list[tuple[str, Any]] = []
        for interrupt in cls._flatten_interrupt_values(raw):
            interrupt_id = getattr(interrupt, "id", None)
            interrupt_value = getattr(interrupt, "value", None)
            if isinstance(interrupt_id, str) and interrupt_id:
                interrupts.append((interrupt_id, interrupt_value))
        return tuple(interrupts)

    @staticmethod
    def _interrupt_matches_gate(value: Any, gate_id: UUID) -> bool:
        return isinstance(value, Mapping) and value.get("gate_id") == str(gate_id)
