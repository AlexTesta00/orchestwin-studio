"""Tests for canonical versioned workflow checkpoints."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.projects.domain import ProjectMode
from orchestwin.workflow.checkpoints import (
    WORKFLOW_CHECKPOINT_SCHEMA_VERSION,
    WorkflowCheckpointRestoreStatus,
    create_workflow_checkpoint,
    restore_workflow_checkpoint,
)
from orchestwin.workflow.routing import start_workflow_run
from orchestwin.workflow.runs import create_workflow_run

PROJECT_ID = UUID("00000000-0000-4000-8000-000000010301")
OWNER_ID = UUID("00000000-0000-4000-8000-000000010302")
RUN_ID = UUID("00000000-0000-4000-8000-000000010303")
FIRST_ID = UUID("00000000-0000-4000-8000-000000010304")
SECOND_ID = UUID("00000000-0000-4000-8000-000000010305")
NOW = datetime(2026, 8, 28, 22, 30, tzinfo=UTC)


def running_run():
    draft = create_workflow_run(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        run_id=RUN_ID,
        created_at=NOW,
    )
    result = start_workflow_run(draft, occurred_at=NOW + timedelta(seconds=1))
    return result.run


def test_checkpoint_creation_is_canonical_linear_and_restorable() -> None:
    first = create_workflow_checkpoint(
        running_run(),
        created_at=NOW + timedelta(seconds=2),
        checkpoint_id=FIRST_ID,
    )
    second = create_workflow_checkpoint(
        first.run,
        created_at=NOW + timedelta(seconds=3),
        previous_checkpoint=first.checkpoint,
        checkpoint_id=SECOND_ID,
    )

    assert first.checkpoint.schema_version == WORKFLOW_CHECKPOINT_SCHEMA_VERSION
    assert first.checkpoint.sequence_number == 1
    assert second.checkpoint.sequence_number == 2
    assert second.checkpoint.parent_checkpoint_id == FIRST_ID
    assert second.run.checkpoint_sequence == 2
    assert " " not in second.checkpoint.payload_json

    restored = restore_workflow_checkpoint(
        second.checkpoint,
        expected_run_id=RUN_ID,
        expected_project_id=PROJECT_ID,
        expected_owner_user_id=OWNER_ID,
    )
    assert restored.status is WorkflowCheckpointRestoreStatus.RESTORED
    assert restored.run == second.run


def test_corrupted_payload_is_rejected_instead_of_silently_restored() -> None:
    created = create_workflow_checkpoint(
        running_run(),
        created_at=NOW + timedelta(seconds=2),
        checkpoint_id=FIRST_ID,
    )
    corrupted = replace(created.checkpoint, payload_json=created.checkpoint.payload_json + " ")

    result = restore_workflow_checkpoint(
        corrupted,
        expected_run_id=RUN_ID,
        expected_project_id=PROJECT_ID,
        expected_owner_user_id=OWNER_ID,
    )

    assert result.status is WorkflowCheckpointRestoreStatus.CORRUPTED
    assert result.run is None


def test_unknown_schema_and_stale_state_are_explicit_restore_outcomes() -> None:
    created = create_workflow_checkpoint(
        running_run(),
        created_at=NOW + timedelta(seconds=2),
        checkpoint_id=FIRST_ID,
    )
    incompatible = replace(created.checkpoint, schema_version=99)

    schema_result = restore_workflow_checkpoint(
        incompatible,
        expected_run_id=RUN_ID,
        expected_project_id=PROJECT_ID,
        expected_owner_user_id=OWNER_ID,
    )
    stale_result = restore_workflow_checkpoint(
        created.checkpoint,
        expected_run_id=RUN_ID,
        expected_project_id=PROJECT_ID,
        expected_owner_user_id=OWNER_ID,
        minimum_state_version=created.checkpoint.state_version + 1,
    )

    assert schema_result.status is WorkflowCheckpointRestoreStatus.UNSUPPORTED_SCHEMA
    assert stale_result.status is WorkflowCheckpointRestoreStatus.STALE_STATE


def test_cross_owner_checkpoint_restore_is_rejected_before_payload_use() -> None:
    created = create_workflow_checkpoint(
        running_run(),
        created_at=NOW + timedelta(seconds=2),
        checkpoint_id=FIRST_ID,
    )

    result = restore_workflow_checkpoint(
        created.checkpoint,
        expected_run_id=RUN_ID,
        expected_project_id=PROJECT_ID,
        expected_owner_user_id=UUID("00000000-0000-4000-8000-000000010399"),
    )

    assert result.status is WorkflowCheckpointRestoreStatus.OWNER_MISMATCH


def test_checkpoint_lineage_must_match_the_run_sequence() -> None:
    first = create_workflow_checkpoint(
        running_run(),
        created_at=NOW + timedelta(seconds=2),
        checkpoint_id=FIRST_ID,
    )

    with pytest.raises(ValueError, match="sequence does not match"):
        create_workflow_checkpoint(
            replace(first.run, checkpoint_sequence=0),
            created_at=NOW + timedelta(seconds=3),
            previous_checkpoint=first.checkpoint,
            checkpoint_id=SECOND_ID,
        )
