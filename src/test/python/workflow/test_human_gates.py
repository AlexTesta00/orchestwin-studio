"""Tests for pure human-gate state transitions."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.workflow.gates import (
    GateArtifactReference,
    HumanGateAction,
    HumanGateEventKind,
    HumanGateIssueCode,
    HumanGateStatus,
    HumanGateTransitionStatus,
    HumanGateType,
    create_human_gate,
    mark_human_gate_stale,
    transition_human_gate,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
OTHER_PROJECT_ID = UUID("00000000-0000-4000-8000-000000000011")
OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
OTHER_USER_ID = UUID("00000000-0000-4000-8000-000000000002")
GATE_ID = UUID("00000000-0000-4000-8000-000000000020")
FIRST_ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000000030")
SECOND_ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000000031")
CREATED_AT = datetime(
    2026,
    8,
    12,
    12,
    0,
    tzinfo=UTC,
)


def artifact(
    *,
    version: int = 1,
    hash_character: str = "a",
    artifact_id: UUID = FIRST_ARTIFACT_ID,
    project_id: UUID = PROJECT_ID,
) -> GateArtifactReference:
    """Create one deterministic Project Brief reference."""
    return GateArtifactReference(
        project_id=project_id,
        gate_type=(HumanGateType.PROJECT_BRIEF),
        artifact_id=artifact_id,
        version=version,
        content_hash=(hash_character * 64),
    )


def build_gate(
    *,
    iteration: int = 1,
    max_iterations: int = 3,
):
    """Create one deterministic draft gate."""
    return create_human_gate(
        gate_id=GATE_ID,
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        gate_type=(HumanGateType.PROJECT_BRIEF),
        artifact=artifact(),
        iteration=iteration,
        max_iterations=max_iterations,
        created_at=CREATED_AT,
    )


def submit_gate(
    gate,
):
    """Submit one gate at a deterministic time."""
    result = transition_human_gate(
        gate,
        action=HumanGateAction.SUBMIT,
        actor_user_id=OWNER_ID,
        occurred_at=(CREATED_AT + timedelta(minutes=1)),
    )

    assert result.status is (HumanGateTransitionStatus.APPLIED)

    return result.gate


def test_gate_starts_as_artifact_bound_draft() -> None:
    """Create the first iteration without transition events."""
    gate = build_gate()

    assert gate.status is (HumanGateStatus.DRAFT)
    assert gate.iteration == 1
    assert gate.max_iterations == 3
    assert gate.event_sequence == 0
    assert gate.artifact.version == 1


def test_submit_and_approve_emit_ordered_events() -> None:
    """Move a draft through pending approval to approval."""
    submitted = transition_human_gate(
        build_gate(),
        action=HumanGateAction.SUBMIT,
        actor_user_id=OWNER_ID,
        occurred_at=(CREATED_AT + timedelta(minutes=1)),
    )

    assert submitted.status is (HumanGateTransitionStatus.APPLIED)
    assert submitted.gate.status is (HumanGateStatus.PENDING_APPROVAL)
    assert submitted.event is not None
    assert submitted.event.kind is (HumanGateEventKind.SUBMIT)
    assert submitted.event.sequence_number == 1

    approved = transition_human_gate(
        submitted.gate,
        action=HumanGateAction.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=(CREATED_AT + timedelta(minutes=2)),
    )

    assert approved.status is (HumanGateTransitionStatus.APPLIED)
    assert approved.gate.status is (HumanGateStatus.APPROVED)
    assert approved.gate.event_sequence == 2
    assert approved.event is not None
    assert approved.event.previous_status is (HumanGateStatus.PENDING_APPROVAL)


@pytest.mark.parametrize(
    "action",
    [
        HumanGateAction.REJECT,
        HumanGateAction.REQUEST_REVISION,
    ],
)
def test_reject_and_revision_require_reason(
    action: HumanGateAction,
) -> None:
    """Reject rationale-free decisions without mutating state."""
    pending = submit_gate(build_gate())

    result = transition_human_gate(
        pending,
        action=action,
        actor_user_id=OWNER_ID,
        occurred_at=(CREATED_AT + timedelta(minutes=2)),
        reason="   ",
    )

    assert result.status is (HumanGateTransitionStatus.REJECTED)
    assert result.issue is (HumanGateIssueCode.REASON_REQUIRED)
    assert result.gate is pending
    assert result.event is None


def test_revision_request_normalizes_reason() -> None:
    """Request another iteration below the configured limit."""
    result = transition_human_gate(
        submit_gate(build_gate()),
        action=(HumanGateAction.REQUEST_REVISION),
        actor_user_id=OWNER_ID,
        occurred_at=(CREATED_AT + timedelta(minutes=2)),
        reason=" Add   measurable goals. ",
    )

    assert result.status is (HumanGateTransitionStatus.APPLIED)
    assert result.gate.status is (HumanGateStatus.REVISION_REQUESTED)
    assert result.event is not None
    assert result.event.reason == ("Add measurable goals.")


def test_final_revision_request_pauses_for_human() -> None:
    """Stop revision cycling after the configured final iteration."""
    result = transition_human_gate(
        submit_gate(
            build_gate(
                iteration=3,
                max_iterations=3,
            )
        ),
        action=(HumanGateAction.REQUEST_REVISION),
        actor_user_id=OWNER_ID,
        occurred_at=(CREATED_AT + timedelta(minutes=2)),
        reason=("A further revision is required."),
    )

    assert result.status is (HumanGateTransitionStatus.APPLIED)
    assert result.gate.status is (HumanGateStatus.PAUSED_NEEDS_HUMAN)


def test_pause_and_resume_restore_previous_state() -> None:
    """Pause pending approval and resume it explicitly."""
    paused = transition_human_gate(
        submit_gate(build_gate()),
        action=HumanGateAction.PAUSE,
        actor_user_id=OWNER_ID,
        occurred_at=(CREATED_AT + timedelta(minutes=2)),
        reason=("Owner requested a temporary pause."),
    )

    assert paused.gate.status is (HumanGateStatus.PAUSED)
    assert paused.gate.resume_status is (HumanGateStatus.PENDING_APPROVAL)

    resumed = transition_human_gate(
        paused.gate,
        action=HumanGateAction.RESUME,
        actor_user_id=OWNER_ID,
        occurred_at=(CREATED_AT + timedelta(minutes=3)),
    )

    assert resumed.status is (HumanGateTransitionStatus.APPLIED)
    assert resumed.gate.status is (HumanGateStatus.PENDING_APPROVAL)
    assert resumed.gate.resume_status is None


def test_owner_can_cancel_revision_work() -> None:
    """Allow explicit cancellation after a revision request."""
    revision_requested = transition_human_gate(
        submit_gate(build_gate()),
        action=(HumanGateAction.REQUEST_REVISION),
        actor_user_id=OWNER_ID,
        occurred_at=(CREATED_AT + timedelta(minutes=2)),
        reason="Revise the artifact.",
    ).gate

    cancelled = transition_human_gate(
        revision_requested,
        action=HumanGateAction.CANCEL,
        actor_user_id=OWNER_ID,
        occurred_at=(CREATED_AT + timedelta(minutes=3)),
    )

    assert cancelled.status is (HumanGateTransitionStatus.APPLIED)
    assert cancelled.gate.status is (HumanGateStatus.CANCELLED)


def test_non_owner_and_out_of_order_actions_are_rejected() -> None:
    """Protect owner authority and monotonic audit ordering."""
    gate = build_gate()

    non_owner = transition_human_gate(
        gate,
        action=HumanGateAction.SUBMIT,
        actor_user_id=OTHER_USER_ID,
        occurred_at=(CREATED_AT + timedelta(minutes=1)),
    )

    out_of_order = transition_human_gate(
        gate,
        action=HumanGateAction.SUBMIT,
        actor_user_id=OWNER_ID,
        occurred_at=(CREATED_AT - timedelta(seconds=1)),
    )

    assert non_owner.issue is (HumanGateIssueCode.ACTOR_NOT_OWNER)
    assert out_of_order.issue is (HumanGateIssueCode.TIMESTAMP_OUT_OF_ORDER)
    assert non_owner.gate is gate
    assert out_of_order.gate is gate


def test_invalid_transition_returns_typed_rejection() -> None:
    """Reject approval before submission without raising."""
    gate = build_gate()

    result = transition_human_gate(
        gate,
        action=HumanGateAction.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=(CREATED_AT + timedelta(minutes=1)),
    )

    assert result.status is (HumanGateTransitionStatus.REJECTED)
    assert result.issue is (HumanGateIssueCode.INVALID_TRANSITION)
    assert result.gate is gate


def test_superseded_artifact_marks_approval_stale() -> None:
    """Invalidate approval when a new current artifact appears."""
    approved = transition_human_gate(
        submit_gate(build_gate()),
        action=HumanGateAction.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=(CREATED_AT + timedelta(minutes=2)),
    ).gate

    replacement = artifact(
        version=2,
        hash_character="b",
        artifact_id=(SECOND_ARTIFACT_ID),
    )

    result = mark_human_gate_stale(
        approved,
        current_artifact=replacement,
        occurred_at=(CREATED_AT + timedelta(minutes=3)),
    )

    assert result.status is (HumanGateTransitionStatus.APPLIED)
    assert result.gate.status is (HumanGateStatus.STALE)
    assert result.event is not None
    assert result.event.kind is (HumanGateEventKind.ARTIFACT_SUPERSEDED)
    assert result.event.actor_user_id is None
    assert result.event.artifact == replacement


def test_same_artifact_does_not_change_gate() -> None:
    """Keep a gate current while its exact artifact remains current."""
    gate = build_gate()

    result = mark_human_gate_stale(
        gate,
        current_artifact=gate.artifact,
        occurred_at=(CREATED_AT + timedelta(minutes=1)),
    )

    assert result.status is (HumanGateTransitionStatus.NO_CHANGE)
    assert result.gate is gate
    assert result.event is None


def test_stale_check_rejects_cross_project_artifact() -> None:
    """Prevent stale detection from crossing project scope."""
    result = mark_human_gate_stale(
        build_gate(),
        current_artifact=artifact(
            project_id=OTHER_PROJECT_ID,
            version=2,
            hash_character="b",
            artifact_id=(SECOND_ARTIFACT_ID),
        ),
        occurred_at=(CREATED_AT + timedelta(minutes=1)),
    )

    assert result.status is (HumanGateTransitionStatus.REJECTED)
    assert result.issue is (HumanGateIssueCode.ARTIFACT_SCOPE_MISMATCH)
