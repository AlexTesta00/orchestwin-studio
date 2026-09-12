"""Ownership, failure recovery and confinement checks for the operator bootstrap."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from orchestwin.web_execution import dependency_network as network
from orchestwin.web_execution.local_runners import CommandOutput
from orchestwin.web_execution.phase_runner import WebPhaseRunnerIdentity


class Docker:
    def __init__(self, root):
        self.root = root
        self.calls = []
        self.networks = {}
        self.containers = {}
        self.dirty = False
        self.remote = False
        self.endpoint = None
        self.fail_probe = False
        self.fail_connect = False
        self.fail_cleanup = False
        self.fail_network_cleanup = False
        self.poison_proxy_environment = False
        self.taint_during_probe = False
        self.fail_create_internal = False
        self.pause_removal = None
        self.resume_removal = None
        self.uninitialized_probe_network = True
        self.bad_prestart_network = False
        self.bad_poststart_network = False
        self.wrong_security = False
        self.uncommitted = False
        self.counter = 0

    def identity(self):
        self.counter += 1
        return f"{self.counter:064x}"

    async def __call__(self, argv, *, timeout, limit, stdin_bytes=None):
        self.calls.append((argv, timeout, limit, stdin_bytes))
        if argv[0] == "git":
            if "rev-parse" in argv:
                value = "a" * 40
            elif "status" in argv:
                value = "?? changed" if self.dirty else ""
            else:
                value = (self.root / argv[-1].split(":", 1)[1]).read_bytes()
                if self.uncommitted:
                    value += b"changed"
            return self.output(value)
        args = argv[3:]
        if args[:2] == ("context", "inspect"):
            endpoint = "tcp://remote:2376" if self.remote else "npipe:////./pipe/docker_engine"
            endpoint = self.endpoint or endpoint
            return self.output(
                [{"Name": "desktop-linux", "Endpoints": {"docker": {"Host": endpoint}}}]
            )
        if args[:2] == ("buildx", "inspect"):
            return self.output("Driver: docker\nEndpoint: desktop-linux\n")
        if args[0] == "info":
            return self.output({"os": "linux", "arch": "amd64"})
        if args[:2] == ("image", "inspect"):
            return self.output([{"Id": args[2], "Os": "linux", "Architecture": "amd64"}])
        if args[:2] == ("buildx", "build"):
            Path(args[args.index("--iidfile") + 1]).write_text("sha256:" + "e" * 64)
            return self.output("")
        if args[:2] == ("network", "create"):
            if self.fail_create_internal and "--internal" in args:
                return self.output("", 1)
            identity = self.identity()
            self.networks[identity] = {
                "Id": identity,
                "Name": args[-1],
                "Driver": "bridge",
                "Internal": "--internal" in args,
                "Labels": self.labels(args),
                "Containers": {},
            }
            return self.output(identity)
        if args[:2] == ("network", "inspect"):
            result = [n for n in self.networks.values() if args[2] in (n["Id"], n["Name"])]
            return self.output(result, 0 if result else 1)
        if args[:2] == ("network", "connect"):
            if self.fail_connect:
                return self.output("", 1)
            self.attach(args[-1], args[-2])
            return self.output("")
        if args[0] == "create":
            identity = self.identity()
            image = next(a for a in args if a.startswith("sha256:"))
            self.containers[identity] = {
                "Id": identity,
                "Name": "/" + args[args.index("--name") + 1],
                "Image": image,
                "Config": {
                    "Labels": self.labels(args),
                    "User": "65532:65532",
                    "Env": [
                        args[index + 1] for index, value in enumerate(args) if value == "--env"
                    ],
                },
                "HostConfig": {
                    "ReadonlyRootfs": not self.wrong_security,
                    "CapDrop": ["ALL"],
                    "SecurityOpt": ["no-new-privileges"],
                    "PortBindings": {},
                    "Privileged": False,
                    "Binds": None,
                    "Mounts": None,
                    "Memory": 268435456,
                    "MemorySwap": 268435456,
                    "NanoCpus": 500000000,
                    "PidsLimit": 64,
                    "LogConfig": {"Type": "none", "Config": {}},
                    "NetworkMode": args[args.index("--network") + 1],
                },
                "Mounts": [],
                "State": {"Running": False},
                "NetworkSettings": {"Networks": {}, "Ports": {}},
            }
            if self.poison_proxy_environment:
                self.containers[identity]["Config"]["Env"] = ["HTTPS_PROXY=http://private-secret"]
            self.attach(identity, args[args.index("--network") + 1])
            if self.labels(args)[network.ROLE_LABEL] == "probe":
                item = self.containers[identity]
                if self.uninitialized_probe_network:
                    networks = item["NetworkSettings"]["Networks"]
                    net = next(iter(networks.values()))
                    net["NetworkID"] = ""
                    item["NetworkSettings"]["Networks"] = {item["HostConfig"]["NetworkMode"]: net}
                if self.bad_prestart_network:
                    item["HostConfig"]["NetworkMode"] = "none"
            return self.output(identity)
        if args[:2] == ("container", "inspect"):
            result = [
                c
                for c in self.containers.values()
                if args[2] in (c["Id"], c["Name"].removeprefix("/"))
            ]
            return self.output(result, 0 if result else 1)
        if args[0] == "start":
            self.containers[args[-1]]["State"]["Running"] = True
            if "--attach" in args:
                item = self.containers[args[-1]]
                item["NetworkSettings"]["Networks"] = {}
                self.attach(args[-1], item["HostConfig"]["NetworkMode"])
                if self.bad_poststart_network:
                    item["NetworkSettings"]["Networks"]["unexpected"] = {"NetworkID": "9" * 64}
                if self.taint_during_probe:
                    (self.root / network.PROBE_PATH).write_bytes(b"changed during probe")
                result = {
                    "schema_version": 1,
                    "passed": not self.fail_probe,
                    "checks": {name: True for name in network.PROBE_CHECKS},
                }
                return self.output(result, 1 if self.fail_probe else 0)
            return self.output(args[-1])
        if args[0] == "rm":
            if self.fail_cleanup:
                return self.output("", 1)
            self.containers.pop(args[-1])
            for item in self.networks.values():
                item["Containers"].pop(args[-1], None)
            return self.output("")
        if args[:2] == ("network", "rm"):
            if self.pause_removal is not None:
                self.pause_removal.set()
                await self.resume_removal.wait()
            if self.fail_cleanup or self.fail_network_cleanup:
                return self.output("", 1)
            assert not self.networks[args[-1]]["Containers"]
            self.networks.pop(args[-1])
            return self.output("")
        if len(args) > 1 and args[0] in {"container", "network"} and args[1] == "ls":
            field, value = args[args.index("--filter") + 1].split("=", 1)
            resources = self.networks if args[0] == "network" else self.containers
            selected = [
                item["Id"]
                for item in resources.values()
                if (item["Id"] == value if field == "id" else value in item["Name"])
            ]
            return self.output("\n".join(selected))
        raise AssertionError(argv)

    @staticmethod
    def labels(args):
        return dict(args[i + 1].split("=", 1) for i, a in enumerate(args) if a == "--label")

    @staticmethod
    def output(value, code=0):
        body = (
            value
            if isinstance(value, bytes)
            else (value.encode() if isinstance(value, str) else json.dumps(value).encode())
        )
        return CommandOutput(code, body, b"")

    def attach(self, container, identifier):
        item = next(n for n in self.networks.values() if identifier in (n["Id"], n["Name"]))
        self.containers[container]["NetworkSettings"]["Networks"][item["Name"]] = {
            "NetworkID": item["Id"],
            "Aliases": [network.PROXY_HOST],
        }
        item["Containers"][container] = {
            "Name": self.containers[container]["Name"].removeprefix("/")
        }


@pytest.fixture
def setup(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    for name in network.INPUT_PATHS:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"// trusted fixture input\n")
    (root / network.RECIPE_PATH).write_text(
        "FROM docker.io/library/node:26.7.0-bookworm-slim@sha256:" + "d" * 64 + "\n"
        "COPY proxy.mjs /opt/orchestwin/dependency-proxy.mjs\nUSER 65532:65532\n"
    )
    monkeypatch.setattr(
        network,
        "load_phase_runner_identity",
        lambda *a, **k: WebPhaseRunnerIdentity("NODE", "sha256:" + "f" * 64, "b" * 64, "c" * 64),
    )
    monkeypatch.setattr(network, "_verify_runtime_checkout", lambda root: None)
    docker = Docker(root)
    arguments = dict(
        repo_root=root,
        runner_manifest=tmp_path / "runners.json",
        output_root=tmp_path / "output",
        docker_context="desktop-linux",
        runner=docker,
    )
    return docker, arguments


def run_create(setup, **changes):
    _, arguments = setup
    arguments = {**arguments, **changes}
    return asyncio.run(network.create_dependency_network(**arguments))


def test_ready_network_is_internal_with_only_hardened_dual_homed_proxy(setup):
    docker, arguments = setup
    result = run_create(setup)
    assert result["status"] == "READY"
    assert result["report_type"] == "CONTROLLED_DEPENDENCY_NETWORK_NOT_PROFILE_VALIDATION"
    assert result["level_d_validated"] is False
    controlled = result["controlled_network"]
    assert controlled["proxy_host"] == network.PROXY_HOST
    assert controlled["proxy_port"] == 3128
    internal = docker.networks[controlled["network_id"]]
    assert internal["Internal"] is True
    assert len(docker.containers) == 1
    proxy = next(iter(docker.containers.values()))
    assert len(proxy["NetworkSettings"]["Networks"]) == 2
    probe = next(call for call in docker.calls if "--attach" in call[0])
    assert probe[1] == 60
    assert probe[3] == (arguments["repo_root"] / network.PROBE_PATH).read_bytes()
    assert all(call[1] <= 300 and call[2] <= 8 * 1024 * 1024 for call in docker.calls)
    assert all("--publish" not in call[0] and "-p" not in call[0] for call in docker.calls)
    assert (arguments["output_root"] / "manifest.json").is_file()


@pytest.mark.parametrize(
    "flag, error",
    [("remote", "LOCAL_DOCKER"), ("dirty", "WORKING_TREE_NOT_CLEAN"), ("uncommitted", "COMMITTED")],
)
def test_preconditions_fail_before_creating_resources(setup, flag, error):
    docker, arguments = setup
    setattr(docker, flag, True)
    with pytest.raises(network.DependencyNetworkError, match=error):
        run_create(setup)
    assert not docker.networks and not docker.containers
    assert not arguments["output_root"].exists()


@pytest.mark.parametrize("flag", ["fail_probe", "fail_connect", "wrong_security"])
def test_partial_failures_remove_only_verified_owned_resources_and_keep_report(setup, flag):
    docker, arguments = setup
    setattr(docker, flag, True)
    with pytest.raises(network.DependencyNetworkError):
        run_create(setup)
    assert not docker.containers and not docker.networks
    report = json.loads((arguments["output_root"] / "manifest.json").read_text())
    assert report["status"] == "FAILED"
    assert report["cleanup_failures"] == []


def test_cleanup_failure_is_preserved_without_masking_probe_failure(setup):
    docker, arguments = setup
    docker.fail_probe = docker.fail_cleanup = True
    with pytest.raises(network.DependencyNetworkError, match="PROBE"):
        run_create(setup)
    report = json.loads((arguments["output_root"] / "manifest.json").read_text())
    assert report["cleanup_failures"]
    assert docker.containers and docker.networks


def test_development_is_explicit_and_never_claims_committed_evidence(setup):
    docker, _ = setup
    docker.dirty = True
    result = run_create(setup, development=True)
    assert result["development"] is True
    assert result["committed_sources_verified"] is False
    assert result["level_d_validated"] is False


def test_remove_preflights_every_owner_before_any_deletion(setup):
    docker, arguments = setup
    result = run_create(setup)
    container = docker.containers[result["resources"]["proxy"]["id"]]
    container["Config"]["Labels"][network.OWNER_LABEL] = "0" * 32
    before = len(docker.calls)
    with pytest.raises(network.DependencyNetworkError, match="OWNERSHIP"):
        asyncio.run(
            network.remove_dependency_network(
                arguments["output_root"] / "manifest.json",
                docker_context="desktop-linux",
                runner=docker,
            )
        )
    assert not any("rm" in call[0] for call in docker.calls[before:])
    assert len(docker.networks) == 2 and len(docker.containers) == 1


def test_remove_checks_manifest_integrity_before_any_docker_action(setup):
    docker, arguments = setup
    run_create(setup)
    path = arguments["output_root"] / "manifest.json"
    report = json.loads(path.read_text())
    report["resources"]["proxy"]["id"] = "9" * 64
    path.write_text(json.dumps(report))
    before = len(docker.calls)
    with pytest.raises(network.DependencyNetworkError, match="MANIFEST"):
        asyncio.run(
            network.remove_dependency_network(path, docker_context="desktop-linux", runner=docker)
        )
    assert len(docker.calls) == before


def test_remove_uses_only_full_verified_ids_and_preserves_original_manifest(setup):
    docker, arguments = setup
    run_create(setup)
    path = arguments["output_root"] / "manifest.json"
    original = path.read_bytes()
    result = asyncio.run(
        network.remove_dependency_network(path, docker_context="desktop-linux", runner=docker)
    )
    assert result["status"] == "REMOVED"
    assert not docker.containers and not docker.networks
    assert path.read_bytes() == original


def test_output_cannot_be_inside_repository(setup):
    _, arguments = setup
    with pytest.raises(network.DependencyNetworkError, match="OUTSIDE_REPOSITORY"):
        run_create(setup, output_root=arguments["repo_root"] / "output")


@pytest.mark.parametrize(
    "endpoint",
    [
        "npipe:////remote/pipe/docker_engine",
        "unix://relative.sock",
        "ssh://host",
        "npipe://./pipe/docker_engine",
    ],
)
def test_remote_named_pipes_and_relative_unix_endpoints_are_rejected(setup, endpoint):
    docker, _ = setup
    docker.endpoint = endpoint
    with pytest.raises(network.DependencyNetworkError, match="LOCAL_DOCKER"):
        run_create(setup)
    assert not docker.networks and not docker.containers


def test_actual_loaded_runtime_cannot_claim_another_checkout(tmp_path):
    with pytest.raises(network.DependencyNetworkError, match="RUNTIME_CHECKOUT"):
        network._verify_runtime_checkout(tmp_path)


def test_proxy_defaults_are_explicitly_cleared_and_container_inspections_redacted(setup):
    docker, arguments = setup
    run_create(setup)
    creates = [call[0] for call in docker.calls if call[0][3] == "create"]
    for command in creates:
        assert command[command.index("--log-driver") + 1] == "none"
        for name in network._PROXY_VARIABLES:
            assert f"{name}=" in command
    inspections = list(arguments["output_root"].glob("*INSPECT_PROXY.stdout.log"))
    assert inspections and all(
        path.read_bytes() == b"INSPECTION_CONTENT_NOT_RECORDED\n" for path in inspections
    )


def test_unexpected_proxy_credentials_are_rejected_and_never_written(setup):
    docker, arguments = setup
    docker.poison_proxy_environment = True
    with pytest.raises(network.DependencyNetworkError, match="INHERITED_PROXY"):
        run_create(setup)
    assert not docker.networks and not docker.containers
    assert all(
        b"private-secret" not in path.read_bytes()
        for path in arguments["output_root"].rglob("*")
        if path.is_file()
    )


def test_source_changed_during_development_still_prevents_ready_and_cleans_up(setup):
    docker, arguments = setup
    docker.taint_during_probe = True
    with pytest.raises(network.DependencyNetworkError, match="SOURCE_CHANGED"):
        run_create(setup, development=True)
    assert not docker.networks and not docker.containers
    assert (
        json.loads((arguments["output_root"] / "manifest.json").read_text())["status"] == "FAILED"
    )


def test_partial_removal_receipt_can_resume_only_remaining_resources(setup):
    docker, arguments = setup
    run_create(setup)
    path = arguments["output_root"] / "manifest.json"
    docker.fail_network_cleanup = True
    with pytest.raises(network.DependencyNetworkError, match="REMOVAL_INCOMPLETE"):
        asyncio.run(
            network.remove_dependency_network(path, docker_context="desktop-linux", runner=docker)
        )
    assert not docker.containers and len(docker.networks) == 2
    receipt = next(arguments["output_root"].glob("removal-*/manifest.json"))
    report = json.loads(receipt.read_text())
    assert set(report["resources"]) == {"internal", "egress"}
    docker.fail_network_cleanup = False
    result = asyncio.run(
        network.remove_dependency_network(receipt, docker_context="desktop-linux", runner=docker)
    )
    assert result["status"] == "REMOVED"
    assert not docker.networks and not docker.containers


def test_create_without_effect_confirms_absence_and_has_no_phantom_resource(setup):
    docker, arguments = setup
    docker.fail_create_internal = True
    with pytest.raises(network.DependencyNetworkError, match="CREATE_INTERNAL"):
        run_create(setup)
    report = json.loads((arguments["output_root"] / "manifest.json").read_text())
    assert report["resources"] == {} and report["cleanup_failures"] == []
    assert any("CONFIRM_ABSENCE" in path.name for path in arguments["output_root"].iterdir())


def test_remove_cancellation_finishes_owned_cleanup_and_writes_receipt(setup):
    docker, arguments = setup
    run_create(setup)

    async def scenario():
        docker.pause_removal, docker.resume_removal = asyncio.Event(), asyncio.Event()
        task = asyncio.create_task(
            network.remove_dependency_network(
                arguments["output_root"] / "manifest.json",
                docker_context="desktop-linux",
                runner=docker,
            )
        )
        await docker.pause_removal.wait()
        task.cancel()
        docker.resume_removal.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert not docker.containers and not docker.networks
    receipt = next(arguments["output_root"].glob("removal-*/manifest.json"))
    assert json.loads(receipt.read_text())["status"] == "REMOVED"


def test_remove_original_manifest_is_idempotent_only_after_confirmed_absence(setup):
    docker, arguments = setup
    run_create(setup)
    path = arguments["output_root"] / "manifest.json"
    for _ in range(2):
        result = asyncio.run(
            network.remove_dependency_network(path, docker_context="desktop-linux", runner=docker)
        )
        assert result["status"] == "REMOVED"
    assert not docker.containers and not docker.networks


def test_prestart_probe_requires_exact_internal_network_mode_even_without_assigned_id(setup):
    docker, _ = setup
    docker.bad_prestart_network = True
    with pytest.raises(network.DependencyNetworkError, match="ATTACHMENTS"):
        run_create(setup)
    assert not any("--attach" in call[0] for call in docker.calls)
    assert not docker.containers and not docker.networks


def test_poststart_probe_checks_actual_network_ids_and_rejects_extra_attachment(setup):
    docker, _ = setup
    docker.bad_poststart_network = True
    with pytest.raises(network.DependencyNetworkError, match="ATTACHMENTS"):
        run_create(setup)
    assert not docker.containers and not docker.networks


def test_sanitized_inspection_retains_network_diagnostics_without_environment(setup):
    docker, arguments = setup
    docker.poison_proxy_environment = True
    with pytest.raises(network.DependencyNetworkError):
        run_create(setup)
    observations = list(arguments["output_root"].glob("*INSPECT_PROXY.observation.json"))
    assert observations
    observation = json.loads(observations[0].read_text())
    assert observation["proxy_environment_cleared"] is False
    assert len(observation["networks"]) == 2
    assert all(len(item["network_id"]) == 64 for item in observation["networks"])
    assert b"private-secret" not in observations[0].read_bytes()
