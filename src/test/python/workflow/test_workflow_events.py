"""Tests for typed, provenance-safe workflow event envelopes."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from orchestwin.projects.domain import ProjectMode
from orchestwin.workflow.events import (
    WorkflowEventType,
    create_workflow_event,
    deserialize_workflow_event_payload,
    serialize_workflow_event_payload,
)
from orchestwin.workflow.routing import advance_workflow_run, start_workflow_run
from orchestwin.workflow.runs import WorkflowRunStatus, WorkflowStage, create_workflow_run

PROJECT_ID = UUID("00000000-0000-4000-8000-000000010701")
OWNER_ID = UUID("00000000-0000-4000-8000-000000010702")
RUN_ID = UUID("00000000-0000-4000-8000-000000010703")
EVENT_ID = UUID("00000000-0000-4000-8000-000000010704")
GATE_ID = UUID("00000000-0000-4000-8000-000000010705")
NOW = datetime(2026, 8, 28, 23, 10, tzinfo=UTC)


def draft_run():
    return create_workflow_run(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        run_id=RUN_ID,
        created_at=NOW,
    )


def test_event_payload_is_canonical_typed_and_reasoning_free() -> None:
    draft = draft_run()
    running = start_workflow_run(draft, occurred_at=NOW + timedelta(seconds=1)).run
    event = create_workflow_event(
        running,
        previous_run=draft,
        event_type=WorkflowEventType.RUN_STARTED,
        sequence_number=1,
        occurred_at=NOW + timedelta(seconds=1),
        event_id=EVENT_ID,
    )
    payload_json = serialize_workflow_event_payload(event.payload)

    assert deserialize_workflow_event_payload(payload_json) == event.payload
    assert event.id == EVENT_ID
    assert event.payload.previous_status is WorkflowRunStatus.DRAFT
    assert "reasoning" not in payload_json
    assert "secret" not in payload_json


def test_waiting_event_requires_the_exact_pending_gate() -> None:
    running = start_workflow_run(
        draft_run(),
        occurred_at=NOW + timedelta(seconds=1),
    ).run
    waiting = advance_workflow_run(
        running,
        next_stage=WorkflowStage.BRIEF_APPROVAL,
        pending_gate_id=GATE_ID,
        occurred_at=NOW + timedelta(seconds=2),
    ).run
    event = create_workflow_event(
        waiting,
        previous_run=running,
        event_type=WorkflowEventType.WAITING_FOR_HUMAN,
        sequence_number=2,
        occurred_at=NOW + timedelta(seconds=2),
    )

    assert event.payload.pending_gate_id == GATE_ID
    assert event.payload.current_stage is WorkflowStage.BRIEF_APPROVAL

    try:
        create_workflow_event(
            replace(waiting, pending_gate_id=None, status=WorkflowRunStatus.RUNNING),
            previous_run=running,
            event_type=WorkflowEventType.WAITING_FOR_HUMAN,
            sequence_number=2,
            occurred_at=NOW + timedelta(seconds=2),
        )
    except ValueError as error:
        assert "WAITING_FOR_HUMAN" in str(error)
    else:
        raise AssertionError("waiting event without a pending gate must be rejected")


def test_budget_exhaustion_event_requires_explicit_human_pause_and_issue_code() -> None:
    running = start_workflow_run(
        draft_run(),
        occurred_at=NOW + timedelta(seconds=1),
    ).run
    paused = replace(
        running,
        status=WorkflowRunStatus.PAUSED_NEEDS_HUMAN,
        resume_status=WorkflowRunStatus.RUNNING,
        state_version=running.state_version + 1,
        updated_at=NOW + timedelta(seconds=2),
    )
    event = create_workflow_event(
        paused,
        previous_run=running,
        event_type=WorkflowEventType.BUDGET_EXHAUSTED,
        sequence_number=3,
        occurred_at=NOW + timedelta(seconds=2),
        issue_code="PROJECT_COST_LIMIT",
    )

    assert event.payload.issue_code == "PROJECT_COST_LIMIT"
    assert event.payload.current_status is WorkflowRunStatus.PAUSED_NEEDS_HUMAN
