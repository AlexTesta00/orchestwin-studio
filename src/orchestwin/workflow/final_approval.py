"""Gate 8 final-output approval bound to an exact final-review version."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from orchestwin.workflow.final_review import FinalReviewAssessment
from orchestwin.workflow.gates import (
    GateArtifactReference,
    HumanGate,
    HumanGateAction,
    HumanGateStatus,
    HumanGateTransitionResult,
    HumanGateTransitionStatus,
    HumanGateType,
    create_human_gate,
    mark_human_gate_stale,
    transition_human_gate,
)
from orchestwin.workflow.routing import (
    WorkflowTransitionStatus,
    advance_workflow_run,
    resume_after_human_gate,
)
from orchestwin.workflow.runs import WorkflowRun, WorkflowRunStatus, WorkflowStage


class FinalApprovalIssueCode(StrEnum):
    """Stable final-approval failures safe for API and workflow boundaries."""

    REVIEW_NOT_READY = "REVIEW_NOT_READY"
    REVIEW_SCOPE_MISMATCH = "REVIEW_SCOPE_MISMATCH"
    GATE_NOT_FINAL_OUTPUT = "GATE_NOT_FINAL_OUTPUT"
    GATE_NOT_APPROVED = "GATE_NOT_APPROVED"
    RUN_GATE_MISMATCH = "RUN_GATE_MISMATCH"
    RUN_NOT_AT_FINAL_APPROVAL = "RUN_NOT_AT_FINAL_APPROVAL"
    ILLEGAL_WORKFLOW_TRANSITION = "ILLEGAL_WORKFLOW_TRANSITION"


class FinalApprovalError(ValueError):
    """Typed expected error raised by the Gate 8 application boundary."""

    def __init__(self, code: FinalApprovalIssueCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class SubmittedFinalApproval:
    """A submitted Gate 8 and its append-only first event."""

    review: FinalReviewAssessment
    transition: HumanGateTransitionResult

    def __post_init__(self) -> None:
        if self.transition.status is not HumanGateTransitionStatus.APPLIED:
            raise ValueError("submitted final approval requires an applied transition")
        if self.transition.gate.status is not HumanGateStatus.PENDING_APPROVAL:
            raise ValueError("submitted final approval must wait for owner approval")
        if self.transition.gate.gate_type is not HumanGateType.FINAL_OUTPUT:
            raise ValueError("submitted final approval must use Gate 8")

    @property
    def gate(self) -> HumanGate:
        return self.transition.gate


def final_review_gate_reference(review: FinalReviewAssessment) -> GateArtifactReference:
    """Translate one exact review version into its Gate 8 artifact reference."""
    return GateArtifactReference(
        project_id=review.project_id,
        gate_type=HumanGateType.FINAL_OUTPUT,
        artifact_id=review.id,
        version=review.version_number,
        content_hash=review.content_hash,
    )


def submit_final_review_for_approval(
    review: FinalReviewAssessment,
    *,
    gate_id: UUID,
    event_id: UUID,
    occurred_at: datetime,
) -> SubmittedFinalApproval:
    """Submit only a review that has no unresolved Gate 8 blockers."""
    if not review.ready_for_gate8:
        raise FinalApprovalError(
            FinalApprovalIssueCode.REVIEW_NOT_READY,
            "final review still contains blocking checks or issues",
        )
    gate = create_human_gate(
        project_id=review.project_id,
        owner_user_id=review.owner_user_id,
        gate_type=HumanGateType.FINAL_OUTPUT,
        artifact=final_review_gate_reference(review),
        gate_id=gate_id,
        created_at=occurred_at,
    )
    transition = transition_human_gate(
        gate,
        action=HumanGateAction.SUBMIT,
        actor_user_id=review.owner_user_id,
        occurred_at=occurred_at,
        event_id=event_id,
    )
    return SubmittedFinalApproval(review=review, transition=transition)


def decide_final_output_gate(
    gate: HumanGate,
    *,
    current_review: FinalReviewAssessment,
    action: HumanGateAction,
    actor_user_id: UUID,
    occurred_at: datetime,
    reason: str | None = None,
    event_id: UUID,
) -> HumanGateTransitionResult:
    """Apply an owner decision or mark a decision prepared for an old review stale."""
    if gate.gate_type is not HumanGateType.FINAL_OUTPUT:
        raise FinalApprovalError(
            FinalApprovalIssueCode.GATE_NOT_FINAL_OUTPUT,
            "the supplied human gate is not Gate 8",
        )
    if (
        current_review.project_id != gate.project_id
        or current_review.owner_user_id != gate.owner_user_id
    ):
        raise FinalApprovalError(
            FinalApprovalIssueCode.REVIEW_SCOPE_MISMATCH,
            "the current final review does not share the Gate 8 scope",
        )

    current_reference = final_review_gate_reference(current_review)
    if current_reference != gate.artifact:
        return mark_human_gate_stale(
            gate,
            current_artifact=current_reference,
            occurred_at=occurred_at,
            event_id=event_id,
        )
    return transition_human_gate(
        gate,
        action=action,
        actor_user_id=actor_user_id,
        occurred_at=occurred_at,
        reason=reason,
        event_id=event_id,
    )


def enter_final_approval_stage(
    run: WorkflowRun,
    *,
    gate: HumanGate,
    occurred_at: datetime,
) -> WorkflowRun:
    """Move the exact final-review run to its waiting Gate 8 stage."""
    if gate.gate_type is not HumanGateType.FINAL_OUTPUT:
        raise FinalApprovalError(
            FinalApprovalIssueCode.GATE_NOT_FINAL_OUTPUT,
            "the supplied gate is not Gate 8",
        )
    if gate.project_id != run.project_id or gate.owner_user_id != run.owner_user_id:
        raise FinalApprovalError(
            FinalApprovalIssueCode.REVIEW_SCOPE_MISMATCH,
            "Gate 8 does not share the workflow owner and project scope",
        )
    transition = advance_workflow_run(
        run,
        next_stage=WorkflowStage.FINAL_APPROVAL,
        occurred_at=occurred_at,
        pending_gate_id=gate.id,
    )
    if transition.status is not WorkflowTransitionStatus.APPLIED:
        raise FinalApprovalError(
            FinalApprovalIssueCode.ILLEGAL_WORKFLOW_TRANSITION,
            "workflow cannot enter final approval from its current state",
        )
    return transition.run


def resume_after_final_output_approval(
    run: WorkflowRun,
    *,
    gate: HumanGate,
    occurred_at: datetime,
) -> WorkflowRun:
    """Resume an exactly approved Gate 8 run and enter deterministic export."""
    if gate.gate_type is not HumanGateType.FINAL_OUTPUT:
        raise FinalApprovalError(
            FinalApprovalIssueCode.GATE_NOT_FINAL_OUTPUT,
            "the supplied gate is not Gate 8",
        )
    if gate.status is not HumanGateStatus.APPROVED:
        raise FinalApprovalError(
            FinalApprovalIssueCode.GATE_NOT_APPROVED,
            "Gate 8 must be approved before export",
        )
    if run.current_stage is not WorkflowStage.FINAL_APPROVAL:
        raise FinalApprovalError(
            FinalApprovalIssueCode.RUN_NOT_AT_FINAL_APPROVAL,
            "workflow run is not at final approval",
        )
    if run.status is not WorkflowRunStatus.WAITING_FOR_HUMAN or run.pending_gate_id != gate.id:
        raise FinalApprovalError(
            FinalApprovalIssueCode.RUN_GATE_MISMATCH,
            "workflow run is not waiting for this exact Gate 8 decision",
        )

    resumed = resume_after_human_gate(run, occurred_at=occurred_at)
    if resumed.status is not WorkflowTransitionStatus.APPLIED:
        raise FinalApprovalError(
            FinalApprovalIssueCode.ILLEGAL_WORKFLOW_TRANSITION,
            "workflow could not resume after Gate 8",
        )
    export = advance_workflow_run(
        resumed.run,
        next_stage=WorkflowStage.EXPORT,
        occurred_at=occurred_at,
    )
    if export.status is not WorkflowTransitionStatus.APPLIED:
        raise FinalApprovalError(
            FinalApprovalIssueCode.ILLEGAL_WORKFLOW_TRANSITION,
            "workflow could not enter export after Gate 8",
        )
    return export.run
