"""Tests for normalized JVM evidence and stable failure signatures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from orchestwin.jvm_execution.evidence import (
    JvmEvidenceReference,
    JvmExecutionReportStatus,
    JvmFailureCategory,
    JvmPhaseResult,
    JvmPhaseResultStatus,
    create_jvm_execution_report,
    failure_signature_for,
    normalize_jvm_message,
)
from orchestwin.jvm_execution.plans import (
    JvmExecutionPhase,
    create_jvm_execution_plan_bundle,
)
from orchestwin.jvm_execution.targets import selection_for
from orchestwin.sandbox.execution_profiles import ExecutionTarget

START = datetime(2026, 8, 28, 10, 0, tzinfo=UTC)
END = START + timedelta(seconds=2)


def ref(digest: str = "a" * 64) -> JvmEvidenceReference:
    return JvmEvidenceReference(
        storage_key=f"sha256/{digest[:2]}/{digest}",
        sha256_digest=digest,
        size_bytes=120,
        media_type="text/plain",
    )


def result(
    bundle,
    phase: JvmExecutionPhase,
    status: JvmPhaseResultStatus = JvmPhaseResultStatus.PASSED,
    *,
    summary: str = "JVM phase completed.",
) -> JvmPhaseResult:
    failed = status is not JvmPhaseResultStatus.PASSED
    phase_plan = bundle.phase(phase)
    return JvmPhaseResult(
        phase=phase,
        status=status,
        command_plan_hash=phase_plan.command_plan.content_hash,
        started_at=START,
        completed_at=END,
        exit_codes=(1,) if failed else (0,),
        stdout_refs=(),
        stderr_refs=(ref(),) if failed else (),
        artifact_refs=(),
        findings=(),
        failure_category=JvmFailureCategory.BUILD if failed else None,
        failure_code="JVM_BUILD_FAILED" if failed else None,
        normalized_summary=summary,
    )


def test_complete_success_requires_every_phase_to_pass() -> None:
    bundle = create_jvm_execution_plan_bundle(selection_for(ExecutionTarget.JVM_KOTLIN))
    results = tuple(result(bundle, phase) for phase in JvmExecutionPhase)

    report = create_jvm_execution_report(bundle, results)

    assert report.status is JvmExecutionReportStatus.PASSED
    assert report.failure_signatures == ()
    assert len(report.content_hash) == 64


def test_partial_success_is_incomplete_not_passed() -> None:
    bundle = create_jvm_execution_plan_bundle(selection_for(ExecutionTarget.JVM_JAVA))

    report = create_jvm_execution_report(
        bundle,
        (result(bundle, JvmExecutionPhase.VALIDATE),),
    )

    assert report.status is JvmExecutionReportStatus.INCOMPLETE


def test_failure_signature_ignores_workspace_uuid_timestamp_hash_and_line_numbers() -> None:
    bundle = create_jvm_execution_plan_bundle(selection_for(ExecutionTarget.JVM_SCALA))
    first = result(
        bundle,
        JvmExecutionPhase.BUILD,
        JvmPhaseResultStatus.FAILED,
        summary=(
            "2026-08-28T10:00:00Z C:\\workspaces\\run-a\\Main.scala:42:7 "
            "run 00000000-0000-4000-8000-000000000001 sha256:" + "a" * 64
        ),
    )
    second = result(
        bundle,
        JvmExecutionPhase.BUILD,
        JvmPhaseResultStatus.FAILED,
        summary=(
            "2026-08-29T11:22:33Z C:\\workspaces\\run-b\\Main.scala:99:3 "
            "run 00000000-0000-4000-8000-000000000002 sha256:" + "b" * 64
        ),
    )

    first_signature = failure_signature_for(first)
    second_signature = failure_signature_for(second)

    assert first_signature is not None
    assert second_signature is not None
    assert first_signature.signature == second_signature.signature
    assert "run-a" not in first_signature.normalized_message
    assert "00000000" not in first_signature.normalized_message


def test_failed_execution_requires_raw_log_evidence() -> None:
    bundle = create_jvm_execution_plan_bundle(selection_for(ExecutionTarget.JVM_KOTLIN))

    with pytest.raises(ValueError, match="retain raw log evidence"):
        JvmPhaseResult(
            phase=JvmExecutionPhase.TEST,
            status=JvmPhaseResultStatus.FAILED,
            command_plan_hash=bundle.phase(JvmExecutionPhase.TEST).command_plan.content_hash,
            started_at=START,
            completed_at=END,
            exit_codes=(1,),
            stdout_refs=(),
            stderr_refs=(),
            artifact_refs=(),
            findings=(),
            failure_category=JvmFailureCategory.TEST,
            failure_code="JVM_TEST_FAILED",
            normalized_summary="A test failed.",
        )


def test_unexecuted_phase_cannot_fabricate_process_evidence() -> None:
    bundle = create_jvm_execution_plan_bundle(selection_for(ExecutionTarget.JVM_KOTLIN))

    with pytest.raises(ValueError, match="must not fabricate process evidence"):
        JvmPhaseResult(
            phase=JvmExecutionPhase.RUN,
            status=JvmPhaseResultStatus.NOT_RUN,
            command_plan_hash=bundle.phase(JvmExecutionPhase.RUN).command_plan.content_hash,
            started_at=None,
            completed_at=None,
            exit_codes=(0,),
            stdout_refs=(ref(),),
            stderr_refs=(),
            artifact_refs=(),
            findings=(),
            failure_category=None,
            failure_code=None,
            normalized_summary="JVM phase was not run.",
        )


def test_normalizer_preserves_diagnostic_words() -> None:
    normalized = normalize_jvm_message(
        "/tmp/workspace/run-123/src/Main.kt line 73:12 unresolved reference: total"
    )

    assert "unresolved reference: total" in normalized
    assert "run-123" not in normalized
