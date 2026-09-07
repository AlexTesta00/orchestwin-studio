"""Tests for immutable versioned final-review assessments."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.projects.domain import ProjectMode
from orchestwin.workflow.final_review import (
    AcceptedFinalLimitation,
    FinalReviewCheck,
    FinalReviewCheckKind,
    FinalReviewCheckStatus,
    FinalReviewIssue,
    FinalReviewIssueSeverity,
    HumanValidationStatus,
    create_final_review_assessment,
)
from orchestwin.workflow.routing import start_workflow_run
from orchestwin.workflow.runs import WorkflowStage, create_workflow_run

PROJECT_ID = UUID("00000000-0000-4000-8000-000000023001")
OWNER_ID = UUID("00000000-0000-4000-8000-000000023002")
RUN_ID = UUID("00000000-0000-4000-8000-000000023003")
REVIEW_IDS = (
    UUID("00000000-0000-4000-8000-000000023010"),
    UUID("00000000-0000-4000-8000-000000023011"),
)
NOW = datetime(2026, 8, 30, 22, 0, tzinfo=UTC)


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
        latest_execution_attempt_id=UUID("00000000-0000-4000-8000-000000023020"),
        latest_evaluation_run_id=UUID("00000000-0000-4000-8000-000000023021"),
        updated_at=NOW + timedelta(seconds=2),
    )


def _checks(
    *,
    failed_kind: FinalReviewCheckKind | None = None,
) -> tuple[FinalReviewCheck, ...]:
    checks = []
    for index, kind in enumerate(FinalReviewCheckKind, start=1):
        failed = kind is failed_kind
        checks.append(
            FinalReviewCheck(
                check_id=f"FRC-{index:02d}",
                kind=kind,
                status=(
                    FinalReviewCheckStatus.NOT_SATISFIED
                    if failed
                    else FinalReviewCheckStatus.SATISFIED
                ),
                summary=f"Review dimension {kind.value} was inspected.",
                evidence_refs=(f"evidence:{kind.value.lower()}",),
                blocking=failed or kind is not FinalReviewCheckKind.HUMAN_VALIDATION,
            )
        )
    return tuple(sorted(checks, key=lambda item: item.sort_key))


def test_final_review_is_ready_only_when_required_checks_and_major_issues_are_clear() -> None:
    review = create_final_review_assessment(
        _run(),
        checks=_checks(),
        accepted_limitations=(
            AcceptedFinalLimitation(
                "LIMIT-001",
                "Empirical target-user validation is not part of this owner approval.",
                "The limitation remains explicit in the thesis evidence package.",
            ),
        ),
        evaluation_aggregation_hash="a" * 64,
        human_validation_status=HumanValidationStatus.PLANNED,
        review_id=REVIEW_IDS[0],
        created_at=NOW + timedelta(seconds=3),
    )

    assert review.ready_for_gate8 is True
    assert review.blocking_check_ids == ()
    assert review.blocking_issue_ids == ()
    assert review.owner_approval_is_empirical_validation is False
    assert review.to_snapshot()["owner_approval_is_empirical_validation"] is False


def test_unsatisfied_check_or_major_issue_blocks_gate8() -> None:
    failed = create_final_review_assessment(
        _run(),
        checks=_checks(failed_kind=FinalReviewCheckKind.EXECUTION_EVIDENCE),
        unresolved_issues=(
            FinalReviewIssue(
                "FINAL-001",
                FinalReviewIssueSeverity.MAJOR,
                "The latest execution report contains a failing primary task.",
                "execution:latest",
            ),
        ),
        evaluation_aggregation_hash="b" * 64,
        review_id=REVIEW_IDS[0],
        created_at=NOW + timedelta(seconds=3),
    )

    assert failed.ready_for_gate8 is False
    assert failed.blocking_check_ids == ("FRC-04",)
    assert failed.blocking_issue_ids == ("FINAL-001",)


def test_final_review_versions_preserve_exact_parent_identity() -> None:
    first = create_final_review_assessment(
        _run(),
        checks=_checks(),
        evaluation_aggregation_hash="c" * 64,
        review_id=REVIEW_IDS[0],
        created_at=NOW + timedelta(seconds=3),
    )
    second = create_final_review_assessment(
        replace(_run(), state_version=4),
        checks=_checks(),
        evaluation_aggregation_hash="d" * 64,
        previous_review=first,
        review_id=REVIEW_IDS[1],
        created_at=NOW + timedelta(seconds=4),
    )

    assert second.version_number == 2
    assert second.parent_review_id == first.id
    assert second.parent_content_hash == first.content_hash
    assert second.content_hash != first.content_hash


def test_review_rejects_missing_required_dimension() -> None:
    with pytest.raises(ValueError, match="exactly one check"):
        create_final_review_assessment(
            _run(),
            checks=_checks()[:-1],
            evaluation_aggregation_hash="e" * 64,
            review_id=REVIEW_IDS[0],
            created_at=NOW + timedelta(seconds=3),
        )


def test_review_rejects_cross_scope_parent() -> None:
    first = create_final_review_assessment(
        _run(),
        checks=_checks(),
        evaluation_aggregation_hash="f" * 64,
        review_id=REVIEW_IDS[0],
        created_at=NOW + timedelta(seconds=3),
    )
    other_run = replace(_run(), id=UUID("00000000-0000-4000-8000-000000023099"))

    with pytest.raises(ValueError, match="share project, run, and owner"):
        create_final_review_assessment(
            other_run,
            checks=_checks(),
            evaluation_aggregation_hash="1" * 64,
            previous_review=first,
            review_id=REVIEW_IDS[1],
            created_at=NOW + timedelta(seconds=4),
        )
