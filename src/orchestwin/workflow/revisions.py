"""Bounded design, implementation, and synthetic-evaluation revision routing."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from orchestwin.evaluation.aggregation import MultiTwinEvaluationAggregation
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.requirements_primitives import (
    normalize_required_text,
    validate_positive_integer,
)
from orchestwin.workflow.routing import (
    DEFAULT_WORKFLOW_LIMITS,
    WorkflowIterationKind,
    WorkflowLimitStatus,
    WorkflowOperationalLimits,
    WorkflowTransitionStatus,
    advance_workflow_run,
    consume_iteration,
)
from orchestwin.workflow.runs import (
    WorkflowBlockingIssue,
    WorkflowBlockingIssueSource,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowStage,
)

_EVALUATION_ARTIFACT_TYPE = "SYNTHETIC_EVALUATION"


class WorkflowRevisionDecision(StrEnum):
    """Explicit owner-visible outcomes of the bounded revision decision stage."""

    REPAIR_CODE = "REPAIR_CODE"
    REVISE_DESIGN = "REVISE_DESIGN"
    REVISE_REQUIREMENTS = "REVISE_REQUIREMENTS"
    REVISE_ARCHITECTURE = "REVISE_ARCHITECTURE"
    REQUEST_HIGH_IMPACT_APPROVAL = "REQUEST_HIGH_IMPACT_APPROVAL"
    REQUEST_HUMAN_DECISION = "REQUEST_HUMAN_DECISION"
    MARK_FINAL_CANDIDATE = "MARK_FINAL_CANDIDATE"


class WorkflowRevisionStatus(StrEnum):
    """Stable result shape for one revision-routing attempt."""

    APPLIED = "APPLIED"
    PAUSED_NEEDS_HUMAN = "PAUSED_NEEDS_HUMAN"
    REJECTED = "REJECTED"


class WorkflowRevisionIssueCode(StrEnum):
    """Expected reasons a revision decision cannot be applied."""

    STATE_VERSION_CONFLICT = "STATE_VERSION_CONFLICT"
    RUN_NOT_ACTIVE = "RUN_NOT_ACTIVE"
    WRONG_STAGE = "WRONG_STAGE"
    EVALUATION_SCOPE_MISMATCH = "EVALUATION_SCOPE_MISMATCH"
    FAILURE_SIGNATURE_REQUIRED = "FAILURE_SIGNATURE_REQUIRED"
    HIGH_IMPACT_GATE_REQUIRED = "HIGH_IMPACT_GATE_REQUIRED"
    HIGH_IMPACT_GATE_NOT_ALLOWED = "HIGH_IMPACT_GATE_NOT_ALLOWED"
    HUMAN_REASON_REQUIRED = "HUMAN_REASON_REQUIRED"
    ILLEGAL_ROUTE = "ILLEGAL_ROUTE"


@dataclass(frozen=True, slots=True)
class WorkflowRevisionRequest:
    """Exact optimistic-concurrency command for one revision route."""

    decision: WorkflowRevisionDecision
    expected_state_version: int
    aggregation: MultiTwinEvaluationAggregation
    occurred_at: datetime
    failure_signature: str | None = None
    identical_failure: bool = False
    high_impact_gate_id: UUID | None = None
    human_reason: str | None = None

    def __post_init__(self) -> None:
        validate_positive_integer(
            self.expected_state_version,
            label="revision expected workflow state version",
        )
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("revision decision timestamp must be timezone-aware")
        if self.failure_signature is not None:
            normalized = normalize_required_text(
                self.failure_signature,
                label="revision failure signature",
                maximum_length=256,
            )
            if normalized != self.failure_signature:
                raise ValueError("revision failure signature must be normalized")
        if self.human_reason is not None:
            normalized_reason = normalize_required_text(
                self.human_reason,
                label="revision human-decision reason",
                maximum_length=1_000,
            )
            if normalized_reason != self.human_reason:
                raise ValueError("revision human-decision reason must be normalized")


@dataclass(frozen=True, slots=True)
class WorkflowRevisionResult:
    """Applied, paused, or rejected revision route with no hidden fallback."""

    status: WorkflowRevisionStatus
    run: WorkflowRun
    decision: WorkflowRevisionDecision
    issue: WorkflowRevisionIssueCode | None = None

    def __post_init__(self) -> None:
        rejected = self.status is WorkflowRevisionStatus.REJECTED
        if rejected != (self.issue is not None):
            raise ValueError("rejected revision results require exactly one issue")
        paused = self.status is WorkflowRevisionStatus.PAUSED_NEEDS_HUMAN
        if paused != (self.run.status is WorkflowRunStatus.PAUSED_NEEDS_HUMAN):
            raise ValueError("paused revision results require a paused workflow run")


def route_workflow_revision(
    run: WorkflowRun,
    request: WorkflowRevisionRequest,
    *,
    limits: WorkflowOperationalLimits = DEFAULT_WORKFLOW_LIMITS,
) -> WorkflowRevisionResult:
    """Apply one bounded revision decision against an exact evaluation result."""
    issue = _precondition_issue(run, request)
    if issue is not None:
        return _rejected(run, request.decision, issue)

    if request.decision is WorkflowRevisionDecision.REQUEST_HIGH_IMPACT_APPROVAL:
        if request.high_impact_gate_id is None:
            return _rejected(
                run,
                request.decision,
                WorkflowRevisionIssueCode.HIGH_IMPACT_GATE_REQUIRED,
            )
        waiting = replace(
            run,
            status=WorkflowRunStatus.WAITING_FOR_HUMAN,
            pending_gate_id=request.high_impact_gate_id,
            blocking_issues=(),
            last_error=None,
            state_version=run.state_version + 1,
            updated_at=request.occurred_at,
        )
        return WorkflowRevisionResult(
            WorkflowRevisionStatus.APPLIED,
            waiting,
            request.decision,
        )

    if request.high_impact_gate_id is not None:
        return _rejected(
            run,
            request.decision,
            WorkflowRevisionIssueCode.HIGH_IMPACT_GATE_NOT_ALLOWED,
        )

    if request.decision is WorkflowRevisionDecision.REQUEST_HUMAN_DECISION:
        if request.human_reason is None:
            return _rejected(
                run,
                request.decision,
                WorkflowRevisionIssueCode.HUMAN_REASON_REQUIRED,
            )
        issue_value = WorkflowBlockingIssue(
            source=WorkflowBlockingIssueSource.HUMAN_DECISION,
            code="REVISION_OWNER_DECISION_REQUIRED",
            summary=request.human_reason,
            recoverable=True,
        )
        paused = replace(
            run,
            status=WorkflowRunStatus.PAUSED_NEEDS_HUMAN,
            pending_gate_id=None,
            resume_status=WorkflowRunStatus.RUNNING,
            blocking_issues=(issue_value,),
            last_error=None,
            state_version=run.state_version + 1,
            updated_at=request.occurred_at,
        )
        return WorkflowRevisionResult(
            WorkflowRevisionStatus.PAUSED_NEEDS_HUMAN,
            paused,
            request.decision,
        )

    iteration_kind = _iteration_kind(request.decision)
    working = run
    if iteration_kind is not None:
        if (
            request.decision is WorkflowRevisionDecision.REPAIR_CODE
            and request.failure_signature is None
        ):
            return _rejected(
                run,
                request.decision,
                WorkflowRevisionIssueCode.FAILURE_SIGNATURE_REQUIRED,
            )
        assessment = consume_iteration(
            working,
            kind=iteration_kind,
            occurred_at=request.occurred_at,
            limits=limits,
            failure_signature=request.failure_signature,
            identical_failure=request.identical_failure,
        )
        if assessment.status is WorkflowLimitStatus.PAUSED:
            return WorkflowRevisionResult(
                WorkflowRevisionStatus.PAUSED_NEEDS_HUMAN,
                assessment.run,
                request.decision,
            )
        working = assessment.run

    target_stage = _target_stage(run.project_mode, request.decision)
    if target_stage is None:
        return _rejected(
            run,
            request.decision,
            WorkflowRevisionIssueCode.ILLEGAL_ROUTE,
        )
    transition = advance_workflow_run(
        working,
        next_stage=target_stage,
        occurred_at=request.occurred_at,
    )
    if transition.status is not WorkflowTransitionStatus.APPLIED:
        return _rejected(
            run,
            request.decision,
            WorkflowRevisionIssueCode.ILLEGAL_ROUTE,
        )
    return WorkflowRevisionResult(
        WorkflowRevisionStatus.APPLIED,
        transition.run,
        request.decision,
    )


def _precondition_issue(
    run: WorkflowRun,
    request: WorkflowRevisionRequest,
) -> WorkflowRevisionIssueCode | None:
    if run.state_version != request.expected_state_version:
        return WorkflowRevisionIssueCode.STATE_VERSION_CONFLICT
    if run.status is not WorkflowRunStatus.RUNNING:
        return WorkflowRevisionIssueCode.RUN_NOT_ACTIVE
    if run.current_stage is not WorkflowStage.REVISION_DECISION:
        return WorkflowRevisionIssueCode.WRONG_STAGE
    if run.latest_evaluation_run_id != request.aggregation.evaluation_run_id:
        return WorkflowRevisionIssueCode.EVALUATION_SCOPE_MISMATCH
    matching_references = tuple(
        reference
        for reference in run.artifact_references
        if reference.artifact_type == _EVALUATION_ARTIFACT_TYPE
        and reference.artifact_id == request.aggregation.evaluation_run_id
    )
    if len(matching_references) != 1:
        return WorkflowRevisionIssueCode.EVALUATION_SCOPE_MISMATCH
    if matching_references[0].content_hash != request.aggregation.evaluation_run_hash:
        return WorkflowRevisionIssueCode.EVALUATION_SCOPE_MISMATCH
    return None


def _iteration_kind(
    decision: WorkflowRevisionDecision,
) -> WorkflowIterationKind | None:
    return {
        WorkflowRevisionDecision.REPAIR_CODE: WorkflowIterationKind.REPAIR,
        WorkflowRevisionDecision.REVISE_DESIGN: WorkflowIterationKind.DESIGN_CYCLE,
        WorkflowRevisionDecision.REVISE_REQUIREMENTS: WorkflowIterationKind.REQUIREMENTS_REVISION,
        WorkflowRevisionDecision.REVISE_ARCHITECTURE: WorkflowIterationKind.ARCHITECTURE_REVISION,
    }.get(decision)


def _target_stage(
    project_mode: ProjectMode,
    decision: WorkflowRevisionDecision,
) -> WorkflowStage | None:
    if decision is WorkflowRevisionDecision.REPAIR_CODE:
        return WorkflowStage.EXECUTION
    if decision is WorkflowRevisionDecision.REVISE_DESIGN:
        return (
            WorkflowStage.DESIGN_EXPLORATION
            if project_mode is ProjectMode.GREENFIELD_GENERATION
            else WorkflowStage.PATCH_PLANNING
        )
    if decision is WorkflowRevisionDecision.REVISE_REQUIREMENTS:
        return WorkflowStage.REQUIREMENTS
    if decision is WorkflowRevisionDecision.REVISE_ARCHITECTURE:
        return WorkflowStage.ARCHITECTURE_AND_TEST_PLAN
    if decision is WorkflowRevisionDecision.MARK_FINAL_CANDIDATE:
        return WorkflowStage.FINAL_REVIEW
    return None


def _rejected(
    run: WorkflowRun,
    decision: WorkflowRevisionDecision,
    issue: WorkflowRevisionIssueCode,
) -> WorkflowRevisionResult:
    return WorkflowRevisionResult(
        WorkflowRevisionStatus.REJECTED,
        run,
        decision,
        issue,
    )
