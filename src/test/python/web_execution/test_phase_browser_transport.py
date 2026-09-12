"""Browser sidecars preserve observations and remove only their own container."""

import asyncio
import json

import pytest

from orchestwin.sandbox.host_process import BoundedHostProcessResult
from orchestwin.web_execution.phase_browser_transport import DockerWebBrowserTransport
from orchestwin.web_execution.phase_runtime import WebPhaseRuntimeError

from .test_phase_runtime import Host as RuntimeHost
from .test_phase_runtime import runtime as create_runtime

IMAGE = "sha256:" + "c" * 64
NETWORK = "d" * 64
CONTAINER = "e" * 64


class Host:
    def __init__(
        self, *, timeout=False, remote=False, cleanup_failure=False, unstarted=False, oom=False
    ):
        self.calls = []
        self.timeout, self.remote = timeout, remote
        self.cleanup_failure, self.unstarted = cleanup_failure, unstarted
        self.oom = oom

    async def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        body = b""
        if "context" in argv:
            body = json.dumps(
                [
                    {
                        "Endpoints": {
                            "docker": {
                                "Host": "tcp://remote:2375"
                                if self.remote
                                else "unix:///var/run/docker.sock"
                            }
                        }
                    }
                ]
            ).encode()
        elif "image" in argv:
            body = json.dumps([{"Id": IMAGE, "Os": "linux", "Architecture": "amd64"}]).encode()
        elif "create" in argv:
            self.operation = argv[argv.index("--label") + 1].split("=", 1)[1]
            body = CONTAINER.encode()
        elif "start" in argv:
            if self.timeout:
                return BoundedHostProcessResult("TIMED_OUT", None, b"partial", b"error", "timeout")
            body = b'{"observed":true}'
            if self.oom:
                return BoundedHostProcessResult("COMPLETED", 137, body, b"Killed", None)
        elif "inspect" in argv:
            body = json.dumps(
                [
                    {
                        "Id": CONTAINER,
                        "Image": IMAGE,
                        "Config": {"Labels": {"org.orchestwin.web-browser": self.operation}},
                        "State": {
                            "Running": False,
                            "Status": "exited",
                            "ExitCode": 137 if self.oom else 0,
                            "OOMKilled": self.oom,
                            "StartedAt": "0001-01-01T00:00:00Z"
                            if self.unstarted
                            else "2026-09-12T10:00:00Z",
                            "FinishedAt": "2026-09-12T10:00:01Z",
                        },
                    }
                ]
            ).encode()
        elif "rm" in argv and self.cleanup_failure:
            return BoundedHostProcessResult("COMPLETED", 1, b"", b"not removed", None)
        return BoundedHostProcessResult("COMPLETED", 0, body, b"", None)


def browser_runtime(tmp_path):
    async def network():
        return NETWORK

    runtime = create_runtime(tmp_path, RuntimeHost())
    runtime.browser_network = network
    return runtime


@pytest.mark.parametrize("case", ["pass", "timeout", "remote", "cleanup", "unstarted", "oom"])
def test_sidecar_transport_binds_network_and_keeps_failure_bytes(tmp_path, case):
    async def scenario():
        host = Host(
            timeout=case == "timeout",
            remote=case == "remote",
            cleanup_failure=case == "cleanup",
            unstarted=case == "unstarted",
            oom=case == "oom",
        )
        runtime = browser_runtime(tmp_path)
        transport = DockerWebBrowserTransport(process_runner=host)
        result = await transport.execute(
            {"operation_id": "f" * 32},
            runtime=runtime,
            image_id=IMAGE,
            harness=b"process.stdout.write('{}')",
            seccomp=b"{}",
        )
        assert result.cleanup_confirmed is (case != "cleanup")
        assert (result.failure_code is None) is (case == "pass")
        if case == "remote":
            assert not any("create" in argv for argv, _ in host.calls)
            return
        create = next(argv for argv, _ in host.calls if "create" in argv)
        assert create[create.index("--network") + 1] == f"container:{NETWORK}"
        assert create[create.index("--user") + 1] == "65532:65532"
        assert "--read-only" in create and "--privileged" not in create
        assert "--mount" not in create and "--publish" not in create
        assert create[create.index("--log-driver") + 1] == "none"
        assert "no-new-privileges:true" in create
        assert any(value.startswith("seccomp=") for value in create)
        assert all(argv[-1] == CONTAINER for argv, _ in host.calls if "rm" in argv)
        executed = next(item for item in result.operations if item[0] == "EXECUTE")[1]
        if case == "timeout":
            assert executed.stdout == b"partial" and executed.stderr == b"error"
        if case == "oom":
            assert result.failure_code == "WEB_BROWSER_OOM_KILLED"
            assert result.process_exit_code == 137
            assert executed.stderr == b"Killed"
            terminal = next(value for label, value in result.operations if label == "TERMINAL")
            assert json.loads(terminal.stdout)[0]["State"]["OOMKilled"] is True
        else:
            assert result.process_exit_code == (0 if case in {"pass", "cleanup"} else None)

    asyncio.run(scenario())


def assert_cleanup_failure_retained(runtime):
    assert len(runtime.browser_cleanup_failures) == 1
    failure = runtime.browser_cleanup_failures[0]
    assert failure.operation_id == "f" * 32
    assert failure.container_id == CONTAINER
    assert failure.container_name == "orchestwin-web-browser-" + "f" * 32
    assert isinstance(failure.operations, tuple)
    removal = next(value for label, value in failure.operations if label == "REMOVE")
    assert removal.exit_code == 1 and removal.stderr == b"not removed"
    return failure


def test_cleanup_failure_survives_normal_result_and_repeated_close(tmp_path):
    async def scenario():
        runtime = browser_runtime(tmp_path)
        result = await DockerWebBrowserTransport(process_runner=Host(cleanup_failure=True)).execute(
            {"operation_id": "f" * 32},
            runtime=runtime,
            image_id=IMAGE,
            harness=b"process.stdout.write('{}')",
            seccomp=b"{}",
        )
        assert result.cleanup_confirmed is False
        assert result.failure_code == "WEB_BROWSER_CLEANUP_UNCONFIRMED"
        failure = assert_cleanup_failure_retained(runtime)
        assert failure.operations == result.operations
        for _ in range(2):
            with pytest.raises(
                WebPhaseRuntimeError, match="WEB_BROWSER_CLEANUP_UNCONFIRMED"
            ) as error:
                await runtime.close()
            assert error.value.browser_cleanup_failures == (failure,)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("cancel_stage", "repeat_cancel", "cleanup_failure"),
    [
        ("create", False, True),
        ("start", False, True),
        ("start", True, True),
        ("rm", False, True),
        ("start", True, False),
    ],
)
def test_cancellation_keeps_unresolved_sidecar_and_cleanup_diagnostics(
    tmp_path, cancel_stage, repeat_cancel, cleanup_failure
):
    class CancelHost(Host):
        def __init__(self):
            super().__init__(cleanup_failure=cleanup_failure)
            self.pending = asyncio.Event()
            self.removing = asyncio.Event()
            self.release_removal = asyncio.Event()

        async def __call__(self, argv, **kwargs):
            observed = await super().__call__(argv, **kwargs)
            if "rm" in argv:
                self.removing.set()
                if cancel_stage == "rm":
                    self.pending.set()
                await self.release_removal.wait()
            elif cancel_stage in argv:
                self.pending.set()
                await asyncio.Event().wait()
            return observed

    async def scenario():
        host = CancelHost()
        runtime = browser_runtime(tmp_path)
        task = asyncio.create_task(
            DockerWebBrowserTransport(process_runner=host).execute(
                {"operation_id": "f" * 32},
                runtime=runtime,
                image_id=IMAGE,
                harness=b"process.stdout.write('{}')",
                seccomp=b"{}",
            )
        )
        await asyncio.wait_for(host.pending.wait(), timeout=1)
        task.cancel()
        await asyncio.wait_for(host.removing.wait(), timeout=1)
        if repeat_cancel:
            task.cancel()
        host.release_removal.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        if cleanup_failure:
            failure = assert_cleanup_failure_retained(runtime)
            with pytest.raises(
                WebPhaseRuntimeError, match="WEB_BROWSER_CLEANUP_UNCONFIRMED"
            ) as error:
                await runtime.close()
            assert error.value.browser_cleanup_failures == (failure,)
        else:
            assert runtime.browser_cleanup_failures == ()
            await runtime.close()

    asyncio.run(scenario())
