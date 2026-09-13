"""Workflow journeys using the JVM adapter with deterministic transport observations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from orchestwin.artifacts.jvm_sources import (
    JvmSourceFileEntry,
    JvmSourceOrigin,
    JvmSourceProvenanceKind,
    JvmSourceProvenanceReference,
    create_jvm_source_revision,
)
from orchestwin.jvm_execution import phase_executor, workspaces
from orchestwin.jvm_execution.attempt_persistence import InMemoryJvmExecutionAttemptRepository
from orchestwin.jvm_execution.attempts import JvmExecutionAttemptTrigger
from orchestwin.jvm_execution.dependency_setup import JVM_SETUP_POLICY_HASH, ControlledJvmNetwork
from orchestwin.jvm_execution.detection import JvmDetectionSnapshot, JvmTextFile
from orchestwin.jvm_execution.evidence import JvmExecutionReportStatus, JvmPhaseResultStatus
from orchestwin.jvm_execution.phase_executor import GovernedJvmPhaseExecutor
from orchestwin.jvm_execution.phase_runtime import JvmContainerPhaseObservation
from orchestwin.jvm_execution.plans import JvmExecutionPhase
from orchestwin.jvm_execution.profile_registry import create_sprint09_jvm_profile_registry
from orchestwin.jvm_execution.targets import jvm_scope_for
from orchestwin.sandbox.docker_runtime import HostProcessResult, HostProcessStatus
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.sandbox.fake_container import InMemorySandboxEvidenceStore
from orchestwin.workflow.jvm_execution import (
    JvmExecutionPurpose,
    JvmExecutionRequest,
    LocalGovernedJvmExecutionService,
)

from .profile_support import declaration_for, runner_for
from .test_workflow import authorized

PROJECT, OWNER = UUID(int=301), UUID(int=302)
NETWORK = ControlledJvmNetwork(
    "owjvmdep-" + "a" * 32 + "-internal", "b" * 64, JVM_SETUP_POLICY_HASH
)
FIXTURES = Path(__file__).parents[2] / "fixtures/jvm_execution"


def inputs(tmp_path, target):
    fixture = {
        ExecutionTarget.JVM_JAVA: "jvm-java-greeting",
        ExecutionTarget.JVM_KOTLIN: "jvm-kotlin-calculator",
        ExecutionTarget.JVM_SCALA: "jvm-scala-greeting",
    }[target]
    root = FIXTURES / fixture
    paths = json.loads((root / "fixture.json").read_text())["source_paths"]
    source = tmp_path / "source"
    source.mkdir()
    entries, texts = [], []
    for relative in paths:
        content = (root / relative).read_bytes()
        destination = source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        entries.append(
            JvmSourceFileEntry(
                relative, digest, len(content), f"sha256/{digest}", "application/octet-stream"
            )
        )
        try:
            decoded = content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        texts.append(JvmTextFile(relative, decoded, digest))
    revision = create_jvm_source_revision(
        revision_id=uuid4(),
        project_id=PROJECT,
        created_by_user_id=OWNER,
        version_number=1,
        based_on=None,
        target=target,
        origin=JvmSourceOrigin.DETERMINISTIC_FIXTURE,
        files=tuple(entries),
        provenance_references=(
            JvmSourceProvenanceReference(
                JvmSourceProvenanceKind.SOURCE_PLAN, "source-plan:fixture", 1, "a" * 64
            ),
        ),
        created_at=datetime.now(UTC),
    )
    snapshot = JvmDetectionSnapshot("a" * 64, tuple(paths), tuple(texts))
    runner = runner_for(target)
    registry = create_sprint09_jvm_profile_registry()
    scope = jvm_scope_for(target)
    contract = registry.find(scope.profile_id, scope.profile_version).create_contract(
        snapshot,
        declaration_for(target),
        source_revision=revision.reference,
        runner=runner,
    )
    request = authorized(
        JvmExecutionRequest(
            PROJECT,
            OWNER,
            revision.reference,
            snapshot,
            declaration_for(target),
            scope.profile_id,
            scope.profile_version,
            runner,
            runner.execution_policy.content_hash,
            JvmExecutionPurpose.PROFILE_VALIDATION,
            JvmExecutionAttemptTrigger.PROFILE_VALIDATION,
            None,
        )
    )
    return source, revision, snapshot, contract, request


class Runtime:
    mode = "pass"

    def __init__(self, **arguments):
        self.args = arguments
        self.workspace = arguments["workspace"]
        self.closed = False
        self.calls = []

    async def run_phase(self, phase):
        self.calls.append(phase)
        if self.mode == "exception":
            raise RuntimeError("transport interrupted")
        if self.mode == "cancel":
            raise asyncio.CancelledError()
        scala = self.args["execution_plan"].target_selection.target is ExecutionTarget.JVM_SCALA
        if phase is JvmExecutionPhase.BUILD and self.mode not in {
            "no-jar",
            "compile-a",
            "compile-b",
        }:
            jar = self.workspace / (
                "target/scala-3.3.8/example.jar" if scala else "build/libs/example.jar"
            )
            jar.parent.mkdir(parents=True, exist_ok=True)
            jar.write_bytes(b"test artifact")
        if phase is JvmExecutionPhase.TEST and self.mode != "no-tests":
            xml = self.workspace / (
                "target/test-reports/TEST-example.xml"
                if scala
                else "build/test-results/test/TEST-example.xml"
            )
            xml.parent.mkdir(parents=True, exist_ok=True)
            child = (
                '<failure message="wrong sum">wrong sum</failure>'
                if self.mode == "failed-test"
                else ""
            )
            xml.write_text(
                f'<testsuite name="example"><testcase name="addition" classname="example">{child}</testcase></testsuite>'
            )
        status, code, oom = HostProcessStatus.COMPLETED, 0, False
        if self.mode == "timeout":
            status, code = HostProcessStatus.TIMED_OUT, None
        if self.mode == "oom":
            oom = True
        if self.mode == "command-failure":
            code = 1
        stderr = b"observed stderr"
        if phase is JvmExecutionPhase.BUILD and self.mode in {"compile-a", "compile-b"}:
            code = 1
            stderr = (
                f"src/main/kotlin/Main.kt:1:1: error: unresolved reference {self.mode}".encode()
            )
        now = datetime.now(UTC)
        process = HostProcessResult(
            status,
            code,
            b"observed stdout",
            stderr,
            None if code is not None else "Timed out.",
        )
        return JvmContainerPhaseObservation(
            self.args["attempt_id"],
            phase,
            self.args["execution_plan"].phase(phase).command_plan.content_hash,
            "sha256:" + self.args["runner_contract"].image.digest,
            "c" * 64,
            NETWORK.network_id if phase is JvmExecutionPhase.SETUP else "none",
            "d" * 64 if phase is JvmExecutionPhase.SETUP else None,
            process,
            now,
            now,
            code,
            oom,
            True,
        )

    async def close(self):
        if self.mode == "cleanup-failure":
            raise RuntimeError("cleanup unconfirmed")
        self.closed = True


@pytest.fixture(autouse=True)
def controlled_adapters(monkeypatch):
    monkeypatch.setattr(workspaces, "require_jvm_workspace_owner", lambda: None)
    monkeypatch.setattr(phase_executor, "require_jvm_workspace_owner", lambda: None)
    monkeypatch.setattr(workspaces, "seed_gradle_wrapper_cache", lambda **kwargs: None)

    async def network(*args, **kwargs):
        return NETWORK

    monkeypatch.setattr(phase_executor, "verify_dependency_network", network)


def application(tmp_path, *, target=ExecutionTarget.JVM_KOTLIN, mode="pass"):
    source, revision, snapshot, contract, request = inputs(tmp_path, target)
    store = InMemorySandboxEvidenceStore()
    instances = []

    def factory(**kwargs):
        instance = Runtime(**kwargs)
        instance.mode = mode
        instances.append(instance)
        return instance

    adapter = GovernedJvmPhaseExecutor(
        contract=contract,
        source_revision=revision,
        snapshot=snapshot,
        source_path=source,
        workspaces_root=tmp_path / "attempts",
        evidence_store=store,
        docker_context="desktop-linux",
        distribution_path=tmp_path / "distribution.zip",
        runtime_factory=factory,
        dependency_network_manifest=tmp_path / "network.json",
        dependency_network_manifest_hash="d" * 64,
    )
    attempts = InMemoryJvmExecutionAttemptRepository(
        owner_user_id=OWNER, project_ids=frozenset({PROJECT})
    )
    app = LocalGovernedJvmExecutionService(
        registry=create_sprint09_jvm_profile_registry(),
        attempts=attempts,
        phase_executor=adapter,
        lifecycle=adapter,
        clock=SimpleNamespace(now=lambda: datetime.now(UTC)),
        ids=SimpleNamespace(new_id=uuid4),
    )
    return SimpleNamespace(
        adapter=adapter,
        store=store,
        instances=instances,
        attempts=attempts,
        app=app,
        request=request,
    )


@pytest.mark.parametrize(
    "target", [ExecutionTarget.JVM_JAVA, ExecutionTarget.JVM_KOTLIN, ExecutionTarget.JVM_SCALA]
)
def test_workflow_records_all_phases_and_keeps_evidence_after_workspace_cleanup(tmp_path, target):
    case = application(tmp_path, target=target)
    result = asyncio.run(case.app.execute(case.request))
    assert result.attempt.report.status is JvmExecutionReportStatus.PASSED
    assert result.attempt.id == case.adapter.attempt_id
    assert case.instances[0].calls == list(JvmExecutionPhase)
    assert case.instances[0].closed and not case.instances[0].workspace.exists()
    assert case.adapter.source_path.is_dir()
    assert asyncio.run(case.attempts.current(project_id=PROJECT)) == result.attempt
    for phase in result.attempt.report.phase_results:
        assert case.store.read(phase.stdout_refs[0].storage_key) == b"observed stdout"
        assert phase.artifact_refs
        for reference in (*phase.stdout_refs, *phase.stderr_refs, *phase.artifact_refs):
            data = case.store.read(reference.storage_key)
            assert hashlib.sha256(data).hexdigest() == reference.sha256_digest
    receipt = json.loads(case.store.read(case.adapter.finalization_reference.storage_key))
    assert receipt["workspace_removed"] and receipt["containers_removed"]
    assert receipt["level_d_validated"] is False


@pytest.mark.parametrize(
    ("mode", "phase", "status"),
    [
        ("no-jar", JvmExecutionPhase.BUILD, JvmPhaseResultStatus.RUNTIME_ERROR),
        ("no-tests", JvmExecutionPhase.TEST, JvmPhaseResultStatus.RUNTIME_ERROR),
        ("failed-test", JvmExecutionPhase.TEST, JvmPhaseResultStatus.FAILED),
        ("command-failure", JvmExecutionPhase.VALIDATE, JvmPhaseResultStatus.FAILED),
        ("timeout", JvmExecutionPhase.VALIDATE, JvmPhaseResultStatus.TIMED_OUT),
        ("oom", JvmExecutionPhase.VALIDATE, JvmPhaseResultStatus.RESOURCE_LIMIT_EXCEEDED),
    ],
)
def test_failures_never_become_passing_or_execute_later_commands(tmp_path, mode, phase, status):
    case = application(tmp_path, mode=mode)
    result = asyncio.run(case.app.execute(case.request))
    assert result.attempt.report.status is JvmExecutionReportStatus.FAILED
    index = tuple(JvmExecutionPhase).index(phase)
    assert result.attempt.report.phase_results[index].status is status
    assert case.instances[0].calls == list(JvmExecutionPhase)[: index + 1]
    assert all(
        item.status is JvmPhaseResultStatus.NOT_RUN
        for item in result.attempt.report.phase_results[index + 1 :]
    )
    assert not case.instances[0].workspace.exists()


@pytest.mark.parametrize("mode", ["exception", "cancel", "cleanup-failure"])
def test_unconfirmed_execution_or_cleanup_never_persists_a_completed_attempt(tmp_path, mode):
    case = application(tmp_path, mode=mode)
    with pytest.raises(asyncio.CancelledError if mode == "cancel" else RuntimeError):
        asyncio.run(case.app.execute(case.request))
    assert asyncio.run(case.attempts.current(project_id=PROJECT)) is None
    if mode == "cleanup-failure":
        assert case.instances[0].workspace.exists()
        case.instances[0].mode = "pass"
        asyncio.run(case.adapter.finalize())
    assert not case.instances[0].workspace.exists()


def test_missing_authorization_allocates_no_workspace_or_runtime(tmp_path):
    case = application(tmp_path)
    asyncio.run(case.app.execute(replace(case.request, authorization=None)))
    assert not case.instances
    assert not case.adapter.root.exists()
    assert not case.store.content


def test_partial_rerun_is_rejected_before_allocation(tmp_path):
    case = application(tmp_path)
    with pytest.raises(ValueError, match="FRESH_CACHE"):
        case.adapter.bind_attempt(
            uuid4(), contract=case.adapter.contract, phases_to_execute=(JvmExecutionPhase.TEST,)
        )
    assert case.adapter.attempt_id is None and not case.adapter.root.exists()


@pytest.mark.parametrize("change", ["source", "extra-file", "extra-directory"])
def test_source_drift_prevents_runtime_allocation(tmp_path, change):
    case = application(tmp_path)
    if change == "source":
        (case.adapter.source_path / "build.gradle.kts").write_text("changed")
    elif change == "extra-file":
        (case.adapter.source_path / "unexpected.txt").write_text("extra")
    else:
        (case.adapter.source_path / "build").mkdir()
    with pytest.raises(ValueError):
        asyncio.run(case.app.execute(case.request))
    assert not case.instances
    assert not case.adapter.root.exists()


def test_workspace_cleanup_refuses_a_replaced_parent(tmp_path):
    case = application(tmp_path)
    owned = workspaces.prepare_jvm_phase_workspace(
        revision=case.adapter.revision,
        snapshot=case.adapter.snapshot,
        source_path=case.adapter.source_path,
        workspaces_root=case.adapter.root,
        attempt_id=uuid4(),
        distribution_path=tmp_path / "zip",
    )
    replacement = owned.parent.with_name(owned.parent.name + "-original")
    owned.parent.rename(replacement)
    owned.path.mkdir(parents=True)
    sentinel = owned.path / "keep.txt"
    sentinel.write_text("unrelated")
    with pytest.raises(ValueError, match="OWNERSHIP"):
        owned.close()
    assert sentinel.read_text() == "unrelated"


def test_distinct_compiler_errors_keep_distinct_repair_signatures_without_jars(tmp_path):
    signatures = []
    for mode in ("compile-a", "compile-b"):
        root = tmp_path / mode
        root.mkdir()
        case = application(root, mode=mode)
        result = asyncio.run(case.app.execute(case.request))
        build = result.attempt.report.phase_results[3]
        assert build.status is JvmPhaseResultStatus.FAILED
        assert build.findings and mode in build.normalized_summary
        assert build.failure_code == "KT_COMPILATION_ERROR"
        signatures.append(result.attempt.report.failure_signatures[0].signature)
    assert signatures[0] != signatures[1]


@pytest.mark.parametrize("field", ["attempt_id", "network_id", "cleanup_confirmed"])
def test_foreign_or_unconfirmed_observation_cannot_be_recorded(tmp_path, field):
    case = application(tmp_path)
    factory = case.adapter.runtime_factory

    def mismatched(**kwargs):
        runtime = factory(**kwargs)
        execute = runtime.run_phase

        async def observe(phase):
            result = await execute(phase)
            value = {"attempt_id": uuid4(), "network_id": "foreign", "cleanup_confirmed": False}
            return replace(result, **{field: value[field]})

        runtime.run_phase = observe
        return runtime

    case.adapter.runtime_factory = mismatched
    with pytest.raises(ValueError, match="OBSERVATION_BINDING"):
        asyncio.run(case.app.execute(case.request))
    assert asyncio.run(case.attempts.current(project_id=PROJECT)) is None
    assert case.instances[0].closed and not case.instances[0].workspace.exists()


def test_snapshot_text_must_match_the_verified_source(tmp_path):
    case = application(tmp_path)
    snapshot = case.adapter.snapshot
    changed = snapshot.text_files[0].content + "\n// another source snapshot\n"
    case.adapter.snapshot = replace(
        snapshot,
        text_files=(
            replace(
                snapshot.text_files[0],
                content=changed,
                sha256_digest=hashlib.sha256(changed.encode()).hexdigest(),
            ),
            *snapshot.text_files[1:],
        ),
    )
    with pytest.raises(ValueError, match="SNAPSHOT_TEXT_MISMATCH"):
        asyncio.run(case.app.execute(case.request))
    assert not case.instances and not case.adapter.root.exists()


def test_owned_workspace_cleanup_removes_read_only_generated_files(tmp_path):
    case = application(tmp_path)
    owned = workspaces.prepare_jvm_phase_workspace(
        revision=case.adapter.revision,
        snapshot=case.adapter.snapshot,
        source_path=case.adapter.source_path,
        workspaces_root=case.adapter.root,
        attempt_id=uuid4(),
        distribution_path=tmp_path / "zip",
    )
    generated = owned.path / "build/cache/locked.bin"
    generated.parent.mkdir(parents=True)
    generated.write_bytes(b"generated")
    generated.chmod(stat.S_IRUSR)
    owned.close()
    assert owned.closed and not owned.parent.exists()
    assert case.adapter.source_path.is_dir()


@pytest.mark.skipif(os.name == "nt", reason="POSIX ownership applies only to the Linux controller")
def test_root_prepared_workspace_is_owned_by_the_unprivileged_runner(tmp_path):
    if os.geteuid() != 0:
        pytest.skip("Changing file ownership requires the root controller")
    case = application(tmp_path)
    owned = workspaces.prepare_jvm_phase_workspace(
        revision=case.adapter.revision,
        snapshot=case.adapter.snapshot,
        source_path=case.adapter.source_path,
        workspaces_root=case.adapter.root,
        attempt_id=uuid4(),
        distribution_path=tmp_path / "zip",
    )
    try:
        assert owned.parent.stat().st_uid == 0
        assert stat.S_IMODE(owned.parent.stat().st_mode) == 0o700
        for path in (owned.path, *owned.path.rglob("*")):
            assert path.stat().st_uid == 65532
            assert path.stat().st_gid == 65532
        assert (case.adapter.source_path / "build.gradle.kts").stat().st_uid == 0
    finally:
        owned.close()
