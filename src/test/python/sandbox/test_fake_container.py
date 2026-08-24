"""Contract tests for the deterministic fake container runtime."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from orchestwin.sandbox.command_plans import (
    CommandNetworkMode,
    CommandPlan,
    StructuredCommand,
)
from orchestwin.sandbox.container_runtime import (
    ContainerExecutionRequest,
    ContainerImageReference,
)
from orchestwin.sandbox.evidence import SandboxCommandStatus, SandboxRunStatus
from orchestwin.sandbox.execution_policy import (
    DEFAULT_SANDBOX_EXECUTION_POLICY,
    validate_sandbox_plan,
)
from orchestwin.sandbox.fake_container import (
    FakeArtifactOutput,
    FakeCommandOutcome,
    FakeCommandOutcomeKind,
    FakeContainerRuntimeAdapter,
)

RUN_ID = UUID("00000000-0000-4000-8000-000000007102")
STARTED_AT = datetime(2026, 8, 24, 11, 0, tzinfo=UTC)
IMAGE = ContainerImageReference("example/web@sha256:" + "d" * 64)


def _command(command_id: str, *, artifacts: frozenset[str] = frozenset()) -> StructuredCommand:
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
        artifact_patterns=artifacts,
    )


def _plan(*commands: StructuredCommand) -> CommandPlan:
    return CommandPlan(
        plan_id="quality.plan",
        profile_id="web.vue",
        profile_version="1",
        commands=commands,
    )


def _request(tmp_path: Path, plan: CommandPlan) -> ContainerExecutionRequest:
    return ContainerExecutionRequest(
        run_id=RUN_ID,
        plan=plan,
        execution_policy=DEFAULT_SANDBOX_EXECUTION_POLICY,
        policy_report=validate_sandbox_plan(plan),
        image=IMAGE,
        workspace_path=tmp_path,
        environment_variables=(),
    )


def _process_outcome(
    *,
    exit_code: int = 0,
    stdout: bytes = b"ok\n",
    stderr: bytes = b"",
    artifacts: tuple[FakeArtifactOutput, ...] = (),
) -> FakeCommandOutcome:
    return FakeCommandOutcome(
        kind=FakeCommandOutcomeKind.PROCESS_EXIT,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration=timedelta(seconds=2),
        artifacts=artifacts,
        failure_message=None,
    )


def test_fake_runtime_executes_sequentially_and_retains_raw_evidence(
    tmp_path: Path,
) -> None:
    """Exercise the runtime contract without Docker, subprocesses, or network access."""
    lint = _command("quality.lint")
    tests = _command("quality.tests", artifacts=frozenset({"reports/*.xml"}))
    plan = _plan(lint, tests)
    report = FakeArtifactOutput(
        normalized_path="reports/tests.xml",
        content=b"<testsuite tests='1'/>",
        media_type="application/xml",
    )
    adapter = FakeContainerRuntimeAdapter(
        {
            "quality.lint": _process_outcome(stdout=b"lint passed\n"),
            "quality.tests": _process_outcome(
                stdout=b"1 passed\n",
                artifacts=(report,),
            ),
        },
        started_at=STARTED_AT,
    )

    run = asyncio.run(adapter.execute(_request(tmp_path, plan)))

    assert run.status is SandboxRunStatus.SUCCEEDED
    assert adapter.executed_command_ids == ("quality.lint", "quality.tests")
    assert len(run.command_evidence) == 2
    test_evidence = run.command_evidence[1]
    assert test_evidence.status is SandboxCommandStatus.SUCCEEDED
    assert adapter.evidence_store.read(test_evidence.stdout_log.storage_key) == b"1 passed\n"
    assert adapter.evidence_store.read(test_evidence.artifacts[0].storage_key) == report.content


def test_fake_runtime_stops_after_an_unexpected_exit_code(tmp_path: Path) -> None:
    """Keep later commands unexecuted after a deterministic process failure."""
    plan = _plan(_command("quality.lint"), _command("quality.tests"))
    adapter = FakeContainerRuntimeAdapter(
        {
            "quality.lint": _process_outcome(exit_code=1, stderr=b"lint failed\n"),
            "quality.tests": _process_outcome(),
        },
        started_at=STARTED_AT,
    )

    run = asyncio.run(adapter.execute(_request(tmp_path, plan)))

    assert run.status is SandboxRunStatus.FAILED
    assert adapter.executed_command_ids == ("quality.lint",)
    assert run.command_evidence[0].exit_code == 1
    assert "expected 0" in run.command_evidence[0].failure_message


def test_fake_runtime_normalizes_timeout_and_missing_outcome(tmp_path: Path) -> None:
    """Preserve runtime categories instead of inventing process exit codes."""
    plan = _plan(_command("quality.tests"))
    timed_out_adapter = FakeContainerRuntimeAdapter(
        {
            "quality.tests": FakeCommandOutcome(
                kind=FakeCommandOutcomeKind.TIMED_OUT,
                exit_code=None,
                stdout=b"partial\n",
                stderr=b"",
                duration=timedelta(seconds=120),
                artifacts=(),
                failure_message="Command exceeded its timeout.",
            )
        },
        started_at=STARTED_AT,
    )
    missing_adapter = FakeContainerRuntimeAdapter({}, started_at=STARTED_AT)

    timed_out = asyncio.run(timed_out_adapter.execute(_request(tmp_path, plan)))
    missing = asyncio.run(missing_adapter.execute(_request(tmp_path, plan)))

    assert timed_out.status is SandboxRunStatus.TIMED_OUT
    assert timed_out.command_evidence[0].exit_code is None
    assert missing.status is SandboxRunStatus.RUNTIME_ERROR
    assert "no configured" in missing.failure_message.casefold()


def test_fake_runtime_rejects_artifacts_outside_approved_patterns(tmp_path: Path) -> None:
    """Keep fake contract behavior aligned with real artifact collection policy."""
    plan = _plan(_command("quality.tests", artifacts=frozenset({"reports/*.xml"})))
    adapter = FakeContainerRuntimeAdapter(
        {
            "quality.tests": _process_outcome(
                artifacts=(
                    FakeArtifactOutput(
                        normalized_path="secrets/token.txt",
                        content=b"not-collected",
                        media_type="text/plain",
                    ),
                )
            )
        },
        started_at=STARTED_AT,
    )

    run = asyncio.run(adapter.execute(_request(tmp_path, plan)))

    assert run.status is SandboxRunStatus.RUNTIME_ERROR
    assert run.command_evidence[0].artifacts == ()
    assert "outside approved" in run.failure_message.casefold()
