"""Tests for the constrained local Docker CLI runtime adapter."""

from __future__ import annotations

import asyncio
import sys
from collections import deque
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from orchestwin.sandbox.command_plans import (
    CommandNetworkMode,
    CommandPlan,
    SecretReference,
    StructuredCommand,
)
from orchestwin.sandbox.container_runtime import (
    ContainerEnvironmentVariable,
    ContainerExecutionRequest,
    ContainerImageReference,
)
from orchestwin.sandbox.docker_runtime import (
    DEFAULT_LOCAL_DOCKER_RUNTIME_POLICY,
    AsyncioHostProcessRunner,
    HostProcessResult,
    HostProcessRunner,
    HostProcessStatus,
    LocalDockerContainerRuntimeAdapter,
)
from orchestwin.sandbox.evidence import SandboxRunStatus
from orchestwin.sandbox.evidence_store import FileSystemSandboxEvidenceStore
from orchestwin.sandbox.execution_policy import (
    DEFAULT_SANDBOX_EXECUTION_POLICY,
    validate_sandbox_plan,
)

RUN_ID = UUID("00000000-0000-4000-8000-000000007202")
IMAGE = ContainerImageReference("example/web@sha256:" + "d" * 64)
OTHER_IMAGE = ContainerImageReference("example/other@sha256:" + "e" * 64)
BASE_TIME = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


class RecordingHostProcessRunner(HostProcessRunner):
    """Return queued outcomes while retaining exact direct invocation values."""

    def __init__(self, results: tuple[HostProcessResult, ...]) -> None:
        self._results = deque(results)
        self.calls: list[tuple[tuple[str, ...], int, int, dict[str, str]]] = []

    async def run(
        self,
        arguments: tuple[str, ...],
        *,
        timeout_seconds: int,
        maximum_output_bytes_per_stream: int,
        environment_overrides: Mapping[str, str],
    ) -> HostProcessResult:
        self.calls.append(
            (
                arguments,
                timeout_seconds,
                maximum_output_bytes_per_stream,
                dict(environment_overrides),
            )
        )
        if not self._results:
            raise AssertionError("recording runner has no queued result")
        return self._results.popleft()


class SequenceClock:
    """Return explicit UTC instants for deterministic nested run evidence."""

    def __init__(self, values: tuple[datetime, ...]) -> None:
        self._values = deque(values)

    def now(self) -> datetime:
        if not self._values:
            raise AssertionError("sequence clock has no queued instant")
        return self._values.popleft()


def _completed(
    exit_code: int = 0,
    *,
    stdout: bytes = b"ok\n",
    stderr: bytes = b"",
) -> HostProcessResult:
    return HostProcessResult(
        status=HostProcessStatus.COMPLETED,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        failure_message=None,
    )


def _command(
    **overrides: object,
) -> StructuredCommand:
    values: dict[str, object] = {
        "command_id": "quality.tests",
        "executable": "python",
        "arguments": ("-m", "pytest", "-q"),
        "working_directory": ".",
        "allowed_environment_keys": frozenset({"CI"}),
        "secret_references": frozenset(),
        "timeout_seconds": 120,
        "network_mode": CommandNetworkMode.DISABLED,
        "expected_exit_codes": frozenset({0}),
        "output_parser_id": "pytest.v1",
        "artifact_patterns": frozenset({"reports/*.xml"}),
    }
    values.update(overrides)
    return StructuredCommand(**values)  # type: ignore[arg-type]


def _plan(command: StructuredCommand | None = None) -> CommandPlan:
    return CommandPlan(
        plan_id="quality.plan",
        profile_id="web.vue",
        profile_version="1",
        commands=(command or _command(),),
    )


def _request(
    workspace: Path,
    *,
    plan: CommandPlan | None = None,
    image: ContainerImageReference = IMAGE,
    environment: tuple[ContainerEnvironmentVariable, ...] = (),
    policy=DEFAULT_SANDBOX_EXECUTION_POLICY,
) -> ContainerExecutionRequest:
    resolved_plan = plan or _plan()
    return ContainerExecutionRequest(
        run_id=RUN_ID,
        plan=resolved_plan,
        execution_policy=policy,
        policy_report=validate_sandbox_plan(resolved_plan, policy=policy),
        image=image,
        workspace_path=workspace,
        environment_variables=environment,
    )


def _clock() -> SequenceClock:
    return SequenceClock(
        (
            BASE_TIME,
            BASE_TIME + timedelta(seconds=1),
            BASE_TIME + timedelta(seconds=3),
            BASE_TIME + timedelta(seconds=4),
        )
    )


def test_asyncio_runner_uses_direct_vectors_and_bounds_retained_output() -> None:
    """Exercise the production host boundary without Docker or a shell."""
    runner = AsyncioHostProcessRunner()
    completed = asyncio.run(
        runner.run(
            (
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write(b'direct\\n')",
            ),
            timeout_seconds=5,
            maximum_output_bytes_per_stream=1024,
            environment_overrides={},
        )
    )
    overflow = asyncio.run(
        runner.run(
            (
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write(b'x' * 4096)",
            ),
            timeout_seconds=5,
            maximum_output_bytes_per_stream=32,
            environment_overrides={},
        )
    )

    assert completed.status is HostProcessStatus.COMPLETED
    assert completed.exit_code == 0
    assert completed.stdout.splitlines() == [b"direct"]
    assert overflow.status is HostProcessStatus.OUTPUT_LIMIT_EXCEEDED
    assert len(overflow.stdout) == 32


def test_docker_adapter_builds_a_least_privilege_argument_vector_and_evidence(
    tmp_path: Path,
) -> None:
    """Translate approved values directly without a shell, socket, or privileged mode."""
    workspace = tmp_path / "workspace"
    (workspace / "reports").mkdir(parents=True)
    report_content = b"<testsuite tests='1'/>"
    (workspace / "reports" / "tests.xml").write_bytes(report_content)
    runner = RecordingHostProcessRunner((_completed(stdout=b"1 passed\n"),))
    store = FileSystemSandboxEvidenceStore(tmp_path / "evidence")
    adapter = LocalDockerContainerRuntimeAdapter(
        process_runner=runner,
        evidence_store=store,
        approved_images=frozenset({IMAGE}),
        clock=_clock(),
    )
    environment = ContainerEnvironmentVariable(
        key="CI",
        value="true",
        is_secret=False,
    )

    run = asyncio.run(adapter.execute(_request(workspace, environment=(environment,))))

    assert run.status is SandboxRunStatus.SUCCEEDED
    assert len(runner.calls) == 1
    arguments, timeout, output_limit, environment_overrides = runner.calls[0]
    assert arguments[:3] == ("docker", "run", "--rm")
    assert arguments[3:5] == ("--pull", "never")
    assert "--read-only" in arguments
    assert _option_value(arguments, "--user") == "65532:65532"
    assert _option_value(arguments, "--cap-drop") == "ALL"
    assert _option_value(arguments, "--security-opt") == "no-new-privileges"
    assert _option_value(arguments, "--network") == "none"
    assert _option_value(arguments, "--pids-limit") == "256"
    assert _option_value(arguments, "--cpus") == "2"
    assert _option_value(arguments, "--memory") == "4096m"
    assert _option_value(arguments, "--workdir") == "/workspace"
    assert _option_value(arguments, "--env") == "CI"
    assert "--privileged" not in arguments
    assert not any("docker.sock" in argument for argument in arguments)
    assert not any(argument in {"sh", "bash", "cmd", "powershell"} for argument in arguments)
    image_index = arguments.index(IMAGE.value)
    assert arguments[image_index + 1 :] == ("python", "-m", "pytest", "-q")
    assert "true" not in arguments
    assert environment_overrides == {"CI": "true"}
    assert timeout == 120
    assert output_limit == DEFAULT_LOCAL_DOCKER_RUNTIME_POLICY.maximum_output_bytes_per_stream

    command_evidence = run.command_evidence[0]
    assert store.read(command_evidence.stdout_log.storage_key) == b"1 passed\n"
    assert store.read(command_evidence.artifacts[0].storage_key) == report_content


def test_docker_adapter_rejects_unapproved_images_before_invocation(tmp_path: Path) -> None:
    """Keep the runtime image registry exact and digest-pinned."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runner = RecordingHostProcessRunner(())
    adapter = LocalDockerContainerRuntimeAdapter(
        process_runner=runner,
        evidence_store=FileSystemSandboxEvidenceStore(tmp_path / "evidence"),
        approved_images=frozenset({IMAGE}),
        clock=SequenceClock((BASE_TIME, BASE_TIME + timedelta(seconds=1))),
    )

    run = asyncio.run(adapter.execute(_request(workspace, image=OTHER_IMAGE)))

    assert run.status is SandboxRunStatus.RUNTIME_ERROR
    assert run.command_evidence == ()
    assert runner.calls == []
    assert "approved runtime registry" in run.failure_message


def test_docker_adapter_force_removes_a_timed_out_container(tmp_path: Path) -> None:
    """Clean up a named container when killing the Docker CLI may bypass ``--rm``."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    timed_out = HostProcessResult(
        status=HostProcessStatus.TIMED_OUT,
        exit_code=None,
        stdout=b"partial\n",
        stderr=b"",
        failure_message="Docker CLI process exceeded the command timeout.",
    )
    runner = RecordingHostProcessRunner((timed_out, _completed()))
    store = FileSystemSandboxEvidenceStore(tmp_path / "evidence")
    adapter = LocalDockerContainerRuntimeAdapter(
        process_runner=runner,
        evidence_store=store,
        approved_images=frozenset({IMAGE}),
        clock=_clock(),
    )

    run = asyncio.run(adapter.execute(_request(workspace)))

    assert run.status is SandboxRunStatus.TIMED_OUT
    assert len(runner.calls) == 2
    run_arguments = runner.calls[0][0]
    container_name = _option_value(run_arguments, "--name")
    assert runner.calls[1][0] == ("docker", "rm", "--force", container_name)
    assert store.read(run.command_evidence[0].stdout_log.storage_key) == b"partial\n"


def test_docker_exit_125_is_a_runtime_error_not_a_test_failure(tmp_path: Path) -> None:
    """Distinguish a rejected Docker invocation from generated-project behavior."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runner = RecordingHostProcessRunner(
        (_completed(exit_code=125, stderr=b"docker: invalid mount\n"),)
    )
    adapter = LocalDockerContainerRuntimeAdapter(
        process_runner=runner,
        evidence_store=FileSystemSandboxEvidenceStore(tmp_path / "evidence"),
        approved_images=frozenset({IMAGE}),
        clock=_clock(),
    )

    run = asyncio.run(adapter.execute(_request(workspace)))

    assert run.status is SandboxRunStatus.RUNTIME_ERROR
    assert run.command_evidence[0].exit_code is None
    assert "rejected" in run.failure_message


def test_docker_adapter_reports_artifact_limit_as_resource_exhaustion(
    tmp_path: Path,
) -> None:
    """Bound collected evidence even when the container command itself succeeds."""
    workspace = tmp_path / "workspace"
    (workspace / "reports").mkdir(parents=True)
    (workspace / "reports" / "large.xml").write_bytes(b"1234")
    runner = RecordingHostProcessRunner((_completed(), _completed()))
    policy = replace(
        DEFAULT_LOCAL_DOCKER_RUNTIME_POLICY,
        maximum_artifact_size_bytes=3,
        maximum_total_artifact_bytes=3,
    )
    adapter = LocalDockerContainerRuntimeAdapter(
        process_runner=runner,
        evidence_store=FileSystemSandboxEvidenceStore(tmp_path / "evidence"),
        approved_images=frozenset({IMAGE}),
        clock=_clock(),
        runtime_policy=policy,
    )

    run = asyncio.run(adapter.execute(_request(workspace)))

    assert run.status is SandboxRunStatus.RESOURCE_LIMIT_EXCEEDED
    assert run.command_evidence[0].exit_code is None
    assert "artifact bytes" in run.failure_message


def test_docker_adapter_rejects_noncanonical_workspace_and_unconfigured_network(
    tmp_path: Path,
) -> None:
    """Block ambiguous bind mounts and controlled networking without an approved bridge."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    noncanonical = workspace / ".." / "workspace"
    runner = RecordingHostProcessRunner(())
    adapter = LocalDockerContainerRuntimeAdapter(
        process_runner=runner,
        evidence_store=FileSystemSandboxEvidenceStore(tmp_path / "evidence"),
        approved_images=frozenset({IMAGE}),
        clock=SequenceClock((BASE_TIME, BASE_TIME + timedelta(seconds=1))),
    )

    mount_failure = asyncio.run(adapter.execute(_request(noncanonical)))
    assert mount_failure.status is SandboxRunStatus.RUNTIME_ERROR
    assert "canonical" in mount_failure.failure_message

    controlled_command = _command(network_mode=CommandNetworkMode.CONTROLLED)
    controlled_plan = _plan(controlled_command)
    controlled_policy = replace(
        DEFAULT_SANDBOX_EXECUTION_POLICY,
        allowed_network_modes=frozenset(
            {CommandNetworkMode.DISABLED, CommandNetworkMode.CONTROLLED}
        ),
    )
    network_adapter = LocalDockerContainerRuntimeAdapter(
        process_runner=runner,
        evidence_store=FileSystemSandboxEvidenceStore(tmp_path / "network-evidence"),
        approved_images=frozenset({IMAGE}),
        clock=SequenceClock((BASE_TIME, BASE_TIME + timedelta(seconds=1))),
    )
    network_failure = asyncio.run(
        network_adapter.execute(
            _request(
                workspace,
                plan=controlled_plan,
                policy=controlled_policy,
            )
        )
    )

    assert network_failure.status is SandboxRunStatus.RUNTIME_ERROR
    assert "approved Docker network" in network_failure.failure_message
    assert runner.calls == []


def test_docker_adapter_blocks_secret_environment_until_gate_7(tmp_path: Path) -> None:
    """Do not expose resolved secrets before the governed high-impact path exists."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    command = _command(
        allowed_environment_keys=frozenset({"TOKEN"}),
        secret_references=frozenset(
            {SecretReference(reference_id="provider.token", environment_key="TOKEN")}
        ),
    )
    plan = _plan(command)
    policy = replace(
        DEFAULT_SANDBOX_EXECUTION_POLICY,
        allowed_environment_keys=(
            DEFAULT_SANDBOX_EXECUTION_POLICY.allowed_environment_keys | {"TOKEN"}
        ),
        allowed_secret_reference_ids=frozenset({"provider.token"}),
    )
    request = _request(
        workspace,
        plan=plan,
        policy=policy,
        environment=(
            ContainerEnvironmentVariable(
                key="TOKEN",
                value="secret-value",
                is_secret=True,
            ),
        ),
    )
    runner = RecordingHostProcessRunner(())
    adapter = LocalDockerContainerRuntimeAdapter(
        process_runner=runner,
        evidence_store=FileSystemSandboxEvidenceStore(tmp_path / "evidence"),
        approved_images=frozenset({IMAGE}),
        clock=SequenceClock((BASE_TIME, BASE_TIME + timedelta(seconds=1))),
    )

    run = asyncio.run(adapter.execute(request))

    assert run.status is SandboxRunStatus.RUNTIME_ERROR
    assert run.command_evidence == ()
    assert "Gate 7" in run.failure_message
    assert runner.calls == []


def test_docker_adapter_does_not_collect_sensitive_wildcard_artifacts(
    tmp_path: Path,
) -> None:
    """Treat broad profile globs as untrusted and keep secret-shaped files out of evidence."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sensitive_content = b"TOKEN=secret-value\n"
    (workspace / ".env.production").write_bytes(sensitive_content)
    command = _command(artifact_patterns=frozenset({"**/*"}))
    runner = RecordingHostProcessRunner((_completed(),))
    evidence_root = tmp_path / "evidence"
    adapter = LocalDockerContainerRuntimeAdapter(
        process_runner=runner,
        evidence_store=FileSystemSandboxEvidenceStore(evidence_root),
        approved_images=frozenset({IMAGE}),
        clock=_clock(),
    )

    run = asyncio.run(adapter.execute(_request(workspace, plan=_plan(command))))

    assert run.status is SandboxRunStatus.RUNTIME_ERROR
    assert run.command_evidence[0].artifacts == ()
    assert "protected" in run.failure_message
    stored_contents = [path.read_bytes() for path in evidence_root.rglob("*") if path.is_file()]
    assert sensitive_content not in stored_contents


def test_docker_adapter_reports_unconfirmed_cleanup(tmp_path: Path) -> None:
    """Retain the original failure while exposing incomplete container cleanup."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    timed_out = HostProcessResult(
        status=HostProcessStatus.TIMED_OUT,
        exit_code=None,
        stdout=b"partial\n",
        stderr=b"",
        failure_message="Docker CLI process exceeded the command timeout.",
    )
    runner = RecordingHostProcessRunner((timed_out, _completed(exit_code=1)))
    adapter = LocalDockerContainerRuntimeAdapter(
        process_runner=runner,
        evidence_store=FileSystemSandboxEvidenceStore(tmp_path / "evidence"),
        approved_images=frozenset({IMAGE}),
        clock=_clock(),
    )

    run = asyncio.run(adapter.execute(_request(workspace)))

    assert run.status is SandboxRunStatus.TIMED_OUT
    assert "command timeout" in run.failure_message
    assert "cleanup could not be confirmed" in run.failure_message
    assert len(runner.calls) == 2


def _option_value(arguments: tuple[str, ...], option: str) -> str:
    index = arguments.index(option)
    return arguments[index + 1]
