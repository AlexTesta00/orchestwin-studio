"""Bounded Docker transport for finite Web commands and isolated HTTP sessions.

The caller supplies a verified temporary workspace and policy-validated commands.
Local config digests remain local identities; they are never labelled registry digests.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orchestwin.sandbox.command_plans import CommandNetworkMode, StructuredCommand
from orchestwin.sandbox.docker_runtime import (
    AsyncioHostProcessRunner,
    HostProcessResult,
    HostProcessStatus,
)
from orchestwin.sandbox.execution_policy import SandboxResourceLimits
from orchestwin.sandbox.host_process import BoundedHostProcessResult

_NODE_WRAPPER = r"""
const {spawn} = require('node:child_process');
const {constants} = require('node:os');
process.umask(0);
const argv = JSON.parse(process.argv[1]);
const child = spawn(argv[0], argv.slice(1), {stdio:'inherit', shell:false});
child.on('error', () => { process.stderr.write('Web command could not start.\n'); process.exitCode = 127; });
child.on('exit', (code, signal) => {
  process.exitCode = code === null ? 128 + (constants.signals[signal] || 0) : code;
});
for (const signal of ['SIGTERM', 'SIGINT', 'SIGHUP']) {
  process.on(signal, () => child.kill(signal));
}
""".strip()

_PHP_WRAPPER = r"""
umask(0);
$args = json_decode($argv[1], true, 512, JSON_THROW_ON_ERROR);
$process = proc_open($args, [0=>STDIN, 1=>STDOUT, 2=>STDERR], $pipes, null, null, ['bypass_shell'=>true]);
if (!is_resource($process)) { fwrite(STDERR, "Web command could not start.\n"); exit(127); }
$code = proc_close($process);
exit($code < 0 ? 125 : $code);
""".strip()


class WebPhaseRuntimeError(RuntimeError):
    """Safe boundary failure without raw Docker configuration or host paths."""

    def __init__(
        self,
        code,
        *,
        result=None,
        observations=(),
        command_result=None,
        browser_cleanup_failures=(),
    ):
        super().__init__(code)
        self.result = result
        self.observations = tuple(observations)
        self.command_result = command_result
        self.browser_cleanup_failures = tuple(browser_cleanup_failures)


@dataclass(frozen=True, slots=True)
class WebBrowserCleanupFailure:
    """An unresolved owned sidecar and its actual bounded transport observations."""

    operation_id: str
    container_id: str | None
    container_name: str
    operations: tuple[tuple[str, BoundedHostProcessResult], ...]


@dataclass(slots=True)
class _ServerSession:
    name: str
    task: asyncio.Task | None = None
    result: HostProcessResult | None = None
    state: dict | None = None
    error: WebPhaseRuntimeError | None = None


@dataclass(frozen=True, slots=True)
class ControlledWebNetwork:
    """Operator-provisioned internal network and restricted egress proxy.

    Provisioning and authorization belong to the trusted execution composition.
    This adapter verifies its immutable Docker ID and policy label before use.
    It never creates a network or falls back to Docker's default bridge.
    """

    name: str
    network_id: str
    policy_hash: str
    proxy_host: str
    proxy_port: int

    def __post_init__(self):
        if any(
            not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}", value)
            for value in (self.name, self.proxy_host)
        ):
            raise ValueError("WEB_CONTROLLED_NETWORK_NAME_INVALID")
        if any(
            not re.fullmatch(r"[0-9a-f]{64}", value)
            for value in (self.network_id, self.policy_hash)
        ):
            raise ValueError("WEB_CONTROLLED_NETWORK_IDENTITY_INVALID")
        if type(self.proxy_port) is not int or not 1 <= self.proxy_port <= 65535:
            raise ValueError("WEB_CONTROLLED_PROXY_PORT_INVALID")


class LocalWebPhaseRuntime:
    """One attempt's containers, never a shared process/session singleton."""

    def __init__(
        self,
        *,
        image_id: str,
        runner_kind: str,
        workspace: Path,
        resources: SandboxResourceLimits,
        docker_context: str,
        process_runner=None,
        controlled_network: ControlledWebNetwork | None = None,
        maximum_output_bytes: int = 1024 * 1024,
    ):
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise ValueError("WEB_LOCAL_IMAGE_ID_INVALID")
        if runner_kind not in {"NODE", "PHP"} or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", docker_context
        ):
            raise ValueError("WEB_RUNTIME_CONFIGURATION_INVALID")
        if (
            type(maximum_output_bytes) is not int
            or not 1 <= maximum_output_bytes <= 8 * 1024 * 1024
        ):
            raise ValueError("WEB_RUNTIME_OUTPUT_LIMIT_INVALID")
        self.image_id, self.runner_kind = image_id, runner_kind
        self.workspace, self.resources = Path(workspace).absolute(), resources
        self.docker = ("docker", "--context", docker_context)
        self.context = docker_context
        self.runner = process_runner or AsyncioHostProcessRunner()
        self.controlled_network = controlled_network
        self.maximum_output_bytes = maximum_output_bytes
        self._names: list[str] = []
        self._servers: list[str] = []
        self._sessions: dict[str, _ServerSession] = {}
        self._browser_cleanup_failures: list[WebBrowserCleanupFailure] = []
        self._opened = False
        self._closed = False

    @property
    def browser_cleanup_failures(self) -> tuple[WebBrowserCleanupFailure, ...]:
        return tuple(self._browser_cleanup_failures)

    def record_browser_cleanup_failure(
        self, *, operation_id, container_id, container_name, operations
    ):
        # This must finish without awaiting: cancellation cannot discard the
        # unresolved resource after the transport's shielded cleanup completes.
        self._browser_cleanup_failures.append(
            WebBrowserCleanupFailure(operation_id, container_id, container_name, tuple(operations))
        )

    async def _call(self, argv, *, timeout_seconds=30):
        return await self.runner.run(
            tuple(argv),
            timeout_seconds=timeout_seconds,
            maximum_output_bytes_per_stream=self.maximum_output_bytes,
            environment_overrides={},
        )

    @staticmethod
    def _require(result):
        if result.status is not HostProcessStatus.COMPLETED or result.exit_code != 0:
            raise WebPhaseRuntimeError("WEB_DOCKER_OPERATION_FAILED", result=result)
        return result

    async def _inspect(self, *argv):
        try:
            data = json.loads(self._require(await self._call((*self.docker, *argv))).stdout)
            if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
                raise ValueError
            return data[0]
        except (ValueError, TypeError):
            raise WebPhaseRuntimeError("WEB_DOCKER_METADATA_INVALID") from None

    async def open(self):
        if self._closed:
            raise WebPhaseRuntimeError("WEB_SESSION_CLOSED")
        if self._opened:
            return
        self._workdir(".")
        context = await self._inspect("context", "inspect", self.context)
        endpoint = context.get("Endpoints", {}).get("docker", {}).get("Host", "")
        if not isinstance(endpoint, str) or not endpoint.startswith(("unix://", "npipe://")):
            raise WebPhaseRuntimeError("WEB_LOCAL_DOCKER_REQUIRED")
        image = await self._inspect("image", "inspect", self.image_id)
        if (
            image.get("Id") != self.image_id
            or image.get("Os") != "linux"
            or image.get("Architecture") != "amd64"
        ):
            raise WebPhaseRuntimeError("WEB_RUNNER_IDENTITY_MISMATCH")
        self._opened = True

    def _workdir(self, relative):
        target = self.workspace if relative == "." else self.workspace / relative
        if ".." in target.parts or not target.is_dir():
            raise WebPhaseRuntimeError("WEB_WORKING_DIRECTORY_INVALID")
        if any(path.is_symlink() or path.is_junction() for path in (target, *target.parents)):
            raise WebPhaseRuntimeError("WEB_WORKSPACE_REDIRECTED")
        if not target.resolve().is_relative_to(self.workspace.resolve()):
            raise WebPhaseRuntimeError("WEB_WORKSPACE_ESCAPE")
        if any(char in str(self.workspace) for char in (",", "\n", "\r", "\x00")):
            raise WebPhaseRuntimeError("WEB_WORKSPACE_MOUNT_INVALID")
        return "/workspace" if relative == "." else f"/workspace/{relative}"

    async def _network(self, command):
        if command.network_mode is CommandNetworkMode.DISABLED:
            return "none", ()
        network = self.controlled_network
        if network is None:
            raise WebPhaseRuntimeError("WEB_CONTROLLED_NETWORK_UNAVAILABLE")
        actual = await self._inspect("network", "inspect", network.network_id)
        if (
            actual.get("Id") != network.network_id
            or actual.get("Name") != network.name
            or actual.get("Internal") is not True
            or actual.get("Driver") != "bridge"
            or actual.get("Labels", {}).get("org.orchestwin.egress-policy") != network.policy_hash
        ):
            raise WebPhaseRuntimeError("WEB_CONTROLLED_NETWORK_IDENTITY_MISMATCH")
        proxy = f"http://{network.proxy_host}:{network.proxy_port}"
        return network.network_id, tuple(
            part
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")
            for part in ("--env", f"{key}={proxy}")
        )

    def _arguments(self, operation, name, command, network, extra_environment):
        r = self.resources
        executable = "php" if self.runner_kind == "PHP" else "node"
        wrapper = _PHP_WRAPPER if self.runner_kind == "PHP" else _NODE_WRAPPER
        flag = "-r" if self.runner_kind == "PHP" else "-e"
        arguments = json.dumps([command.executable, *command.arguments], ensure_ascii=True)
        return (
            *self.docker,
            operation,
            "--name",
            name,
            "--pull=never",
            "--init",
            "--user",
            "65532:65532",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            str(r.pids_limit),
            "--memory",
            f"{r.memory_mib}m",
            "--memory-swap",
            f"{r.memory_mib}m",
            "--cpus",
            str(r.cpu_count),
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,nodev,size={r.writable_tmpfs_mib}m,mode=1777",
            "--network",
            network,
            "--log-driver",
            "none",
            "--mount",
            f"type=bind,source={self.workspace},target=/workspace",
            "--workdir",
            self._workdir(command.working_directory),
            "--env",
            "HOME=/tmp",
            "--env",
            "NPM_CONFIG_CACHE=/tmp/npm-cache",
            "--env",
            "COMPOSER_HOME=/tmp/composer",
            "--env",
            "CI=true",
            "--env",
            "NODE_ENV=development",
            *(
                part
                for key in ("HTTP_PROXY", "HTTPS_PROXY", "FTP_PROXY", "ALL_PROXY", "NO_PROXY")
                for variant in (key, key.lower())
                for part in ("--env", f"{variant}=")
            ),
            *extra_environment,
            "--entrypoint",
            executable,
            self.image_id,
            flag,
            wrapper,
            "--",
            arguments,
        )

    async def _terminal_launch(self, name, observed):
        """Distinguish Docker CLI failures from a completed process in the owned image."""
        try:
            metadata = await self._inspect("inspect", name)
            state = metadata.get("State")
            if not isinstance(state, dict):
                raise ValueError
            started = datetime.fromisoformat(state.get("StartedAt"))
            finished = datetime.fromisoformat(state.get("FinishedAt"))
            if (
                observed.status is not HostProcessStatus.COMPLETED
                or metadata.get("Image") != self.image_id
                or state.get("Status") != "exited"
                or state.get("Running") is not False
                or type(state.get("ExitCode")) is not int
                or state["ExitCode"] != observed.exit_code
                or started.tzinfo is None
                or finished.tzinfo is None
                or started <= datetime(1970, 1, 1, tzinfo=UTC)
                or finished < started
            ):
                raise ValueError
            return state
        except (OSError, TypeError, ValueError, WebPhaseRuntimeError):
            raise WebPhaseRuntimeError("WEB_COMMAND_LAUNCH_UNCONFIRMED", result=observed) from None

    async def run_command(self, command: StructuredCommand):
        await self.open()
        network, environment = await self._network(command)
        name = f"orchestwin-web-phase-{uuid4().hex}"
        self._names.append(name)
        observed = None
        command_observed = False
        try:
            observed = await self._call(
                self._arguments("run", name, command, network, environment),
                timeout_seconds=command.timeout_seconds,
            )
            if observed.status is HostProcessStatus.COMPLETED:
                await self._terminal_launch(name, observed)
            command_observed = True
            return observed
        finally:
            try:
                await self._remove((name,))
            except WebPhaseRuntimeError as error:
                if observed is not None:
                    if command_observed:
                        error.command_result = observed
                    else:
                        error.result = observed
                raise

    async def _capture_server(self, session, timeout_seconds):
        """Own one bounded attach stream and remove runaway containers immediately."""
        try:
            session.result = await self._call(
                (*self.docker, "start", "--attach", session.name),
                timeout_seconds=timeout_seconds,
            )
        except OSError:
            session.result = HostProcessResult(
                HostProcessStatus.RUNTIME_ERROR, None, b"", b"", "Web attach transport failed."
            )
        if session.result.status is not HostProcessStatus.COMPLETED:
            try:
                # Killing the Docker CLI on a host limit does not stop its container.
                # Retain only an observed final State, before force-removal discards it.
                killed = await self._call((*self.docker, "kill", session.name))
                inspected = await self._inspect("inspect", session.name)
                state = inspected.get("State")
                if not isinstance(state, dict) or state.get("Running") is not False:
                    self._require(killed)
                    raise WebPhaseRuntimeError("WEB_SERVER_TERMINATION_UNCONFIRMED")
                session.state = state
            except WebPhaseRuntimeError as error:
                session.error = error
            finally:
                try:
                    await self._remove((session.name,))
                except WebPhaseRuntimeError as error:
                    session.error = error
        return session.result

    async def _drain_sessions(self, sessions):
        """Reap attach transports after removal, including repeated cancellation."""
        tasks = tuple(item.task for item in sessions if item.task is not None)
        if not tasks:
            return

        async def drain():
            await asyncio.gather(*tasks)

        task = asyncio.create_task(drain())
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        if cancelled:
            raise asyncio.CancelledError

    async def start_command(self, command: StructuredCommand):
        await self.open()
        if (
            command.network_mode is not CommandNetworkMode.DISABLED
            or len(self._sessions) >= 2
            or any(item.result is not None for item in self._sessions.values())
        ):
            raise WebPhaseRuntimeError("WEB_SERVER_PLAN_INVALID")
        name = f"orchestwin-web-server-{uuid4().hex}"
        network = "none" if not self._servers else f"container:{self._servers[0]}"
        self._names.append(name)
        session = _ServerSession(name)
        command_observed = False
        try:
            self._require(await self._call(self._arguments("create", name, command, network, ())))
            self._sessions[name] = session
            session.task = asyncio.create_task(
                self._capture_server(session, command.timeout_seconds)
            )
            deadline = asyncio.get_running_loop().time() + min(30, command.timeout_seconds)
            while True:
                # Scheduling attach before inspect also avoids interpreting a created container
                # as a failed application before Docker has started it.
                await asyncio.sleep(0)
                if session.result is not None or session.task.done():
                    await asyncio.shield(session.task)
                    session.state = await self._terminal_launch(name, session.result)
                    command_observed = True
                    raise WebPhaseRuntimeError(
                        "WEB_SERVER_DID_NOT_START", command_result=session.result
                    )
                state = await self._inspect("inspect", name)
                if state.get("Image") != self.image_id:
                    raise WebPhaseRuntimeError("WEB_RUNNER_IDENTITY_MISMATCH")
                if state.get("State", {}).get("Running") is True and session.result is None:
                    self._servers.append(name)
                    return name
                if asyncio.get_running_loop().time() >= deadline:
                    raise WebPhaseRuntimeError("WEB_SERVER_START_TIMEOUT", result=session.result)
                await asyncio.sleep(0.02)
        except BaseException as original:
            cleanup_error = None
            try:
                await self._remove((name,))
            except WebPhaseRuntimeError as error:
                cleanup_error = error
            finally:
                await self._drain_sessions((session,))
            self._sessions.pop(name, None)
            if isinstance(original, asyncio.CancelledError):
                raise
            if cleanup_error is not None:
                if command_observed:
                    cleanup_error.command_result = session.result
                elif session.result is not None:
                    cleanup_error.result = session.result
                raise cleanup_error from original
            if isinstance(original, WebPhaseRuntimeError) and command_observed:
                original.command_result = session.result
            raise

    async def browser_network(self) -> str:
        """Expose only the immutable ID of this attempt's running isolated server."""
        if (
            self._closed
            or not self._servers
            or any(item.result is not None for item in self._sessions.values())
        ):
            raise WebPhaseRuntimeError("WEB_SERVER_NOT_RUNNING")
        actual = await self._inspect("inspect", self._servers[0])
        identifier = actual.get("Id")
        if (
            not isinstance(identifier, str)
            or re.fullmatch(r"[0-9a-f]{64}", identifier) is None
            or actual.get("Image") != self.image_id
            or actual.get("State", {}).get("Running") is not True
            or actual.get("HostConfig", {}).get("NetworkMode") != "none"
            or actual.get("Config", {}).get("User") != "65532:65532"
        ):
            raise WebPhaseRuntimeError("WEB_BROWSER_NETWORK_UNVERIFIED")
        return identifier

    async def invoke(self, argv: tuple[str, ...], *, timeout_seconds: int):
        if not self._servers:
            raise WebPhaseRuntimeError("WEB_SERVER_NOT_RUNNING")
        for session in self._sessions.values():
            if session.result is not None:
                raise WebPhaseRuntimeError(
                    "WEB_SERVER_EXITED_BEFORE_CONTROLLER", command_result=session.result
                )
        return await self._call(
            (*self.docker, "exec", "--user", "65532:65532", self._servers[0], *argv),
            timeout_seconds=timeout_seconds,
        )

    async def stop_servers(self):
        observations = []
        sessions = tuple(reversed(tuple(self._sessions.values())))
        failure = None
        try:
            for session in sessions:
                running = False
                try:
                    if session.result is None:
                        before = await self._inspect("inspect", session.name)
                        running = before.get("State", {}).get("Running") is True
                        if running:
                            killed = await self._call((*self.docker, "kill", session.name))
                            running = (
                                killed.status is HostProcessStatus.COMPLETED
                                and killed.exit_code == 0
                            )
                            # A natural exit can race this kill. Inspect and preserve its
                            # final streams instead of discarding them on the CLI error.
                    await asyncio.shield(session.task)
                    if session.state is None:
                        after = await self._inspect("inspect", session.name)
                        session.state = after.get("State")
                    result = session.result
                    state = session.state
                    if not isinstance(state, dict) or type(state.get("ExitCode")) is not int:
                        raise WebPhaseRuntimeError(
                            "WEB_SERVER_TERMINATION_UNCONFIRMED", command_result=result
                        )
                    observations.append(
                        {
                            "container": session.name,
                            "state": state,
                            "terminated_by_controller": running,
                            "stdout": result.stdout,
                            "stderr": result.stderr,
                            "transport_status": result.status.value,
                            "transport_exit_code": result.exit_code,
                        }
                    )
                    if result.status is not HostProcessStatus.COMPLETED:
                        raise WebPhaseRuntimeError(
                            "WEB_SERVER_TRANSPORT_FAILED", command_result=result
                        )
                    if state.get("Running") is not False:
                        raise WebPhaseRuntimeError(
                            "WEB_SERVER_TERMINATION_UNCONFIRMED", command_result=result
                        )
                    if session.error is not None:
                        raise WebPhaseRuntimeError(
                            str(session.error), result=session.error.result, command_result=result
                        )
                except WebPhaseRuntimeError as error:
                    failure = failure or error
        finally:
            try:
                await self._remove(
                    tuple(item.name for item in sessions if item.name in self._names)
                )
            except WebPhaseRuntimeError as error:
                failure = failure or error
            finally:
                await self._drain_sessions(sessions)
            self._sessions.clear()
        if failure is not None:
            failure.observations = tuple(observations)
            if failure.command_result is None or failure.command_result not in tuple(
                item.result for item in sessions
            ):
                failure.command_result = next(
                    (item.result for item in sessions if item.result is not None), None
                )
            raise failure
        return observations

    async def _remove(self, names):
        async def cleanup():
            failed = False
            last_failure = None
            for name in names:
                result = await self._call((*self.docker, "rm", "--force", name))
                absent = (
                    result.stderr.decode(errors="replace").strip()
                    == f"Error response from daemon: No such container: {name}"
                )
                if result.status is not HostProcessStatus.COMPLETED or (
                    result.exit_code != 0 and not absent
                ):
                    failed = True
                    last_failure = result
                    continue
                if name in self._names:
                    self._names.remove(name)
                if name in self._servers:
                    self._servers.remove(name)
            if failed:
                raise WebPhaseRuntimeError("WEB_CONTAINER_CLEANUP_UNCONFIRMED", result=last_failure)

        task = asyncio.create_task(cleanup())
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        if cancelled:
            raise asyncio.CancelledError

    async def close(self):
        try:
            await self._remove(tuple(reversed(self._names)))
        finally:
            try:
                await self._drain_sessions(tuple(self._sessions.values()))
            finally:
                self._sessions.clear()
                self._closed = True
        if self._browser_cleanup_failures:
            # App server removal does not prove that its browser sidecar exited.
            # Keep this sticky across close retries so finalization retains the
            # workspace and the diagnostics instead of reporting a false PASS.
            raise WebPhaseRuntimeError(
                "WEB_BROWSER_CLEANUP_UNCONFIRMED",
                browser_cleanup_failures=self.browser_cleanup_failures,
            )
