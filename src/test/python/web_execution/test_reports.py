"""Tests for normalized Web reports, raw evidence, and stable failure signatures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.sandbox.command_plans import (
    CommandNetworkMode,
    CommandPlan,
    StructuredCommand,
)
from orchestwin.sandbox.evidence import (
    SandboxArtifactReference,
    SandboxCommandEvidence,
    SandboxCommandStatus,
    SandboxLogReference,
    SandboxLogStream,
    SandboxRunEvidence,
    SandboxRunStatus,
)
from orchestwin.web_execution.plans import (
    WebExecutionPhase,
    WebPhaseExecutionKind,
    WebPhasePlan,
)
from orchestwin.web_execution.reports import (
    WebExecutionReport,
    WebExecutionReportStatus,
    WebFailureCategory,
    WebNormalizedFinding,
    WebPhaseResultStatus,
    create_web_failure_signature,
    create_web_no_op_phase_result,
    normalize_failure_message,
    normalize_web_command_phase,
)

STARTED_AT = datetime(2026, 8, 26, 14, 0, tzinfo=UTC)
COMPLETED_AT = STARTED_AT + timedelta(seconds=2)


def command_plan() -> CommandPlan:
    return CommandPlan(
        plan_id="web.test.root",
        profile_id="web.vue",
        profile_version="1.0.0",
        commands=(
            StructuredCommand(
                command_id="root.test",
                executable="npm",
                arguments=("test", "--", "--run"),
                working_directory=".",
                allowed_environment_keys=frozenset({"CI"}),
                secret_references=frozenset(),
                timeout_seconds=600,
                network_mode=CommandNetworkMode.DISABLED,
                expected_exit_codes=frozenset({0}),
                output_parser_id="vitest.v1",
                artifact_patterns=frozenset({"reports/**"}),
            ),
        ),
    )


def phase_plan(plan: CommandPlan) -> WebPhasePlan:
    return WebPhasePlan(
        phase=WebExecutionPhase.TEST,
        execution_kind=WebPhaseExecutionKind.COMMAND_PLANS,
        command_plans=(plan,),
        adapter_action_id=None,
        no_op_reason=None,
    )


def sandbox_run(
    plan: CommandPlan,
    *,
    run_status: SandboxRunStatus,
    command_status: SandboxCommandStatus,
    failure_message: str | None,
    exit_code: int | None,
    run_id: str = "11111111-1111-4111-8111-111111111111",
) -> SandboxRunEvidence:
    return SandboxRunEvidence(
        run_id=UUID(run_id),
        plan_id=plan.plan_id,
        plan_content_hash=plan.content_hash,
        profile_id=plan.profile_id,
        profile_version=plan.profile_version,
        image_reference="runner@sha256:" + "a" * 64,
        runtime_reference="fake-runtime-v1",
        status=run_status,
        started_at=STARTED_AT,
        finished_at=COMPLETED_AT,
        planned_command_ids=("root.test",),
        command_evidence=(
            SandboxCommandEvidence(
                command_id="root.test",
                status=command_status,
                started_at=STARTED_AT,
                finished_at=COMPLETED_AT,
                exit_code=exit_code,
                stdout_log=SandboxLogReference(
                    stream=SandboxLogStream.STDOUT,
                    sha256_digest="b" * 64,
                    size_bytes=12,
                    storage_key="sha256/bb/test.stdout",
                ),
                stderr_log=SandboxLogReference(
                    stream=SandboxLogStream.STDERR,
                    sha256_digest="c" * 64,
                    size_bytes=24,
                    storage_key="sha256/cc/test.stderr",
                ),
                artifacts=(
                    SandboxArtifactReference(
                        normalized_path="reports/vitest.json",
                        sha256_digest="d" * 64,
                        size_bytes=36,
                        storage_key="sha256/dd/vitest.json",
                        media_type="application/json",
                    ),
                ),
                output_parser_id="vitest.v1",
                failure_message=failure_message,
            ),
        ),
        failure_message=failure_message,
    )


def test_normalizes_successful_sandbox_run_and_preserves_raw_evidence() -> None:
    plan = command_plan()
    result = normalize_web_command_phase(
        phase_plan(plan),
        runs=(
            sandbox_run(
                plan,
                run_status=SandboxRunStatus.SUCCEEDED,
                command_status=SandboxCommandStatus.SUCCEEDED,
                failure_message=None,
                exit_code=0,
            ),
        ),
    )

    assert result.status is WebPhaseResultStatus.PASSED
    assert result.command_plan_hashes == (plan.content_hash,)
    assert result.stdout_refs[0].storage_key == "sha256/bb/test.stdout"
    assert result.stderr_refs[0].storage_key == "sha256/cc/test.stderr"
    assert result.artifact_refs[0].media_type == "application/json"
    assert result.failure_category is None


def test_normalizes_test_failure_and_generates_a_tool_specific_code() -> None:
    plan = command_plan()
    result = normalize_web_command_phase(
        phase_plan(plan),
        runs=(
            sandbox_run(
                plan,
                run_status=SandboxRunStatus.FAILED,
                command_status=SandboxCommandStatus.FAILED,
                failure_message="Vitest failed in /tmp/workspaces/run-1 at line 47.",
                exit_code=1,
            ),
        ),
        findings=(
            WebNormalizedFinding(
                code="ASSERTION_FAILED",
                message="Expected 200 but received 500.",
                source_tool="vitest",
                location="tests/api.spec.ts::returns health",
            ),
        ),
    )

    assert result.status is WebPhaseResultStatus.FAILED
    assert result.failure_category is WebFailureCategory.TEST
    assert result.failure_code == "TEST_VITEST_V1_FAILED"
    assert "<workspace-path>" in result.normalized_summary
    assert result.exit_codes == (1,)


def test_failure_signature_ignores_volatile_runtime_values() -> None:
    plan = command_plan()
    first = normalize_web_command_phase(
        phase_plan(plan),
        runs=(
            sandbox_run(
                plan,
                run_status=SandboxRunStatus.FAILED,
                command_status=SandboxCommandStatus.FAILED,
                failure_message=(
                    "2026-08-26T14:00:01Z failed in /tmp/workspaces/"
                    "11111111-1111-4111-8111-111111111111 at line 12."
                ),
                exit_code=1,
            ),
        ),
    )
    second = normalize_web_command_phase(
        phase_plan(plan),
        runs=(
            sandbox_run(
                plan,
                run_status=SandboxRunStatus.FAILED,
                command_status=SandboxCommandStatus.FAILED,
                failure_message=(
                    "2026-08-26T14:05:09Z failed in /tmp/workspaces/"
                    "22222222-2222-4222-8222-222222222222 at line 99."
                ),
                exit_code=1,
                run_id="22222222-2222-4222-8222-222222222222",
            ),
        ),
    )

    first_signature = create_web_failure_signature(
        first,
        profile_id="web.vue",
        profile_version="1.0.0",
    )
    second_signature = create_web_failure_signature(
        second,
        profile_id="web.vue",
        profile_version="1.0.0",
    )

    assert first_signature.digest == second_signature.digest
    assert first_signature.normalized_message == (
        "<timestamp> failed in <workspace-path> at line <line>."
    )


def test_timeout_and_resource_limit_remain_distinct_failures() -> None:
    plan = command_plan()
    timeout = normalize_web_command_phase(
        phase_plan(plan),
        runs=(
            sandbox_run(
                plan,
                run_status=SandboxRunStatus.TIMED_OUT,
                command_status=SandboxCommandStatus.TIMED_OUT,
                failure_message="Command timed out.",
                exit_code=None,
            ),
        ),
    )
    resource = normalize_web_command_phase(
        phase_plan(plan),
        runs=(
            sandbox_run(
                plan,
                run_status=SandboxRunStatus.RESOURCE_LIMIT_EXCEEDED,
                command_status=SandboxCommandStatus.RESOURCE_LIMIT_EXCEEDED,
                failure_message="Memory limit exceeded.",
                exit_code=None,
            ),
        ),
    )

    assert timeout.status is WebPhaseResultStatus.TIMED_OUT
    assert timeout.failure_category is WebFailureCategory.TIMEOUT
    assert resource.status is WebPhaseResultStatus.RESOURCE_LIMIT_EXCEEDED
    assert resource.failure_category is WebFailureCategory.RESOURCE_LIMIT


def test_explicit_no_op_phase_is_skipped_without_process_evidence() -> None:
    result = create_web_no_op_phase_result(
        WebPhasePlan(
            phase=WebExecutionPhase.BUILD,
            execution_kind=WebPhaseExecutionKind.NO_OP,
            command_plans=(),
            adapter_action_id=None,
            no_op_reason="Static projects have no compilation phase.",
        )
    )

    assert result.status is WebPhaseResultStatus.SKIPPED
    assert result.command_plan_hashes == ()
    assert result.stdout_refs == ()


def test_report_does_not_convert_partial_or_failed_execution_to_success() -> None:
    plan = command_plan()
    failed = normalize_web_command_phase(
        phase_plan(plan),
        runs=(
            sandbox_run(
                plan,
                run_status=SandboxRunStatus.FAILED,
                command_status=SandboxCommandStatus.FAILED,
                failure_message="One or more deterministic tests failed.",
                exit_code=1,
            ),
        ),
    )
    report = WebExecutionReport(
        source_revision_content_hash="e" * 64,
        source_tree_hash="f" * 64,
        profile_id="web.vue",
        profile_version="1.0.0",
        runner_image_digest="0" * 64,
        policy_content_hash="1" * 64,
        phase_results=(failed,),
    )

    assert report.status is WebExecutionReportStatus.FAILED
    assert len(report.failure_signatures()) == 1


def test_normalization_rejects_sandbox_evidence_for_another_plan() -> None:
    plan = command_plan()
    run = sandbox_run(
        plan,
        run_status=SandboxRunStatus.SUCCEEDED,
        command_status=SandboxCommandStatus.SUCCEEDED,
        failure_message=None,
        exit_code=0,
    )
    mismatched = SandboxRunEvidence(
        run_id=run.run_id,
        plan_id=run.plan_id,
        plan_content_hash="9" * 64,
        profile_id=run.profile_id,
        profile_version=run.profile_version,
        image_reference=run.image_reference,
        runtime_reference=run.runtime_reference,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        planned_command_ids=run.planned_command_ids,
        command_evidence=run.command_evidence,
        failure_message=run.failure_message,
    )

    with pytest.raises(ValueError, match="another Web command plan"):
        normalize_web_command_phase(phase_plan(plan), runs=(mismatched,))


def test_failure_message_normalization_rejects_empty_content() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        normalize_failure_message("")
