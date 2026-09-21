"""Docker session contracts without starting Docker or project commands."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from orchestwin.sandbox.docker_runtime import HostProcessResult, HostProcessStatus
from orchestwin.sandbox.execution_policy import DEFAULT_SANDBOX_RESOURCE_LIMITS
from orchestwin.web_execution.detection import detect_web_project
from orchestwin.web_execution.lockfiles import validate_web_dependency_locks
from orchestwin.web_execution.phase_runtime import LocalWebPhaseRuntime, WebPhaseRuntimeError
from orchestwin.web_execution.plans import WebExecutionPhase, create_structured_web_phase_plans

from .test_profile_fixture_matrix import detection_snapshot

IMAGE = "sha256:" + "a" * 64


def terminal_state(exit_code=0):
    return {
        "Status": "exited",
        "Running": False,
        "ExitCode": exit_code,
        "OOMKilled": False,
        "StartedAt": "2026-09-12T12:00:00.123456789Z",
        "FinishedAt": "2026-09-12T12:00:01.987654321Z",
    }


def static_command():
    snapshot = detection_snapshot({"index.html": "<!doctype html><html><body>ok</body></html>"})
    selection = detect_web_project(snapshot).selected.selection
    lock = validate_web_dependency_locks(snapshot, selection=selection)
    return (
        create_structured_web_phase_plans(snapshot, selection=selection, lock_report=lock)
        .phase(WebExecutionPhase.RUN)
        .command_plans[0]
        .commands[0]
    )


class Host:
    def __init__(self, *, remote=False, wrong_image=False, timeout=False):
        self.calls = []
        self.remote = remote
        self.wrong_image = wrong_image
        self.timeout = timeout
        self.streams = {}
        self.finished_commands = {}

    async def run(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        payload = b""
        if "context" in argv:
            payload = json.dumps(
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
            payload = json.dumps(
                [
                    {
                        "Id": "sha256:" + "b" * 64 if self.wrong_image else IMAGE,
                        "Os": "linux",
                        "Architecture": "amd64",
                    }
                ]
            ).encode()
        elif "inspect" in argv:
            payload = json.dumps(
                [
                    self.finished_commands.get(
                        argv[-1],
                        {
                            "Image": IMAGE,
                            "State": {"Running": True, "ExitCode": 0, "OOMKilled": False},
                        },
                    )
                ]
            ).encode()
        elif "run" in argv:
            if self.timeout:
                return HostProcessResult(
                    HostProcessStatus.TIMED_OUT, None, b"partial", b"", "timeout"
                )
            name = argv[argv.index("--name") + 1]
            self.finished_commands[name] = {"Image": IMAGE, "State": terminal_state()}
        elif "start" in argv and "--attach" in argv:
            event = self.streams.setdefault(argv[-1], asyncio.Event())
            await event.wait()
        elif "rm" in argv or "kill" in argv:
            event = self.streams.get(argv[-1])
            if event is not None:
                event.set()
        return HostProcessResult(HostProcessStatus.COMPLETED, 0, payload, b"", None)


def runtime(tmp_path, host):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return LocalWebPhaseRuntime(
        image_id=IMAGE,
        runner_kind="NODE",
        workspace=workspace,
        resources=DEFAULT_SANDBOX_RESOURCE_LIMITS,
        docker_context="local-test",
        process_runner=host,
    )


def test_background_server_shares_only_its_isolated_network_and_cleanup(tmp_path: Path):
    async def scenario():
        host = Host()
        adapter = runtime(tmp_path, host)
        await adapter.open()
        first = await adapter.start_command(static_command())
        second = await adapter.start_command(static_command())
        assert first != second
        await adapter.invoke(("node", "--version"), timeout_seconds=3)
        await adapter.close()
        creates = [argv for argv, _ in host.calls if "create" in argv]
        assert creates[0][creates[0].index("--network") + 1] == "none"
        assert creates[1][creates[1].index("--network") + 1] == f"container:{first}"
        for argv in creates:
            assert IMAGE in argv
            assert argv[argv.index("--user") + 1] == "65532:65532"
            assert "--read-only" in argv and "--cap-drop" in argv
            assert "--privileged" not in argv and "--publish" not in argv
            assert "docker.sock" not in " ".join(argv)
        removed = [argv[-1] for argv, _ in host.calls if "rm" in argv]
        assert set(removed) == {first, second}

    asyncio.run(scenario())


@pytest.mark.parametrize("condition", ["remote", "wrong_image"])
def test_preflight_identity_failure_starts_no_container(tmp_path: Path, condition):
    async def scenario():
        host = Host(**{condition: True})
        with pytest.raises(WebPhaseRuntimeError):
            await runtime(tmp_path, host).open()
        assert not any("run" in argv or "create" in argv for argv, _ in host.calls)

    asyncio.run(scenario())


def test_terminal_timeout_retains_transport_failure_and_removes_only_own_container(tmp_path):
    async def scenario():
        host = Host(timeout=True)
        adapter = runtime(tmp_path, host)
        await adapter.open()
        result = await adapter.run_command(static_command())
        assert result.status is HostProcessStatus.TIMED_OUT and result.stdout == b"partial"
        run = next(argv for argv, _ in host.calls if "run" in argv)
        assert any(
            "rm" in argv and argv[-1] == run[run.index("--name") + 1] for argv, _ in host.calls
        )

    asyncio.run(scenario())


class FiniteObservationHost(Host):
    def __init__(self, *, exit_code=125, state=None, image=IMAGE, missing=False):
        super().__init__()
        self.observation = HostProcessResult(
            HostProcessStatus.COMPLETED, exit_code, b"observed stdout", b"observed stderr", None
        )
        self.metadata = {
            "Image": image,
            "State": terminal_state(exit_code) if state is None else state,
        }
        self.missing = missing

    async def run(self, argv, **kwargs):
        operation = argv[3]
        if operation in {"run", "inspect"}:
            self.calls.append((argv, kwargs))
            if operation == "run":
                return self.observation
            if self.missing:
                return HostProcessResult(
                    HostProcessStatus.COMPLETED, 1, b"", b"No such container", None
                )
            return HostProcessResult(
                HostProcessStatus.COMPLETED, 0, json.dumps([self.metadata]).encode(), b"", None
            )
        return await super().run(argv, **kwargs)


@pytest.mark.parametrize("exit_code", [0, 23, 125, 126, 127])
def test_terminal_application_exit_requires_matching_container_state_before_removal(
    tmp_path, exit_code
):
    async def scenario():
        host = FiniteObservationHost(exit_code=exit_code)
        adapter = runtime(tmp_path, host)
        result = await adapter.run_command(static_command())
        assert result is host.observation
        operations = [argv[3] for argv, _ in host.calls]
        assert operations.index("run") < operations.index("inspect") < operations.index("rm")
        await adapter.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "invalid",
    [
        "missing",
        "wrong_image",
        "created",
        "exit_mismatch",
        "unstarted",
        "unfinished",
        "reversed",
        "naive_time",
    ],
)
def test_docker_completion_without_terminal_launch_proof_has_no_application_exit(tmp_path, invalid):
    async def scenario():
        state = terminal_state(125)
        if invalid == "created":
            state["Status"] = "created"
        elif invalid == "exit_mismatch":
            state["ExitCode"] = 0
        elif invalid == "unstarted":
            state["StartedAt"] = "0001-01-01T00:00:00Z"
        elif invalid == "unfinished":
            state["FinishedAt"] = "0001-01-01T00:00:00Z"
        elif invalid == "reversed":
            state["FinishedAt"] = "2026-09-12T11:00:00Z"
        elif invalid == "naive_time":
            state["StartedAt"] = "2026-09-12T12:00:00"
        host = FiniteObservationHost(
            state=state,
            image="sha256:" + "f" * 64 if invalid == "wrong_image" else IMAGE,
            missing=invalid == "missing",
        )
        adapter = runtime(tmp_path, host)
        with pytest.raises(WebPhaseRuntimeError) as error:
            await adapter.run_command(static_command())
        assert error.value.result is host.observation
        assert error.value.result.exit_code == 125
        assert error.value.command_result is None
        assert any(argv[3] == "rm" for argv, _ in host.calls)
        await adapter.close()

    asyncio.run(scenario())
