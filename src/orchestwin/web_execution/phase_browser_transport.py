"""Bounded browser sidecar on an owned Web server's isolated network namespace."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from orchestwin.sandbox.host_process import BoundedHostProcessResult, run_bounded_host_process
from orchestwin.web_execution.verified_browser_runner import read_json


@dataclass(frozen=True, slots=True)
class WebBrowserTransportResult:
    operations: tuple[tuple[str, BoundedHostProcessResult], ...]
    process_exit_code: int | None
    cleanup_confirmed: bool
    failure_code: str | None
    container_id: str | None
    network_container_id: str | None


class BrowserTransportError(RuntimeError):
    pass


def _ok(result):
    return result.status == "COMPLETED" and result.exit_code == 0


class DockerWebBrowserTransport:
    """No source mounts, published ports, pulls, socket mounts or host networking."""

    def __init__(self, *, process_runner=None):
        self.runner = process_runner or run_bounded_host_process

    async def execute(self, job, *, runtime, image_id, harness: bytes, seccomp: bytes):
        operations = []
        container_id = network_id = None
        attempted = False
        cleanup_confirmed = True
        failure_code = None
        process_exit_code = None
        operation = job["operation_id"]
        if re.fullmatch(r"[0-9a-f]{32}", operation) is None:
            raise ValueError("WEB_BROWSER_OPERATION_INVALID")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
            raise ValueError("WEB_BROWSER_IMAGE_INVALID")
        name = f"orchestwin-web-browser-{operation}"
        docker = runtime.docker

        async def command(argv, label, *, required=True, stdin=None, timeout=30):
            result = await self.runner(
                tuple(argv),
                timeout_seconds=timeout,
                maximum_output_bytes_per_stream=32 * 1024 * 1024,
                environment_overrides={},
                stdin_bytes=stdin,
            )
            operations.append((label, result))
            if required and not _ok(result):
                raise BrowserTransportError(f"WEB_BROWSER_{label}_FAILED")
            return result

        async def inspect(argv, label, *, required=True):
            observed = await command(argv, label, required=required)
            if not _ok(observed):
                return None
            data = read_json(observed.stdout)
            if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
                raise BrowserTransportError("WEB_BROWSER_INSPECTION_INVALID")
            return data[0]

        async def cleanup():
            nonlocal container_id
            target = container_id or name
            value = await inspect((*docker, "inspect", target), "CLEANUP_INSPECT", required=False)
            if value is None:
                last = operations[-1][1]
                return last.status == "COMPLETED" and last.stderr.decode(
                    errors="replace"
                ).strip() in {
                    f"Error: No such object: {target}",
                    f"Error response from daemon: No such container: {target}",
                }
            identifier = value.get("Id")
            if (
                not isinstance(identifier, str)
                or re.fullmatch(r"[0-9a-f]{64}", identifier) is None
                or value.get("Config", {}).get("Labels", {}).get("org.orchestwin.web-browser")
                != operation
            ):
                return False
            # A cancelled create may have created the sidecar without returning
            # its ID. The owned label lets cleanup recover the actual identity.
            container_id = identifier
            return _ok(
                await command((*docker, "rm", "--force", identifier), "REMOVE", required=False)
            )

        # The private seccomp copy is an input to Docker, never a container mount.
        with tempfile.TemporaryDirectory(prefix="orchestwin-browser-policy-") as temporary:
            policy_path = Path(temporary) / "seccomp.json"
            policy_path.write_bytes(seccomp)
            try:
                context = await inspect((*docker, "context", "inspect", docker[-1]), "CONTEXT")
                endpoint = context.get("Endpoints", {}).get("docker", {}).get("Host", "")
                if not isinstance(endpoint, str) or not endpoint.startswith(
                    ("unix://", "npipe://")
                ):
                    raise BrowserTransportError("WEB_BROWSER_LOCAL_DOCKER_REQUIRED")
                image = await inspect((*docker, "image", "inspect", image_id), "IMAGE")
                if (
                    image.get("Id") != image_id
                    or image.get("Os") != "linux"
                    or image.get("Architecture") != "amd64"
                ):
                    raise BrowserTransportError("WEB_BROWSER_IMAGE_MISMATCH")
                network_id = await runtime.browser_network()
                if re.fullmatch(r"[0-9a-f]{64}", network_id) is None:
                    raise BrowserTransportError("WEB_BROWSER_NETWORK_INVALID")
                r = runtime.resources
                arguments = (
                    *docker,
                    "create",
                    "--interactive",
                    "--init",
                    "--name",
                    name,
                    "--label",
                    f"org.orchestwin.web-browser={operation}",
                    "--pull=never",
                    "--network",
                    f"container:{network_id}",
                    "--user",
                    "65532:65532",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges:true",
                    "--security-opt",
                    f"seccomp={policy_path}",
                    "--pids-limit",
                    str(r.pids_limit),
                    "--memory",
                    f"{r.memory_mib}m",
                    "--memory-swap",
                    f"{r.memory_mib}m",
                    "--cpus",
                    str(r.cpu_count),
                    "--shm-size",
                    "256m",
                    "--tmpfs",
                    f"/tmp:rw,noexec,nosuid,nodev,size={r.writable_tmpfs_mib}m,mode=1777",
                    "--log-driver",
                    "none",
                    "--env",
                    "HOME=/tmp",
                    *(
                        part
                        for key in (
                            "HTTP_PROXY",
                            "HTTPS_PROXY",
                            "FTP_PROXY",
                            "ALL_PROXY",
                            "NO_PROXY",
                        )
                        for variant in (key, key.lower())
                        for part in ("--env", f"{variant}=")
                    ),
                    "--entrypoint",
                    "node",
                    image_id,
                    "-e",
                    harness.decode("utf-8"),
                )
                if len(subprocess.list2cmdline(arguments)) > 30000:
                    raise BrowserTransportError("WEB_BROWSER_PORTABLE_ARGV_LIMIT")
                wire = json.dumps(
                    job, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
                ).encode()
                if len(wire) > 65536:
                    raise BrowserTransportError("WEB_BROWSER_JOB_LIMIT")
                attempted = True
                cleanup_confirmed = False
                created = await command(arguments, "CREATE")
                identifier = created.stdout.decode().strip()
                if re.fullmatch(r"[0-9a-f]{64}", identifier) is None:
                    raise BrowserTransportError("WEB_BROWSER_CONTAINER_ID_INVALID")
                container_id = identifier
                observed = await command(
                    (*docker, "start", "--attach", "--interactive", container_id),
                    "EXECUTE",
                    required=False,
                    stdin=wire,
                    timeout=120,
                )
                if observed.status != "COMPLETED":
                    raise BrowserTransportError("WEB_BROWSER_TRANSPORT_LIMIT_OR_FAILURE")
                terminal = await inspect((*docker, "inspect", container_id), "TERMINAL")
                state = terminal.get("State", {})
                started = datetime.fromisoformat(state.get("StartedAt"))
                finished = datetime.fromisoformat(state.get("FinishedAt"))
                if (
                    terminal.get("Id") != container_id
                    or terminal.get("Image") != image_id
                    or state.get("Running") is not False
                    or state.get("Status") != "exited"
                    or type(state.get("ExitCode")) is not int
                    or state["ExitCode"] != observed.exit_code
                    or started.tzinfo is None
                    or finished.tzinfo is None
                    or started <= datetime(1970, 1, 1, tzinfo=UTC)
                    or finished < started
                ):
                    raise BrowserTransportError("WEB_BROWSER_EXIT_UNVERIFIED")
                process_exit_code = state["ExitCode"]
                if state.get("OOMKilled") is True:
                    raise BrowserTransportError("WEB_BROWSER_OOM_KILLED")
                if process_exit_code != 0:
                    raise BrowserTransportError("WEB_BROWSER_PROCESS_FAILED")
                if await runtime.browser_network() != network_id:
                    raise BrowserTransportError("WEB_BROWSER_SERVER_CHANGED")
            except asyncio.CancelledError:
                raise
            except Exception as error:
                failure_code = (
                    str(error)
                    if isinstance(error, BrowserTransportError)
                    else "WEB_BROWSER_TRANSPORT_ERROR"
                )
            finally:
                if attempted:
                    task = asyncio.create_task(cleanup())
                    cancelled = False
                    while not task.done():
                        try:
                            await asyncio.shield(task)
                        except asyncio.CancelledError:
                            cancelled = True
                        except Exception:
                            break
                    try:
                        cleanup_confirmed = task.result()
                    except Exception:
                        cleanup_confirmed = False
                    if not cleanup_confirmed:
                        failure_code = "WEB_BROWSER_CLEANUP_UNCONFIRMED"
                        runtime.record_browser_cleanup_failure(
                            operation_id=operation,
                            container_id=container_id,
                            container_name=name,
                            operations=tuple(operations),
                        )
                    if cancelled:
                        raise asyncio.CancelledError
        return WebBrowserTransportResult(
            tuple(operations),
            process_exit_code,
            cleanup_confirmed,
            failure_code,
            container_id,
            network_id,
        )
