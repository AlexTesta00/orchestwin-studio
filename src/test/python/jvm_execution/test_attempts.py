"""Tests for immutable JVM execution attempt identity and lineage."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from orchestwin.jvm_execution.attempts import JvmExecutionAttemptTrigger
from orchestwin.jvm_execution.evidence import JvmExecutionReportStatus
from orchestwin.jvm_execution.plans import JvmExecutionPhase

from .attempt_support import execution_attempt


def test_attempt_snapshot_is_stable_and_bound_to_complete_evidence() -> None:
    attempt = execution_attempt()

    assert len(attempt.content_hash) == 64
    assert attempt.to_snapshot()["content_hash"] == attempt.content_hash
    assert tuple(result.phase for result in attempt.report.phase_results) == tuple(
        JvmExecutionPhase
    )


def test_later_attempt_requires_exact_predecessor_and_non_initial_trigger() -> None:
    first = execution_attempt()
    second = execution_attempt(
        attempt_id=UUID("91000000-0000-4000-8000-000000000005"),
        attempt_number=2,
        previous_attempt_id=first.id,
        trigger=JvmExecutionAttemptTrigger.MANUAL_RERUN,
    )

    assert second.previous_attempt_id == first.id
    with pytest.raises(ValueError, match="INITIAL JVM trigger"):
        replace(second, trigger=JvmExecutionAttemptTrigger.INITIAL)


def test_executed_phase_cannot_be_not_run() -> None:
    attempt = execution_attempt()
    results = list(attempt.report.phase_results)
    result = results[0]
    results[0] = replace(
        result,
        status=result.status.NOT_RUN,
        started_at=None,
        completed_at=None,
        exit_codes=(),
    )

    with pytest.raises(ValueError, match="executed JVM phase"):
        replace(
            attempt,
            report=replace(
                attempt.report,
                status=JvmExecutionReportStatus.INCOMPLETE,
                phase_results=tuple(results),
            ),
        )
