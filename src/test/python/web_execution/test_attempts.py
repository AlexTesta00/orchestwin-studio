"""Tests for immutable Web execution-attempt identity and report binding."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.artifacts.web_sources import WebSourceRevisionReference
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

PROJECT_ID = UUID("30000000-0000-4000-8000-000000000001")
OWNER_ID = UUID("30000000-0000-4000-8000-000000000002")
ATTEMPT_ID = UUID("30000000-0000-4000-8000-000000000003")
STARTED_AT = datetime(2026, 8, 27, 11, 0, tzinfo=UTC)
COMPLETED_AT = STARTED_AT + timedelta(seconds=2)


def source_reference() -> WebSourceRevisionReference:
    return WebSourceRevisionReference(
        revision_id=UUID("30000000-0000-4000-8000-000000000004"),
        project_id=PROJECT_ID,
        version_number=1,
        content_hash="a" * 64,
        source_tree_hash="b" * 64,
    )


def phase_result(phase: WebExecutionPhase) -> WebPhaseResult:
    if phase is WebExecutionPhase.VALIDATE:
        return WebPhaseResult(
            phase=phase,
            status=WebPhaseResultStatus.PASSED,
            command_plan_hashes=(),
            started_at=STARTED_AT,
            completed_at=COMPLETED_AT,
            exit_codes=(),
            stdout_refs=(),
            stderr_refs=(),
            artifact_refs=(),
            findings=(),
            failure_category=None,
            failure_code=None,
            normalized_summary="Web project validation passed.",
        )
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


def report() -> WebExecutionReport:
    source = source_reference()
    return WebExecutionReport(
        source_revision_content_hash=source.content_hash,
        source_tree_hash=source.source_tree_hash,
        profile_id="web.static",
        profile_version="1.0.0",
        runner_image_digest="c" * 64,
        policy_content_hash="d" * 64,
        phase_results=tuple(phase_result(phase) for phase in WebExecutionPhase),
    )


def attempt() -> WebExecutionAttempt:
    return WebExecutionAttempt(
        id=ATTEMPT_ID,
        project_id=PROJECT_ID,
        created_by_user_id=OWNER_ID,
        attempt_number=1,
        previous_attempt_id=None,
        source_revision=source_reference(),
        profile_validation_content_hash="e" * 64,
        execution_plan_content_hash="f" * 64,
        trigger=WebExecutionAttemptTrigger.INITIAL,
        executed_phases=(WebExecutionPhase.VALIDATE,),
        report=report(),
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
    )


def test_attempt_hash_covers_source_profile_plan_and_report() -> None:
    candidate = attempt()

    assert len(candidate.content_hash) == 64
    assert candidate.to_snapshot()["content_hash"] == candidate.content_hash
    assert candidate.report.source_tree_hash == candidate.source_revision.source_tree_hash


def test_report_for_another_source_revision_is_rejected() -> None:
    mismatched = report()
    mismatched = WebExecutionReport(
        source_revision_content_hash="9" * 64,
        source_tree_hash=mismatched.source_tree_hash,
        profile_id=mismatched.profile_id,
        profile_version=mismatched.profile_version,
        runner_image_digest=mismatched.runner_image_digest,
        policy_content_hash=mismatched.policy_content_hash,
        phase_results=mismatched.phase_results,
    )

    with pytest.raises(ValueError, match="another source revision"):
        WebExecutionAttempt(
            id=ATTEMPT_ID,
            project_id=PROJECT_ID,
            created_by_user_id=OWNER_ID,
            attempt_number=1,
            previous_attempt_id=None,
            source_revision=source_reference(),
            profile_validation_content_hash="e" * 64,
            execution_plan_content_hash="f" * 64,
            trigger=WebExecutionAttemptTrigger.INITIAL,
            executed_phases=(WebExecutionPhase.VALIDATE,),
            report=mismatched,
            started_at=STARTED_AT,
            completed_at=COMPLETED_AT,
        )


def test_later_attempt_requires_predecessor_and_non_initial_trigger() -> None:
    with pytest.raises(ValueError, match="requires a predecessor"):
        WebExecutionAttempt(
            id=ATTEMPT_ID,
            project_id=PROJECT_ID,
            created_by_user_id=OWNER_ID,
            attempt_number=2,
            previous_attempt_id=None,
            source_revision=source_reference(),
            profile_validation_content_hash="e" * 64,
            execution_plan_content_hash="f" * 64,
            trigger=WebExecutionAttemptTrigger.MANUAL_RERUN,
            executed_phases=(WebExecutionPhase.VALIDATE,),
            report=report(),
            started_at=STARTED_AT,
            completed_at=COMPLETED_AT,
        )
