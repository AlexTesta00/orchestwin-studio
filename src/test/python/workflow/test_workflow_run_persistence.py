"""Tests for workflow run and checkpoint persistence contracts."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from orchestwin.projects.domain import ProjectMode
from orchestwin.workflow.checkpoints import create_workflow_checkpoint
from orchestwin.workflow.routing import start_workflow_run
from orchestwin.workflow.run_persistence import (
    InMemoryWorkflowRunRepository,
    WorkflowRunStoreStatus,
    checkpoint_record_to_domain,
    checkpoint_to_record,
    workflow_run_record_to_domain,
    workflow_run_to_record,
)
from orchestwin.workflow.runs import create_workflow_run

PROJECT_ID = UUID("00000000-0000-4000-8000-000000010401")
OWNER_ID = UUID("00000000-0000-4000-8000-000000010402")
RUN_ID = UUID("00000000-0000-4000-8000-000000010403")
CHECKPOINT_ID = UUID("00000000-0000-4000-8000-000000010404")
NOW = datetime(2026, 8, 28, 22, 40, tzinfo=UTC)


def draft_run():
    return create_workflow_run(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        run_id=RUN_ID,
        created_at=NOW,
    )


def test_record_projections_round_trip_canonical_domain_state() -> None:
    run = draft_run()
    record = workflow_run_to_record(run)

    assert workflow_run_record_to_domain(record) == run

    started = start_workflow_run(run, occurred_at=NOW + timedelta(seconds=1)).run
    creation = create_workflow_checkpoint(
        started,
        created_at=NOW + timedelta(seconds=2),
        checkpoint_id=CHECKPOINT_ID,
    )
    checkpoint_record = checkpoint_to_record(creation.checkpoint)
    assert checkpoint_record_to_domain(checkpoint_record) == creation.checkpoint


def test_in_memory_repository_applies_checkpoint_with_compare_and_set() -> None:
    async def scenario() -> None:
        repository = InMemoryWorkflowRunRepository(
            owner_user_id=OWNER_ID,
            project_ids=frozenset({PROJECT_ID}),
        )
        created = await repository.create(draft_run())
        assert created.status is WorkflowRunStoreStatus.CREATED

        started = start_workflow_run(created.run, occurred_at=NOW + timedelta(seconds=1)).run
        creation = create_workflow_checkpoint(
            started,
            created_at=NOW + timedelta(seconds=2),
            checkpoint_id=CHECKPOINT_ID,
        )
        saved = await repository.save_checkpoint(previous_run=created.run, creation=creation)
        stale = await repository.save_checkpoint(previous_run=created.run, creation=creation)

        assert saved.status is WorkflowRunStoreStatus.UPDATED
        assert stale.status is WorkflowRunStoreStatus.STATE_CONFLICT
        assert await repository.list_checkpoints(run_id=RUN_ID) == (creation.checkpoint,)

    asyncio.run(scenario())


def test_owner_scope_hides_cross_owner_or_unknown_projects() -> None:
    async def scenario() -> None:
        repository = InMemoryWorkflowRunRepository(
            owner_user_id=OWNER_ID,
            project_ids=frozenset({PROJECT_ID}),
        )
        foreign = replace(
            draft_run(),
            owner_user_id=UUID("00000000-0000-4000-8000-000000010499"),
        )
        result = await repository.create(foreign)

        assert result.status is WorkflowRunStoreStatus.PROJECT_NOT_FOUND
        assert await repository.get_owned(run_id=foreign.id) is None

    asyncio.run(scenario())
