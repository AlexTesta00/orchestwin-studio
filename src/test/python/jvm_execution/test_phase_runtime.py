"""Confinement, lifecycle and truthful observations for finite JVM containers."""

from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import replace
from uuid import UUID

import pytest

from orchestwin.jvm_execution import phase_runtime as runtime
from orchestwin.jvm_execution.dependency_setup import (
    JVM_SETUP_POLICY_HASH,
    ControlledJvmNetwork,
    setup_configuration,
)
from orchestwin.jvm_execution.phase_runtime import JvmPhaseRuntimeError, LocalJvmPhaseRuntime
from orchestwin.jvm_execution.plans import JvmExecutionPhase, create_jvm_execution_plan_bundle
from orchestwin.jvm_execution.targets import selection_for
from orchestwin.sandbox.docker_runtime import HostProcessResult, HostProcessStatus
from orchestwin.sandbox.execution_profiles import ExecutionTarget

from .profile_support import runner_for

ATTEMPT = UUID("54333333-3333-4333-8333-333333333333")
NETWORK = ControlledJvmNetwork(
    "owjvmdep-" + "a" * 32 + "-internal",
    "b" * 64,
    JVM_SETUP_POLICY_HASH,
)


class Docker:
    def __init__(self):
        self.calls = []
        self.containers = {}
        self.created = []
        self.started = []
        self.mutate = None
        self.remote = False
        self.image_volumes = False
        self.gradle_volume = False
        self.process_status = HostProcessStatus.COMPLETED
        self.exit_code = 0
        self.oom = False
        self.exit_mismatch = False
        self.fail_remove = False
        self.fail_create_after_allocation = False
        self.wrong_created_id = False
        self.pause = None
        self.entered = None
        self.release = None

    def output(self, value=b"", exit_code=0):
        if isinstance(value, (list, dict)):
            value = json.dumps(value).encode()
        if isinstance(value, str):
            value = value.encode()
        return HostProcessResult(HostProcessStatus.COMPLETED, exit_code, value, b"", None)

    async def run(self, argv, **options):
        self.calls.append((argv, options))
        assert argv[:3] == ("docker", "--context", "desktop-linux")
        assert options["environment_overrides"] == {}
        args = argv[3:]
        if args[:2] == ("context", "inspect"):
            return self.output(
                [
                    {
                        "Name": "desktop-linux",
                        "Endpoints": {
                            "docker": {
                                "Host": "tcp://remote:2376"
                                if self.remote
                                else "npipe:////./pipe/docker_engine",
                            }
                        },
                    }
                ]
            )
        if args[:2] == ("image", "inspect"):
            return self.output(
                [
                    {
                        "Id": args[2],
                        "Os": "linux",
                        "Architecture": "amd64",
                        "Config": {
                            "Volumes": {"/other": {}}
                            if self.image_volumes
                            else ({"/home/gradle/.gradle": {}} if self.gradle_volume else None)
                        },
                    }
                ]
            )
        if args[:2] == ("container", "ls"):
            query = args[args.index("--filter") + 1]
            return self.output(
                "\n".join(
                    key
                    for key, item in self.containers.items()
                    if query == f"id={key}" or query == f"name=^{item['Name']}$"
                )
            )
        if args[0] == "create":

            def option(key):
                return args[args.index(key) + 1]

            identifier = f"{len(self.created) + 1:064x}"
            name = option("--name")
            entry_index = args.index("--entrypoint")
            image = args[entry_index + 2]
            source = (
                option("--mount")
                .removeprefix("type=bind,source=")
                .removesuffix(",target=/workspace")
            )
            label_values = [
                args[i + 1].split("=", 1) for i, part in enumerate(args) if part == "--label"
            ]
            environment = [args[i + 1] for i, part in enumerate(args) if part == "--env"]
            item = {
                "Id": identifier,
                "Name": "/" + name,
                "Image": image,
                "Config": {
                    "User": option("--user"),
                    "WorkingDir": option("--workdir"),
                    "Entrypoint": [args[entry_index + 1]],
                    "Cmd": list(args[entry_index + 3 :]),
                    "Env": environment,
                    "Labels": dict(label_values),
                },
                "HostConfig": {
                    "ReadonlyRootfs": "--read-only" in args,
                    "Privileged": False,
                    "Init": "--init" in args,
                    "CapDrop": [option("--cap-drop")],
                    "CapAdd": None,
                    "SecurityOpt": [option("--security-opt")],
                    "IpcMode": "private",
                    "CgroupnsMode": "private",
                    "Memory": int(option("--memory")[:-1]) * 1024 * 1024,
                    "MemorySwap": int(option("--memory-swap")[:-1]) * 1024 * 1024,
                    "NanoCpus": int(float(option("--cpus")) * 1_000_000_000),
                    "PidsLimit": int(option("--pids-limit")),
                    "Tmpfs": dict(
                        args[i + 1].split(":", 1)
                        for i, part in enumerate(args)
                        if part == "--tmpfs"
                    ),
                    "NetworkMode": option("--network"),
                    "LogConfig": {"Type": option("--log-driver"), "Config": {}},
                    "Mounts": [{"Type": "bind", "Source": source, "Target": "/workspace"}],
                },
                "Mounts": [{"Type": "bind", "Destination": "/workspace", "RW": True}],
                "NetworkSettings": {
                    "Networks": {
                        "none" if option("--network") == "none" else NETWORK.name: {
                            "NetworkID": ""
                        },
                    }
                },
                "State": {"Status": "created", "Running": False, "OOMKilled": False, "ExitCode": 0},
            }
            if self.mutate:
                self.mutate(item)
            self.containers[identifier] = item
            self.created.append(copy.deepcopy(item))
            if self.pause == "create":
                self.entered.set()
                await self.release.wait()
            return self.output(
                "f" * 64 if self.wrong_created_id else identifier,
                1 if self.fail_create_after_allocation else 0,
            )
        if args[:2] == ("container", "inspect"):
            item = self.containers.get(args[2]) or next(
                (item for item in self.containers.values() if item["Name"] == "/" + args[2]), None
            )
            return self.output([item] if item else [], 0 if item else 1)
        if args[0] == "start":
            item = self.containers[args[-1]]
            self.started.append(item["Id"])
            item["State"] = {
                "Status": "exited",
                "Running": False,
                "ExitCode": self.exit_code + int(self.exit_mismatch),
                "OOMKilled": self.oom,
                "StartedAt": "2026-09-13T10:00:00Z",
                "FinishedAt": "2026-09-13T10:00:01Z",
            }
            for details in item["NetworkSettings"]["Networks"].values():
                details["NetworkID"] = (
                    "c" * 64 if item["HostConfig"]["NetworkMode"] == "none" else NETWORK.network_id
                )
            if self.pause == "start":
                self.entered.set()
                await self.release.wait()
            if self.process_status is not HostProcessStatus.COMPLETED:
                item["State"]["Status"], item["State"]["Running"] = "running", True
                return HostProcessResult(
                    self.process_status,
                    None,
                    b"partial stdout",
                    b"partial stderr",
                    "Transport limit reached.",
                )
            return HostProcessResult(
                HostProcessStatus.COMPLETED, self.exit_code, b"real stdout", b"real stderr", None
            )
        if args[:2] == ("container", "rm"):
            if self.pause == "remove":
                self.entered.set()
                await self.release.wait()
            if self.fail_remove:
                return self.output("", 1)
            del self.containers[args[-1]]
            return self.output(args[-1])
        raise AssertionError(args)


def configure(workspace, target, phase):
    configuration = setup_configuration(
        target, ATTEMPT, NETWORK if phase is JvmExecutionPhase.SETUP else None
    )
    for relative, payload in configuration.file_payloads:
        destination = workspace / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    (workspace / f".orchestwin/jvm/{ATTEMPT.hex}/home").mkdir(parents=True, exist_ok=True)


def build(tmp_path, *, target=ExecutionTarget.JVM_KOTLIN, docker=None):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    configure(workspace, target, JvmExecutionPhase.VALIDATE)
    docker = docker or Docker()
    transport = LocalJvmPhaseRuntime(
        attempt_id=ATTEMPT,
        execution_plan=create_jvm_execution_plan_bundle(selection_for(target)),
        runner_contract=runner_for(target),
        workspace=workspace,
        docker_context="desktop-linux",
        dependency_network_manifest=tmp_path / "manifest.json",
        dependency_network_manifest_hash="d" * 64,
        process_runner=docker,
    )
    return transport, docker


@pytest.mark.parametrize(
    "target", [ExecutionTarget.JVM_JAVA, ExecutionTarget.JVM_KOTLIN, ExecutionTarget.JVM_SCALA]
)
def test_all_phases_enforce_network_identity_and_return_real_output(tmp_path, monkeypatch, target):
    transport, docker = build(tmp_path, target=target)
    network_calls = []

    async def verify(path, **kwargs):
        network_calls.append((path, kwargs))
        return NETWORK

    monkeypatch.setattr(runtime, "verify_dependency_network", verify)

    async def scenario():
        for phase in JvmExecutionPhase:
            configure(transport.workspace, target, phase)
            result = await transport.run_phase(phase)
            assert result.attempt_id == ATTEMPT
            assert result.command_plan_hash == transport.plan.phase(phase).command_plan.content_hash
            assert (
                result.process.stdout == b"real stdout" and result.process.stderr == b"real stderr"
            )
            assert result.container_exit_code == 0 and result.cleanup_confirmed
            assert result.network_id == (
                NETWORK.network_id if phase is JvmExecutionPhase.SETUP else "none"
            )
            assert result.dependency_network_manifest_hash == (
                "d" * 64 if phase is JvmExecutionPhase.SETUP else None
            )
            assert not docker.containers
        await transport.close()

    asyncio.run(scenario())
    assert len(network_calls) == 1
    assert network_calls[0][1]["expected_content_hash"] == "d" * 64
    assert len(docker.created) == len(docker.started) == 7
    assert all(item["HostConfig"]["Memory"] == 4096 * 1024 * 1024 for item in docker.created)
    assert all(item["HostConfig"]["PidsLimit"] == 256 for item in docker.created)
    assert all(item["Config"]["User"] == "65532:65532" for item in docker.created)
    assert all("--publish" not in argv and argv[3] != "run" for argv, _ in docker.calls)
    for argv, options in docker.calls:
        if argv[3] == "start":
            phase = tuple(JvmExecutionPhase)[docker.started.index(argv[-1])]
            assert (
                options["timeout_seconds"]
                == transport.plan.phase(phase).command_plan.commands[0].timeout_seconds
            )


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("Config", "User", "0:0"),
        ("Config", "Cmd", ["unexpected"]),
        ("Config", "Env", ["JAVA_TOOL_OPTIONS=-javaagent:/host/agent.jar"]),
        ("HostConfig", "ReadonlyRootfs", False),
        ("HostConfig", "Privileged", True),
        ("HostConfig", "NetworkMode", "bridge"),
        ("HostConfig", "CapAdd", ["SYS_ADMIN"]),
        ("HostConfig", "SecurityOpt", []),
        ("HostConfig", "Memory", 0),
        ("HostConfig", "PidsLimit", 0),
        ("HostConfig", "NanoCpus", 0),
        ("HostConfig", "PortBindings", {"8080/tcp": [{"HostPort": "8080"}]}),
        ("HostConfig", "Binds", ["/var/run/docker.sock:/var/run/docker.sock"]),
        ("HostConfig", "Tmpfs", {"/tmp": "rw"}),
        ("NetworkSettings", "Networks", {"bridge": {"NetworkID": "c" * 64}}),
    ],
)
def test_container_drift_is_rejected_before_start_and_owned_container_removed(
    tmp_path, section, key, value
):
    transport, docker = build(tmp_path)
    docker.mutate = lambda item: item[section].__setitem__(key, value)
    with pytest.raises(JvmPhaseRuntimeError, match="MISMATCH"):
        asyncio.run(transport.run_phase(JvmExecutionPhase.VALIDATE))
    assert docker.started == []
    assert not docker.containers


@pytest.mark.parametrize("change", ["remote", "image_volumes", "configuration", "order"])
def test_untrusted_inputs_never_create_a_container(tmp_path, change):
    transport, docker = build(tmp_path)
    phase = JvmExecutionPhase.VALIDATE
    if change in {"remote", "image_volumes"}:
        setattr(docker, change, True)
    elif change == "configuration":
        next(transport.workspace.rglob("gradle.properties")).write_text("poisoned")
    else:
        phase = JvmExecutionPhase.TEST
    with pytest.raises(JvmPhaseRuntimeError):
        asyncio.run(transport.run_phase(phase))
    assert not docker.created


@pytest.mark.parametrize(
    "status", [HostProcessStatus.TIMED_OUT, HostProcessStatus.OUTPUT_LIMIT_EXCEEDED]
)
def test_host_limit_preserves_partial_output_and_removes_running_container(tmp_path, status):
    transport, docker = build(tmp_path)
    docker.process_status = status
    observation = asyncio.run(transport.run_phase(JvmExecutionPhase.VALIDATE))
    assert observation.process.status is status
    assert observation.process.stdout == b"partial stdout"
    assert observation.container_exit_code is None
    assert observation.cleanup_confirmed and not docker.containers
    with pytest.raises(JvmPhaseRuntimeError, match="ORDER"):
        asyncio.run(transport.run_phase(JvmExecutionPhase.SETUP))


@pytest.mark.parametrize(("exit_code", "oom"), [(1, False), (137, True)])
def test_failure_and_oom_are_preserved_and_stop_later_phases(tmp_path, exit_code, oom):
    transport, docker = build(tmp_path)
    docker.exit_code, docker.oom = exit_code, oom
    observation = asyncio.run(transport.run_phase(JvmExecutionPhase.VALIDATE))
    assert observation.container_exit_code == observation.process.exit_code == exit_code
    assert observation.oom_killed is oom
    assert not docker.containers
    with pytest.raises(JvmPhaseRuntimeError, match="ORDER"):
        asyncio.run(transport.run_phase(JvmExecutionPhase.SETUP))


def test_cli_success_without_matching_container_completion_is_not_phase_success(tmp_path):
    transport, docker = build(tmp_path)
    docker.exit_mismatch = True
    with pytest.raises(JvmPhaseRuntimeError, match="COMPLETION_UNCONFIRMED") as caught:
        asyncio.run(transport.run_phase(JvmExecutionPhase.VALIDATE))
    assert caught.value.command_result.stdout == b"real stdout"
    assert not docker.containers


def test_failed_create_recovers_owned_id_and_removes_only_that_container(tmp_path):
    transport, docker = build(tmp_path)
    docker.fail_create_after_allocation = True
    with pytest.raises(JvmPhaseRuntimeError, match="OPERATION_FAILED"):
        asyncio.run(transport.run_phase(JvmExecutionPhase.VALIDATE))
    assert not docker.containers and not docker.started


def test_unconfirmed_created_id_recovers_owned_resource_by_name(tmp_path):
    transport, docker = build(tmp_path)
    docker.wrong_created_id = True
    with pytest.raises(JvmPhaseRuntimeError, match="ID_MISMATCH"):
        asyncio.run(transport.run_phase(JvmExecutionPhase.VALIDATE))
    assert not docker.containers and not docker.started


def test_gradle_image_volume_is_masked_without_a_persistent_cache(tmp_path):
    transport, docker = build(tmp_path)
    docker.gradle_volume = True
    observed = asyncio.run(transport.run_phase(JvmExecutionPhase.VALIDATE))
    assert observed.cleanup_confirmed
    assert docker.created[0]["HostConfig"]["Tmpfs"]["/home/gradle/.gradle"] == (
        "ro,noexec,nosuid,nodev,size=1m,mode=000"
    )
    assert all(mount["Type"] != "volume" for mount in docker.created[0]["Mounts"])


def test_foreign_container_is_never_removed(tmp_path):
    transport, docker = build(tmp_path)
    docker.mutate = lambda item: item["Config"]["Labels"].__setitem__(
        "org.orchestwin.jvm-phase-owner", "foreign"
    )
    with pytest.raises(JvmPhaseRuntimeError, match="OWNERSHIP_MISMATCH"):
        asyncio.run(transport.run_phase(JvmExecutionPhase.VALIDATE))
    assert len(docker.containers) == 1
    assert not docker.started
    assert all(argv[3:5] != ("container", "rm") for argv, _ in docker.calls)


def test_cleanup_failure_retains_command_output_and_can_be_retried(tmp_path):
    transport, docker = build(tmp_path)
    docker.fail_remove = True
    with pytest.raises(JvmPhaseRuntimeError) as caught:
        asyncio.run(transport.run_phase(JvmExecutionPhase.VALIDATE))
    assert caught.value.command_result.stdout == b"real stdout"
    assert docker.containers
    docker.fail_remove = False
    asyncio.run(transport.close())
    asyncio.run(transport.close())
    assert not docker.containers


@pytest.mark.parametrize("pause", ["create", "start", "remove"])
def test_cancellation_during_resource_lifecycle_waits_for_owned_cleanup(tmp_path, pause):
    transport, docker = build(tmp_path)

    async def scenario():
        docker.pause = pause
        docker.entered, docker.release = asyncio.Event(), asyncio.Event()
        task = asyncio.create_task(transport.run_phase(JvmExecutionPhase.VALIDATE))
        await asyncio.wait_for(docker.entered.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        if pause == "remove":
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and docker.containers
        docker.release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert not docker.containers
        await transport.close()

    asyncio.run(scenario())


def test_modified_canonical_plan_is_rejected_at_construction(tmp_path):
    transport, _ = build(tmp_path)
    original = transport.plan.phases[0]
    command = replace(original.command_plan.commands[0], arguments=("unsafe",))
    modified = replace(original, command_plan=replace(original.command_plan, commands=(command,)))
    with pytest.raises(ValueError, match="canonical"):
        LocalJvmPhaseRuntime(
            attempt_id=ATTEMPT,
            execution_plan=replace(transport.plan, phases=(modified, *transport.plan.phases[1:])),
            runner_contract=transport.contract,
            workspace=transport.workspace,
            docker_context="desktop-linux",
        )
