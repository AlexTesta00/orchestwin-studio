"""Bounded Docker transport for canonical JVM phases in a prepared workspace.

The trusted caller owns source verification, per-attempt cache preparation and
authorization. This transport owns only its containers; it does not publish Level D
evidence or relabel a local Docker config digest as a registry manifest digest.
"""

from __future__ import annotations

import asyncio
import json
import re
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from orchestwin.jvm_execution.dependency_network import CommandOutput, verify_dependency_network
from orchestwin.jvm_execution.dependency_setup import setup_configuration
from orchestwin.jvm_execution.plans import JvmExecutionPhase, JvmExecutionPlanBundle
from orchestwin.jvm_execution.runner_contracts import JvmContainerRunnerContract
from orchestwin.jvm_execution.targets import JvmBuildSystem
from orchestwin.sandbox.docker_runtime import (
    AsyncioHostProcessRunner,
    HostProcessResult,
    HostProcessStatus,
)

_ID = re.compile(r"[0-9a-f]{64}")
_OWNER = "org.orchestwin.jvm-phase-owner"
_ATTEMPT = "org.orchestwin.jvm-execution-attempt"
_PLAN = "org.orchestwin.jvm-command-plan"
_CLEARED = (
    *(
        name
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "FTP_PROXY", "ALL_PROXY", "NO_PROXY")
        for name in (key, key.lower())
    ),
    "JAVA_OPTS",
    "JAVA_TOOL_OPTIONS",
    "_JAVA_OPTIONS",
    "JDK_JAVA_OPTIONS",
    "GRADLE_OPTS",
    "CLASSPATH",
    "SBT_OPTS",
)


class JvmPhaseRuntimeError(RuntimeError):
    """Safe code plus actual bounded command output, if a command was observed."""

    def __init__(self, code: str, *, command_result: HostProcessResult | None = None):
        super().__init__(code)
        self.command_result = command_result


@dataclass(frozen=True, slots=True)
class JvmContainerPhaseObservation:
    """Transport observations; phase normalization and durable storage are separate."""

    attempt_id: UUID
    phase: JvmExecutionPhase
    command_plan_hash: str
    image_id: str
    container_id: str
    network_id: str
    dependency_network_manifest_hash: str | None
    process: HostProcessResult
    started_at: datetime
    completed_at: datetime
    container_exit_code: int | None
    oom_killed: bool
    cleanup_confirmed: bool


@dataclass(slots=True)
class _OwnedContainer:
    name: str
    plan_hash: str
    identifier: str | None = None


class LocalJvmPhaseRuntime:
    """Sequential finite phases, with one isolated container per canonical command.

    The workspace must be a fresh verified copy owned by the calling executor.
    Runtime configuration files must already match ``setup_configuration`` for
    this phase. No host environment or cache is forwarded into the container.
    """

    def __init__(
        self,
        *,
        attempt_id: UUID,
        execution_plan: JvmExecutionPlanBundle,
        runner_contract: JvmContainerRunnerContract,
        workspace: Path,
        docker_context: str,
        dependency_network_manifest: Path | None = None,
        dependency_network_manifest_hash: str | None = None,
        process_runner=None,
        maximum_output_bytes: int = 2 * 1024 * 1024,
    ):
        if not isinstance(attempt_id, UUID) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", docker_context
        ):
            raise ValueError("JVM_RUNTIME_IDENTITY_INVALID")
        if (
            type(maximum_output_bytes) is not int
            or not 1 <= maximum_output_bytes <= 8 * 1024 * 1024
        ):
            raise ValueError("JVM_RUNTIME_OUTPUT_LIMIT_INVALID")
        if (dependency_network_manifest is None) != (dependency_network_manifest_hash is None):
            raise ValueError("JVM_RUNTIME_NETWORK_RECEIPT_REQUIRED")
        if dependency_network_manifest_hash is not None and not _ID.fullmatch(
            dependency_network_manifest_hash
        ):
            raise ValueError("JVM_RUNTIME_NETWORK_RECEIPT_HASH_INVALID")
        self.attempt_id, self.plan, self.contract = attempt_id, execution_plan, runner_contract
        self.workspace = Path(workspace)
        self._workspace_identity = self._workspace_stat()
        # This also rejects a modified plan, policy, or mismatched runner family.
        self.contract.create_request(
            run_id=attempt_id,
            execution_plan=execution_plan,
            phase=JvmExecutionPhase.VALIDATE,
            workspace_path=self.workspace,
        )
        self.image_id = f"sha256:{runner_contract.image.digest}"
        self.context = docker_context
        self.docker = ("docker", "--context", docker_context)
        self.manifest, self.manifest_hash = (
            dependency_network_manifest,
            dependency_network_manifest_hash,
        )
        self.runner = process_runner or AsyncioHostProcessRunner()
        self.maximum_output_bytes = maximum_output_bytes
        self._owner = uuid4().hex
        self._owned: _OwnedContainer | None = None
        self._next_phase = 0
        self._busy = self._closed = self._failed = False

    def _workspace_stat(self):
        path = self.workspace
        if not path.is_absolute() or any(
            character in str(path) for character in (",", "\r", "\n", "\0")
        ):
            raise ValueError("JVM_RUNTIME_WORKSPACE_INVALID")
        if ".." in path.parts or path.resolve() != path:
            raise ValueError("JVM_RUNTIME_WORKSPACE_INVALID")
        self._regular(path, directory=True)
        info = path.stat()
        return info.st_dev, info.st_ino

    @staticmethod
    def _regular(path: Path, *, directory=False):
        for parent in (path, *path.parents):
            if parent.is_symlink() or parent.is_junction():
                raise JvmPhaseRuntimeError("JVM_RUNTIME_WORKSPACE_REDIRECTED")
        info = path.stat()
        if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
            raise JvmPhaseRuntimeError("JVM_RUNTIME_FILE_TYPE_INVALID")
        return info

    async def _call(self, *arguments, timeout=30):
        return await self.runner.run(
            (*self.docker, *arguments),
            timeout_seconds=timeout,
            maximum_output_bytes_per_stream=self.maximum_output_bytes,
            environment_overrides={},
        )

    @staticmethod
    def _require(result):
        if result.status is not HostProcessStatus.COMPLETED or result.exit_code != 0:
            raise JvmPhaseRuntimeError("JVM_DOCKER_OPERATION_FAILED")
        return result

    async def _inspect(self, kind, identifier):
        result = self._require(await self._call(kind, "inspect", identifier))
        try:
            data = json.loads(result.stdout)
            if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
                raise ValueError
            return data[0]
        except (ValueError, TypeError):
            raise JvmPhaseRuntimeError("JVM_DOCKER_METADATA_INVALID") from None

    async def _open(self):
        if self._workspace_stat() != self._workspace_identity:
            raise JvmPhaseRuntimeError("JVM_RUNTIME_WORKSPACE_REPLACED")
        context = await self._inspect("context", self.context)
        endpoint = context.get("Endpoints", {}).get("docker", {}).get("Host", "")
        if (
            context.get("Name") != self.context
            or not isinstance(endpoint, str)
            or not (
                re.fullmatch(r"npipe:/{4}\./pipe/[A-Za-z0-9_.-]+", endpoint)
                or re.fullmatch(r"unix:///[A-Za-z0-9_./-]+", endpoint)
            )
        ):
            raise JvmPhaseRuntimeError("JVM_LOCAL_DOCKER_REQUIRED")
        actual = await self._inspect("image", self.image_id)
        if (
            actual.get("Id") != self.image_id
            or actual.get("Os") != "linux"
            or actual.get("Architecture") != "amd64"
            or set(actual.get("Config", {}).get("Volumes") or {})
            - (
                {"/home/gradle/.gradle"}
                if self.contract.build_system is JvmBuildSystem.GRADLE_KOTLIN_DSL
                else set()
            )
        ):
            raise JvmPhaseRuntimeError("JVM_RUNNER_IDENTITY_MISMATCH")

    async def _network(self, phase):
        if phase is not JvmExecutionPhase.SETUP:
            return None
        if self.manifest is None:
            raise JvmPhaseRuntimeError("JVM_CONTROLLED_NETWORK_UNAVAILABLE")

        async def transport(argv, *, timeout, limit, stdin_bytes=None):
            assert stdin_bytes is None
            result = await self.runner.run(
                argv,
                timeout_seconds=timeout,
                maximum_output_bytes_per_stream=limit,
                environment_overrides={},
            )
            return CommandOutput(
                result.exit_code, result.stdout, result.stderr, result.status.value
            )

        return await verify_dependency_network(
            self.manifest,
            expected_content_hash=self.manifest_hash,
            docker_context=self.context,
            runner=transport,
        )

    def _configuration(self, network):
        config = setup_configuration(self.plan.target_selection.target, self.attempt_id, network)
        for relative, expected in config.file_payloads:
            path = self.workspace / relative
            info = self._regular(path)
            if info.st_nlink != 1 or info.st_size != len(expected):
                raise JvmPhaseRuntimeError("JVM_RUNTIME_CONFIGURATION_MISMATCH")
            with path.open("rb") as stream:
                actual = stream.read(len(expected) + 1)
            if actual != expected:
                raise JvmPhaseRuntimeError("JVM_RUNTIME_CONFIGURATION_MISMATCH")
        home = next(
            variable.value for variable in config.environment_variables if variable.key == "HOME"
        )
        self._regular(self.workspace / home.removeprefix("/workspace/"), directory=True)
        return config.environment_variables

    def _environment(self, variables):
        return {**dict.fromkeys(_CLEARED, ""), **{item.key: item.value for item in variables}}

    def _tmpfs(self):
        values = {
            "/tmp": f"rw,exec,nosuid,nodev,size={self.contract.resources.writable_tmpfs_mib}m,mode=1777"
        }
        if self.contract.build_system is JvmBuildSystem.GRADLE_KOTLIN_DSL:
            # The pinned Gradle base declares VOLUME here. Mask it to prevent an
            # anonymous persistent cache; all dependency bytes belong to the attempt.
            values["/home/gradle/.gradle"] = "ro,noexec,nosuid,nodev,size=1m,mode=000"
        return values

    def _arguments(self, owned, command, network_id, variables):
        resources = self.contract.resources
        return (
            "create",
            "--name",
            owned.name,
            "--pull=never",
            "--init",
            "--label",
            f"{_OWNER}={self._owner}",
            "--label",
            f"{_ATTEMPT}={self.attempt_id}",
            "--label",
            f"{_PLAN}={owned.plan_hash}",
            "--user",
            "65532:65532",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--ipc=private",
            "--cgroupns=private",
            "--cpus",
            str(resources.cpu_count),
            "--memory",
            f"{resources.memory_mib}m",
            "--memory-swap",
            f"{resources.memory_mib}m",
            "--pids-limit",
            str(resources.pids_limit),
            *(
                part
                for path, options in self._tmpfs().items()
                for part in ("--tmpfs", f"{path}:{options}")
            ),
            "--network",
            network_id,
            "--log-driver",
            "none",
            "--mount",
            f"type=bind,source={self.workspace},target=/workspace",
            "--workdir",
            "/workspace",
            *(
                part
                for key, value in sorted(self._environment(variables).items())
                for part in ("--env", f"{key}={value}")
            ),
            "--entrypoint",
            command.executable,
            self.image_id,
            *command.arguments,
        )

    def _identity(self, item, owned):
        labels = item.get("Config", {}).get("Labels") or {}
        identifier = item.get("Id")
        if (
            not isinstance(identifier, str)
            or not _ID.fullmatch(identifier)
            or (owned.identifier is not None and identifier != owned.identifier)
            or item.get("Name") != f"/{owned.name}"
            or item.get("Image") != self.image_id
            or labels.get(_OWNER) != self._owner
            or labels.get(_ATTEMPT) != str(self.attempt_id)
            or labels.get(_PLAN) != owned.plan_hash
        ):
            raise JvmPhaseRuntimeError("JVM_CONTAINER_OWNERSHIP_MISMATCH")

    def _verify_container(self, item, owned, command, network_id, variables, *, prestart):
        self._identity(item, owned)
        config, host = item.get("Config", {}), item.get("HostConfig", {})
        resources = self.contract.resources
        environment = config.get("Env") or []
        mounts = host.get("Mounts") or []
        expected_mount = {"Type": "bind", "Source": str(self.workspace), "Target": "/workspace"}
        if (
            config.get("User") != "65532:65532"
            or config.get("WorkingDir") != "/workspace"
            or config.get("Entrypoint") != [command.executable]
            or config.get("Cmd") != list(command.arguments)
            or any(
                [entry for entry in environment if entry.startswith(f"{key}=")]
                != [f"{key}={value}"]
                for key, value in self._environment(variables).items()
            )
            or host.get("ReadonlyRootfs") is not True
            or host.get("Privileged") is not False
            or host.get("Init") is not True
            or host.get("CapDrop") != ["ALL"]
            or host.get("CapAdd")
            or host.get("SecurityOpt") != ["no-new-privileges"]
            or host.get("IpcMode") != "private"
            or host.get("CgroupnsMode") != "private"
            or host.get("PidMode")
            or host.get("UTSMode")
            or host.get("Memory") != resources.memory_mib * 1024 * 1024
            or host.get("MemorySwap") != resources.memory_mib * 1024 * 1024
            or host.get("NanoCpus") != int(resources.cpu_count * 1_000_000_000)
            or host.get("PidsLimit") != resources.pids_limit
            or host.get("Tmpfs") != self._tmpfs()
            or host.get("NetworkMode") != network_id
            or host.get("LogConfig") != {"Type": "none", "Config": {}}
            or any(
                host.get(key)
                for key in (
                    "Binds",
                    "VolumesFrom",
                    "Devices",
                    "DeviceRequests",
                    "PortBindings",
                    "PublishAllPorts",
                )
            )
            or len(mounts) != 1
            or any(mounts[0].get(key) != value for key, value in expected_mount.items())
            or mounts[0].get("ReadOnly", False) is not False
            or len(item.get("Mounts", [])) != 1
            or item["Mounts"][0].get("Type") != "bind"
            or item["Mounts"][0].get("Destination") != "/workspace"
            or item["Mounts"][0].get("RW") is not True
            or any((item.get("NetworkSettings", {}).get("Ports") or {}).values())
        ):
            raise JvmPhaseRuntimeError("JVM_CONTAINER_SECURITY_MISMATCH")
        networks = item.get("NetworkSettings", {}).get("Networks") or {}
        if len(networks) != 1 or (
            network_id != "none"
            and any(
                details.get("NetworkID") not in ({"", network_id} if prestart else {network_id})
                for details in networks.values()
            )
        ):
            raise JvmPhaseRuntimeError("JVM_CONTAINER_NETWORK_MISMATCH")
        if network_id == "none" and set(networks) != {"none"}:
            raise JvmPhaseRuntimeError("JVM_CONTAINER_NETWORK_MISMATCH")
        if prestart and (
            item.get("State", {}).get("Status") != "created"
            or item["State"].get("Running") is not False
        ):
            raise JvmPhaseRuntimeError("JVM_CONTAINER_ALREADY_STARTED")

    async def _absent(self, owned):
        selection = f"id={owned.identifier}" if owned.identifier else f"name=^/{owned.name}$"
        result = self._require(
            await self._call(
                "container",
                "ls",
                "--all",
                "--no-trunc",
                "--filter",
                selection,
                "--format",
                "{{.ID}}",
            )
        )
        return not result.stdout.strip()

    async def _remove_owned(self):
        owned = self._owned
        if owned is None:
            return
        if await self._absent(owned):
            self._owned = None
            return
        item = await self._inspect("container", owned.identifier or owned.name)
        self._identity(item, owned)
        owned.identifier = item["Id"]
        self._require(await self._call("container", "rm", "--force", owned.identifier))
        if not await self._absent(owned):
            raise JvmPhaseRuntimeError("JVM_CONTAINER_CLEANUP_UNCONFIRMED")
        self._owned = None

    async def _cleanup(self):
        task = asyncio.create_task(self._remove_owned())
        cancelled = False
        try:
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    cancelled = True
            task.result()
        finally:
            if cancelled:
                raise asyncio.CancelledError

    async def close(self):
        """Retry pending owned cleanup; never remove the workspace or dependency network."""
        if self._busy:
            raise JvmPhaseRuntimeError("JVM_RUNTIME_PHASE_ACTIVE")
        self._closed = True
        await self._cleanup()

    async def run_phase(self, phase: JvmExecutionPhase) -> JvmContainerPhaseObservation:
        if (
            self._busy
            or self._closed
            or self._failed
            or self._next_phase >= len(JvmExecutionPhase)
            or phase is not tuple(JvmExecutionPhase)[self._next_phase]
        ):
            raise JvmPhaseRuntimeError("JVM_RUNTIME_PHASE_ORDER_INVALID")
        self._busy = True
        process = None
        try:
            await self._open()
            network = await self._network(phase)
            network_id = "none" if network is None else network.network_id
            variables = self._configuration(network)
            request = self.contract.create_request(
                run_id=self.attempt_id,
                execution_plan=self.plan,
                phase=phase,
                workspace_path=self.workspace,
                environment_variables=variables,
            )
            command = request.plan.commands[0]
            owned = _OwnedContainer(
                f"owjvmphase-{self.attempt_id.hex}-{phase.value.lower()}", request.plan.content_hash
            )
            if not await self._absent(owned):
                raise JvmPhaseRuntimeError("JVM_CONTAINER_NAME_ALREADY_PRESENT")
            self._owned = owned
            created = self._require(
                await self._call(*self._arguments(owned, command, network_id, variables))
            )
            identifier = created.stdout.decode("ascii").strip()
            if not _ID.fullmatch(identifier):
                raise JvmPhaseRuntimeError("JVM_CONTAINER_ID_INVALID")
            # Keep recovery by the owned name until the returned ID is confirmed.
            actual = await self._inspect("container", owned.name)
            self._identity(actual, owned)
            if actual["Id"] != identifier:
                raise JvmPhaseRuntimeError("JVM_CONTAINER_ID_MISMATCH")
            owned.identifier = identifier
            self._verify_container(actual, owned, command, network_id, variables, prestart=True)
            started = datetime.now(UTC)
            process = await self._call(
                "start", "--attach", identifier, timeout=command.timeout_seconds
            )
            actual = await self._inspect("container", identifier)
            self._verify_container(actual, owned, command, network_id, variables, prestart=False)
            state = actual.get("State", {})
            exit_code = (
                state.get("ExitCode")
                if state.get("Status") == "exited" and state.get("Running") is False
                else None
            )
            if process.status is HostProcessStatus.COMPLETED:
                try:
                    start = datetime.fromisoformat(state.get("StartedAt", ""))
                    finish = datetime.fromisoformat(state.get("FinishedAt", ""))
                    if (
                        type(exit_code) is not int
                        or exit_code != process.exit_code
                        or start.tzinfo is None
                        or finish.tzinfo is None
                        or start <= datetime(1970, 1, 1, tzinfo=UTC)
                        or finish < start
                    ):
                        raise ValueError
                except (ValueError, TypeError):
                    raise JvmPhaseRuntimeError(
                        "JVM_COMMAND_COMPLETION_UNCONFIRMED", command_result=process
                    ) from None
            if type(state.get("OOMKilled")) is not bool:
                raise JvmPhaseRuntimeError("JVM_CONTAINER_STATE_INVALID", command_result=process)
            await self._cleanup()
            observation = JvmContainerPhaseObservation(
                self.attempt_id,
                phase,
                request.plan.content_hash,
                self.image_id,
                identifier,
                network_id,
                self.manifest_hash if network else None,
                process,
                started,
                datetime.now(UTC),
                exit_code,
                state["OOMKilled"],
                True,
            )
            self._next_phase += 1
            self._failed = (
                process.status is not HostProcessStatus.COMPLETED
                or process.exit_code != 0
                or state["OOMKilled"]
            )
            return observation
        except BaseException as error:
            self._failed = True
            if isinstance(error, JvmPhaseRuntimeError) and error.command_result is None:
                error.command_result = process
            raise
        finally:
            try:
                await self._cleanup()
            except BaseException as error:
                self._failed = True
                if isinstance(error, JvmPhaseRuntimeError) and error.command_result is None:
                    error.command_result = process
                raise
            finally:
                self._busy = False
