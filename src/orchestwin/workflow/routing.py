"""Pure legal routing and operational-limit policies for workflow runs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final
from uuid import UUID

from orchestwin.projects.domain import ProjectMode
from orchestwin.workflow.runs import (
    WorkflowBlockingIssue,
    WorkflowBlockingIssueSource,
    WorkflowFailureCounter,
    WorkflowIterationCounters,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowStage,
)


class WorkflowTransitionStatus(StrEnum):
    """Stable outcomes of a deterministic workflow transition attempt."""

    APPLIED = "APPLIED"
    NO_CHANGE = "NO_CHANGE"
    REJECTED = "REJECTED"


class WorkflowTransitionIssueCode(StrEnum):
    """Expected reasons a workflow stage transition may be rejected."""

    RUN_NOT_DRAFT = "RUN_NOT_DRAFT"
    RUN_NOT_ACTIVE = "RUN_NOT_ACTIVE"
    ILLEGAL_STAGE_TRANSITION = "ILLEGAL_STAGE_TRANSITION"
    GATE_ID_REQUIRED = "GATE_ID_REQUIRED"
    GATE_ID_NOT_ALLOWED = "GATE_ID_NOT_ALLOWED"
    TIMESTAMP_NOT_AWARE = "TIMESTAMP_NOT_AWARE"
    TIMESTAMP_OUT_OF_ORDER = "TIMESTAMP_OUT_OF_ORDER"


class WorkflowIterationKind(StrEnum):
    """Bounded loop kinds tracked by the common workflow state."""

    CLARIFICATION = "CLARIFICATION"
    REQUIREMENTS_REVISION = "REQUIREMENTS_REVISION"
    DESIGN_CYCLE = "DESIGN_CYCLE"
    ARCHITECTURE_REVISION = "ARCHITECTURE_REVISION"
    REPAIR = "REPAIR"


class WorkflowLimitStatus(StrEnum):
    """Outcome of checking or consuming an operational limit."""

    WITHIN_LIMIT = "WITHIN_LIMIT"
    WARNING = "WARNING"
    PAUSED = "PAUSED"


@dataclass(frozen=True, slots=True)
class WorkflowTransitionResult:
    """Typed result of starting or advancing a workflow run."""

    status: WorkflowTransitionStatus
    run: WorkflowRun
    issue: WorkflowTransitionIssueCode | None = None

    def __post_init__(self) -> None:
        rejected = self.status is WorkflowTransitionStatus.REJECTED
        if rejected != (self.issue is not None):
            raise ValueError("workflow transition result issue shape is inconsistent")


@dataclass(frozen=True, slots=True)
class WorkflowOperationalLimits:
    """Owner-visible defaults for bounded loops, cost, and sandbox time."""

    clarification_loops: int = 3
    requirements_revisions: int = 3
    design_cycles: int = 3
    architecture_revisions: int = 2
    repairs_per_failure: int = 5
    identical_failure_tolerance: int = 2
    estimated_cost_micros: int = 5_000_000
    sandbox_elapsed_seconds: int = 3600
    warning_percent: int = 70

    def __post_init__(self) -> None:
        limits = (
            self.clarification_loops,
            self.requirements_revisions,
            self.design_cycles,
            self.architecture_revisions,
            self.repairs_per_failure,
            self.identical_failure_tolerance,
            self.estimated_cost_micros,
            self.sandbox_elapsed_seconds,
        )
        if any(isinstance(value, bool) or value < 1 for value in limits):
            raise ValueError("workflow operational limits must be positive integers")
        if not 1 <= self.warning_percent < 100:
            raise ValueError("workflow warning percent must be between 1 and 99")


@dataclass(frozen=True, slots=True)
class WorkflowLimitAssessment:
    """Result of one iteration or budget check."""

    status: WorkflowLimitStatus
    run: WorkflowRun
    issues: tuple[WorkflowBlockingIssue, ...] = ()

    def __post_init__(self) -> None:
        paused = self.status is WorkflowLimitStatus.PAUSED
        if paused != (self.run.status is WorkflowRunStatus.PAUSED_NEEDS_HUMAN):
            raise ValueError("paused limit assessment must contain a paused workflow run")
        if paused != bool(self.issues):
            raise ValueError("paused limit assessment must expose blocking issues")


DEFAULT_WORKFLOW_LIMITS: Final = WorkflowOperationalLimits()

_HUMAN_GATE_STAGES: Final = frozenset(
    {
        WorkflowStage.BRIEF_APPROVAL,
        WorkflowStage.TEAM_APPROVAL,
        WorkflowStage.USER_TWIN_APPROVAL,
        WorkflowStage.REQUIREMENTS_APPROVAL,
        WorkflowStage.DESIGN_APPROVAL,
        WorkflowStage.ARCHITECTURE_APPROVAL,
        WorkflowStage.FINAL_APPROVAL,
    }
)

_GREENFIELD_TRANSITIONS: Final = MappingProxyType(
    {
        WorkflowStage.INTAKE: frozenset({WorkflowStage.BRIEF_APPROVAL}),
        WorkflowStage.BRIEF_APPROVAL: frozenset({WorkflowStage.TEAM_SELECTION}),
        WorkflowStage.TEAM_SELECTION: frozenset({WorkflowStage.TEAM_APPROVAL}),
        WorkflowStage.TEAM_APPROVAL: frozenset({WorkflowStage.USER_MODELING}),
        WorkflowStage.USER_MODELING: frozenset({WorkflowStage.USER_TWIN_APPROVAL}),
        WorkflowStage.USER_TWIN_APPROVAL: frozenset({WorkflowStage.REQUIREMENTS}),
        WorkflowStage.REQUIREMENTS: frozenset({WorkflowStage.REQUIREMENTS_APPROVAL}),
        WorkflowStage.REQUIREMENTS_APPROVAL: frozenset({WorkflowStage.DESIGN_EXPLORATION}),
        WorkflowStage.DESIGN_EXPLORATION: frozenset({WorkflowStage.DESIGN_APPROVAL}),
        WorkflowStage.DESIGN_APPROVAL: frozenset({WorkflowStage.ARCHITECTURE_AND_TEST_PLAN}),
        WorkflowStage.ARCHITECTURE_AND_TEST_PLAN: frozenset({WorkflowStage.ARCHITECTURE_APPROVAL}),
        WorkflowStage.ARCHITECTURE_APPROVAL: frozenset({WorkflowStage.IMPLEMENTATION}),
        WorkflowStage.IMPLEMENTATION: frozenset({WorkflowStage.EXECUTION}),
        WorkflowStage.EXECUTION: frozenset({WorkflowStage.SYNTHETIC_EVALUATION}),
        WorkflowStage.SYNTHETIC_EVALUATION: frozenset({WorkflowStage.REVISION_DECISION}),
        WorkflowStage.REVISION_DECISION: frozenset(
            {
                WorkflowStage.EXECUTION,
                WorkflowStage.DESIGN_EXPLORATION,
                WorkflowStage.REQUIREMENTS,
                WorkflowStage.ARCHITECTURE_AND_TEST_PLAN,
                WorkflowStage.FINAL_REVIEW,
            }
        ),
        WorkflowStage.FINAL_REVIEW: frozenset({WorkflowStage.FINAL_APPROVAL}),
        WorkflowStage.FINAL_APPROVAL: frozenset({WorkflowStage.EXPORT}),
        WorkflowStage.EXPORT: frozenset(),
    }
)

_BROWNFIELD_TRANSITIONS: Final = MappingProxyType(
    {
        WorkflowStage.INTAKE: frozenset({WorkflowStage.SOURCE_INGESTION}),
        WorkflowStage.SOURCE_INGESTION: frozenset({WorkflowStage.STACK_DETECTION}),
        WorkflowStage.STACK_DETECTION: frozenset({WorkflowStage.ARCHITECTURE_RECOVERY}),
        WorkflowStage.ARCHITECTURE_RECOVERY: frozenset({WorkflowStage.REQUIREMENTS_INFERENCE}),
        WorkflowStage.REQUIREMENTS_INFERENCE: frozenset({WorkflowStage.BASELINE_EXECUTION}),
        WorkflowStage.BASELINE_EXECUTION: frozenset({WorkflowStage.BRIEF_APPROVAL}),
        WorkflowStage.BRIEF_APPROVAL: frozenset({WorkflowStage.TEAM_SELECTION}),
        WorkflowStage.TEAM_SELECTION: frozenset({WorkflowStage.TEAM_APPROVAL}),
        WorkflowStage.TEAM_APPROVAL: frozenset({WorkflowStage.USER_MODELING}),
        WorkflowStage.USER_MODELING: frozenset({WorkflowStage.USER_TWIN_APPROVAL}),
        WorkflowStage.USER_TWIN_APPROVAL: frozenset({WorkflowStage.REQUIREMENTS}),
        WorkflowStage.REQUIREMENTS: frozenset({WorkflowStage.REQUIREMENTS_APPROVAL}),
        WorkflowStage.REQUIREMENTS_APPROVAL: frozenset({WorkflowStage.PATCH_PLANNING}),
        WorkflowStage.PATCH_PLANNING: frozenset({WorkflowStage.DESIGN_APPROVAL}),
        WorkflowStage.DESIGN_APPROVAL: frozenset({WorkflowStage.ARCHITECTURE_AND_TEST_PLAN}),
        WorkflowStage.ARCHITECTURE_AND_TEST_PLAN: frozenset({WorkflowStage.ARCHITECTURE_APPROVAL}),
        WorkflowStage.ARCHITECTURE_APPROVAL: frozenset({WorkflowStage.IMPLEMENTATION}),
        WorkflowStage.IMPLEMENTATION: frozenset({WorkflowStage.EXECUTION}),
        WorkflowStage.EXECUTION: frozenset({WorkflowStage.SYNTHETIC_EVALUATION}),
        WorkflowStage.SYNTHETIC_EVALUATION: frozenset({WorkflowStage.REVISION_DECISION}),
        WorkflowStage.REVISION_DECISION: frozenset(
            {
                WorkflowStage.EXECUTION,
                WorkflowStage.PATCH_PLANNING,
                WorkflowStage.REQUIREMENTS,
                WorkflowStage.ARCHITECTURE_AND_TEST_PLAN,
                WorkflowStage.FINAL_REVIEW,
            }
        ),
        WorkflowStage.FINAL_REVIEW: frozenset({WorkflowStage.FINAL_APPROVAL}),
        WorkflowStage.FINAL_APPROVAL: frozenset({WorkflowStage.EXPORT}),
        WorkflowStage.EXPORT: frozenset(),
    }
)


def is_human_gate_stage(stage: WorkflowStage) -> bool:
    """Return whether entering the stage requires an exact human-gate identifier."""
    return stage in _HUMAN_GATE_STAGES


def legal_next_stages(
    *,
    project_mode: ProjectMode,
    current_stage: WorkflowStage,
) -> frozenset[WorkflowStage]:
    """Return the explicit legal next stages for one mode and current stage."""
    transitions = (
        _GREENFIELD_TRANSITIONS
        if project_mode is ProjectMode.GREENFIELD_GENERATION
        else _BROWNFIELD_TRANSITIONS
    )
    return transitions.get(current_stage, frozenset())


def start_workflow_run(
    run: WorkflowRun,
    *,
    occurred_at: datetime,
) -> WorkflowTransitionResult:
    """Start a draft workflow exactly once."""
    issue = _timestamp_issue(run, occurred_at)
    if issue is not None:
        return WorkflowTransitionResult(WorkflowTransitionStatus.REJECTED, run, issue)
    if run.status is WorkflowRunStatus.RUNNING:
        return WorkflowTransitionResult(WorkflowTransitionStatus.NO_CHANGE, run)
    if run.status is not WorkflowRunStatus.DRAFT:
        return WorkflowTransitionResult(
            WorkflowTransitionStatus.REJECTED,
            run,
            WorkflowTransitionIssueCode.RUN_NOT_DRAFT,
        )

    started = replace(
        run,
        status=WorkflowRunStatus.RUNNING,
        state_version=run.state_version + 1,
        started_at=occurred_at,
        updated_at=occurred_at,
    )
    return WorkflowTransitionResult(WorkflowTransitionStatus.APPLIED, started)


def advance_workflow_run(
    run: WorkflowRun,
    *,
    next_stage: WorkflowStage,
    occurred_at: datetime,
    pending_gate_id: UUID | None = None,
) -> WorkflowTransitionResult:
    """Advance through one legal edge while preserving human interrupts explicitly."""
    issue = _timestamp_issue(run, occurred_at)
    if issue is not None:
        return WorkflowTransitionResult(WorkflowTransitionStatus.REJECTED, run, issue)
    if run.status is not WorkflowRunStatus.RUNNING:
        return WorkflowTransitionResult(
            WorkflowTransitionStatus.REJECTED,
            run,
            WorkflowTransitionIssueCode.RUN_NOT_ACTIVE,
        )
    if next_stage not in legal_next_stages(
        project_mode=run.project_mode,
        current_stage=run.current_stage,
    ):
        return WorkflowTransitionResult(
            WorkflowTransitionStatus.REJECTED,
            run,
            WorkflowTransitionIssueCode.ILLEGAL_STAGE_TRANSITION,
        )

    requires_gate = is_human_gate_stage(next_stage)
    if requires_gate and pending_gate_id is None:
        return WorkflowTransitionResult(
            WorkflowTransitionStatus.REJECTED,
            run,
            WorkflowTransitionIssueCode.GATE_ID_REQUIRED,
        )
    if not requires_gate and pending_gate_id is not None:
        return WorkflowTransitionResult(
            WorkflowTransitionStatus.REJECTED,
            run,
            WorkflowTransitionIssueCode.GATE_ID_NOT_ALLOWED,
        )

    advanced = replace(
        run,
        current_stage=next_stage,
        status=(
            WorkflowRunStatus.WAITING_FOR_HUMAN if requires_gate else WorkflowRunStatus.RUNNING
        ),
        pending_gate_id=pending_gate_id,
        blocking_issues=(),
        last_error=None,
        state_version=run.state_version + 1,
        updated_at=occurred_at,
    )
    return WorkflowTransitionResult(WorkflowTransitionStatus.APPLIED, advanced)


def resume_after_human_gate(
    run: WorkflowRun,
    *,
    occurred_at: datetime,
) -> WorkflowTransitionResult:
    """Resume a run only after the application has applied the exact gate decision."""
    issue = _timestamp_issue(run, occurred_at)
    if issue is not None:
        return WorkflowTransitionResult(WorkflowTransitionStatus.REJECTED, run, issue)
    if run.status is not WorkflowRunStatus.WAITING_FOR_HUMAN:
        return WorkflowTransitionResult(
            WorkflowTransitionStatus.REJECTED,
            run,
            WorkflowTransitionIssueCode.RUN_NOT_ACTIVE,
        )

    resumed = replace(
        run,
        status=WorkflowRunStatus.RUNNING,
        pending_gate_id=None,
        state_version=run.state_version + 1,
        updated_at=occurred_at,
    )
    return WorkflowTransitionResult(WorkflowTransitionStatus.APPLIED, resumed)


def consume_iteration(
    run: WorkflowRun,
    *,
    kind: WorkflowIterationKind,
    occurred_at: datetime,
    limits: WorkflowOperationalLimits = DEFAULT_WORKFLOW_LIMITS,
    failure_signature: str | None = None,
    identical_failure: bool = False,
) -> WorkflowLimitAssessment:
    """Consume one bounded loop attempt or pause before exceeding its limit."""
    issue = _timestamp_issue(run, occurred_at)
    if issue is not None:
        raise ValueError(issue.value)
    if run.status is not WorkflowRunStatus.RUNNING:
        raise ValueError("workflow iterations may be consumed only while running")

    counters = run.iteration_counters
    if kind is WorkflowIterationKind.REPAIR:
        if failure_signature is None:
            raise ValueError("repair iteration requires a failure signature")
        updated, limit_issue = _consume_repair_counter(
            counters,
            failure_signature=failure_signature,
            identical_failure=identical_failure,
            limits=limits,
        )
    else:
        if failure_signature is not None or identical_failure:
            raise ValueError("non-repair iterations cannot include failure metadata")
        updated, limit_issue = _consume_named_counter(counters, kind=kind, limits=limits)

    if limit_issue is not None:
        paused = _pause_for_issues(run, occurred_at=occurred_at, issues=(limit_issue,))
        return WorkflowLimitAssessment(
            WorkflowLimitStatus.PAUSED,
            paused,
            (limit_issue,),
        )

    consumed = replace(
        run,
        iteration_counters=updated,
        state_version=run.state_version + 1,
        updated_at=occurred_at,
    )
    return WorkflowLimitAssessment(WorkflowLimitStatus.WITHIN_LIMIT, consumed)


def assess_budget_limits(
    run: WorkflowRun,
    *,
    occurred_at: datetime,
    limits: WorkflowOperationalLimits = DEFAULT_WORKFLOW_LIMITS,
) -> WorkflowLimitAssessment:
    """Pause at hard budget limits and warn once configured usage reaches the threshold."""
    issue = _timestamp_issue(run, occurred_at)
    if issue is not None:
        raise ValueError(issue.value)

    exhausted: list[WorkflowBlockingIssue] = []
    if run.budget_state.estimated_cost_micros >= limits.estimated_cost_micros:
        exhausted.append(
            _limit_issue(
                code="PROJECT_COST_LIMIT",
                summary="The configured project model-cost budget is exhausted.",
            )
        )
    if run.budget_state.sandbox_elapsed_seconds >= limits.sandbox_elapsed_seconds:
        exhausted.append(
            _limit_issue(
                code="SANDBOX_TIME_LIMIT",
                summary="The configured complete build and evaluation time is exhausted.",
            )
        )

    if exhausted:
        issues = tuple(sorted(exhausted, key=lambda item: item.sort_key))
        paused = _pause_for_issues(run, occurred_at=occurred_at, issues=issues)
        return WorkflowLimitAssessment(WorkflowLimitStatus.PAUSED, paused, issues)

    warning_ratio = limits.warning_percent / 100
    cost_warning = run.budget_state.estimated_cost_micros >= int(
        limits.estimated_cost_micros * warning_ratio
    )
    sandbox_warning = run.budget_state.sandbox_elapsed_seconds >= int(
        limits.sandbox_elapsed_seconds * warning_ratio
    )
    status = (
        WorkflowLimitStatus.WARNING
        if cost_warning or sandbox_warning
        else WorkflowLimitStatus.WITHIN_LIMIT
    )
    return WorkflowLimitAssessment(status, run)


def _timestamp_issue(
    run: WorkflowRun,
    occurred_at: datetime,
) -> WorkflowTransitionIssueCode | None:
    if occurred_at.tzinfo is None:
        return WorkflowTransitionIssueCode.TIMESTAMP_NOT_AWARE
    if occurred_at < run.updated_at:
        return WorkflowTransitionIssueCode.TIMESTAMP_OUT_OF_ORDER
    return None


def _consume_named_counter(
    counters: WorkflowIterationCounters,
    *,
    kind: WorkflowIterationKind,
    limits: WorkflowOperationalLimits,
) -> tuple[WorkflowIterationCounters, WorkflowBlockingIssue | None]:
    fields = {
        WorkflowIterationKind.CLARIFICATION: (
            "clarification_count",
            limits.clarification_loops,
            "CLARIFICATION_LIMIT",
            "The clarification-loop limit is exhausted.",
        ),
        WorkflowIterationKind.REQUIREMENTS_REVISION: (
            "requirements_revision_count",
            limits.requirements_revisions,
            "REQUIREMENTS_REVISION_LIMIT",
            "The requirements-revision limit is exhausted.",
        ),
        WorkflowIterationKind.DESIGN_CYCLE: (
            "design_cycle_count",
            limits.design_cycles,
            "DESIGN_CYCLE_LIMIT",
            "The design, implementation, and evaluation cycle limit is exhausted.",
        ),
        WorkflowIterationKind.ARCHITECTURE_REVISION: (
            "architecture_revision_count",
            limits.architecture_revisions,
            "ARCHITECTURE_REVISION_LIMIT",
            "The architecture-redesign limit is exhausted.",
        ),
    }
    if kind not in fields:
        raise ValueError("unsupported non-repair workflow iteration kind")

    field, limit, code, summary = fields[kind]
    current = getattr(counters, field)
    if current >= limit:
        return counters, _limit_issue(code=code, summary=summary)
    return replace(counters, **{field: current + 1}), None


def _consume_repair_counter(
    counters: WorkflowIterationCounters,
    *,
    failure_signature: str,
    identical_failure: bool,
    limits: WorkflowOperationalLimits,
) -> tuple[WorkflowIterationCounters, WorkflowBlockingIssue | None]:
    existing = next(
        (item for item in counters.failure_counters if item.failure_signature == failure_signature),
        None,
    )
    repair_count = 0 if existing is None else existing.repair_count
    identical_count = 0 if existing is None else existing.identical_failure_count

    if repair_count >= limits.repairs_per_failure:
        return counters, _limit_issue(
            code="REPAIR_LIMIT",
            summary="The repair-attempt limit for this failure signature is exhausted.",
        )
    if identical_failure and identical_count >= limits.identical_failure_tolerance:
        return counters, _limit_issue(
            code="IDENTICAL_FAILURE_LIMIT",
            summary="The repeated-identical-failure tolerance is exhausted.",
        )

    replacement = WorkflowFailureCounter(
        failure_signature=failure_signature,
        repair_count=repair_count + 1,
        identical_failure_count=identical_count + (1 if identical_failure else 0),
    )
    remaining = tuple(
        item for item in counters.failure_counters if item.failure_signature != failure_signature
    )
    ordered = tuple(sorted((*remaining, replacement), key=lambda item: item.sort_key))
    return replace(counters, failure_counters=ordered), None


def _limit_issue(*, code: str, summary: str) -> WorkflowBlockingIssue:
    return WorkflowBlockingIssue(
        code=code,
        source=WorkflowBlockingIssueSource.OPERATIONAL_LIMIT,
        summary=summary,
        recoverable=True,
    )


def _pause_for_issues(
    run: WorkflowRun,
    *,
    occurred_at: datetime,
    issues: tuple[WorkflowBlockingIssue, ...],
) -> WorkflowRun:
    return replace(
        run,
        status=WorkflowRunStatus.PAUSED_NEEDS_HUMAN,
        resume_status=WorkflowRunStatus.RUNNING,
        blocking_issues=tuple(sorted(issues, key=lambda item: item.sort_key)),
        state_version=run.state_version + 1,
        updated_at=occurred_at,
    )
