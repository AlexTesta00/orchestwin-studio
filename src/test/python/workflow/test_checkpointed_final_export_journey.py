"""End-to-end workflow tests from a durable final-review checkpoint to export."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.artifacts.export_archive import (
    assemble_final_export_archive,
    complete_workflow_after_export,
    validate_final_export_archive,
)
from orchestwin.artifacts.export_manifest import (
    ExportArtifactCategory,
    FinalExportEntry,
    FinalExportOmission,
    create_final_export_manifest,
)
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.requirements_primitives import canonical_json
from orchestwin.workflow.checkpoints import (
    WorkflowCheckpointRestoreStatus,
    create_workflow_checkpoint,
    restore_workflow_checkpoint,
)
from orchestwin.workflow.final_approval import (
    decide_final_output_gate,
    enter_final_approval_stage,
    resume_after_final_output_approval,
    submit_final_review_for_approval,
)
from orchestwin.workflow.final_review import (
    AcceptedFinalLimitation,
    FinalReviewCheck,
    FinalReviewCheckKind,
    FinalReviewCheckStatus,
    HumanValidationStatus,
    create_final_review_assessment,
)
from orchestwin.workflow.gates import HumanGateAction, HumanGateStatus
from orchestwin.workflow.routing import start_workflow_run
from orchestwin.workflow.runs import WorkflowRunStatus, WorkflowStage, create_workflow_run

PROJECT_ID = UUID("00000000-0000-4000-8000-000000030001")
OWNER_ID = UUID("00000000-0000-4000-8000-000000030002")
RUN_IDS = {
    ProjectMode.GREENFIELD_GENERATION: UUID("00000000-0000-4000-8000-000000030010"),
    ProjectMode.BROWNFIELD_ASSESSMENT: UUID("00000000-0000-4000-8000-000000030011"),
}
CHECKPOINT_IDS = {
    ProjectMode.GREENFIELD_GENERATION: UUID("00000000-0000-4000-8000-000000030020"),
    ProjectMode.BROWNFIELD_ASSESSMENT: UUID("00000000-0000-4000-8000-000000030021"),
}
NOW = datetime(2026, 8, 31, 5, 0, tzinfo=UTC)
LIMITATION_ID = "LIMIT-EMPIRICAL-VALIDATION"


def _checks() -> tuple[FinalReviewCheck, ...]:
    return tuple(
        sorted(
            (
                FinalReviewCheck(
                    check_id=f"FINAL-{index:02d}",
                    kind=kind,
                    status=FinalReviewCheckStatus.SATISFIED,
                    summary=f"The {kind.value} dimension is satisfied by recorded evidence.",
                    evidence_refs=(f"evidence:{kind.value.lower()}",),
                    blocking=True,
                )
                for index, kind in enumerate(FinalReviewCheckKind, start=1)
            ),
            key=lambda item: item.sort_key,
        )
    )


def _omissions() -> tuple[FinalExportOmission, ...]:
    return tuple(
        FinalExportOmission(
            category=category,
            reason=(
                "This focused workflow fixture records the category as an accepted test limitation."
            ),
            accepted_limitation_id=LIMITATION_ID,
        )
        for category in ExportArtifactCategory
        if category is not ExportArtifactCategory.FINAL_REVIEW
    )


@pytest.mark.parametrize(
    "project_mode",
    [ProjectMode.GREENFIELD_GENERATION, ProjectMode.BROWNFIELD_ASSESSMENT],
)
def test_checkpointed_final_review_gate8_and_export_journey(project_mode: ProjectMode) -> None:
    """Recover exact state, approve Gate 8, and produce a reproducible final ZIP."""
    run_id = RUN_IDS[project_mode]
    draft = create_workflow_run(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        project_mode=project_mode,
        run_id=run_id,
        created_at=NOW,
    )
    running = start_workflow_run(draft, occurred_at=NOW + timedelta(seconds=1)).run
    final_review_run = replace(
        running,
        current_stage=WorkflowStage.FINAL_REVIEW,
        latest_execution_attempt_id=UUID("00000000-0000-4000-8000-000000030030"),
        latest_evaluation_run_id=UUID("00000000-0000-4000-8000-000000030031"),
        updated_at=NOW + timedelta(seconds=2),
    )
    checkpointed = create_workflow_checkpoint(
        final_review_run,
        created_at=NOW + timedelta(seconds=2),
        checkpoint_id=CHECKPOINT_IDS[project_mode],
    )

    restored = restore_workflow_checkpoint(
        checkpointed.checkpoint,
        expected_run_id=run_id,
        expected_project_id=PROJECT_ID,
        expected_owner_user_id=OWNER_ID,
        minimum_state_version=final_review_run.state_version,
    )
    assert restored.status is WorkflowCheckpointRestoreStatus.RESTORED
    assert restored.run == checkpointed.run
    assert restored.run is not None

    review = create_final_review_assessment(
        restored.run,
        checks=_checks(),
        accepted_limitations=(
            AcceptedFinalLimitation(
                LIMITATION_ID,
                "Owner approval remains distinct from empirical target-user validation.",
                "The export preserves this methodological limitation explicitly.",
            ),
        ),
        evaluation_aggregation_hash="a" * 64,
        human_validation_status=HumanValidationStatus.PLANNED,
        review_id=UUID(
            "00000000-0000-4000-8000-000000030040"
            if project_mode is ProjectMode.GREENFIELD_GENERATION
            else "00000000-0000-4000-8000-000000030041"
        ),
        created_at=NOW + timedelta(seconds=3),
    )
    submitted = submit_final_review_for_approval(
        review,
        gate_id=UUID(
            "00000000-0000-4000-8000-000000030050"
            if project_mode is ProjectMode.GREENFIELD_GENERATION
            else "00000000-0000-4000-8000-000000030051"
        ),
        event_id=UUID(
            "00000000-0000-4000-8000-000000030060"
            if project_mode is ProjectMode.GREENFIELD_GENERATION
            else "00000000-0000-4000-8000-000000030061"
        ),
        occurred_at=NOW + timedelta(seconds=4),
    )
    waiting = enter_final_approval_stage(
        restored.run,
        gate=submitted.gate,
        occurred_at=NOW + timedelta(seconds=4),
    )
    decision_event_id = UUID(
        "00000000-0000-4000-8000-000000030070"
        if project_mode is ProjectMode.GREENFIELD_GENERATION
        else "00000000-0000-4000-8000-000000030071"
    )
    approved = decide_final_output_gate(
        submitted.gate,
        current_review=review,
        action=HumanGateAction.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=NOW + timedelta(seconds=5),
        event_id=decision_event_id,
    )
    assert approved.gate.status is HumanGateStatus.APPROVED
    exporting = resume_after_final_output_approval(
        waiting,
        gate=approved.gate,
        occurred_at=NOW + timedelta(seconds=6),
    )

    review_content = canonical_json(review.to_snapshot()).encode("utf-8")
    entry = FinalExportEntry(
        path="reports/final-review.json",
        category=ExportArtifactCategory.FINAL_REVIEW,
        artifact_id=review.id,
        artifact_version=review.version_number,
        content_hash=hashlib.sha256(review_content).hexdigest(),
        media_type="application/json",
        size_bytes=len(review_content),
        required=True,
    )
    manifest = create_final_export_manifest(
        review,
        approved_gate=approved.gate,
        approval_event_id=decision_event_id,
        entries=(entry,),
        omissions=_omissions(),
        manifest_id=UUID(
            "00000000-0000-4000-8000-000000030080"
            if project_mode is ProjectMode.GREENFIELD_GENERATION
            else "00000000-0000-4000-8000-000000030081"
        ),
        created_at=NOW + timedelta(seconds=7),
    )
    contents = {entry.path: review_content}
    first = assemble_final_export_archive(
        manifest,
        content_by_path=contents,
        archive_id=UUID(
            "00000000-0000-4000-8000-000000030090"
            if project_mode is ProjectMode.GREENFIELD_GENERATION
            else "00000000-0000-4000-8000-000000030091"
        ),
        created_at=NOW + timedelta(seconds=8),
    )
    second = assemble_final_export_archive(
        manifest,
        content_by_path=contents,
        archive_id=UUID(
            "00000000-0000-4000-8000-000000030092"
            if project_mode is ProjectMode.GREENFIELD_GENERATION
            else "00000000-0000-4000-8000-000000030093"
        ),
        created_at=NOW + timedelta(seconds=9),
    )

    assert first.archive_bytes == second.archive_bytes
    assert first.archive_hash == second.archive_hash
    validate_final_export_archive(manifest, archive_bytes=first.archive_bytes)
    completed = complete_workflow_after_export(
        exporting,
        archive=first,
        occurred_at=NOW + timedelta(seconds=10),
    )

    assert completed.status is WorkflowRunStatus.APPROVED
    assert completed.current_stage is WorkflowStage.EXPORT
    assert manifest.owner_approval_is_empirical_validation is False
    assert "not empirical evidence" in manifest.synthetic_feedback_disclaimer
