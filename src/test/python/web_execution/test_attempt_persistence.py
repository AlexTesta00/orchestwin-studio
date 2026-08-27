"""Tests for owner-scoped append-only Web execution-attempt persistence."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from orchestwin.artifacts.web_sources import WebSourceRevisionReference
from orchestwin.web_execution.attempt_persistence import (
    InMemoryWebExecutionAttemptRepository,
    WebExecutionAttemptAppendStatus,
    web_execution_attempt_from_record,
    web_execution_attempt_to_record,
)
from orchestwin.web_execution.attempts import (
    WebExecutionAttempt,
    WebExecutionAttemptTrigger,
)
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.reports import (
    WebExecutionReport,
    WebPhaseResult,
    WebPhaseResultStatus,
)

PROJECT_ID = UUID("30000000-0000-4000-8000-000000000101")
FOREIGN_PROJECT_ID = UUID("30000000-0000-4000-8000-000000000102")
OWNER_ID = UUID("30000000-0000-4000-8000-000000000103")
BASE_TIME = datetime(2026, 8, 27, 11, 30, tzinfo=UTC)


def create_attempt(*, attempt_id: UUID) -> WebExecutionAttempt:
    source = WebSourceRevisionReference(
        revision_id=UUID("30000000-0000-4000-8000-000000000199"),
        project_id=PROJECT_ID,
        version_number=1,
        content_hash="a" * 64,
        source_tree_hash="b" * 64,
    )
    report = WebExecutionReport(
        source_revision_content_hash=source.content_hash,
        source_tree_hash=source.source_tree_hash,
        profile_id="web.static",
        profile_version="1.0.0",
        runner_image_digest="c" * 64,
        policy_content_hash="d" * 64,
        phase_results=tuple(
            _passed_validation_result()
            if phase is WebExecutionPhase.VALIDATE
            else _skipped_result(phase)
            for phase in WebExecutionPhase
        ),
    )
    return WebExecutionAttempt(
        id=attempt_id,
        project_id=PROJECT_ID,
        created_by_user_id=OWNER_ID,
        attempt_number=1,
        previous_attempt_id=None,
        source_revision=source,
        profile_validation_content_hash="e" * 64,
        execution_plan_content_hash="f" * 64,
        trigger=WebExecutionAttemptTrigger.INITIAL,
        executed_phases=(WebExecutionPhase.VALIDATE,),
        report=report,
        started_at=BASE_TIME,
        completed_at=BASE_TIME + timedelta(seconds=2),
    )


def _passed_validation_result() -> WebPhaseResult:
    return WebPhaseResult(
        phase=WebExecutionPhase.VALIDATE,
        status=WebPhaseResultStatus.PASSED,
        command_plan_hashes=(),
        started_at=BASE_TIME,
        completed_at=BASE_TIME + timedelta(seconds=1),
        exit_codes=(),
        stdout_refs=(),
        stderr_refs=(),
        artifact_refs=(),
        findings=(),
        failure_category=None,
        failure_code=None,
        normalized_summary="Web project validation passed.",
    )


def _skipped_result(phase: WebExecutionPhase) -> WebPhaseResult:
    return WebPhaseResult(
        phase=phase,
        status=WebPhaseResultStatus.SKIPPED,
        command_plan_hashes=(),
        started_at=None,
        completed_at=None,
        exit_codes=(),
        stdout_refs=(),
        stderr_refs=(),
        artifact_refs=(),
        findings=(),
        failure_category=None,
        failure_code=None,
        normalized_summary="Phase is not required by this deterministic fixture.",
    )


def test_record_round_trip_revalidates_nested_report_and_projections() -> None:
    original = create_attempt(
        attempt_id=UUID("30000000-0000-4000-8000-000000000104"),
    )

    restored = web_execution_attempt_from_record(web_execution_attempt_to_record(original))

    assert restored == original
    assert restored.content_hash == original.content_hash


def test_in_memory_repository_is_idempotent_owner_scoped_and_linear() -> None:
    repository = InMemoryWebExecutionAttemptRepository(
        owner_user_id=OWNER_ID,
        project_ids=frozenset({PROJECT_ID}),
    )
    first = create_attempt(
        attempt_id=UUID("30000000-0000-4000-8000-000000000105"),
    )
    second = replace(
        first,
        id=UUID("30000000-0000-4000-8000-000000000106"),
        attempt_number=2,
        previous_attempt_id=first.id,
        trigger=WebExecutionAttemptTrigger.MANUAL_RERUN,
    )

    async def scenario() -> None:
        assert (await repository.append(first)).status is (WebExecutionAttemptAppendStatus.APPENDED)
        assert (await repository.append(first)).status is (
            WebExecutionAttemptAppendStatus.ALREADY_PRESENT
        )
        assert (await repository.append(second)).status is (
            WebExecutionAttemptAppendStatus.APPENDED
        )
        assert await repository.current(project_id=PROJECT_ID) == second
        assert await repository.history(project_id=PROJECT_ID) == (first, second)

    asyncio.run(scenario())


def test_repository_hides_foreign_project_and_rejects_non_next_attempt() -> None:
    hidden = InMemoryWebExecutionAttemptRepository(
        owner_user_id=OWNER_ID,
        project_ids=frozenset({FOREIGN_PROJECT_ID}),
    )
    candidate = create_attempt(
        attempt_id=UUID("30000000-0000-4000-8000-000000000107"),
    )
    visible = InMemoryWebExecutionAttemptRepository(
        owner_user_id=OWNER_ID,
        project_ids=frozenset({PROJECT_ID}),
    )
    conflicting = replace(
        candidate,
        id=UUID("30000000-0000-4000-8000-000000000108"),
        attempt_number=2,
        previous_attempt_id=candidate.id,
        trigger=WebExecutionAttemptTrigger.MANUAL_RERUN,
    )

    hidden_result = asyncio.run(hidden.append(candidate))
    conflict_result = asyncio.run(visible.append(conflicting))

    assert hidden_result.status is WebExecutionAttemptAppendStatus.PROJECT_NOT_FOUND
    assert conflict_result.status is WebExecutionAttemptAppendStatus.ATTEMPT_CONFLICT
