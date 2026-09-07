"""Tests for the governed LangGraph orchestration shell."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from langgraph.checkpoint.memory import InMemorySaver

from orchestwin.projects.domain import ProjectMode
from orchestwin.workflow.langgraph_graph import (
    WorkflowGraphIssueCode,
    WorkflowGraphStep,
    WorkflowGraphStepKind,
    build_governed_workflow_graph,
    create_workflow_gate_resume_command,
)
from orchestwin.workflow.routing import start_workflow_run
from orchestwin.workflow.runs import (
    WorkflowRunStatus,
    WorkflowStage,
    create_workflow_run,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000010201")
OWNER_ID = UUID("00000000-0000-4000-8000-000000010202")
GATE_ID = UUID("00000000-0000-4000-8000-000000010203")
DECISION_ID = UUID("00000000-0000-4000-8000-000000010204")
NOW = datetime(2026, 8, 28, 22, 20, tzinfo=UTC)


def test_compiled_graph_starts_a_draft_run_through_domain_routing() -> None:
    graph = build_governed_workflow_graph()
    draft = create_workflow_run(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        created_at=NOW,
    )

    output = graph.invoke(
        {
            "run": draft,
            "step": WorkflowGraphStep(
                kind=WorkflowGraphStepKind.START,
                occurred_at=NOW + timedelta(seconds=1),
            ),
            "trace": (),
        }
    )

    assert output["run"].status is WorkflowRunStatus.RUNNING
    assert output["run"].state_version == 2
    assert output["trace"] == ("apply_step",)


def test_compiled_graph_interrupts_and_resumes_only_the_exact_gate() -> None:
    checkpointer = InMemorySaver()
    graph = build_governed_workflow_graph(checkpointer=checkpointer)
    draft = create_workflow_run(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        created_at=NOW,
    )
    running = start_workflow_run(
        draft,
        occurred_at=NOW + timedelta(seconds=1),
    ).run
    config = {"configurable": {"thread_id": str(running.id)}}

    interrupted = graph.invoke(
        {
            "run": running,
            "step": WorkflowGraphStep(
                kind=WorkflowGraphStepKind.ADVANCE,
                occurred_at=NOW + timedelta(seconds=2),
                next_stage=WorkflowStage.BRIEF_APPROVAL,
                pending_gate_id=GATE_ID,
            ),
            "trace": (),
        },
        config=config,
    )

    assert interrupted["run"].status is WorkflowRunStatus.WAITING_FOR_HUMAN
    assert interrupted["run"].pending_gate_id == GATE_ID
    pending_interrupt = interrupted["__interrupt__"][0]
    assert pending_interrupt.value["gate_id"] == str(GATE_ID)

    checkpointed = graph.get_state(config).values
    assert checkpointed["run"] == interrupted["run"]
    assert checkpointed["run"].artifact_references == ()
    assert checkpointed["run"].blocking_issues == ()

    resumed = graph.invoke(
        create_workflow_gate_resume_command(
            interrupt_id=pending_interrupt.id,
            gate_id=GATE_ID,
            decision_id=DECISION_ID,
            decision_applied=True,
            occurred_at=NOW + timedelta(seconds=3),
        ),
        config=config,
    )

    assert resumed["run"].status is WorkflowRunStatus.RUNNING
    assert resumed["run"].pending_gate_id is None
    assert resumed["applied_decision_id"] == str(DECISION_ID)
    assert resumed["trace"] == ("apply_step", "wait_for_human")


def test_wrong_gate_resume_is_rejected_without_changing_waiting_state() -> None:
    checkpointer = InMemorySaver()
    graph = build_governed_workflow_graph(checkpointer=checkpointer)
    draft = create_workflow_run(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        created_at=NOW,
    )
    running = start_workflow_run(
        draft,
        occurred_at=NOW + timedelta(seconds=1),
    ).run
    config = {"configurable": {"thread_id": str(running.id)}}
    interrupted = graph.invoke(
        {
            "run": running,
            "step": WorkflowGraphStep(
                kind=WorkflowGraphStepKind.ADVANCE,
                occurred_at=NOW + timedelta(seconds=2),
                next_stage=WorkflowStage.BRIEF_APPROVAL,
                pending_gate_id=GATE_ID,
            ),
            "trace": (),
        },
        config=config,
    )
    pending_interrupt = interrupted["__interrupt__"][0]

    resumed = graph.invoke(
        create_workflow_gate_resume_command(
            interrupt_id=pending_interrupt.id,
            gate_id=UUID("00000000-0000-4000-8000-000000010299"),
            decision_id=DECISION_ID,
            decision_applied=True,
            occurred_at=NOW + timedelta(seconds=3),
        ),
        config=config,
    )

    assert resumed["run"].status is WorkflowRunStatus.WAITING_FOR_HUMAN
    assert resumed["transition_issue"] == WorkflowGraphIssueCode.GATE_ID_MISMATCH.value
