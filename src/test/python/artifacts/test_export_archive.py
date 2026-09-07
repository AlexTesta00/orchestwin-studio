"""Tests for secure reproducible final ZIP assembly and completion."""

from __future__ import annotations

import hashlib
import io
import zipfile
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
from orchestwin.workflow.runs import WorkflowRunStatus, WorkflowStage, create_workflow_run

PROJECT_ID = UUID("00000000-0000-4000-8000-000000026001")
OWNER_ID = UUID("00000000-0000-4000-8000-000000026002")
RUN_ID = UUID("00000000-0000-4000-8000-000000026003")
NOW = datetime(2026, 8, 31, 1, 0, tzinfo=UTC)
CONTENT = b'{"status":"approved"}\n'
PATH = "reports/final-review.json"


def _manifest_and_run():
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
                "Focused fixture omits unrelated artifact categories.",
                "Every omission remains explicit in the manifest.",
            ),
        ),
        review_id=UUID("00000000-0000-4000-8000-000000026010"),
        created_at=NOW + timedelta(seconds=2),
    )
    submitted = submit_final_review_for_approval(
        review,
        gate_id=UUID("00000000-0000-4000-8000-000000026011"),
        event_id=UUID("00000000-0000-4000-8000-000000026012"),
        occurred_at=NOW + timedelta(seconds=3),
    )
    approved = transition_human_gate(
        submitted.gate,
        action=HumanGateAction.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=NOW + timedelta(seconds=4),
        event_id=UUID("00000000-0000-4000-8000-000000026013"),
    )
    entry = FinalExportEntry(
        path=PATH,
        category=ExportArtifactCategory.FINAL_REVIEW,
        artifact_id=review.id,
        artifact_version=review.version_number,
        content_hash=hashlib.sha256(CONTENT).hexdigest(),
        media_type="application/json",
        size_bytes=len(CONTENT),
        required=True,
    )
    omissions = tuple(
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
    manifest = create_final_export_manifest(
        review,
        approved_gate=approved.gate,
        approval_event_id=UUID("00000000-0000-4000-8000-000000026013"),
        entries=(entry,),
        omissions=omissions,
        manifest_id=UUID("00000000-0000-4000-8000-000000026014"),
        created_at=NOW + timedelta(seconds=5),
    )
    export_run = replace(
        run,
        current_stage=WorkflowStage.EXPORT,
        updated_at=NOW + timedelta(seconds=5),
    )
    return manifest, export_run


def test_two_assemblies_of_the_same_state_are_byte_identical() -> None:
    manifest, run = _manifest_and_run()
    kwargs = dict(
        content_by_path={PATH: CONTENT},
        archive_id=UUID("00000000-0000-4000-8000-000000026020"),
        created_at=NOW + timedelta(seconds=6),
    )

    first = assemble_final_export_archive(manifest, **kwargs)
    second = assemble_final_export_archive(manifest, **kwargs)

    assert first.archive_bytes == second.archive_bytes
    assert first.archive_hash == second.archive_hash
    validate_final_export_archive(manifest, archive_bytes=first.archive_bytes)
    completed = complete_workflow_after_export(
        run,
        archive=first,
        occurred_at=NOW + timedelta(seconds=7),
    )
    assert completed.status is WorkflowRunStatus.APPROVED


def test_archive_rejects_content_not_matching_the_manifest() -> None:
    manifest, _ = _manifest_and_run()

    with pytest.raises(ValueError, match="hash does not match"):
        assemble_final_export_archive(
            manifest,
            content_by_path={PATH: b"X" + CONTENT[1:]},
            created_at=NOW + timedelta(seconds=6),
        )


def test_verifier_rejects_symbolic_link_metadata() -> None:
    manifest, _ = _manifest_and_run()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", b"{}")
        link = zipfile.ZipInfo(PATH)
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        archive.writestr(link, b"target")

    with pytest.raises(ValueError):
        validate_final_export_archive(manifest, archive_bytes=output.getvalue())
