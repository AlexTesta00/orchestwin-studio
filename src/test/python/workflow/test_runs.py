"""Tests for immutable durable project workflow-run state."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.projects.domain import ProjectMode
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionProfileReference,
)
from orchestwin.workflow.runs import (
    WorkflowArtifactReference,
    WorkflowBlockingIssue,
    WorkflowBlockingIssueSource,
    WorkflowCapabilityState,
    WorkflowRunStatus,
    WorkflowStage,
    create_workflow_run,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000010001")
OWNER_ID = UUID("00000000-0000-4000-8000-000000010002")
RUN_ID = UUID("00000000-0000-4000-8000-000000010003")
NOW = datetime(2026, 8, 28, 22, 0, tzinfo=UTC)


def test_create_workflow_run_starts_as_an_empty_durable_draft() -> None:
    run = create_workflow_run(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        run_id=RUN_ID,
        created_at=NOW,
    )

    assert run.id == RUN_ID
    assert run.current_stage is WorkflowStage.INTAKE
    assert run.status is WorkflowRunStatus.DRAFT
    assert run.state_version == 1
    assert run.checkpoint_sequence == 0
    assert run.started_at is None
    assert run.artifact_references == ()
    assert run.to_snapshot()["project_mode"] == "GREENFIELD_GENERATION"


def test_run_requires_canonical_versioned_artifact_references() -> None:
    run = create_workflow_run(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        created_at=NOW,
    )
    first = WorkflowArtifactReference(
        artifact_type="PROJECT_BRIEF",
        artifact_id=UUID("00000000-0000-4000-8000-000000010004"),
        version_number=1,
        content_hash="a" * 64,
    )
    second = WorkflowArtifactReference(
        artifact_type="AGENT_TEAM",
        artifact_id=UUID("00000000-0000-4000-8000-000000010005"),
        version_number=2,
        content_hash="b" * 64,
    )

    with pytest.raises(ValueError, match="canonical order"):
        replace(run, artifact_references=(first, second))

    ordered = replace(run, artifact_references=(second, first))
    assert [item.artifact_type for item in ordered.artifact_references] == [
        "AGENT_TEAM",
        "PROJECT_BRIEF",
    ]


def test_capability_state_keeps_level_and_profile_identity_together() -> None:
    profile = ExecutionProfileReference(
        profile_id="jvm.kotlin-gradle",
        profile_version="1.0.0",
        content_hash="c" * 64,
    )
    state = WorkflowCapabilityState(
        selected_profile=profile,
        capability_status=ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C,
        unsupported_requirements=("Automatic JVM execution is not validated.",),
        owner_decision_required=True,
    )

    assert state.to_snapshot()["capability_status"] == "DESIGN_ONLY_LEVEL_C"

    with pytest.raises(ValueError, match="supplied together"):
        WorkflowCapabilityState(selected_profile=profile)


def test_waiting_and_paused_states_preserve_exact_gate_resume_semantics() -> None:
    run = create_workflow_run(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        project_mode=ProjectMode.BROWNFIELD_ASSESSMENT,
        created_at=NOW,
    )
    gate_id = UUID("00000000-0000-4000-8000-000000010006")
    started = replace(
        run,
        status=WorkflowRunStatus.WAITING_FOR_HUMAN,
        current_stage=WorkflowStage.BRIEF_APPROVAL,
        pending_gate_id=gate_id,
        started_at=NOW,
    )
    paused = replace(
        started,
        status=WorkflowRunStatus.PAUSED,
        resume_status=WorkflowRunStatus.WAITING_FOR_HUMAN,
    )

    assert paused.pending_gate_id == gate_id
    assert paused.resume_status is WorkflowRunStatus.WAITING_FOR_HUMAN

    with pytest.raises(ValueError, match="pending gate"):
        replace(started, pending_gate_id=None)


def test_blocking_issues_are_typed_canonical_and_unique() -> None:
    issue = WorkflowBlockingIssue(
        code="BUDGET_LIMIT",
        source=WorkflowBlockingIssueSource.OPERATIONAL_LIMIT,
        summary="The project budget is exhausted.",
        recoverable=True,
    )
    run = create_workflow_run(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        created_at=NOW,
    )

    paused = replace(
        run,
        status=WorkflowRunStatus.PAUSED_NEEDS_HUMAN,
        resume_status=WorkflowRunStatus.RUNNING,
        blocking_issues=(issue,),
        started_at=NOW,
    )
    assert paused.blocking_issues == (issue,)

    with pytest.raises(ValueError, match="identities must be unique"):
        replace(paused, blocking_issues=(issue, issue))
