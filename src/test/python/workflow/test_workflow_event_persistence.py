"""Tests for ordered, replayable workflow event persistence."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from orchestwin.projects.domain import ProjectMode
from orchestwin.workflow.event_persistence import (
    InMemoryWorkflowEventRepository,
    WorkflowEventAppendStatus,
    workflow_event_record_to_domain,
    workflow_event_to_record,
)
from orchestwin.workflow.events import WorkflowEventType, create_workflow_event
from orchestwin.workflow.routing import start_workflow_run
from orchestwin.workflow.runs import create_workflow_run

PROJECT_ID = UUID("00000000-0000-4000-8000-000000010801")
OWNER_ID = UUID("00000000-0000-4000-8000-000000010802")
RUN_ID = UUID("00000000-0000-4000-8000-000000010803")
EVENT_ID = UUID("00000000-0000-4000-8000-000000010804")
NOW = datetime(2026, 8, 28, 23, 20, tzinfo=UTC)


def event_fixture():
    draft = create_workflow_run(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        run_id=RUN_ID,
        created_at=NOW,
    )
    running = start_workflow_run(draft, occurred_at=NOW + timedelta(seconds=1)).run
    event = create_workflow_event(
        running,
        previous_run=draft,
        event_type=WorkflowEventType.RUN_STARTED,
        sequence_number=1,
        occurred_at=NOW + timedelta(seconds=1),
        event_id=EVENT_ID,
    )
    return event


def test_event_record_round_trip_verifies_canonical_payload_hash() -> None:
    event = event_fixture()

    assert workflow_event_record_to_domain(workflow_event_to_record(event)) == event


def test_repository_enforces_sequence_idempotence_and_replay_cursor() -> None:
    async def scenario() -> None:
        repository = InMemoryWorkflowEventRepository(
            owner_user_id=OWNER_ID,
            run_projects={RUN_ID: PROJECT_ID},
        )
        event = event_fixture()
        appended = await repository.append(event, expected_previous_sequence=0)
        repeated = await repository.append(event, expected_previous_sequence=0)
        stale = await repository.append(event, expected_previous_sequence=1)

        assert appended.status is WorkflowEventAppendStatus.APPENDED
        assert repeated.status is WorkflowEventAppendStatus.ALREADY_PRESENT
        assert stale.status is WorkflowEventAppendStatus.SEQUENCE_CONFLICT
        assert await repository.list_after(run_id=RUN_ID, after_sequence=0) == (event,)
        assert await repository.list_after(run_id=RUN_ID, after_sequence=1) == ()

    asyncio.run(scenario())


def test_repository_hides_events_from_a_different_owner_scope() -> None:
    async def scenario() -> None:
        repository = InMemoryWorkflowEventRepository(
            owner_user_id=UUID("00000000-0000-4000-8000-000000010899"),
            run_projects={RUN_ID: PROJECT_ID},
        )
        result = await repository.append(event_fixture(), expected_previous_sequence=0)

        assert result.status is WorkflowEventAppendStatus.RUN_NOT_FOUND
        assert await repository.list_after(run_id=RUN_ID) == ()

    asyncio.run(scenario())
