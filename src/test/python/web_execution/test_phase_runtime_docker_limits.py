"""Opt-in real transport checks; these never promote a profile or start a formal run."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from uuid import uuid4

import pytest

from orchestwin.sandbox.command_plans import CommandNetworkMode, CommandPlan, StructuredCommand
from orchestwin.sandbox.docker_runtime import HostProcessResult, HostProcessStatus
from orchestwin.sandbox.execution_policy import (
    DEFAULT_SANDBOX_RESOURCE_LIMITS,
    SandboxPolicyValidationStatus,
    validate_sandbox_plan,
)
from orchestwin.web_execution.detection import detect_web_project
from orchestwin.web_execution.lockfiles import validate_web_dependency_locks
from orchestwin.web_execution.phase_health import probe_web_health
from orchestwin.web_execution.phase_runner import load_phase_runner_identity
from orchestwin.web_execution.phase_runtime import LocalWebPhaseRuntime, WebPhaseRuntimeError
from orchestwin.web_execution.plans import WebExecutionPhase, create_structured_web_phase_plans
from orchestwin.web_execution.runtime_evidence import WebHealthCheckSpec, WebHealthCheckStatus

from .test_profile_fixture_matrix import detection_snapshot, fixture_files

MANIFEST = os.environ.get("ORCHESTWIN_WEB_PHASE_TEST_BOOTSTRAP_MANIFEST")
pytestmark = pytest.mark.skipif(
    not MANIFEST, reason="explicit Web runner Docker integration is disabled"
)
OUTPUT_LIMIT = 64 * 1024


def writable_workspace(tmp_path: Path, files: dict[str, str]) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o777)
    workspace.chmod(0o777)
    for relative, content in files.items():
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        for parent in target.parents:
            if parent == workspace:
                break
            parent.chmod(0o777)
        target.write_text(content, encoding="utf-8", newline="\n")
        target.chmod(0o666)
    return workspace


def runtime_and_trace(tmp_path: Path, files: dict[str, str], *, kind: str):
    manifest_path = Path(MANIFEST)
    identity = load_phase_runner_identity(
        manifest_path, repo_root=Path(__file__).parents[4], kind=kind
    )
    manifest = json.loads(manifest_path.read_bytes())
    runtime = LocalWebPhaseRuntime(
        image_id=identity.image_id,
        runner_kind=kind,
        workspace=writable_workspace(tmp_path, files),
        resources=DEFAULT_SANDBOX_RESOURCE_LIMITS,
        docker_context=manifest["environment"]["docker_context"],
        maximum_output_bytes=OUTPUT_LIMIT,
    )
    trace = {
        "purpose": "UNIT5_DEVELOPMENT_RUNTIME_INTEGRATION",
        "formal_run_started": False,
        "level_d_validated": False,
        "runner_kind": kind,
        "local_image_id": identity.image_id,
        "bootstrap_manifest_hash": identity.bootstrap_manifest_hash,
        "recipe_content_hash": identity.recipe_content_hash,
        "operations": [],
        "cleanup_confirmed": False,
    }
    return runtime, trace


def preserve_stream(tmp_path: Path, label: str, stream: str, body: bytes):
    name = f"{label}.{stream}.log"
    (tmp_path / name).write_bytes(body)
    return {"path": name, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}


def preserve_process(tmp_path: Path, trace: dict, label: str, result: HostProcessResult):
    trace["operations"].append(
        {
            "operation": label,
            "status": result.status.value,
            "exit_code": result.exit_code,
            "failure_message": result.failure_message,
            "stdout": preserve_stream(tmp_path, label, "stdout", result.stdout),
            "stderr": preserve_stream(tmp_path, label, "stderr", result.stderr),
        }
    )


def preserve_error(tmp_path: Path, trace: dict, error: BaseException):
    trace["exception"] = {"type": type(error).__name__, "message": str(error)}
    result = getattr(error, "result", None)
    if isinstance(result, HostProcessResult):
        preserve_process(tmp_path, trace, "failed-operation", result)
    for number, row in enumerate(getattr(error, "observations", ())):
        preserve_server(tmp_path, trace, row, label=f"failed-server-{number}")


def preserve_server(tmp_path: Path, trace: dict, row: dict, *, label: str):
    trace["operations"].append(
        {
            "operation": label,
            **{key: value for key, value in row.items() if key not in {"stdout", "stderr"}},
            "stdout": preserve_stream(tmp_path, label, "stdout", row["stdout"]),
            "stderr": preserve_stream(tmp_path, label, "stderr", row["stderr"]),
        }
    )


async def close_and_preserve(tmp_path: Path, runtime: LocalWebPhaseRuntime, trace: dict):
    try:
        await runtime.close()
        trace["cleanup_confirmed"] = True
    except BaseException as error:
        trace["cleanup_exception"] = {"type": type(error).__name__, "message": str(error)}
        raise
    finally:
        (tmp_path / "development-runtime-results.json").write_text(
            json.dumps(trace, indent=2), encoding="utf-8"
        )


def validated_node_command(*, timeout_seconds: int) -> StructuredCommand:
    command = StructuredCommand(
        command_id="development.node-probe",
        executable="node",
        arguments=("probe.js",),
        working_directory=".",
        allowed_environment_keys=frozenset(),
        secret_references=frozenset(),
        timeout_seconds=timeout_seconds,
        network_mode=CommandNetworkMode.DISABLED,
        expected_exit_codes=frozenset({0}),
        output_parser_id=None,
        artifact_patterns=frozenset(),
    )
    plan = CommandPlan("development.node-probe-plan", "web.static", "1.0.0", (command,))
    policy = validate_sandbox_plan(plan)
    assert policy.status is SandboxPolicyValidationStatus.ACCEPTED, policy.to_snapshot()
    return command


def test_real_php_lint_loopback_health_and_controller_termination(tmp_path: Path):
    async def scenario():
        files = fixture_files("web-php-valid")
        snapshot = detection_snapshot(files)
        detected = detect_web_project(snapshot).selected
        assert detected is not None
        selection = detected.selection
        locks = validate_web_dependency_locks(snapshot, selection=selection)
        plan = create_structured_web_phase_plans(snapshot, selection=selection, lock_report=locks)
        lint = plan.phase(WebExecutionPhase.STATIC_CHECK).command_plans[0]
        serve = plan.phase(WebExecutionPhase.RUN).command_plans[0]
        for command_plan in (lint, serve):
            policy = validate_sandbox_plan(command_plan)
            assert policy.status is SandboxPolicyValidationStatus.ACCEPTED, policy.to_snapshot()
        runtime, trace = runtime_and_trace(tmp_path, files, kind="PHP")
        try:
            result = await runtime.run_command(lint.commands[0])
            preserve_process(tmp_path, trace, "php-lint", result)
            assert result.status is HostProcessStatus.COMPLETED, result
            assert result.exit_code == 0, result
            server = await runtime.start_command(serve.commands[0])
            trace["server"] = server
            health = await probe_web_health(
                WebHealthCheckSpec("php.root", "127.0.0.1", 8080, "/", (200,), 2, 10, 250),
                invoke=runtime.invoke,
                runner_kind="PHP",
            )
            trace["health"] = health.to_snapshot()
            assert health.status is WebHealthCheckStatus.HEALTHY, health.to_snapshot()
            assert health.attempts[-1].status_code == 200
            stopped = await runtime.stop_servers()
            for number, row in enumerate(stopped):
                preserve_server(tmp_path, trace, row, label=f"php-server-{number}")
            assert len(stopped) == 1, stopped
            assert stopped[0]["container"] == server
            assert stopped[0]["terminated_by_controller"] is True, stopped
            assert stopped[0]["state"]["Running"] is False, stopped
            assert stopped[0]["state"]["ExitCode"] == 137, stopped
            assert stopped[0]["state"]["OOMKilled"] is False, stopped
            assert b"PHP" in stopped[0]["stderr"], stopped
        except BaseException as error:
            preserve_error(tmp_path, trace, error)
            raise
        finally:
            await close_and_preserve(tmp_path, runtime, trace)

    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["output-limit", "nonzero-exit", "reserved-exit", "timeout"])
def test_real_node_finite_process_preserves_failure_and_bounded_output(tmp_path: Path, case: str):
    async def scenario():
        scripts = {
            "output-limit": "const fs = require('node:fs'); fs.writeSync(1, Buffer.alloc(1048576, 'x'));",
            "nonzero-exit": "const fs = require('node:fs'); fs.writeSync(1, 'executed\\n'); fs.writeSync(2, 'expected exit 7\\n'); process.exit(7);",
            "reserved-exit": "const fs = require('node:fs'); fs.writeSync(1, 'executed\\n'); fs.writeSync(2, 'expected exit 125\\n'); process.exit(125);",
            "timeout": "const fs = require('node:fs'); fs.writeSync(1, 'waiting\\n'); fs.writeSync(2, 'timer active\\n'); setInterval(() => {}, 1000);",
        }
        runtime, trace = runtime_and_trace(tmp_path, {"probe.js": scripts[case]}, kind="NODE")
        command = validated_node_command(timeout_seconds=5 if case == "timeout" else 15)
        trace["command"] = command.to_snapshot()
        trace["case"] = case
        try:
            result = await runtime.run_command(command)
            preserve_process(tmp_path, trace, "node-probe", result)
            assert len(result.stdout) <= OUTPUT_LIMIT, result
            assert len(result.stderr) <= OUTPUT_LIMIT, result
            if case == "output-limit":
                assert result.status is HostProcessStatus.OUTPUT_LIMIT_EXCEEDED, result
                assert result.exit_code is None
                assert result.stdout == b"x" * OUTPUT_LIMIT
            elif case in {"nonzero-exit", "reserved-exit"}:
                expected_exit = 125 if case == "reserved-exit" else 7
                assert result.status is HostProcessStatus.COMPLETED, result
                assert result.exit_code == expected_exit, result
                assert result.stdout == b"executed\n"
                assert result.stderr == f"expected exit {expected_exit}\n".encode()
            else:
                assert result.status is HostProcessStatus.TIMED_OUT, result
                assert result.exit_code is None
                assert result.stdout == b"waiting\n"
                assert result.stderr == b"timer active\n"
        except BaseException as error:
            preserve_error(tmp_path, trace, error)
            raise
        finally:
            await close_and_preserve(tmp_path, runtime, trace)

    asyncio.run(scenario())


_PHP_HEADER_SERVER = r"""<?php
declare(strict_types=1);
$server = stream_socket_server('tcp://127.0.0.1:8080', $errno, $message);
if ($server === false) throw new RuntimeException('TCP fixture failed to listen');
file_put_contents('/workspace/tcp-server.ready', 'ready');
while (true) {
    $client = @stream_socket_accept($server, 1);
    if ($client === false) continue;
    stream_set_timeout($client, 1);
    $request = '';
    while (!str_contains($request, "\r\n\r\n") && strlen($request) <= 16384) {
        $part = fread($client, 1024);
        if ($part === false || $part === '') break;
        $request .= $part;
    }
    if (str_starts_with($argv[1], 'chunked-')) {
        fwrite($client, "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n");
        fwrite($client, $argv[1] === 'chunked-valid' ? "5\r\nhello\r\n6\r\n world\r\n0\r\n\r\n" : "5\r\nhi");
        fclose($client);
        continue;
    }
    fwrite($client, "HTTP/1.1 200 OK\r\nX-Probe: ");
    if ($argv[1] === 'oversized') @fwrite($client, str_repeat('a', 17000));
    for ($number = 0; $number < 200; $number++) {
        if (@fwrite($client, 'abcde') === false) break;
        fflush($client);
        usleep(50000);
    }
    fclose($client);
}
"""

_PHP_PROBE_PROCESS_CHECK = r"""<?php
declare(strict_types=1);
$remaining = [];
foreach (glob('/proc/[0-9]*/cmdline') as $path) {
    $body = @file_get_contents($path);
    if ($body === false || $body === '') continue;
    $args = explode("\0", $body);
    if (count($args) < 3 || $args[1] !== '-r') continue;
    $hash = hash('sha256', $args[2]);
    if ($hash === $argv[1]) $remaining[] = [
        'pid' => (int)basename(dirname($path)), 'code_sha256' => $hash,
    ];
}
echo json_encode($remaining, JSON_THROW_ON_ERROR);
"""


def validated_php_header_server(case: str) -> StructuredCommand:
    command = StructuredCommand(
        command_id="development.php-header-server",
        executable="php",
        arguments=("controlled-server.php", case),
        working_directory=".",
        allowed_environment_keys=frozenset(),
        secret_references=frozenset(),
        timeout_seconds=25,
        network_mode=CommandNetworkMode.DISABLED,
        expected_exit_codes=frozenset({0}),
        output_parser_id=None,
        artifact_patterns=frozenset(),
    )
    plan = CommandPlan("development.php-header-plan", "web.php", "1.0.0", (command,))
    policy = validate_sandbox_plan(plan)
    assert policy.status is SandboxPolicyValidationStatus.ACCEPTED, policy.to_snapshot()
    return command


@pytest.mark.parametrize(
    "case,error_code", [("oversized", "RESPONSE_LIMIT_EXCEEDED"), ("slow", "TIMEOUT")]
)
def test_real_php_header_acquisition_is_bounded_and_reaps_probe(
    tmp_path: Path, case: str, error_code: str
):
    async def scenario():
        files = {
            "controlled-server.php": _PHP_HEADER_SERVER,
            "remaining-probes.php": _PHP_PROBE_PROCESS_CHECK,
        }
        runtime, trace = runtime_and_trace(tmp_path, files, kind="PHP")
        trace["case"] = case
        probe_results = []
        probe_hashes = []

        async def invoke(argv, *, timeout_seconds):
            assert argv[:2] == ("php", "-r")
            probe_hashes.append(hashlib.sha256(argv[2].encode()).hexdigest())
            result = await runtime.invoke(argv, timeout_seconds=timeout_seconds)
            probe_results.append(result)
            preserve_process(tmp_path, trace, f"header-probe-{len(probe_results)}", result)
            return result

        try:
            trace["server"] = await runtime.start_command(validated_php_header_server(case))
            ready = runtime.workspace / "tcp-server.ready"
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            assert ready.is_file(), "Controlled TCP fixture did not report readiness"
            spec = WebHealthCheckSpec("php.headers", "127.0.0.1", 8080, "/", (200,), 1, 1, 1)
            started = time.monotonic()
            health = await probe_web_health(spec, invoke=invoke, runner_kind="PHP")
            elapsed = time.monotonic() - started
            trace["health"] = health.to_snapshot()
            trace["probe_elapsed_seconds"] = elapsed
            assert len(probe_hashes) == 1
            remaining = await runtime.invoke(
                ("php", "remaining-probes.php", probe_hashes[0]), timeout_seconds=3
            )
            preserve_process(tmp_path, trace, "remaining-probes", remaining)
            # Observe the container before removal, so cleanup cannot hide a timed-out PHP exec.
            assert remaining.status is HostProcessStatus.COMPLETED, remaining
            assert remaining.exit_code == 0, remaining
            assert json.loads(remaining.stdout) == [], remaining
            assert len(probe_results) == 1
            raw = probe_results[0]
            assert raw.status is HostProcessStatus.COMPLETED, raw
            assert raw.exit_code == 0, raw
            payload = json.loads(raw.stdout)
            assert payload["status_code"] is None, payload
            assert payload["error_code"] == error_code, payload
            assert 0 <= payload["latency_milliseconds"] <= 1250, payload
            assert elapsed < spec.request_timeout_seconds + 2, elapsed
            assert health.status is (
                WebHealthCheckStatus.TIMED_OUT if case == "slow" else WebHealthCheckStatus.UNHEALTHY
            ), health.to_snapshot()
            assert health.attempts[-1].error_code == error_code, health.to_snapshot()
        except BaseException as error:
            preserve_error(tmp_path, trace, error)
            raise
        finally:
            try:
                for number, row in enumerate(await runtime.stop_servers()):
                    preserve_server(tmp_path, trace, row, label=f"header-server-{number}")
            finally:
                await close_and_preserve(tmp_path, runtime, trace)

    asyncio.run(scenario())


@pytest.mark.parametrize("case", ["chunked-valid", "chunked-truncated"])
def test_real_php_health_validates_chunked_body_completion(tmp_path: Path, case: str):
    async def scenario():
        runtime, trace = runtime_and_trace(
            tmp_path, {"controlled-server.php": _PHP_HEADER_SERVER}, kind="PHP"
        )
        trace["case"] = case
        probe_results = []

        async def invoke(argv, *, timeout_seconds):
            result = await runtime.invoke(argv, timeout_seconds=timeout_seconds)
            probe_results.append(result)
            preserve_process(tmp_path, trace, "chunked-probe", result)
            return result

        try:
            trace["server"] = await runtime.start_command(validated_php_header_server(case))
            ready = runtime.workspace / "tcp-server.ready"
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            assert ready.is_file(), "Controlled TCP fixture did not report readiness"
            health = await probe_web_health(
                WebHealthCheckSpec("php.chunked", "127.0.0.1", 8080, "/", (200,), 1, 1, 1),
                invoke=invoke,
                runner_kind="PHP",
            )
            trace["health"] = health.to_snapshot()
            assert len(probe_results) == 1
            raw = probe_results[0]
            assert raw.status is HostProcessStatus.COMPLETED, raw
            assert raw.exit_code == 0, raw
            payload = json.loads(raw.stdout)
            if case == "chunked-valid":
                assert health.status is WebHealthCheckStatus.HEALTHY, health.to_snapshot()
                assert payload["status_code"] == 200, payload
                assert payload["error_code"] is None, payload
            else:
                assert health.status is WebHealthCheckStatus.UNHEALTHY, health.to_snapshot()
                assert payload["status_code"] is None, payload
                assert payload["error_code"] == "RESPONSE_INCOMPLETE", payload
        except BaseException as error:
            preserve_error(tmp_path, trace, error)
            raise
        finally:
            try:
                for number, row in enumerate(await runtime.stop_servers()):
                    preserve_server(tmp_path, trace, row, label=f"chunked-server-{number}")
            finally:
                await close_and_preserve(tmp_path, runtime, trace)

    asyncio.run(scenario())


def test_real_docker_launch_failure_is_not_an_application_exit(tmp_path: Path, monkeypatch):
    async def scenario():
        runtime, trace = runtime_and_trace(
            tmp_path, {"probe.js": "process.stdout.write('application executed');"}, kind="NODE"
        )
        trace["case"] = "docker-daemon-before-launch"
        original = runtime._arguments
        missing = f"/orchestwin-intentionally-absent-{uuid4().hex}"

        def inject_daemon_failure(*args):
            argv = original(*args)
            # A nonexistent bind source is rejected by Docker before the app starts.
            return (*argv[:4], "--mount", f"type=bind,source={missing},target=/missing", *argv[4:])

        monkeypatch.setattr(runtime, "_arguments", inject_daemon_failure)
        try:
            with pytest.raises(WebPhaseRuntimeError) as failure:
                returned = await runtime.run_command(validated_node_command(timeout_seconds=15))
                preserve_process(tmp_path, trace, "unexpected-application-result", returned)
            preserve_error(tmp_path, trace, failure.value)
            assert failure.value.command_result is None
            diagnostic = failure.value.result
            assert diagnostic is not None
            assert diagnostic.status is HostProcessStatus.COMPLETED, diagnostic
            assert diagnostic.exit_code == 125, diagnostic
            assert b"application executed" not in diagnostic.stdout
            assert b"bind source path does not exist" in diagnostic.stderr
        finally:
            await close_and_preserve(tmp_path, runtime, trace)

    asyncio.run(scenario())
