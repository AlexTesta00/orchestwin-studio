"""Tests for deterministic workflow routing and operational limits."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from orchestwin.projects.domain import ProjectMode
from orchestwin.workflow.routing import (
    WorkflowIterationKind,
    WorkflowLimitStatus,
    WorkflowOperationalLimits,
    WorkflowTransitionIssueCode,
    WorkflowTransitionStatus,
    advance_workflow_run,
    assess_budget_limits,
    consume_iteration,
    legal_next_stages,
    resume_after_human_gate,
    start_workflow_run,
)
from orchestwin.workflow.runs import (
    WorkflowBudgetState,
    WorkflowRunStatus,
    WorkflowStage,
    create_workflow_run,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000010101")
OWNER_ID = UUID("00000000-0000-4000-8000-000000010102")
GATE_ID = UUID("00000000-0000-4000-8000-000000010103")
START = datetime(2026, 8, 28, 22, 10, tzinfo=UTC)


def running_run(*, mode: ProjectMode = ProjectMode.GREENFIELD_GENERATION):
    draft = create_workflow_run(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        project_mode=mode,
        created_at=START,
    )
    result = start_workflow_run(draft, occurred_at=START + timedelta(seconds=1))
    assert result.status is WorkflowTransitionStatus.APPLIED
    return result.run


def test_greenfield_and_brownfield_routes_remain_distinct() -> None:
    assert legal_next_stages(
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        current_stage=WorkflowStage.INTAKE,
    ) == frozenset({WorkflowStage.BRIEF_APPROVAL})
    assert legal_next_stages(
        project_mode=ProjectMode.BROWNFIELD_ASSESSMENT,
        current_stage=WorkflowStage.INTAKE,
    ) == frozenset({WorkflowStage.SOURCE_INGESTION})


def test_human_gate_stage_requires_an_exact_gate_before_pausing() -> None:
    run = running_run()
    missing = advance_workflow_run(
        run,
        next_stage=WorkflowStage.BRIEF_APPROVAL,
        occurred_at=START + timedelta(seconds=2),
    )
    entered = advance_workflow_run(
        run,
        next_stage=WorkflowStage.BRIEF_APPROVAL,
        occurred_at=START + timedelta(seconds=2),
        pending_gate_id=GATE_ID,
    )

    assert missing.status is WorkflowTransitionStatus.REJECTED
    assert missing.issue is WorkflowTransitionIssueCode.GATE_ID_REQUIRED
    assert entered.status is WorkflowTransitionStatus.APPLIED
    assert entered.run.status is WorkflowRunStatus.WAITING_FOR_HUMAN
    assert entered.run.pending_gate_id == GATE_ID

    resumed = resume_after_human_gate(
        entered.run,
        occurred_at=START + timedelta(seconds=3),
    )
    assert resumed.run.status is WorkflowRunStatus.RUNNING
    assert resumed.run.pending_gate_id is None


def test_routing_cannot_skip_a_mandatory_gate() -> None:
    run = running_run()

    result = advance_workflow_run(
        run,
        next_stage=WorkflowStage.TEAM_SELECTION,
        occurred_at=START + timedelta(seconds=2),
    )

    assert result.status is WorkflowTransitionStatus.REJECTED
    assert result.issue is WorkflowTransitionIssueCode.ILLEGAL_STAGE_TRANSITION
    assert result.run == run


def test_iteration_limit_pauses_instead_of_manufacturing_progress() -> None:
    limits = WorkflowOperationalLimits(design_cycles=1)
    run = running_run()
    consumed = consume_iteration(
        run,
        kind=WorkflowIterationKind.DESIGN_CYCLE,
        occurred_at=START + timedelta(seconds=2),
        limits=limits,
    )
    paused = consume_iteration(
        consumed.run,
        kind=WorkflowIterationKind.DESIGN_CYCLE,
        occurred_at=START + timedelta(seconds=3),
        limits=limits,
    )

    assert consumed.status is WorkflowLimitStatus.WITHIN_LIMIT
    assert consumed.run.iteration_counters.design_cycle_count == 1
    assert paused.status is WorkflowLimitStatus.PAUSED
    assert paused.run.status is WorkflowRunStatus.PAUSED_NEEDS_HUMAN
    assert paused.issues[0].code == "DESIGN_CYCLE_LIMIT"


def test_repeated_failure_limit_is_scoped_to_the_stable_signature() -> None:
    limits = WorkflowOperationalLimits(
        repairs_per_failure=3,
        identical_failure_tolerance=1,
    )
    run = running_run()
    first = consume_iteration(
        run,
        kind=WorkflowIterationKind.REPAIR,
        failure_signature="BUILD_FAILURE:abc123",
        identical_failure=True,
        occurred_at=START + timedelta(seconds=2),
        limits=limits,
    )
    second = consume_iteration(
        first.run,
        kind=WorkflowIterationKind.REPAIR,
        failure_signature="BUILD_FAILURE:abc123",
        identical_failure=True,
        occurred_at=START + timedelta(seconds=3),
        limits=limits,
    )

    assert second.status is WorkflowLimitStatus.PAUSED
    assert second.issues[0].code == "IDENTICAL_FAILURE_LIMIT"


def test_budget_warning_and_hard_pause_use_integer_usage() -> None:
    limits = WorkflowOperationalLimits(
        estimated_cost_micros=100,
        sandbox_elapsed_seconds=100,
        warning_percent=70,
    )
    run = running_run()
    warning = replace(
        run,
        budget_state=WorkflowBudgetState(estimated_cost_micros=70),
    )
    exhausted = replace(
        run,
        budget_state=WorkflowBudgetState(sandbox_elapsed_seconds=100),
    )

    warning_result = assess_budget_limits(
        warning,
        occurred_at=START + timedelta(seconds=2),
        limits=limits,
    )
    exhausted_result = assess_budget_limits(
        exhausted,
        occurred_at=START + timedelta(seconds=2),
        limits=limits,
    )

    assert warning_result.status is WorkflowLimitStatus.WARNING
    assert exhausted_result.status is WorkflowLimitStatus.PAUSED
    assert exhausted_result.run.status is WorkflowRunStatus.PAUSED_NEEDS_HUMAN
    assert exhausted_result.issues[0].code == "SANDBOX_TIME_LIMIT"
