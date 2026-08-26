"""Tests for immutable sandbox runs, raw logs, and artifact evidence."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
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
    create_sandbox_run_evidence,
)

RUN_ID = UUID("00000000-0000-4000-8000-000000007001")
STARTED_AT = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)


def _command(command_id: str = "quality.tests") -> StructuredCommand:
    return StructuredCommand(
        command_id=command_id,
        executable="python",
        arguments=("-m", "pytest"),
        working_directory=".",
        allowed_environment_keys=frozenset({"CI"}),
        secret_references=frozenset(),
        timeout_seconds=120,
        network_mode=CommandNetworkMode.DISABLED,
        expected_exit_codes=frozenset({0}),
        output_parser_id="pytest.v1",
        artifact_patterns=frozenset({"reports/*.xml"}),
    )


def _plan(*commands: StructuredCommand) -> CommandPlan:
    return CommandPlan(
        plan_id="quality.plan",
        profile_id="web.vue",
        profile_version="1",
        commands=commands or (_command(),),
    )


def _log(stream: SandboxLogStream, content_marker: str) -> SandboxLogReference:
    digest = "a" * 64 if stream is SandboxLogStream.STDOUT else "b" * 64
    return SandboxLogReference(
        stream=stream,
        sha256_digest=digest,
        size_bytes=len(content_marker.encode()),
        storage_key=f"sandbox-runs/{RUN_ID}/{content_marker}.log",
    )


def _artifact() -> SandboxArtifactReference:
    return SandboxArtifactReference(
        normalized_path="reports/tests.xml",
        sha256_digest="c" * 64,
        size_bytes=42,
        storage_key=f"sandbox-runs/{RUN_ID}/artifacts/reports/tests.xml",
        media_type="application/xml",
    )


def _evidence(
    *,
    command_id: str = "quality.tests",
    status: SandboxCommandStatus = SandboxCommandStatus.SUCCEEDED,
    exit_code: int | None = 0,
    failure_message: str | None = None,
    offset_seconds: int = 0,
) -> SandboxCommandEvidence:
    started_at = STARTED_AT + timedelta(seconds=offset_seconds)
    return SandboxCommandEvidence(
        command_id=command_id,
        status=status,
        started_at=started_at,
        finished_at=started_at + timedelta(seconds=5),
        exit_code=exit_code,
        stdout_log=_log(SandboxLogStream.STDOUT, f"{command_id}-stdout"),
        stderr_log=_log(SandboxLogStream.STDERR, f"{command_id}-stderr"),
        artifacts=(_artifact(),) if command_id == "quality.tests" else (),
        output_parser_id="pytest.v1",
        failure_message=failure_message,
    )


def test_log_and_artifact_references_expose_metadata_without_raw_content() -> None:
    """Preserve complete raw evidence behind content-addressed references."""
    stdout = _log(SandboxLogStream.STDOUT, "stdout")
    artifact = _artifact()

    assert stdout.to_snapshot()["stream"] == "STDOUT"
    assert "content" not in stdout.to_snapshot()
    assert artifact.to_snapshot()["normalized_path"] == "reports/tests.xml"
    assert "host_path" not in artifact.to_snapshot()


def test_successful_command_requires_both_raw_streams_and_one_exit_code() -> None:
    """Prevent summaries from replacing or contradicting process evidence."""
    evidence = _evidence()

    assert evidence.status is SandboxCommandStatus.SUCCEEDED
    assert evidence.duration_seconds == 5
    assert evidence.stdout_log.stream is SandboxLogStream.STDOUT
    assert evidence.stderr_log.stream is SandboxLogStream.STDERR

    with pytest.raises(ValueError, match="requires an exit code"):
        replace(evidence, exit_code=None)

    with pytest.raises(ValueError, match="wrong stream"):
        replace(evidence, stdout_log=evidence.stderr_log)


def test_failed_and_non_process_command_shapes_remain_distinct() -> None:
    """Keep test failures separate from timeout and runtime-boundary failures."""
    failed = _evidence(
        status=SandboxCommandStatus.FAILED,
        exit_code=1,
        failure_message="Command returned an unexpected exit code.",
    )
    timed_out = _evidence(
        status=SandboxCommandStatus.TIMED_OUT,
        exit_code=None,
        failure_message="Command exceeded its timeout.",
    )

    assert failed.exit_code == 1
    assert timed_out.exit_code is None

    with pytest.raises(ValueError, match="non-process"):
        replace(timed_out, exit_code=124)


def test_successful_run_is_bound_to_every_planned_command_and_exact_hash() -> None:
    """Make success impossible when execution stops before the plan is complete."""
    first = _command("quality.lint")
    second = _command("quality.tests")
    plan = _plan(first, second)
    command_evidence = (
        _evidence(command_id="quality.lint"),
        _evidence(command_id="quality.tests", offset_seconds=5),
    )

    run = create_sandbox_run_evidence(
        run_id=RUN_ID,
        plan=plan,
        image_reference="example/web@sha256:" + "d" * 64,
        runtime_reference="fake.runtime",
        started_at=STARTED_AT,
        finished_at=STARTED_AT + timedelta(seconds=10),
        command_evidence=command_evidence,
    )

    assert run.status is SandboxRunStatus.SUCCEEDED
    assert run.plan_content_hash == plan.content_hash
    assert run.planned_command_ids == ("quality.lint", "quality.tests")
    assert run.failure_message is None


def test_incomplete_successful_prefix_becomes_a_runtime_error() -> None:
    """Never report success merely because the commands that did run passed."""
    plan = _plan(_command("quality.lint"), _command("quality.tests"))

    run = create_sandbox_run_evidence(
        run_id=RUN_ID,
        plan=plan,
        image_reference="example/web@sha256:" + "d" * 64,
        runtime_reference="fake.runtime",
        started_at=STARTED_AT,
        finished_at=STARTED_AT + timedelta(seconds=5),
        command_evidence=(_evidence(command_id="quality.lint"),),
    )

    assert run.status is SandboxRunStatus.RUNTIME_ERROR
    assert run.failure_message is not None


def test_failed_and_timed_out_commands_determine_the_run_status() -> None:
    """Normalize final adapter outcomes without hiding their failure category."""
    plan = _plan()
    failed_command = _evidence(
        status=SandboxCommandStatus.FAILED,
        exit_code=2,
        failure_message="Tests failed.",
    )
    timed_out_command = _evidence(
        status=SandboxCommandStatus.TIMED_OUT,
        exit_code=None,
        failure_message="Command exceeded its timeout.",
    )

    failed_run = create_sandbox_run_evidence(
        run_id=RUN_ID,
        plan=plan,
        image_reference="example/web@sha256:" + "d" * 64,
        runtime_reference="fake.runtime",
        started_at=STARTED_AT,
        finished_at=STARTED_AT + timedelta(seconds=5),
        command_evidence=(failed_command,),
    )
    timed_out_run = create_sandbox_run_evidence(
        run_id=RUN_ID,
        plan=plan,
        image_reference="example/web@sha256:" + "d" * 64,
        runtime_reference="fake.runtime",
        started_at=STARTED_AT,
        finished_at=STARTED_AT + timedelta(seconds=5),
        command_evidence=(timed_out_command,),
    )

    assert failed_run.status is SandboxRunStatus.FAILED
    assert timed_out_run.status is SandboxRunStatus.TIMED_OUT


def test_run_rejects_out_of_order_or_out_of_range_command_evidence() -> None:
    """Keep command evidence a timestamped prefix of the approved plan."""
    plan = _plan(_command("quality.lint"), _command("quality.tests"))
    out_of_order = _evidence(
        command_id="quality.tests",
        status=SandboxCommandStatus.FAILED,
        exit_code=1,
        failure_message="Tests failed.",
    )

    with pytest.raises(ValueError, match="sequential plan prefix"):
        create_sandbox_run_evidence(
            run_id=RUN_ID,
            plan=plan,
            image_reference="example/web@sha256:" + "d" * 64,
            runtime_reference="fake.runtime",
            started_at=STARTED_AT,
            finished_at=STARTED_AT + timedelta(seconds=5),
            command_evidence=(out_of_order,),
        )

    outside_range = _evidence(
        command_id="quality.lint",
        status=SandboxCommandStatus.FAILED,
        exit_code=1,
        failure_message="Lint failed.",
        offset_seconds=10,
    )
    with pytest.raises(ValueError, match="inside the run time range"):
        create_sandbox_run_evidence(
            run_id=RUN_ID,
            plan=plan,
            image_reference="example/web@sha256:" + "d" * 64,
            runtime_reference="fake.runtime",
            started_at=STARTED_AT,
            finished_at=STARTED_AT + timedelta(seconds=5),
            command_evidence=(outside_range,),
        )


def test_evidence_requires_utc_timestamps_and_is_immutable() -> None:
    """Keep persisted ordering comparable and prevent post-run mutation."""
    evidence = _evidence()

    with pytest.raises(FrozenInstanceError):
        evidence.exit_code = 1  # type: ignore[misc]

    naive_start = STARTED_AT.replace(tzinfo=None)
    with pytest.raises(ValueError, match="UTC-aware"):
        replace(evidence, started_at=naive_start)


def test_run_snapshot_preserves_references_and_omits_raw_stream_content() -> None:
    """Expose auditable evidence metadata without duplicating stored bytes."""
    plan = _plan()
    run = create_sandbox_run_evidence(
        run_id=RUN_ID,
        plan=plan,
        image_reference="example/web@sha256:" + "d" * 64,
        runtime_reference="fake.runtime",
        started_at=STARTED_AT,
        finished_at=STARTED_AT + timedelta(seconds=5),
        command_evidence=(_evidence(),),
    )

    snapshot = run.to_snapshot()

    assert snapshot["schema_version"] == 1
    assert snapshot["status"] == "SUCCEEDED"
    assert snapshot["plan_content_hash"] == plan.content_hash
    command_snapshot = snapshot["command_evidence"][0]  # type: ignore[index]
    assert command_snapshot["stdout_log"]["storage_key"].endswith("stdout.log")
    assert "content" not in command_snapshot["stdout_log"]


def test_run_constructor_rejects_status_that_contradicts_command_evidence() -> None:
    """Prevent adapters from labelling a timeout or runtime error as a test failure."""
    plan = _plan()
    timed_out = _evidence(
        status=SandboxCommandStatus.TIMED_OUT,
        exit_code=None,
        failure_message="Command exceeded its timeout.",
    )

    with pytest.raises(ValueError, match="contradicts"):
        SandboxRunEvidence(
            run_id=RUN_ID,
            plan_id=plan.plan_id,
            plan_content_hash=plan.content_hash,
            profile_id=plan.profile_id,
            profile_version=plan.profile_version,
            image_reference="example/web@sha256:" + "d" * 64,
            runtime_reference="fake.runtime",
            status=SandboxRunStatus.FAILED,
            started_at=STARTED_AT,
            finished_at=STARTED_AT + timedelta(seconds=5),
            planned_command_ids=("quality.tests",),
            command_evidence=(timed_out,),
            failure_message="Command failed.",
        )


def test_run_factory_rejects_success_or_parser_metadata_that_contradicts_the_plan() -> None:
    """Bind adapter success and normalized output to the exact command contract."""
    plan = _plan()
    unexpected_success = replace(_evidence(), exit_code=2)
    wrong_parser = replace(_evidence(), output_parser_id="generic.v1")

    with pytest.raises(ValueError, match="expected exit codes"):
        create_sandbox_run_evidence(
            run_id=RUN_ID,
            plan=plan,
            image_reference="example/web@sha256:" + "d" * 64,
            runtime_reference="fake.runtime",
            started_at=STARTED_AT,
            finished_at=STARTED_AT + timedelta(seconds=5),
            command_evidence=(unexpected_success,),
        )

    with pytest.raises(ValueError, match="output parser"):
        create_sandbox_run_evidence(
            run_id=RUN_ID,
            plan=plan,
            image_reference="example/web@sha256:" + "d" * 64,
            runtime_reference="fake.runtime",
            started_at=STARTED_AT,
            finished_at=STARTED_AT + timedelta(seconds=5),
            command_evidence=(wrong_parser,),
        )
