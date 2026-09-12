"""Regressions for complete bounded server streams and reliable cleanup."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from dataclasses import replace

import pytest

from orchestwin.sandbox.docker_runtime import HostProcessResult, HostProcessStatus
from orchestwin.sandbox.host_process import BoundedHostProcessResult
from orchestwin.web_execution.phase_runtime import WebPhaseRuntimeError

from .test_phase_runtime import IMAGE, Host, runtime, static_command, terminal_state


def completed(code=0, stdout=b"", stderr=b""):
    return HostProcessResult(HostProcessStatus.COMPLETED, code, stdout, stderr, None)


class LifecycleHost(Host):
    """An attached process stays pending until its real container exits."""

    def __init__(self, *, startup_exit=None, cleanup_fails=False):
        super().__init__()
        self.startup_exit = startup_exit
        self.cleanup_fails = cleanup_fails
        self.states = {}
        self.streams = {}
        self.stream_started = asyncio.Event()
        self.removed = asyncio.Event()
        self.finished_streams = set()
        self.finite = completed(23, b"build output", b"build failure")

    async def run(self, argv, **kwargs):
        operation = argv[3]
        if operation in {"context", "image"}:
            return await super().run(argv, **kwargs)
        self.calls.append((argv, kwargs))
        if operation == "create":
            name = argv[argv.index("--name") + 1]
            self.states[name] = {"Status": "created", "Running": False, "ExitCode": 0}
            self.streams[name] = asyncio.get_running_loop().create_future()
        elif operation == "start":
            name = argv[-1]
            self.states[name] = {"Status": "running", "Running": True, "ExitCode": 0}
            if "--attach" not in argv:
                return completed()
            self.stream_started.set()
            if self.startup_exit is not None:
                self.finish(name, completed(self.startup_exit, b"boot output", b"startup error"))
            try:
                return await self.streams[name]
            finally:
                self.finished_streams.add(name)
        elif operation == "inspect":
            return completed(
                stdout=json.dumps([{"Image": IMAGE, "State": self.states[argv[-1]]}]).encode()
            )
        elif operation == "kill":
            self.finish(argv[-1], completed(137, b"server output", b"server error"))
        elif operation == "rm":
            if self.cleanup_fails:
                return completed(1, stderr=b"cleanup failed")
            name = argv[-1]
            if name in self.streams:
                self.finish(name, completed(137, b"server output", b"server error"))
            self.removed.set()
        elif operation == "run":
            self.states[argv[argv.index("--name") + 1]] = terminal_state(self.finite.exit_code)
            return self.finite
        return completed()

    def finish(self, name, result, *, keep_running=False):
        if not keep_running:
            self.states[name] = {
                **terminal_state(result.exit_code if result.exit_code is not None else 137),
            }
        if not self.streams[name].done():
            self.streams[name].set_result(result)


def test_command_cleanup_failure_keeps_actual_command_result(tmp_path):
    async def scenario():
        host = LifecycleHost(cleanup_fails=True)
        adapter = runtime(tmp_path, host)
        with pytest.raises(WebPhaseRuntimeError) as failure:
            await adapter.run_command(static_command())
        assert failure.value.command_result == host.finite
        assert failure.value.result.stderr == b"cleanup failed"
        assert "CLEANUP" in str(failure.value)
        host.cleanup_fails = False
        await adapter.close()

    asyncio.run(scenario())


def test_server_uses_attached_complete_stream_without_rotating_logs(tmp_path):
    async def scenario():
        host = LifecycleHost()
        adapter = runtime(tmp_path, host)
        command = static_command()
        name = await adapter.start_command(command)
        create = next(argv for argv, _ in host.calls if argv[3] == "create")
        assert create[create.index("--log-driver") + 1] == "none"
        assert "--log-opt" not in create
        environment = {
            create[index + 1].split("=", 1)[0]: create[index + 1].split("=", 1)[1]
            for index, token in enumerate(create)
            if token == "--env"
        }
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "FTP_PROXY", "ALL_PROXY", "NO_PROXY"):
            assert environment[key] == environment[key.lower()] == ""
        attach, limits = next((argv, limits) for argv, limits in host.calls if argv[3] == "start")
        assert "--attach" in attach
        assert limits["timeout_seconds"] == command.timeout_seconds
        assert limits["maximum_output_bytes_per_stream"] == adapter.maximum_output_bytes
        observations = await adapter.stop_servers()
        assert len(observations) == 1
        assert observations[0]["container"] == name
        assert observations[0]["state"]["ExitCode"] == 137
        assert observations[0]["terminated_by_controller"] is True
        assert observations[0]["stdout"] == b"server output"
        assert observations[0]["stderr"] == b"server error"
        assert observations[0]["transport_status"] == "COMPLETED"
        assert name in host.finished_streams
        assert not any(argv[3] == "logs" for argv, _ in host.calls)
        await adapter.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_immediate_startup_exit_preserves_actual_output_and_exit(tmp_path, cleanup_fails):
    async def scenario():
        host = LifecycleHost(startup_exit=19, cleanup_fails=cleanup_fails)
        adapter = runtime(tmp_path, host)
        with pytest.raises(WebPhaseRuntimeError) as failure:
            await adapter.start_command(static_command())
        observed = failure.value.command_result
        assert observed is not None
        assert observed.exit_code == 19
        assert observed.stdout == b"boot output" and observed.stderr == b"startup error"
        assert any(argv[3] == "rm" for argv, _ in host.calls)
        host.cleanup_fails = False
        await adapter.close()

    asyncio.run(scenario())


def test_attach_daemon_exit_before_launch_is_only_a_transport_diagnostic(tmp_path):
    diagnostic = completed(125, b"docker startup", b"daemon refused start")

    class BeforeLaunchHost(LifecycleHost):
        async def run(self, argv, **kwargs):
            if argv[3] == "start":
                self.calls.append((argv, kwargs))
                self.streams[argv[-1]].set_result(diagnostic)
                return diagnostic
            return await super().run(argv, **kwargs)

    async def scenario():
        host = BeforeLaunchHost()
        adapter = runtime(tmp_path, host)
        with pytest.raises(WebPhaseRuntimeError) as error:
            await adapter.start_command(static_command())
        assert error.value.command_result is None
        assert error.value.result is diagnostic
        assert host.removed.is_set()
        await adapter.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "status", [HostProcessStatus.TIMED_OUT, HostProcessStatus.OUTPUT_LIMIT_EXCEEDED]
)
def test_background_limit_removes_server_without_waiting_for_finalize(tmp_path, status):
    async def scenario():
        host = LifecycleHost()
        adapter = runtime(tmp_path, host)
        name = await adapter.start_command(static_command())
        assert any(argv[3] == "start" and "--attach" in argv for argv, _ in host.calls)
        observed = HostProcessResult(
            status, None, b"bounded output", b"bounded error", "limit reached"
        )
        host.finish(name, observed, keep_running=True)
        await asyncio.wait_for(host.removed.wait(), timeout=1)
        with pytest.raises(WebPhaseRuntimeError) as failure:
            await adapter.stop_servers()
        assert failure.value.command_result == observed
        assert failure.value.observations[0]["transport_status"] == status.value
        assert failure.value.observations[0]["stdout"] == b"bounded output"
        assert failure.value.observations[0]["state"]["Running"] is False
        assert failure.value.observations[0]["state"]["ExitCode"] == 137
        assert failure.value.observations[0]["terminated_by_controller"] is False
        await adapter.close()

    asyncio.run(scenario())


def test_stop_cleanup_failure_keeps_observations_for_every_server(tmp_path):
    async def scenario():
        host = LifecycleHost()
        adapter = runtime(tmp_path, host)
        names = {
            await adapter.start_command(static_command()),
            await adapter.start_command(static_command()),
        }
        host.cleanup_fails = True
        with pytest.raises(WebPhaseRuntimeError) as failure:
            await adapter.stop_servers()
        assert {item["container"] for item in failure.value.observations} == names
        assert all(item["stdout"] == b"server output" for item in failure.value.observations)
        assert failure.value.command_result.stdout == b"server output"
        host.cleanup_fails = False
        await adapter.close()

    asyncio.run(scenario())


def test_close_reaps_servers_but_keeps_unconfirmed_browser_cleanup_sticky(tmp_path):
    async def scenario():
        host = LifecycleHost()
        adapter = runtime(tmp_path, host)
        name = await adapter.start_command(static_command())
        diagnostic = BoundedHostProcessResult("COMPLETED", 1, b"", b"not removed", None)
        adapter.record_browser_cleanup_failure(
            operation_id="f" * 32,
            container_id="e" * 64,
            container_name="orchestwin-web-browser-" + "f" * 32,
            operations=(("REMOVE", diagnostic),),
        )
        for _ in range(2):
            with pytest.raises(
                WebPhaseRuntimeError, match="WEB_BROWSER_CLEANUP_UNCONFIRMED"
            ) as error:
                await adapter.close()
            assert error.value.browser_cleanup_failures == adapter.browser_cleanup_failures
            assert error.value.browser_cleanup_failures[0].operations == (("REMOVE", diagnostic),)
        assert host.removed.is_set()
        assert name in host.finished_streams
        assert not adapter._names and not adapter._sessions

    asyncio.run(scenario())


def test_cancellation_during_start_removes_owned_container_and_reaps_attach(tmp_path):
    async def scenario():
        host = LifecycleHost()
        original = host.run
        pending_inspect = asyncio.Event()

        async def run(argv, **kwargs):
            if argv[3] == "inspect" and host.stream_started.is_set():
                pending_inspect.set()
                await asyncio.Event().wait()
            return await original(argv, **kwargs)

        host.run = run
        adapter = runtime(tmp_path, host)
        task = asyncio.create_task(adapter.start_command(static_command()))
        await asyncio.wait_for(pending_inspect.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        assert host.removed.is_set()
        assert host.finished_streams == set(host.streams)
        await adapter.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["NODE", "PHP"])
def test_trusted_wrapper_transports_exact_argv_as_json_without_shell(tmp_path, kind):
    async def scenario():
        host = LifecycleHost()
        adapter = runtime(tmp_path, host)
        adapter.runner_kind = kind
        command = replace(
            static_command(),
            executable="php" if kind == "PHP" else "node",
            arguments=("literal ; $(unsafe) `value`",),
        )
        await adapter.run_command(command)
        argv = next(argv for argv, _ in host.calls if argv[3] == "run")
        assert argv[argv.index("--entrypoint") + 1] == ("php" if kind == "PHP" else "node")
        assert json.loads(argv[-1]) == [command.executable, *command.arguments]
        assert argv[-2] == "--"
        assert "umask(0)" in argv[-3]
        assert "/bin/sh" not in argv and "sh" not in argv
        await adapter.close()

    asyncio.run(scenario())


def test_node_wrapper_forwards_actual_exit_streams_and_literal_arguments(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node syntax/runtime check requires a local Node binary")

    async def wrapper_argv():
        host = LifecycleHost()
        adapter = runtime(tmp_path, host)
        await adapter.run_command(static_command())
        argv = next(argv for argv, _ in host.calls if argv[3] == "run")
        return list(argv[argv.index(IMAGE) + 1 :])

    arguments = asyncio.run(wrapper_argv())
    arguments[-1] = json.dumps(
        [
            node,
            "-e",
            "process.stdout.write(process.argv[1]);process.stderr.write('stderr');process.exit(29)",
            "--",
            "literal ; $(unsafe) `value`",
        ]
    )
    result = subprocess.run([node, *arguments], capture_output=True, timeout=5, check=False)
    assert result.returncode == 29
    assert result.stdout == b"literal ; $(unsafe) `value`"
    assert result.stderr == b"stderr"
