"""Tests for exact deterministic final-export manifests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.artifacts.export_manifest import (
    ExportArtifactCategory,
    FinalExportEntry,
    FinalExportOmission,
    create_final_export_manifest,
)
from orchestwin.projects.domain import ProjectMode
from orchestwin.workflow.final_approval import submit_final_review_for_approval
from orchestwin.workflow.final_review import (
    AcceptedFinalLimitation,
    FinalReviewCheck,
    FinalReviewCheckKind,
    FinalReviewCheckStatus,
    create_final_review_assessment,
)
from orchestwin.workflow.gates import HumanGateAction, transition_human_gate
from orchestwin.workflow.routing import start_workflow_run
from orchestwin.workflow.runs import WorkflowStage, create_workflow_run

PROJECT_ID = UUID("00000000-0000-4000-8000-000000025001")
OWNER_ID = UUID("00000000-0000-4000-8000-000000025002")
RUN_ID = UUID("00000000-0000-4000-8000-000000025003")
REVIEW_ID = UUID("00000000-0000-4000-8000-000000025010")
GATE_ID = UUID("00000000-0000-4000-8000-000000025011")
EVENT_IDS = (
    UUID("00000000-0000-4000-8000-000000025020"),
    UUID("00000000-0000-4000-8000-000000025021"),
)
MANIFEST_ID = UUID("00000000-0000-4000-8000-000000025030")
NOW = datetime(2026, 8, 31, 0, 0, tzinfo=UTC)


def _review_and_gate():
    draft = create_workflow_run(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        run_id=RUN_ID,
        created_at=NOW,
    )
    run = start_workflow_run(draft, occurred_at=NOW + timedelta(seconds=1)).run
    run = replace(run, current_stage=WorkflowStage.FINAL_REVIEW)
    checks = tuple(
        sorted(
            (
                FinalReviewCheck(
                    check_id=f"FRC-{index:02d}",
                    kind=kind,
                    status=FinalReviewCheckStatus.SATISFIED,
                    summary=f"{kind.value} was inspected.",
                    evidence_refs=(),
                    blocking=False,
                )
                for index, kind in enumerate(FinalReviewCheckKind, start=1)
            ),
            key=lambda item: item.sort_key,
        )
    )
    review = create_final_review_assessment(
        run,
        checks=checks,
        accepted_limitations=(
            AcceptedFinalLimitation(
                "LIMIT-001",
                "Empirical target-user validation is outside this owner approval.",
                "The limitation remains visible in the export.",
            ),
        ),
        review_id=REVIEW_ID,
        created_at=NOW + timedelta(seconds=2),
    )
    submitted = submit_final_review_for_approval(
        review,
        gate_id=GATE_ID,
        event_id=EVENT_IDS[0],
        occurred_at=NOW + timedelta(seconds=3),
    )
    approved = transition_human_gate(
        submitted.gate,
        action=HumanGateAction.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=NOW + timedelta(seconds=4),
        event_id=EVENT_IDS[1],
    )
    return review, approved.gate


def _entry(path: str = "reports/final-review.json") -> FinalExportEntry:
    return FinalExportEntry(
        path=path,
        category=ExportArtifactCategory.FINAL_REVIEW,
        artifact_id=REVIEW_ID,
        artifact_version=1,
        content_hash="a" * 64,
        media_type="application/json",
        size_bytes=128,
        required=True,
    )


def _omissions() -> tuple[FinalExportOmission, ...]:
    return tuple(
        sorted(
            (
                FinalExportOmission(
                    category,
                    f"{category.value} is not produced by this focused fixture.",
                    "LIMIT-001",
                )
                for category in ExportArtifactCategory
                if category is not ExportArtifactCategory.FINAL_REVIEW
            ),
            key=lambda item: item.sort_key,
        )
    )


def test_same_approved_state_produces_the_same_manifest_hash() -> None:
    review, gate = _review_and_gate()
    arguments = dict(
        approved_gate=gate,
        approval_event_id=EVENT_IDS[1],
        entries=(_entry(),),
        omissions=_omissions(),
        manifest_id=MANIFEST_ID,
        created_at=NOW + timedelta(seconds=5),
    )

    first = create_final_export_manifest(review, **arguments)
    second = create_final_export_manifest(review, **arguments)

    assert first == second
    assert first.content_hash == second.content_hash
    assert first.owner_approval_is_empirical_validation is False
    assert "not empirical evidence" in first.synthetic_feedback_disclaimer


def test_manifest_rejects_a_gate_for_another_review() -> None:
    review, gate = _review_and_gate()
    wrong_gate = replace(gate, artifact=replace(gate.artifact, content_hash="b" * 64))

    with pytest.raises(ValueError, match="exact final-review version"):
        create_final_export_manifest(
            review,
            approved_gate=wrong_gate,
            approval_event_id=EVENT_IDS[1],
            entries=(_entry(),),
            omissions=_omissions(),
            manifest_id=MANIFEST_ID,
            created_at=NOW + timedelta(seconds=5),
        )


@pytest.mark.parametrize(
    "path",
    ("../secret.txt", "/absolute.txt", "C:/windows.txt", "folder\\item.txt", "manifest.json"),
)
def test_manifest_rejects_unsafe_or_reserved_paths(path: str) -> None:
    with pytest.raises(ValueError):
        _entry(path)
