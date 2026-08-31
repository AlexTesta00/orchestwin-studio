"""Tests for append-only final-review persistence projections."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.projects.domain import ProjectMode
from orchestwin.workflow.final_review import (
    FinalReviewCheck,
    FinalReviewCheckKind,
    FinalReviewCheckStatus,
    create_final_review_assessment,
)
from orchestwin.workflow.final_review_persistence import (
    FinalReviewPersistenceConflict,
    InMemoryFinalReviewRepository,
    final_review_record_to_domain,
    final_review_to_record,
)
from orchestwin.workflow.routing import start_workflow_run
from orchestwin.workflow.runs import WorkflowStage, create_workflow_run

PROJECT_ID = UUID("00000000-0000-4000-8000-000000024101")
OWNER_ID = UUID("00000000-0000-4000-8000-000000024102")
RUN_ID = UUID("00000000-0000-4000-8000-000000024103")
NOW = datetime(2026, 8, 30, 23, 30, tzinfo=UTC)


def _review():
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
    return create_final_review_assessment(
        run,
        checks=checks,
        review_id=UUID("00000000-0000-4000-8000-000000024110"),
        created_at=NOW + timedelta(seconds=2),
    )


def test_record_round_trip_preserves_exact_final_review() -> None:
    review = _review()

    restored = final_review_record_to_domain(final_review_to_record(review))

    assert restored == review


def test_in_memory_repository_is_owner_scoped_and_append_only() -> None:
    async def scenario() -> None:
        repository = InMemoryFinalReviewRepository()
        review = _review()
        assert await repository.append(review) == review
        assert (
            await repository.get_owned(
                review_id=review.id,
                owner_user_id=OWNER_ID,
            )
            == review
        )
        assert (
            await repository.get_owned(
                review_id=review.id,
                owner_user_id=UUID("00000000-0000-4000-8000-000000024199"),
            )
            is None
        )
        with pytest.raises(FinalReviewPersistenceConflict):
            await repository.append(review)

    asyncio.run(scenario())
