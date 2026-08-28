"""Deterministic builders shared by JVM attempt and workflow tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from orchestwin.artifacts.jvm_sources import JvmSourceRevisionReference
from orchestwin.jvm_execution.attempts import (
    JvmExecutionAttempt,
    JvmExecutionAttemptTrigger,
)
from orchestwin.jvm_execution.evidence import (
    JvmEvidenceReference,
    JvmFailureCategory,
    JvmPhaseResult,
    JvmPhaseResultStatus,
    create_jvm_execution_report,
)
from orchestwin.jvm_execution.plans import (
    JvmExecutionPhase,
    create_jvm_execution_plan_bundle,
)
from orchestwin.jvm_execution.targets import jvm_scope_for, selection_for
from orchestwin.sandbox.execution_profiles import ExecutionTarget

PROJECT_ID = UUID("91000000-0000-4000-8000-000000000001")
OWNER_ID = UUID("91000000-0000-4000-8000-000000000002")
STARTED_AT = datetime(2026, 8, 28, 18, 30, tzinfo=UTC)
COMPLETED_AT = STARTED_AT + timedelta(seconds=7)
DEFAULT_REVISION_ID = UUID("91000000-0000-4000-8000-000000000003")
DEFAULT_ATTEMPT_ID = UUID("91000000-0000-4000-8000-000000000004")


def source_reference(
    *,
    version_number: int = 1,
    revision_id: UUID = DEFAULT_REVISION_ID,
    content_hash: str = "a" * 64,
    source_tree_hash: str = "b" * 64,
) -> JvmSourceRevisionReference:
    return JvmSourceRevisionReference(
        revision_id=revision_id,
        project_id=PROJECT_ID,
        version_number=version_number,
        content_hash=content_hash,
        source_tree_hash=source_tree_hash,
    )


def phase_result(
    target: ExecutionTarget,
    phase: JvmExecutionPhase,
    *,
    status: JvmPhaseResultStatus = JvmPhaseResultStatus.PASSED,
) -> JvmPhaseResult:
    bundle = create_jvm_execution_plan_bundle(selection_for(target))
    failed = status in {
        JvmPhaseResultStatus.FAILED,
        JvmPhaseResultStatus.TIMED_OUT,
        JvmPhaseResultStatus.RESOURCE_LIMIT_EXCEEDED,
        JvmPhaseResultStatus.CANCELLED,
        JvmPhaseResultStatus.RUNTIME_ERROR,
    }
    evidence = JvmEvidenceReference(
        storage_key="sha256/cc/" + "c" * 64,
        sha256_digest="c" * 64,
        size_bytes=12,
        media_type="text/plain",
    )
    return JvmPhaseResult(
        phase=phase,
        status=status,
        command_plan_hash=bundle.phase(phase).command_plan.content_hash,
        started_at=(
            None
            if status
            in {
                JvmPhaseResultStatus.NOT_RUN,
                JvmPhaseResultStatus.SKIPPED,
                JvmPhaseResultStatus.POLICY_BLOCKED,
            }
            else STARTED_AT
        ),
        completed_at=(
            None
            if status
            in {
                JvmPhaseResultStatus.NOT_RUN,
                JvmPhaseResultStatus.SKIPPED,
                JvmPhaseResultStatus.POLICY_BLOCKED,
            }
            else COMPLETED_AT
        ),
        exit_codes=(() if status is JvmPhaseResultStatus.NOT_RUN else ((1,) if failed else (0,))),
        stdout_refs=(),
        stderr_refs=((evidence,) if failed else ()),
        artifact_refs=(),
        findings=(),
        failure_category=(JvmFailureCategory.TEST if failed else None),
        failure_code=("JVM_TEST_FAILED" if failed else None),
        normalized_summary=("JVM test failed." if failed else "JVM phase completed."),
    )


def execution_report(
    target: ExecutionTarget = ExecutionTarget.JVM_KOTLIN,
    *,
    failure_phase: JvmExecutionPhase | None = None,
) -> tuple[object, object]:
    bundle = create_jvm_execution_plan_bundle(selection_for(target))
    results = tuple(
        phase_result(
            target,
            phase,
            status=(
                JvmPhaseResultStatus.FAILED
                if phase is failure_phase
                else JvmPhaseResultStatus.PASSED
            ),
        )
        for phase in JvmExecutionPhase
    )
    return bundle, create_jvm_execution_report(bundle, results)


def execution_attempt(
    *,
    attempt_id: UUID = DEFAULT_ATTEMPT_ID,
    attempt_number: int = 1,
    previous_attempt_id: UUID | None = None,
    trigger: JvmExecutionAttemptTrigger = JvmExecutionAttemptTrigger.INITIAL,
    source: JvmSourceRevisionReference | None = None,
    failure_phase: JvmExecutionPhase | None = None,
    executed_phases: tuple[JvmExecutionPhase, ...] | None = None,
    created_by_user_id: UUID = OWNER_ID,
) -> JvmExecutionAttempt:
    target = ExecutionTarget.JVM_KOTLIN
    bundle, report = execution_report(target, failure_phase=failure_phase)
    scope = jvm_scope_for(target)
    return JvmExecutionAttempt(
        id=attempt_id,
        project_id=PROJECT_ID,
        created_by_user_id=created_by_user_id,
        attempt_number=attempt_number,
        previous_attempt_id=previous_attempt_id,
        source_revision=source or source_reference(),
        profile_id=scope.profile_id,
        profile_version=scope.profile_version,
        profile_validation_content_hash="d" * 64,
        execution_plan_content_hash=bundle.content_hash,
        runner_id="jvm.gradle",
        runner_version="1.0.0",
        runner_image_digest="e" * 64,
        policy_content_hash="f" * 64,
        trigger=trigger,
        executed_phases=executed_phases or tuple(JvmExecutionPhase),
        report=report,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
    )
