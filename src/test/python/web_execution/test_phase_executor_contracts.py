"""Execute the real contract matrix with a controlled transport, without promotion."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from orchestwin.sandbox.command_plans import CommandNetworkMode
from orchestwin.sandbox.docker_runtime import HostProcessResult, HostProcessStatus
from orchestwin.sandbox.evidence_store import FileSystemSandboxEvidenceStore
from orchestwin.sandbox.execution_policy import (
    DEFAULT_SANDBOX_EXECUTION_POLICY,
    DEFAULT_SANDBOX_RESOURCE_LIMITS,
)
from orchestwin.sandbox.execution_profiles import ExecutionCapabilityStatus
from orchestwin.web_execution.detection import detect_web_project
from orchestwin.web_execution.lockfiles import validate_web_dependency_locks
from orchestwin.web_execution.phase_executor import GovernedWebPhaseExecutor
from orchestwin.web_execution.phase_runner import WebPhaseRunnerIdentity
from orchestwin.web_execution.phase_runtime import WebPhaseRuntimeError
from orchestwin.web_execution.plans import WebExecutionPhase, WebPhaseExecutionKind
from orchestwin.web_execution.profile_contracts import WebProfileRunnerSet
from orchestwin.web_execution.profile_registry import create_sprint08_web_profile_registry
from orchestwin.web_execution.workspaces import PreparedWebWorkspace

from .test_phase_runtime import Host, static_command
from .test_phase_runtime import runtime as local_runtime
from .test_profile_fixture_matrix import detection_snapshot, fixture_files, matrix

CONTROLLED_NETWORK = object()  # Trusted composition sentinel accepted only by this fake.
TEST_POLICY = replace(
    DEFAULT_SANDBOX_EXECUTION_POLICY,
    allowed_network_modes=frozenset({CommandNetworkMode.DISABLED, CommandNetworkMode.CONTROLLED}),
)


def stream_bytes(command_id, stream):
    return f"{command_id}:{stream}\n".encode() + b"\x00\xff"


class FakeRuntime:
    """Return bounded observations while retaining the actual requested commands."""

    def __init__(
        self,
        *,
        image_id,
        runner_kind,
        workspace,
        resources,
        docker_context,
        process_runner=None,
        controlled_network=None,
        maximum_output_bytes=1024 * 1024,
    ):
        self.image_id, self.runner_kind = image_id, runner_kind
        self.workspace, self.resources = Path(workspace), resources
        self.docker_context = docker_context
        self.process_runner = process_runner
        self.controlled_network = controlled_network
        self.maximum_output_bytes = maximum_output_bytes
        self.commands = []
        self.started_commands = []
        self.probes = []
        self.servers = {}
        self.stopped = []
        self.reports = {}
        self.fail_command_id = None
        self.opened = False
        self.close_count = 0

    async def open(self):
        assert self.close_count == 0
        assert self.workspace.is_dir()
        self.opened = True

    async def run_command(self, command):
        assert self.opened and self.close_count == 0
        self.commands.append(command)
        if "reports/**" in command.artifact_patterns:
            content = json.dumps(
                {"command_id": command.command_id, "result": "controlled test observation"},
                sort_keys=True,
            ).encode()
            path = (
                self.workspace
                / command.working_directory
                / "reports"
                / f"{command.command_id}.json"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            self.reports[path.relative_to(self.workspace).as_posix()] = content
        return HostProcessResult(
            HostProcessStatus.COMPLETED,
            17 if command.command_id == self.fail_command_id else 0,
            stream_bytes(command.command_id, "stdout"),
            stream_bytes(command.command_id, "stderr"),
            None,
        )

    async def start_command(self, command):
        assert self.opened and self.close_count == 0
        self.started_commands.append(command)
        name = f"fake-server-{len(self.started_commands)}"
        self.servers[name] = command
        return name

    async def invoke(self, argv, *, timeout_seconds):
        assert self.servers and self.close_count == 0
        self.probes.append((argv, timeout_seconds))
        return HostProcessResult(
            HostProcessStatus.COMPLETED,
            0,
            b'{"status_code":200,"error_code":null,"latency_milliseconds":1}',
            b"",
            None,
        )

    async def stop_servers(self):
        observations = [
            {
                "container": name,
                "state": {"Running": False, "ExitCode": 137, "OOMKilled": False},
                "terminated_by_controller": True,
                "stdout": stream_bytes(command.command_id, "server stdout"),
                "stderr": stream_bytes(command.command_id, "server stderr"),
            }
            for name, command in self.servers.items()
        ]
        self.servers.clear()
        self.stopped.extend(observations)
        return observations

    async def close(self):
        assert not self.servers
        self.close_count += 1


def executor_for_fixture(tmp_path, fixture_id, *, fail_command_id=None):
    files = fixture_files(fixture_id)
    source = tmp_path / "prepared"
    source.mkdir()
    entries = []
    for name, text in sorted(files.items(), key=lambda item: (item[0].casefold(), item[0])):
        content = text.encode("utf-8")
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        entries.append(
            {
                "normalized_path": name,
                "sha256_digest": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
        )
    tree_hash = hashlib.sha256(
        json.dumps(
            {"files": entries}, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    prepared = PreparedWebWorkspace(
        source,
        "11111111-1111-4111-8111-111111111111",
        "a" * 64,
        tree_hash,
        len(files),
        sum(entry["size_bytes"] for entry in entries),
    )
    snapshot = detection_snapshot(files)
    detection = detect_web_project(snapshot)
    assert detection.selected is not None
    selection = detection.selected.selection
    profile = create_sprint08_web_profile_registry().for_target(selection.target)
    assert profile is not None
    lock_report = validate_web_dependency_locks(snapshot, selection=selection)
    contract = profile.create_contract(
        snapshot,
        selection=selection,
        lock_report=lock_report,
        source_revision_content_hash=prepared.source_revision_content_hash,
        source_tree_hash=prepared.source_tree_hash,
        runners=WebProfileRunnerSet(
            "b" * 64, "c" * 64 if profile.scope.requires_browser_evidence else None
        ),
    )
    runtimes = []

    def runtime_factory(**kwargs):
        runtime = FakeRuntime(**kwargs)
        runtime.fail_command_id = fail_command_id
        runtimes.append(runtime)
        return runtime

    store = FileSystemSandboxEvidenceStore(tmp_path / "evidence")
    executor = GovernedWebPhaseExecutor(
        contract=contract,
        prepared_workspace=prepared,
        snapshot=snapshot,
        lock_report=lock_report,
        runner_identity=WebPhaseRunnerIdentity(
            "PHP" if selection.target.value == "WEB_PHP" else "NODE",
            "sha256:" + "b" * 64,
            "d" * 64,
            "e" * 64,
        ),
        execution_policy=TEST_POLICY,
        resources=DEFAULT_SANDBOX_RESOURCE_LIMITS,
        workspaces_root=tmp_path / "phases",
        evidence_store=store,
        docker_context="controlled-test",
        runtime_factory=runtime_factory,
        controlled_network=CONTROLLED_NETWORK,
    )
    return executor, contract, store, runtimes, files


def commands_in(phase):
    return tuple(command for plan in phase.command_plans for command in plan.commands)


def invocation(command):
    return command.working_directory, (command.executable, *command.arguments)


def manifest_for(result, store):
    for reference in result.artifact_refs:
        content = json.loads(store.read(reference.storage_key))
        if content.get("phase") == result.phase.value:
            return content
    pytest.fail(f"Missing persisted phase manifest: {result.phase.value}")


def persisted_bytes(reference, store):
    content = store.read(reference.storage_key)
    assert content is not None
    assert hashlib.sha256(content).hexdigest() == reference.sha256_digest
    assert len(content) == reference.size_bytes
    return content


@pytest.mark.parametrize("fixture", matrix()["valid_fixtures"], ids=lambda item: item["id"])
def test_real_contract_matrix_preserves_commands_logs_artifacts_and_browser_boundary(
    tmp_path, fixture
):
    async def scenario():
        executor, contract, store, runtimes, files = executor_for_fixture(tmp_path, fixture["id"])
        results = {}
        for phase in contract.execution_plan.phases:
            if phase.phase is WebExecutionPhase.COLLECT_ARTIFACTS:
                break
            result = await executor.execute(phase, contract=contract)
            results[phase.phase] = result
            if phase.execution_kind is WebPhaseExecutionKind.NO_OP:
                assert result.status.value == "SKIPPED"
                assert not result.exit_codes and not result.command_plan_hashes
                assert (
                    not result.stdout_refs and not result.stderr_refs and not result.artifact_refs
                )
                assert result.started_at is None and result.completed_at is None
            elif phase.phase is WebExecutionPhase.BROWSER_EVIDENCE:
                assert result.status.value == "POLICY_BLOCKED"
                assert result.failure_code == "WEB_BROWSER_EVIDENCE_ADAPTER_UNAVAILABLE"
                assert not result.exit_codes and not result.stdout_refs
            else:
                assert result.status.value == "PASSED", (phase.phase, result.failure_code)
                metadata = manifest_for(result, store)
                assert metadata["contract_hash"] == contract.content_hash
                assert metadata["source_tree_hash"] == contract.source_tree_hash
                assert metadata["policy_hash"] == TEST_POLICY.content_hash
                assert metadata["level_d_validated"] is False

        assert len(runtimes) == 1
        runtime = runtimes[0]
        assert runtime.controlled_network is CONTROLLED_NETWORK
        assert runtime.image_id == "sha256:" + contract.runners.execution_runner_image_digest
        assert runtime.resources == DEFAULT_SANDBOX_RESOURCE_LIMITS
        assert runtime.docker_context == "controlled-test"
        terminal_phases = tuple(
            phase
            for phase in contract.execution_plan.phases
            if phase.execution_kind is WebPhaseExecutionKind.COMMAND_PLANS
            and phase.phase is not WebExecutionPhase.RUN
        )
        expected_commands = tuple(
            command for phase in terminal_phases for command in commands_in(phase)
        )
        assert tuple(runtime.commands) == expected_commands
        assert tuple(map(invocation, runtime.commands)) == tuple(map(invocation, expected_commands))
        for phase in terminal_phases:
            result = results[phase.phase]
            expected = commands_in(phase)
            assert result.exit_codes == (0,) * len(expected)
            assert result.command_plan_hashes == tuple(
                sorted(plan.content_hash for plan in phase.command_plans)
            )
            assert {persisted_bytes(ref, store) for ref in result.stdout_refs} == {
                stream_bytes(command.command_id, "stdout") for command in expected
            }
            assert {persisted_bytes(ref, store) for ref in result.stderr_refs} == {
                stream_bytes(command.command_id, "stderr") for command in expected
            }

        run_commands = commands_in(contract.execution_plan.phase(WebExecutionPhase.RUN))
        sessions = 2 if fixture["target"] == "WEB_STATIC" else 1
        assert tuple(runtime.started_commands) == run_commands * sessions
        assert not results[WebExecutionPhase.RUN].exit_codes
        assert len(runtime.probes) == len(contract.health_checks) * sessions
        for (argv, timeout), spec in zip(
            runtime.probes, contract.health_checks * sessions, strict=True
        ):
            assert argv[0] == ("php" if fixture["target"] == "WEB_PHP" else "node")
            request = json.loads(argv[-1])
            assert (request["port"], request["path"]) == (spec.port, spec.path)
            assert timeout == spec.request_timeout_seconds + 2

        final = await executor.finalize()
        assert final.status.value == "PASSED"
        assert await executor.finalize() is final
        assert runtime.close_count == 1
        assert not runtime.workspace.exists()
        assert len(runtime.stopped) == len(run_commands) * sessions
        metadata = manifest_for(final, store)
        assert metadata["observations"]["cleanup_confirmed"] is True
        observations = metadata["observations"]["processes"]
        assert len(observations) == len(runtime.stopped)
        for observed in observations:
            assert observed["exit_code"] == 137
            assert observed["terminated_by_controller"] is True
            for stream in ("stdout", "stderr"):
                reference = observed[f"{stream}_ref"]
                assert store.read(reference["storage_key"]) == stream_bytes(
                    observed["command_id"], f"server {stream}"
                )
        final_bytes = {persisted_bytes(ref, store) for ref in final.artifact_refs}
        assert set(runtime.reports.values()) <= final_bytes
        if fixture["target"] != "WEB_STATIC":
            assert runtime.reports
            test_bytes = {
                persisted_bytes(ref, store) for ref in results[WebExecutionPhase.TEST].artifact_refs
            }
            assert set(runtime.reports.values()) <= test_bytes
        assert all(
            (executor.prepared.path / name).read_bytes() == text.encode("utf-8")
            for name, text in files.items()
        )
        assert (
            contract.validation.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
        )
        assert contract.validation.validation_evidence_refs == ()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("fixture_id", "failed_command"),
    [
        ("web-vue-node-js-valid", "backend.lint"),
        ("web-vue-node-ts-valid", "backend.typescript"),
    ],
)
def test_vue_node_failure_keeps_observed_prefix_and_blocks_following_work(
    tmp_path, fixture_id, failed_command
):
    async def scenario():
        executor, contract, store, runtimes, _ = executor_for_fixture(
            tmp_path, fixture_id, fail_command_id=failed_command
        )
        for name in (WebExecutionPhase.VALIDATE, WebExecutionPhase.SETUP):
            result = await executor.execute(contract.execution_plan.phase(name), contract=contract)
            assert result.status.value == "PASSED"
        phase = contract.execution_plan.phase(WebExecutionPhase.STATIC_CHECK)
        result = await executor.execute(phase, contract=contract)
        assert result.status.value == "FAILED"
        assert result.failure_category.value == "STATIC_CHECK"
        backend_commands = phase.command_plans[0].commands
        expected_exit_codes = (0,) * (len(backend_commands) - 1) + (17,)
        assert result.exit_codes == expected_exit_codes
        assert result.command_plan_hashes == (phase.command_plans[0].content_hash,)
        expected_commands = (
            *commands_in(contract.execution_plan.phase(WebExecutionPhase.SETUP)),
            *backend_commands,
        )
        assert tuple(runtimes[0].commands) == expected_commands
        assert not runtimes[0].started_commands
        assert {persisted_bytes(ref, store) for ref in result.stdout_refs} == {
            stream_bytes(command.command_id, "stdout") for command in backend_commands
        }
        assert {persisted_bytes(ref, store) for ref in result.stderr_refs} == {
            stream_bytes(command.command_id, "stderr") for command in backend_commands
        }
        metadata = manifest_for(result, store)
        assert len(metadata["sandbox_runs"]) == 1
        assert (
            metadata["sandbox_runs"][0]["plan_content_hash"] == phase.command_plans[0].content_hash
        )
        blocked = await executor.execute(
            contract.execution_plan.phase(WebExecutionPhase.BUILD), contract=contract
        )
        assert blocked.status.value == "POLICY_BLOCKED"
        assert blocked.failure_code == "WEB_PHASE_SESSION_ALREADY_FINISHED"
        assert tuple(runtimes[0].commands) == expected_commands
        final = await executor.finalize()
        assert final.status.value == "PASSED"
        assert runtimes[0].close_count == 1
        assert not runtimes[0].workspace.exists()

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["missing", "different_path"])
def test_bound_contract_cannot_remove_or_replace_canonical_health_checks(tmp_path, change):
    executor, contract, _, runtimes, _ = executor_for_fixture(tmp_path, "web-vue-js-valid")
    checks = (
        ()
        if change == "missing"
        else (replace(contract.health_checks[0], path="/different-health-target"),)
    )
    forged = replace(contract, health_checks=checks)
    executor.contract = forged
    result = asyncio.run(
        executor.execute(forged.execution_plan.phase(WebExecutionPhase.VALIDATE), contract=forged)
    )
    assert result.status.value == "POLICY_BLOCKED"
    assert result.failure_code == "WEB_HEALTH_CONTRACT_MISMATCH"
    assert not result.stdout_refs and not result.stderr_refs and not result.exit_codes
    assert not runtimes
    assert not (tmp_path / "phases").exists()


@pytest.mark.parametrize(
    "command_failed", [False, True], ids=["artifact_only", "command_and_artifact"]
)
def test_artifact_rejection_preserves_observed_streams_exit_and_command_failure(
    tmp_path, monkeypatch, command_failed
):
    async def scenario():
        executor, contract, store, runtimes, _ = executor_for_fixture(
            tmp_path,
            "web-vue-js-valid",
            fail_command_id="root.test" if command_failed else None,
        )
        for name in (
            WebExecutionPhase.VALIDATE,
            WebExecutionPhase.SETUP,
            WebExecutionPhase.STATIC_CHECK,
            WebExecutionPhase.BUILD,
        ):
            result = await executor.execute(contract.execution_plan.phase(name), contract=contract)
            assert result.status.value == "PASSED"

        def reject_unsafe_artifacts(patterns):
            assert "reports/**" in tuple(patterns)
            assert runtimes[0].commands[-1].command_id == "root.test"
            raise WebPhaseRuntimeError("WEB_ARTIFACT_COLLECTION_FAILED")

        phase = contract.execution_plan.phase(WebExecutionPhase.TEST)
        with monkeypatch.context() as patch:
            patch.setattr(executor, "_collect", reject_unsafe_artifacts)
            result = await executor.execute(phase, contract=contract)
        assert result.status.value == ("FAILED" if command_failed else "RUNTIME_ERROR")
        assert result.failure_category.value == (
            "TEST" if command_failed else "ARTIFACT_COLLECTION"
        )
        assert result.failure_code == (
            "TEST_VITEST_V1_FAILED" if command_failed else "WEB_ARTIFACT_COLLECTION_FAILED"
        )
        assert result.exit_codes == (17 if command_failed else 0,)
        assert result.command_plan_hashes == (phase.command_plans[0].content_hash,)
        assert [persisted_bytes(ref, store) for ref in result.stdout_refs] == [
            stream_bytes("root.test", "stdout")
        ]
        assert [persisted_bytes(ref, store) for ref in result.stderr_refs] == [
            stream_bytes("root.test", "stderr")
        ]
        metadata = manifest_for(result, store)
        assert metadata["artifact_failure"] == "WEB_ARTIFACT_COLLECTION_FAILED"
        assert len(metadata["sandbox_runs"]) == 1
        assert metadata["sandbox_runs"][0]["status"] == (
            "FAILED" if command_failed else "SUCCEEDED"
        )
        final = await executor.finalize()
        assert final.status.value == "PASSED"
        assert runtimes[0].close_count == 1
        assert not runtimes[0].workspace.exists()

    asyncio.run(scenario())


@pytest.mark.parametrize("within_plan", [False, True], ids=["between_plans", "within_plan"])
@pytest.mark.parametrize("error_type", [WebPhaseRuntimeError, OSError, ValueError])
def test_pre_spawn_boundary_failure_preserves_prior_commands_without_inventing_an_exit(
    tmp_path, monkeypatch, within_plan, error_type
):
    async def scenario():
        executor, contract, store, runtimes, _ = executor_for_fixture(
            tmp_path, "web-vue-node-ts-valid"
        )
        await executor.execute(
            contract.execution_plan.phase(WebExecutionPhase.VALIDATE), contract=contract
        )
        if within_plan:
            result = await executor.execute(
                contract.execution_plan.phase(WebExecutionPhase.SETUP), contract=contract
            )
            assert result.status.value == "PASSED"
        else:
            await executor._get_runtime()
        runtime = runtimes[0]
        original = runtime.run_command
        failed_id = "backend.typescript" if within_plan else "frontend.npm-ci"
        phase = contract.execution_plan.phase(
            WebExecutionPhase.STATIC_CHECK if within_plan else WebExecutionPhase.SETUP
        )

        async def fail_before_launch(command):
            if command.command_id == failed_id:
                raise error_type(
                    "WEB_WORKING_DIRECTORY_INVALID"
                    if error_type is WebPhaseRuntimeError
                    else "private-error-path must not escape"
                )
            return await original(command)

        monkeypatch.setattr(runtime, "run_command", fail_before_launch)
        result = await executor.execute(phase, contract=contract)
        assert result.status.value == "RUNTIME_ERROR"
        assert result.failure_category.value == "RUNTIME"
        assert result.exit_codes == (0,)
        preceding = "backend.lint" if within_plan else "backend.npm-ci"
        assert stream_bytes(preceding, "stdout") in {
            persisted_bytes(ref, store) for ref in result.stdout_refs
        }
        assert result.command_plan_hashes == tuple(
            sorted(plan.content_hash for plan in phase.command_plans[: 1 if within_plan else 2])
        )
        metadata = manifest_for(result, store)
        assert "private-error-path" not in json.dumps(metadata)
        commands = [
            command for run in metadata["sandbox_runs"] for command in run["command_evidence"]
        ]
        assert [command["command_id"] for command in commands] == [preceding, failed_id]
        assert commands[-1]["exit_code"] is None
        assert commands[-1]["status"] == "RUNTIME_ERROR"
        assert metadata["runtime_failures"][-1]["command_result_observed"] is False
        assert metadata["runtime_failures"][-1]["command_id"] == failed_id
        await executor.finalize()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "command_observed", [False, True], ids=["docker_preflight", "command_cleanup"]
)
def test_runtime_failure_separates_docker_diagnostics_from_observed_command_exit(
    tmp_path, monkeypatch, command_observed
):
    async def scenario():
        executor, contract, store, runtimes, _ = executor_for_fixture(tmp_path, "web-vue-js-valid")
        for name in (
            WebExecutionPhase.VALIDATE,
            WebExecutionPhase.SETUP,
            WebExecutionPhase.STATIC_CHECK,
            WebExecutionPhase.BUILD,
        ):
            result = await executor.execute(contract.execution_plan.phase(name), contract=contract)
            assert result.status.value == "PASSED"
        runtime = runtimes[0]
        original = runtime.run_command

        async def runtime_error(command):
            diagnostic = HostProcessResult(
                HostProcessStatus.COMPLETED,
                1,
                b"docker diagnostic stdout",
                b"docker operation failed",
                None,
            )
            error = WebPhaseRuntimeError("WEB_CONTAINER_CLEANUP_UNCONFIRMED", result=diagnostic)
            if command_observed:
                error.command_result = await original(command)
            raise error

        monkeypatch.setattr(runtime, "run_command", runtime_error)
        result = await executor.execute(
            contract.execution_plan.phase(WebExecutionPhase.TEST), contract=contract
        )
        assert result.status.value == "RUNTIME_ERROR"
        assert result.failure_category.value == "RUNTIME"
        assert result.failure_code == "SANDBOX_RUNTIME_ERROR"
        assert result.exit_codes == ((0,) if command_observed else ())
        metadata = manifest_for(result, store)
        command = metadata["sandbox_runs"][0]["command_evidence"][0]
        assert command["status"] == ("SUCCEEDED" if command_observed else "RUNTIME_ERROR")
        failure = metadata["runtime_failures"][0]
        assert failure["command_result_observed"] is command_observed
        diagnostic = failure["transport_observation"]
        assert diagnostic["exit_code"] == 1
        assert store.read(diagnostic["stderr_ref"]["storage_key"]) == b"docker operation failed"
        if command_observed:
            assert stream_bytes("root.test", "stdout") in {
                persisted_bytes(ref, store) for ref in result.stdout_refs
            }
        await executor.finalize()

    asyncio.run(scenario())


def test_identical_artifact_bytes_keep_both_paths_in_phase_and_final_inventory(
    tmp_path, monkeypatch
):
    async def scenario():
        executor, contract, store, runtimes, _ = executor_for_fixture(tmp_path, "web-vue-js-valid")
        for name in (
            WebExecutionPhase.VALIDATE,
            WebExecutionPhase.SETUP,
            WebExecutionPhase.STATIC_CHECK,
            WebExecutionPhase.BUILD,
        ):
            result = await executor.execute(contract.execution_plan.phase(name), contract=contract)
            assert result.status.value == "PASSED"
        runtime = runtimes[0]
        original = runtime.run_command

        async def create_duplicate_report(command):
            observed = await original(command)
            report = runtime.workspace / "reports/root.test.json"
            (runtime.workspace / "reports/copy.json").write_bytes(report.read_bytes())
            return observed

        monkeypatch.setattr(runtime, "run_command", create_duplicate_report)
        result = await executor.execute(
            contract.execution_plan.phase(WebExecutionPhase.TEST), contract=contract
        )
        final = await executor.finalize()
        for phase_result in (result, final):
            inventory = manifest_for(phase_result, store)["generated_artifacts"]
            assert {item["normalized_path"] for item in inventory} == {
                "reports/root.test.json",
                "reports/copy.json",
            }
            assert len(inventory) == 2
            assert inventory[0]["reference"] == inventory[1]["reference"]
            reference = inventory[0]["reference"]
            assert store.read(reference["storage_key"]) == runtime.reports["reports/root.test.json"]

    asyncio.run(scenario())


def test_running_server_state_cannot_claim_a_terminal_exit(tmp_path, monkeypatch):
    async def scenario():
        executor, contract, store, runtimes, _ = executor_for_fixture(tmp_path, "web-vue-js-valid")
        for name in tuple(WebExecutionPhase):
            if name is WebExecutionPhase.HEALTH_CHECK:
                break
            result = await executor.execute(contract.execution_plan.phase(name), contract=contract)
            assert result.status.value in {"PASSED", "SKIPPED"}
        runtime = runtimes[0]
        original = runtime.stop_servers

        async def unconfirmed_stop():
            rows = await original()
            for row in rows:
                row["state"] = {**row["state"], "Running": True, "ExitCode": 0}
            return rows

        monkeypatch.setattr(runtime, "stop_servers", unconfirmed_stop)
        result = await executor.finalize()
        assert result.is_failure
        observed = manifest_for(result, store)["observations"]["processes"][0]
        assert observed["exit_code"] is None
        assert observed["application_exit_observed"] is False
        assert store.read(observed["stdout_ref"]["storage_key"])

    asyncio.run(scenario())


def test_local_runtime_keeps_command_and_cleanup_process_observations_separate(tmp_path):
    application = HostProcessResult(
        HostProcessStatus.COMPLETED, 0, b"application", b"app stderr", None
    )
    cleanup = HostProcessResult(HostProcessStatus.COMPLETED, 1, b"docker", b"cleanup failed", None)

    class CleanupFailureHost(Host):
        fail_cleanup = True

        async def run(self, argv, **kwargs):
            if "run" in argv:
                await super().run(argv, **kwargs)
                return application
            if "rm" in argv and self.fail_cleanup:
                return cleanup
            return await super().run(argv, **kwargs)

    async def scenario():
        host = CleanupFailureHost()
        adapter = local_runtime(tmp_path, host)
        try:
            with pytest.raises(WebPhaseRuntimeError) as raised:
                await adapter.run_command(static_command())
            assert raised.value.command_result is application
            assert raised.value.result is cleanup
        finally:
            host.fail_cleanup = False
            await adapter.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("boundary", ["runtime_open", "container_start", "application_exit"])
def test_startup_records_only_an_observed_application_exit(tmp_path, monkeypatch, boundary):
    async def scenario():
        executor, contract, store, runtimes, _ = executor_for_fixture(tmp_path, "web-vue-js-valid")
        for name in (
            WebExecutionPhase.VALIDATE,
            WebExecutionPhase.SETUP,
            WebExecutionPhase.STATIC_CHECK,
            WebExecutionPhase.BUILD,
            WebExecutionPhase.TEST,
        ):
            result = await executor.execute(contract.execution_plan.phase(name), contract=contract)
            assert result.status.value == "PASSED"
        observed = boundary == "application_exit"

        async def fail_startup(*_args):
            raise WebPhaseRuntimeError(
                "WEB_SERVER_DID_NOT_START" if observed else "WEB_DOCKER_OPERATION_FAILED",
                result=HostProcessResult(
                    HostProcessStatus.COMPLETED, 1, b"docker", b"diagnostic", None
                ),
                command_result=HostProcessResult(
                    HostProcessStatus.COMPLETED, 23, b"boot output", b"startup error", None
                )
                if observed
                else None,
            )

        runtime = runtimes[0]
        monkeypatch.setattr(
            runtime, "open" if boundary == "runtime_open" else "start_command", fail_startup
        )
        phase = contract.execution_plan.phase(WebExecutionPhase.RUN)
        result = await executor.execute(phase, contract=contract)
        assert result.status.value == "RUNTIME_ERROR"
        assert result.failure_category.value == "RUNTIME"
        assert result.exit_codes == ((23,) if observed else ())
        assert [persisted_bytes(ref, store) for ref in result.stdout_refs] == [
            b"boot output" if observed else b""
        ]
        assert result.command_plan_hashes == (
            () if boundary == "runtime_open" else (phase.command_plans[0].content_hash,)
        )
        failure = manifest_for(result, store)["observations"]["runtime_failures"][0]
        assert failure["command_result_observed"] is observed
        assert failure["transport_observation"]["exit_code"] == 1
        await executor.finalize()

    asyncio.run(scenario())
