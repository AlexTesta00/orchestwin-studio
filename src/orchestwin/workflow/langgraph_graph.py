"""Explicit LangGraph shell around deterministic workflow-domain transitions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated, NotRequired, TypedDict, cast
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Checkpointer, Command, interrupt

from orchestwin.workflow.routing import (
    WorkflowTransitionResult,
    WorkflowTransitionStatus,
    advance_workflow_run,
    resume_after_human_gate,
    start_workflow_run,
)
from orchestwin.workflow.runs import (
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowStage,
)


class WorkflowGraphStepKind(StrEnum):
    """Deterministic operation requested from one graph invocation."""

    START = "START"
    ADVANCE = "ADVANCE"


class WorkflowGraphIssueCode(StrEnum):
    """Graph-shell errors that do not belong to domain routing."""

    INVALID_STEP = "INVALID_STEP"
    INVALID_RESUME_PAYLOAD = "INVALID_RESUME_PAYLOAD"
    GATE_ID_MISMATCH = "GATE_ID_MISMATCH"
    HUMAN_DECISION_NOT_APPLIED = "HUMAN_DECISION_NOT_APPLIED"


@dataclass(frozen=True, slots=True)
class WorkflowGraphStep:
    """One explicit, side-effect-free workflow transition request."""

    kind: WorkflowGraphStepKind
    occurred_at: datetime
    next_stage: WorkflowStage | None = None
    pending_gate_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None:
            raise ValueError("workflow graph step timestamp must be timezone-aware")
        if self.kind is WorkflowGraphStepKind.START:
            if self.next_stage is not None or self.pending_gate_id is not None:
                raise ValueError("start graph step cannot include stage or gate data")
        elif self.kind is WorkflowGraphStepKind.ADVANCE:
            if self.next_stage is None:
                raise ValueError("advance graph step requires a next stage")
        else:
            raise ValueError("unsupported workflow graph step kind")


@dataclass(frozen=True, slots=True)
class WorkflowGateResume:
    """Validated acknowledgement that the exact gate decision was applied externally."""

    gate_id: UUID
    decision_id: UUID
    decision_applied: bool
    occurred_at: datetime

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None:
            raise ValueError("workflow gate resume timestamp must be timezone-aware")

    def to_interrupt_value(self) -> dict[str, object]:
        """Return the narrow business payload supplied to one exact interrupt."""
        return {
            "gate_id": str(self.gate_id),
            "decision_id": str(self.decision_id),
            "decision_applied": self.decision_applied,
            "occurred_at": self.occurred_at.isoformat(),
        }

    @classmethod
    def from_interrupt_value(cls, value: object) -> WorkflowGateResume:
        """Parse the narrow public resume payload returned through LangGraph."""
        if not isinstance(value, Mapping):
            raise ValueError("workflow gate resume payload must be an object")

        expected = {"gate_id", "decision_id", "decision_applied", "occurred_at"}
        if set(value) != expected:
            raise ValueError("workflow gate resume payload has unexpected fields")

        try:
            gate_id = UUID(str(value["gate_id"]))
            decision_id = UUID(str(value["decision_id"]))
            decision_applied = value["decision_applied"]
            occurred_at = datetime.fromisoformat(str(value["occurred_at"]))
        except (TypeError, ValueError) as error:
            raise ValueError("workflow gate resume payload is invalid") from error

        if not isinstance(decision_applied, bool):
            raise ValueError("workflow gate resume decision_applied must be boolean")

        return cls(
            gate_id=gate_id,
            decision_id=decision_id,
            decision_applied=decision_applied,
            occurred_at=occurred_at,
        )


def create_workflow_gate_resume_command(
    *,
    interrupt_id: str,
    gate_id: UUID,
    decision_id: UUID,
    decision_applied: bool,
    occurred_at: datetime,
) -> Command:
    """Target one recorded LangGraph interrupt with one validated gate payload."""
    if not interrupt_id or interrupt_id.strip() != interrupt_id:
        raise ValueError("workflow interrupt ID must be a non-empty normalized string")

    resume = WorkflowGateResume(
        gate_id=gate_id,
        decision_id=decision_id,
        decision_applied=decision_applied,
        occurred_at=occurred_at,
    )
    return Command(resume={interrupt_id: resume.to_interrupt_value()})


class WorkflowInterruptEnvelope(TypedDict):
    """Public, reasoning-free payload emitted at a human interrupt."""

    kind: str
    run_id: str
    project_id: str
    gate_id: str
    stage: str
    state_version: int


class GovernedWorkflowState(TypedDict):
    """Typed graph state containing durable domain state and one requested step."""

    run: WorkflowRun
    step: WorkflowGraphStep
    trace: Annotated[tuple[str, ...], _append_trace]
    transition_status: NotRequired[str]
    transition_issue: NotRequired[str | None]
    applied_decision_id: NotRequired[str | None]


def _append_trace(
    current: Sequence[str],
    update: Sequence[str] | None,
) -> tuple[str, ...]:
    """Append explicit node names without mutating prior graph state."""
    if update is None:
        return tuple(current)
    return (*current, *update)


def apply_workflow_graph_step(
    run: WorkflowRun,
    step: WorkflowGraphStep,
) -> WorkflowTransitionResult:
    """Apply one graph command through the deterministic domain functions."""
    if step.kind is WorkflowGraphStepKind.START:
        return start_workflow_run(run, occurred_at=step.occurred_at)
    if step.kind is WorkflowGraphStepKind.ADVANCE and step.next_stage is not None:
        return advance_workflow_run(
            run,
            next_stage=step.next_stage,
            occurred_at=step.occurred_at,
            pending_gate_id=step.pending_gate_id,
        )
    raise ValueError(WorkflowGraphIssueCode.INVALID_STEP.value)


def _apply_step_node(state: GovernedWorkflowState) -> dict[str, object]:
    result = apply_workflow_graph_step(state["run"], state["step"])
    return {
        "run": result.run,
        "transition_status": result.status.value,
        "transition_issue": result.issue.value if result.issue is not None else None,
        "applied_decision_id": None,
        "trace": ("apply_step",),
    }


def _route_after_step(state: GovernedWorkflowState) -> str:
    if state.get("transition_status") != WorkflowTransitionStatus.APPLIED.value:
        return "end"
    if state["run"].status is WorkflowRunStatus.WAITING_FOR_HUMAN:
        return "wait_for_human"
    return "end"


def _interrupt_envelope(run: WorkflowRun) -> WorkflowInterruptEnvelope:
    if run.pending_gate_id is None:
        raise ValueError("waiting workflow run requires a pending gate")
    return {
        "kind": "workflow.human_gate.required",
        "run_id": str(run.id),
        "project_id": str(run.project_id),
        "gate_id": str(run.pending_gate_id),
        "stage": run.current_stage.value,
        "state_version": run.state_version,
    }


def _wait_for_human_node(state: GovernedWorkflowState) -> dict[str, object]:
    run = state["run"]
    expected_gate_id = run.pending_gate_id
    raw_resume = interrupt(_interrupt_envelope(run))

    try:
        resume = WorkflowGateResume.from_interrupt_value(raw_resume)
    except ValueError:
        return {
            "transition_status": WorkflowTransitionStatus.REJECTED.value,
            "transition_issue": WorkflowGraphIssueCode.INVALID_RESUME_PAYLOAD.value,
            "trace": ("wait_for_human",),
        }

    if resume.gate_id != expected_gate_id:
        return {
            "transition_status": WorkflowTransitionStatus.REJECTED.value,
            "transition_issue": WorkflowGraphIssueCode.GATE_ID_MISMATCH.value,
            "trace": ("wait_for_human",),
        }
    if not resume.decision_applied:
        return {
            "transition_status": WorkflowTransitionStatus.REJECTED.value,
            "transition_issue": WorkflowGraphIssueCode.HUMAN_DECISION_NOT_APPLIED.value,
            "trace": ("wait_for_human",),
        }

    result = resume_after_human_gate(run, occurred_at=resume.occurred_at)
    return {
        "run": result.run,
        "transition_status": result.status.value,
        "transition_issue": result.issue.value if result.issue is not None else None,
        "applied_decision_id": str(resume.decision_id),
        "trace": ("wait_for_human",),
    }


def build_governed_workflow_graph(
    *,
    checkpointer: Checkpointer = None,
) -> CompiledStateGraph[
    GovernedWorkflowState,
    None,
    GovernedWorkflowState,
    GovernedWorkflowState,
]:
    """Compile the governed project graph without hiding domain routing rules."""
    builder = StateGraph(GovernedWorkflowState)
    builder.add_node("apply_step", _apply_step_node)
    builder.add_node("wait_for_human", _wait_for_human_node)
    builder.add_edge(START, "apply_step")
    builder.add_conditional_edges(
        "apply_step",
        _route_after_step,
        {
            "wait_for_human": "wait_for_human",
            "end": END,
        },
    )
    builder.add_edge("wait_for_human", END)
    return cast(
        CompiledStateGraph[
            GovernedWorkflowState,
            None,
            GovernedWorkflowState,
            GovernedWorkflowState,
        ],
        builder.compile(checkpointer=checkpointer),
    )
