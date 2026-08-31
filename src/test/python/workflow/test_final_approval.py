"""Tests for exact-version Gate 8 final-output approval."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.projects.domain import ProjectMode
from orchestwin.workflow.final_approval import (
    FinalApprovalError,
    FinalApprovalIssueCode,
    decide_final_output_gate,
    enter_final_approval_stage,
    resume_after_final_output_approval,
    submit_final_review_for_approval,
)
from orchestwin.workflow.final_review import (
    FinalReviewCheck,
    FinalReviewCheckKind,
    FinalReviewCheckStatus,
    create_final_review_assessment,
)
from orchestwin.workflow.gates import HumanGateAction, HumanGateStatus
from orchestwin.workflow.routing import start_workflow_run
from orchestwin.workflow.runs import WorkflowStage, create_workflow_run

PROJECT_ID = UUID("00000000-0000-4000-8000-000000024001")
OWNER_ID = UUID("00000000-0000-4000-8000-000000024002")
RUN_ID = UUID("00000000-0000-4000-8000-000000024003")
REVIEW_IDS = (
    UUID("00000000-0000-4000-8000-000000024010"),
    UUID("00000000-0000-4000-8000-000000024011"),
)
GATE_ID = UUID("00000000-0000-4000-8000-000000024020")
EVENT_IDS = (
    UUID("00000000-0000-4000-8000-000000024030"),
    UUID("00000000-0000-4000-8000-000000024031"),
    UUID("00000000-0000-4000-8000-000000024032"),
)
NOW = datetime(2026, 8, 30, 23, 0, tzinfo=UTC)


def _run():
    draft = create_workflow_run(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        run_id=RUN_ID,
        created_at=NOW,
    )
    running = start_workflow_run(draft, occurred_at=NOW + timedelta(seconds=1)).run
    return replace(
        running,
        current_stage=WorkflowStage.FINAL_REVIEW,
        updated_at=NOW + timedelta(seconds=2),
    )


def _checks(*, ready: bool = True) -> tuple[FinalReviewCheck, ...]:
    checks = []
    for index, kind in enumerate(FinalReviewCheckKind, start=1):
        failed = not ready and kind is FinalReviewCheckKind.DEFINITION_OF_DONE
        checks.append(
            FinalReviewCheck(
                check_id=f"FRC-{index:02d}",
                kind=kind,
                status=(
                    FinalReviewCheckStatus.NOT_SATISFIED
                    if failed
                    else FinalReviewCheckStatus.SATISFIED
                ),
                summary=f"Final dimension {kind.value} was inspected.",
                evidence_refs=(f"evidence:{kind.value.lower()}",),
                blocking=failed,
            )
        )
    return tuple(sorted(checks, key=lambda item: item.sort_key))


def _review(*, ready: bool = True, review_id: UUID = REVIEW_IDS[0], previous=None):
    run = replace(_run(), state_version=(4 if previous else 3))
    return create_final_review_assessment(
        run,
        checks=_checks(ready=ready),
        previous_review=previous,
        review_id=review_id,
        created_at=NOW + timedelta(seconds=3 if previous is None else 4),
    )


def test_gate8_approves_exact_review_then_enters_export() -> None:
    review = _review()
    submitted = submit_final_review_for_approval(
        review,
        gate_id=GATE_ID,
        event_id=EVENT_IDS[0],
        occurred_at=NOW + timedelta(seconds=5),
    )
    waiting_run = enter_final_approval_stage(
        _run(),
        gate=submitted.gate,
        occurred_at=NOW + timedelta(seconds=5),
    )
    approved = decide_final_output_gate(
        submitted.gate,
        current_review=review,
        action=HumanGateAction.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=NOW + timedelta(seconds=6),
        event_id=EVENT_IDS[1],
    )
    export_run = resume_after_final_output_approval(
        waiting_run,
        gate=approved.gate,
        occurred_at=NOW + timedelta(seconds=7),
    )

    assert approved.gate.status is HumanGateStatus.APPROVED
    assert export_run.current_stage is WorkflowStage.EXPORT
    assert export_run.pending_gate_id is None


def test_gate8_rejects_review_with_blocking_checks() -> None:
    with pytest.raises(FinalApprovalError) as captured:
        submit_final_review_for_approval(
            _review(ready=False),
            gate_id=GATE_ID,
            event_id=EVENT_IDS[0],
            occurred_at=NOW + timedelta(seconds=5),
        )

    assert captured.value.code is FinalApprovalIssueCode.REVIEW_NOT_READY


def test_gate8_decision_is_marked_stale_after_review_supersession() -> None:
    first = _review()
    submitted = submit_final_review_for_approval(
        first,
        gate_id=GATE_ID,
        event_id=EVENT_IDS[0],
        occurred_at=NOW + timedelta(seconds=5),
    )
    second = _review(review_id=REVIEW_IDS[1], previous=first)

    stale = decide_final_output_gate(
        submitted.gate,
        current_review=second,
        action=HumanGateAction.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=NOW + timedelta(seconds=6),
        event_id=EVENT_IDS[2],
    )

    assert stale.gate.status is HumanGateStatus.STALE
    assert stale.event is not None
    assert stale.event.artifact.artifact_id == second.id
