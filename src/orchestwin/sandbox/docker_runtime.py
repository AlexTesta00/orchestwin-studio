"""Constrained local Docker CLI adapter for policy-approved command plans."""

from __future__ import annotations

import asyncio
import mimetypes
import os
import re
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final, Protocol

from orchestwin.sandbox.command_plans import CommandNetworkMode, StructuredCommand
from orchestwin.sandbox.container_runtime import (
    ContainerExecutionRequest,
    ContainerImageReference,
    ContainerRuntimePort,
    SystemUtcClock,
    UtcClock,
)
from orchestwin.sandbox.evidence import (
    SandboxArtifactReference,
    SandboxCommandEvidence,
    SandboxCommandStatus,
    SandboxEvidenceStore,
    SandboxLogStream,
    SandboxRunEvidence,
    create_sandbox_run_evidence,
)

_MEBIBYTE: Final = 1024 * 1024
_CONTROLLED_NETWORK_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")


class HostProcessStatus(StrEnum):
    """Boundary outcomes from launching the Docker CLI without a shell."""

    COMPLETED = "COMPLETED"
    TIMED_OUT = "TIMED_OUT"
    OUTPUT_LIMIT_EXCEEDED = "OUTPUT_LIMIT_EXCEEDED"
    SPAWN_ERROR = "SPAWN_ERROR"
    RUNTIME_ERROR = "RUNTIME_ERROR"


@dataclass(frozen=True, slots=True)
class HostProcessResult:
    """Raw bounded stdout/stderr plus one typed host process outcome."""

    status: HostProcessStatus
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    failure_message: str | None

    def __post_init__(self) -> None:
        """Protect process and non-process boundary result shapes."""
        if not isinstance(self.stdout, bytes) or not isinstance(self.stderr, bytes):
            raise TypeError("host process streams must be bytes")
        if self.failure_message is not None and (
            not self.failure_message
            or self.failure_message != " ".join(self.failure_message.split())
        ):
            raise ValueError("host process failure message must be normalized")

        if self.status is HostProcessStatus.COMPLETED:
            if (
                self.exit_code is None
                or isinstance(self.exit_code, bool)
                or not 0 <= self.exit_code <= 255
                or self.failure_message is not None
            ):
                raise ValueError("completed host process requires only a portable exit code")
        elif self.exit_code is not None or self.failure_message is None:
            raise ValueError("failed host process requires only a failure message")


class HostProcessRunner(Protocol):
    """Narrow host adapter used only to invoke prebuilt Docker CLI vectors."""

    async def run(
        self,
        arguments: tuple[str, ...],
        *,
        timeout_seconds: int,
        maximum_output_bytes_per_stream: int,
        environment_overrides: Mapping[str, str],
    ) -> HostProcessResult:
        """Invoke one argument vector directly, never through a shell."""
        ...


class AsyncioHostProcessRunner:
    """Production process adapter using ``create_subprocess_exec`` and bounded streams."""

    async def run(
        self,
        arguments: tuple[str, ...],
        *,
        timeout_seconds: int,
        maximum_output_bytes_per_stream: int,
        environment_overrides: Mapping[str, str],
    ) -> HostProcessResult:
        """Launch a direct process and terminate it on timeout or output overflow."""
        if not arguments:
            raise ValueError("host process argument vector must not be empty")
        if timeout_seconds < 1 or maximum_output_bytes_per_stream < 1:
            raise ValueError("host process limits must be positive")

        environment = os.environ.copy()
        environment.update(environment_overrides)
        try:
            process = await asyncio.create_subprocess_exec(
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
            )
        except OSError:
            return HostProcessResult(
                status=HostProcessStatus.SPAWN_ERROR,
                exit_code=None,
                stdout=b"",
                stderr=b"",
                failure_message="Docker CLI process could not be started.",
            )

        if process.stdout is None or process.stderr is None:
            await _terminate_process(process)
            return HostProcessResult(
                status=HostProcessStatus.RUNTIME_ERROR,
                exit_code=None,
                stdout=b"",
                stderr=b"",
                failure_message="Docker CLI streams were not available.",
            )

        stdout_buffer = bytearray()
        stderr_buffer = bytearray()
        stdout_task = asyncio.create_task(
            _read_bounded_stream(
                process.stdout,
                stdout_buffer,
                maximum_bytes=maximum_output_bytes_per_stream,
            )
        )
        stderr_task = asyncio.create_task(
            _read_bounded_stream(
                process.stderr,
                stderr_buffer,
                maximum_bytes=maximum_output_bytes_per_stream,
            )
        )
        wait_task = asyncio.create_task(process.wait())
        tasks = {stdout_task, stderr_task, wait_task}

        done, pending = await asyncio.wait(
            tasks,
            timeout=timeout_seconds,
            return_when=asyncio.FIRST_EXCEPTION,
        )

        output_limit_exceeded = any(
            isinstance(task.exception(), _OutputLimitExceeded)
            for task in done
            if not task.cancelled() and task.exception() is not None
        )
        unexpected_error = any(
            task.exception() is not None and not isinstance(task.exception(), _OutputLimitExceeded)
            for task in done
            if not task.cancelled()
        )

        if output_limit_exceeded:
            await _terminate_process(process)
            await _cancel_tasks(pending)
            return HostProcessResult(
                status=HostProcessStatus.OUTPUT_LIMIT_EXCEEDED,
                exit_code=None,
                stdout=bytes(stdout_buffer),
                stderr=bytes(stderr_buffer),
                failure_message="Docker CLI output exceeded the configured stream limit.",
            )

        if unexpected_error:
            await _terminate_process(process)
            await _cancel_tasks(pending)
            return HostProcessResult(
                status=HostProcessStatus.RUNTIME_ERROR,
                exit_code=None,
                stdout=bytes(stdout_buffer),
                stderr=bytes(stderr_buffer),
                failure_message="Docker CLI output could not be collected safely.",
            )

        if pending:
            await _terminate_process(process)
            await _cancel_tasks(pending)
            return HostProcessResult(
                status=HostProcessStatus.TIMED_OUT,
                exit_code=None,
                stdout=bytes(stdout_buffer),
                stderr=bytes(stderr_buffer),
                failure_message="Docker CLI process exceeded the command timeout.",
            )

        return_code = wait_task.result()
        if return_code < 0 or return_code > 255:
            return HostProcessResult(
                status=HostProcessStatus.RUNTIME_ERROR,
                exit_code=None,
                stdout=bytes(stdout_buffer),
                stderr=bytes(stderr_buffer),
                failure_message="Docker CLI process terminated without a portable exit code.",
            )

        return HostProcessResult(
            status=HostProcessStatus.COMPLETED,
            exit_code=return_code,
            stdout=bytes(stdout_buffer),
            stderr=bytes(stderr_buffer),
            failure_message=None,
        )


def _validate_absolute_container_path(value: str, *, label: str) -> None:
    """Require a canonical absolute POSIX path with no parent traversal."""
    path = PurePosixPath(value)
    if (
        not value.startswith("/")
        or value == "/"
        or "//" in value
        or any(part in {".", ".."} for part in path.parts)
        or path.as_posix() != value
    ):
        raise ValueError(f"{label} must be a canonical absolute POSIX path")


@dataclass(frozen=True, slots=True)
class LocalDockerRuntimePolicy:
    """Adapter-local hardening and evidence collection bounds."""

    container_user: str
    workspace_container_path: str
    tmpfs_container_path: str
    maximum_output_bytes_per_stream: int
    maximum_artifacts_per_command: int
    maximum_artifact_size_bytes: int
    maximum_total_artifact_bytes: int
    cleanup_timeout_seconds: int
    prohibited_artifact_names: frozenset[str]
    prohibited_artifact_suffixes: frozenset[str]

    def __post_init__(self) -> None:
        """Reject unsafe container identities, paths, and non-positive bounds."""
        if (
            not self.container_user
            or self.container_user != self.container_user.strip()
            or any(character in self.container_user for character in ("\x00", "\r", "\n"))
        ):
            raise ValueError("Docker container user must be normalized")
        _validate_absolute_container_path(
            self.workspace_container_path,
            label="Docker workspace container path",
        )
        _validate_absolute_container_path(
            self.tmpfs_container_path,
            label="Docker tmpfs container path",
        )
        if self.workspace_container_path == self.tmpfs_container_path:
            raise ValueError("Docker workspace and tmpfs paths must be distinct")

        integer_limits = (
            self.maximum_output_bytes_per_stream,
            self.maximum_artifacts_per_command,
            self.maximum_artifact_size_bytes,
            self.maximum_total_artifact_bytes,
            self.cleanup_timeout_seconds,
        )
        if any(isinstance(value, bool) or value < 1 for value in integer_limits):
            raise ValueError("Docker runtime integer limits must be positive")
        if self.maximum_artifact_size_bytes > self.maximum_total_artifact_bytes:
            raise ValueError("Docker artifact size limit must not exceed total limit")

        if not self.prohibited_artifact_names or any(
            not name
            or name != name.casefold()
            or name != name.strip()
            or "/" in name
            or "\\" in name
            for name in self.prohibited_artifact_names
        ):
            raise ValueError("Docker prohibited artifact names must be lowercase tokens")
        if not self.prohibited_artifact_suffixes or any(
            not suffix.startswith(".")
            or suffix != suffix.casefold()
            or suffix != suffix.strip()
            or "/" in suffix
            or "\\" in suffix
            for suffix in self.prohibited_artifact_suffixes
        ):
            raise ValueError("Docker prohibited artifact suffixes must be lowercase extensions")


DEFAULT_LOCAL_DOCKER_RUNTIME_POLICY: Final = LocalDockerRuntimePolicy(
    container_user="65532:65532",
    workspace_container_path="/workspace",
    tmpfs_container_path="/tmp",
    maximum_output_bytes_per_stream=10 * _MEBIBYTE,
    maximum_artifacts_per_command=100,
    maximum_artifact_size_bytes=25 * _MEBIBYTE,
    maximum_total_artifact_bytes=50 * _MEBIBYTE,
    cleanup_timeout_seconds=30,
    prohibited_artifact_names=frozenset(
        {
            ".git",
            ".npmrc",
            ".orchestwin",
            ".pypirc",
            ".ssh",
            "credentials.json",
            "gradle.properties",
            "id_ed25519",
            "id_rsa",
            "local.properties",
            "service-account.json",
            "settings.xml",
        }
    ),
    prohibited_artifact_suffixes=frozenset(
        {
            ".jks",
            ".key",
            ".keystore",
            ".p12",
            ".pem",
            ".pfx",
        }
    ),
)


@dataclass(frozen=True, slots=True)
class _ArtifactCollectionResult:
    artifacts: tuple[SandboxArtifactReference, ...]
    failure_status: SandboxCommandStatus | None
    failure_message: str | None

    def __post_init__(self) -> None:
        """Keep successful and failed collection outcomes unambiguous."""
        if (self.failure_status is None) != (self.failure_message is None):
            raise ValueError("artifact collection failure status and message must align")
        if self.failure_message is not None and (
            not self.failure_message
            or self.failure_message != " ".join(self.failure_message.split())
        ):
            raise ValueError("artifact collection failure message must be normalized")


class LocalDockerContainerRuntimeAdapter(ContainerRuntimePort):
    """Run each structured command in a fresh least-privilege Docker container."""

    def __init__(
        self,
        *,
        process_runner: HostProcessRunner,
        evidence_store: SandboxEvidenceStore,
        approved_images: frozenset[ContainerImageReference],
        docker_executable: str = "docker",
        controlled_network_name: str | None = None,
        clock: UtcClock | None = None,
        runtime_policy: LocalDockerRuntimePolicy = DEFAULT_LOCAL_DOCKER_RUNTIME_POLICY,
    ) -> None:
        """Bind explicit runtime dependencies and immutable adapter policy."""
        if not approved_images:
            raise ValueError("Docker runtime requires at least one approved image")
        if (
            not docker_executable
            or docker_executable != docker_executable.strip()
            or any(character in docker_executable for character in ("\x00", "\r", "\n"))
        ):
            raise ValueError("Docker executable must be normalized")
        if controlled_network_name is not None and (
            not _CONTROLLED_NETWORK_PATTERN.fullmatch(controlled_network_name)
            or controlled_network_name.casefold() in {"bridge", "host", "none"}
        ):
            raise ValueError("controlled Docker network must be an explicit custom name")

        self._process_runner = process_runner
        self._evidence_store = evidence_store
        self._approved_images = approved_images
        self._docker_executable = docker_executable
        self._controlled_network_name = controlled_network_name
        self._clock = clock or SystemUtcClock()
        self._runtime_policy = runtime_policy

    async def execute(
        self,
        request: ContainerExecutionRequest,
    ) -> SandboxRunEvidence:
        """Execute an exact approved plan sequentially and preserve raw evidence."""
        run_started_at = self._clock.now()
        preflight_failure = self._preflight_failure(request)
        if preflight_failure is not None:
            return create_sandbox_run_evidence(
                run_id=request.run_id,
                plan=request.plan,
                image_reference=request.image.value,
                runtime_reference="docker.cli.v1",
                started_at=run_started_at,
                finished_at=self._clock.now(),
                command_evidence=(),
                failure_message=preflight_failure,
            )

        command_evidence: list[SandboxCommandEvidence] = []
        for index, command in enumerate(request.plan.commands, start=1):
            container_name = _container_name(request, index=index)
            command_started_at = self._clock.now()
            process_result = await self._process_runner.run(
                self._build_run_arguments(
                    request,
                    command=command,
                    container_name=container_name,
                ),
                timeout_seconds=command.timeout_seconds,
                maximum_output_bytes_per_stream=(
                    self._runtime_policy.maximum_output_bytes_per_stream
                ),
                environment_overrides={
                    variable.key: variable.value for variable in request.environment_for(command)
                },
            )
            command_finished_at = self._clock.now()

            cleanup_confirmed = True
            if process_result.status is not HostProcessStatus.COMPLETED:
                cleanup_confirmed = await self._cleanup_container(container_name)

            evidence = self._create_command_evidence(
                request,
                command=command,
                process_result=process_result,
                started_at=command_started_at,
                finished_at=command_finished_at,
                cleanup_confirmed=cleanup_confirmed,
            )
            command_evidence.append(evidence)
            if evidence.status is not SandboxCommandStatus.SUCCEEDED:
                break

        return create_sandbox_run_evidence(
            run_id=request.run_id,
            plan=request.plan,
            image_reference=request.image.value,
            runtime_reference="docker.cli.v1",
            started_at=run_started_at,
            finished_at=self._clock.now(),
            command_evidence=tuple(command_evidence),
        )

    def _preflight_failure(self, request: ContainerExecutionRequest) -> str | None:
        """Reject unapproved images and ambiguous host mounts before Docker starts."""
        if request.image not in self._approved_images:
            return "Container image is not present in the approved runtime registry."
        if not _is_safe_workspace(request.workspace_path):
            return "Container workspace path is not canonical and symlink-free."
        workspace_text = str(request.workspace_path)
        if any(character in workspace_text for character in ("\x00", "\r", "\n", ",")):
            return "Container workspace path is incompatible with safe Docker mount syntax."
        if any(variable.is_secret for variable in request.environment_variables):
            return "Secret environment injection requires the governed Gate 7 runtime path."
        if (
            any(
                command.network_mode is CommandNetworkMode.CONTROLLED
                for command in request.plan.commands
            )
            and self._controlled_network_name is None
        ):
            return "Controlled network mode has no approved Docker network."
        return None

    def _build_run_arguments(
        self,
        request: ContainerExecutionRequest,
        *,
        command: StructuredCommand,
        container_name: str,
    ) -> tuple[str, ...]:
        """Translate structured values into one direct Docker CLI argument vector."""
        resources = request.resources
        network_name = (
            "none"
            if command.network_mode is CommandNetworkMode.DISABLED
            else self._controlled_network_name
        )
        if network_name is None:
            raise ValueError("controlled Docker network was not configured")

        workspace_source = str(request.workspace_path.resolve(strict=True))
        workspace_target = self._runtime_policy.workspace_container_path
        working_directory = workspace_target
        if command.working_directory != ".":
            working_directory = (
                f"{workspace_target}/{PurePosixPath(command.working_directory).as_posix()}"
            )

        environment_arguments = tuple(
            argument
            for variable in request.environment_for(command)
            for argument in ("--env", variable.key)
        )
        return (
            self._docker_executable,
            "run",
            "--rm",
            "--pull",
            "never",
            "--name",
            container_name,
            "--init",
            "--user",
            self._runtime_policy.container_user,
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--ipc",
            "none",
            "--pids-limit",
            str(resources.pids_limit),
            "--cpus",
            _format_cpu_count(resources.cpu_count),
            "--memory",
            f"{resources.memory_mib}m",
            "--ulimit",
            f"nproc={resources.pids_limit}:{resources.pids_limit}",
            "--ulimit",
            "nofile=1024:1024",
            "--tmpfs",
            (
                f"{self._runtime_policy.tmpfs_container_path}:"
                "rw,noexec,nosuid,nodev,"
                f"size={resources.writable_tmpfs_mib}m"
            ),
            "--network",
            network_name,
            "--mount",
            f"type=bind,source={workspace_source},target={workspace_target}",
            "--workdir",
            working_directory,
            *environment_arguments,
            request.image.value,
            command.executable,
            *command.arguments,
        )

    def _create_command_evidence(
        self,
        request: ContainerExecutionRequest,
        *,
        command: StructuredCommand,
        process_result: HostProcessResult,
        started_at: datetime,
        finished_at: datetime,
        cleanup_confirmed: bool,
    ) -> SandboxCommandEvidence:
        """Store raw streams, collect bounded artifacts, and normalize status."""
        stdout_log = self._evidence_store.store_log(
            run_id=request.run_id,
            command_id=command.command_id,
            stream=SandboxLogStream.STDOUT,
            content=process_result.stdout,
        )
        stderr_log = self._evidence_store.store_log(
            run_id=request.run_id,
            command_id=command.command_id,
            stream=SandboxLogStream.STDERR,
            content=process_result.stderr,
        )

        collection = self._collect_artifacts(
            request,
            command=command,
        )
        status, exit_code, failure_message = _normalize_process_result(
            process_result,
            command=command,
        )
        if collection.failure_status is not None:
            status = collection.failure_status
            exit_code = None
            failure_message = collection.failure_message
        if not cleanup_confirmed:
            cleanup_message = "Container cleanup could not be confirmed."
            failure_message = (
                cleanup_message
                if failure_message is None
                else f"{failure_message} {cleanup_message}"
            )

        return SandboxCommandEvidence(
            command_id=command.command_id,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            exit_code=exit_code,
            stdout_log=stdout_log,
            stderr_log=stderr_log,
            artifacts=collection.artifacts,
            output_parser_id=command.output_parser_id,
            failure_message=failure_message,
        )

    def _collect_artifacts(
        self,
        request: ContainerExecutionRequest,
        *,
        command: StructuredCommand,
    ) -> _ArtifactCollectionResult:
        """Collect only regular matched files under strict count and byte limits."""
        workspace = request.workspace_path.resolve(strict=True)
        candidates: dict[str, Path] = {}
        try:
            for pattern in sorted(command.artifact_patterns):
                for candidate in workspace.glob(pattern):
                    if candidate.is_dir():
                        continue
                    normalized_path = candidate.relative_to(workspace).as_posix()
                    candidates.setdefault(normalized_path, candidate)
        except (OSError, ValueError):
            return _ArtifactCollectionResult(
                artifacts=(),
                failure_status=SandboxCommandStatus.RUNTIME_ERROR,
                failure_message="Sandbox artifacts could not be enumerated safely.",
            )

        if len(candidates) > self._runtime_policy.maximum_artifacts_per_command:
            return _ArtifactCollectionResult(
                artifacts=(),
                failure_status=SandboxCommandStatus.RESOURCE_LIMIT_EXCEEDED,
                failure_message="Sandbox artifact count exceeded the collection limit.",
            )

        artifacts: list[SandboxArtifactReference] = []
        total_bytes = 0
        for normalized_path, candidate in sorted(candidates.items()):
            if not _is_safe_artifact(
                candidate,
                workspace=workspace,
                runtime_policy=self._runtime_policy,
            ):
                return _ArtifactCollectionResult(
                    artifacts=tuple(artifacts),
                    failure_status=SandboxCommandStatus.RUNTIME_ERROR,
                    failure_message=(
                        "Sandbox artifact is protected or is not a regular workspace file."
                    ),
                )
            try:
                size_bytes = candidate.stat().st_size
            except OSError:
                return _ArtifactCollectionResult(
                    artifacts=tuple(artifacts),
                    failure_status=SandboxCommandStatus.RUNTIME_ERROR,
                    failure_message="Sandbox artifact metadata could not be read.",
                )

            total_bytes += size_bytes
            if (
                size_bytes > self._runtime_policy.maximum_artifact_size_bytes
                or total_bytes > self._runtime_policy.maximum_total_artifact_bytes
            ):
                return _ArtifactCollectionResult(
                    artifacts=tuple(artifacts),
                    failure_status=SandboxCommandStatus.RESOURCE_LIMIT_EXCEEDED,
                    failure_message="Sandbox artifact bytes exceeded the collection limit.",
                )

            try:
                with candidate.open("rb") as artifact_file:
                    content = artifact_file.read(
                        self._runtime_policy.maximum_artifact_size_bytes + 1
                    )
            except OSError:
                return _ArtifactCollectionResult(
                    artifacts=tuple(artifacts),
                    failure_status=SandboxCommandStatus.RUNTIME_ERROR,
                    failure_message="Sandbox artifact content could not be read.",
                )
            if len(content) != size_bytes:
                return _ArtifactCollectionResult(
                    artifacts=tuple(artifacts),
                    failure_status=SandboxCommandStatus.RUNTIME_ERROR,
                    failure_message="Sandbox artifact changed during collection.",
                )

            media_type = mimetypes.guess_type(normalized_path)[0] or "application/octet-stream"
            artifacts.append(
                self._evidence_store.store_artifact(
                    run_id=request.run_id,
                    command_id=command.command_id,
                    normalized_path=normalized_path,
                    content=content,
                    media_type=media_type,
                )
            )

        return _ArtifactCollectionResult(
            artifacts=tuple(artifacts),
            failure_status=None,
            failure_message=None,
        )

    async def _cleanup_container(self, container_name: str) -> bool:
        """Attempt removal after interruption and report whether Docker confirmed it."""
        try:
            result = await self._process_runner.run(
                (
                    self._docker_executable,
                    "rm",
                    "--force",
                    container_name,
                ),
                timeout_seconds=self._runtime_policy.cleanup_timeout_seconds,
                maximum_output_bytes_per_stream=_MEBIBYTE,
                environment_overrides={},
            )
        except (OSError, RuntimeError):
            return False
        return result.status is HostProcessStatus.COMPLETED and result.exit_code == 0


class _OutputLimitExceeded(Exception):
    """Internal signal used to terminate a process with bounded retained output."""


async def _read_bounded_stream(
    stream: asyncio.StreamReader,
    buffer: bytearray,
    *,
    maximum_bytes: int,
) -> None:
    """Drain one process stream and stop before retained output exceeds its limit."""
    while True:
        chunk = await stream.read(64 * 1024)
        if not chunk:
            return
        remaining = maximum_bytes - len(buffer)
        if len(chunk) > remaining:
            if remaining > 0:
                buffer.extend(chunk[:remaining])
            raise _OutputLimitExceeded
        buffer.extend(chunk)


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    """Terminate and reap one process without leaking a background child."""
    if process.returncode is None:
        with suppress(ProcessLookupError):
            process.kill()
    with suppress(ProcessLookupError, OSError):
        await process.wait()


async def _cancel_tasks(tasks: set[asyncio.Task[object]]) -> None:
    """Cancel and retrieve remaining reader/wait tasks."""
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def _normalize_process_result(
    result: HostProcessResult,
    *,
    command: StructuredCommand,
) -> tuple[SandboxCommandStatus, int | None, str | None]:
    """Map Docker CLI outcomes to shared sandbox evidence categories."""
    if result.status is HostProcessStatus.COMPLETED:
        if result.exit_code == 125:
            return (
                SandboxCommandStatus.RUNTIME_ERROR,
                None,
                "Docker runtime rejected the container invocation.",
            )
        if result.exit_code in command.expected_exit_codes:
            return SandboxCommandStatus.SUCCEEDED, result.exit_code, None
        expected = ", ".join(str(code) for code in sorted(command.expected_exit_codes))
        return (
            SandboxCommandStatus.FAILED,
            result.exit_code,
            f"Container command returned exit code {result.exit_code}; expected {expected}.",
        )

    status = {
        HostProcessStatus.TIMED_OUT: SandboxCommandStatus.TIMED_OUT,
        HostProcessStatus.OUTPUT_LIMIT_EXCEEDED: (SandboxCommandStatus.RESOURCE_LIMIT_EXCEEDED),
        HostProcessStatus.SPAWN_ERROR: SandboxCommandStatus.RUNTIME_ERROR,
        HostProcessStatus.RUNTIME_ERROR: SandboxCommandStatus.RUNTIME_ERROR,
    }[result.status]
    return status, None, result.failure_message


def _container_name(request: ContainerExecutionRequest, *, index: int) -> str:
    """Create a deterministic Docker-safe name without project/user data."""
    return f"orchestwin-{request.run_id.hex[:12]}-{index:02d}"


def _format_cpu_count(cpu_count: float) -> str:
    """Serialize CPU limits without unnecessary decimal noise."""
    numeric_value = float(cpu_count)
    if numeric_value.is_integer():
        return str(int(numeric_value))
    return format(numeric_value, ".3f").rstrip("0")


def _is_safe_workspace(workspace: Path) -> bool:
    """Reject non-canonical paths and symlinks in every existing component."""
    try:
        resolved = workspace.resolve(strict=True)
    except OSError:
        return False
    if workspace != resolved or not resolved.is_dir() or resolved.is_symlink():
        return False

    current = Path(resolved.anchor)
    for part in resolved.parts[1:]:
        current = current / part
        if current.is_symlink():
            return False
    return True


def _is_safe_artifact(
    candidate: Path,
    *,
    workspace: Path,
    runtime_policy: LocalDockerRuntimePolicy,
) -> bool:
    """Accept only non-sensitive regular files fully contained in the workspace."""
    try:
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(workspace):
            return False
        if candidate != resolved or candidate.is_symlink() or not candidate.is_file():
            return False

        relative_parts = candidate.relative_to(workspace).parts
        lowered_parts = tuple(part.casefold() for part in relative_parts)
        if any(
            part in runtime_policy.prohibited_artifact_names or part.startswith(".env")
            for part in lowered_parts
        ):
            return False
        if any(
            lowered_parts[-1].endswith(suffix)
            for suffix in runtime_policy.prohibited_artifact_suffixes
        ):
            return False

        current = workspace
        for part in relative_parts:
            current = current / part
            if current.is_symlink():
                return False
        return True
    except (OSError, ValueError):
        return False
