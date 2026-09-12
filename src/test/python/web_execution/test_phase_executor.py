"""Governed phase execution binds real input bytes, plans and terminal evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from orchestwin.sandbox.evidence_store import FileSystemSandboxEvidenceStore
from orchestwin.sandbox.execution_policy import (
    DEFAULT_SANDBOX_EXECUTION_POLICY,
    DEFAULT_SANDBOX_RESOURCE_LIMITS,
)
from orchestwin.web_execution.detection import detect_web_project
from orchestwin.web_execution.lockfiles import validate_web_dependency_locks
from orchestwin.web_execution.phase_executor import GovernedWebPhaseExecutor
from orchestwin.web_execution.phase_runner import WebPhaseRunnerIdentity
from orchestwin.web_execution.phase_runtime import WebPhaseRuntimeError
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.profile_contracts import WebProfileRunnerSet
from orchestwin.web_execution.profile_registry import create_sprint08_web_profile_registry
from orchestwin.web_execution.workspaces import PreparedWebWorkspace

from .test_profile_fixture_matrix import detection_snapshot


def setup_executor(tmp_path: Path, *, files=None, runtime_factory=None):
    files = files or {"index.html": "<!doctype html><html lang='en'><body>ok</body></html>"}
    original = tmp_path / "source"
    original.mkdir()
    entries = []
    for path, text in sorted(files.items()):
        target = original / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode())
        entries.append(
            {
                "normalized_path": path,
                "sha256_digest": hashlib.sha256(text.encode()).hexdigest(),
                "size_bytes": len(text.encode()),
            }
        )
    tree = hashlib.sha256(
        json.dumps(
            {"files": entries}, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    prepared = PreparedWebWorkspace(
        original,
        "11111111-1111-4111-8111-111111111111",
        "a" * 64,
        tree,
        len(files),
        sum(row["size_bytes"] for row in entries),
    )
    snapshot = detection_snapshot(files)
    selection = detect_web_project(snapshot).selected.selection
    lock = validate_web_dependency_locks(snapshot, selection=selection)
    profile = create_sprint08_web_profile_registry().find("web.static", "1.0.0")
    contract = profile.create_contract(
        snapshot,
        selection=selection,
        lock_report=lock,
        source_revision_content_hash=prepared.source_revision_content_hash,
        source_tree_hash=tree,
        runners=WebProfileRunnerSet("b" * 64, "c" * 64),
    )
    store = FileSystemSandboxEvidenceStore(tmp_path / "evidence")
    executor = GovernedWebPhaseExecutor(
        contract=contract,
        prepared_workspace=prepared,
        snapshot=snapshot,
        lock_report=lock,
        runner_identity=WebPhaseRunnerIdentity("NODE", "sha256:" + "b" * 64, "d" * 64, "e" * 64),
        execution_policy=DEFAULT_SANDBOX_EXECUTION_POLICY,
        resources=DEFAULT_SANDBOX_RESOURCE_LIMITS,
        workspaces_root=tmp_path / "work",
        evidence_store=store,
        runtime_factory=runtime_factory,
        docker_context="local-test",
    )
    return executor, contract, store, original


def test_unrelated_phase_plan_is_blocked_before_creating_workspace_or_runtime(tmp_path):
    executor, contract, _, _ = setup_executor(
        tmp_path, runtime_factory=lambda **_: pytest.fail("runtime must not be created")
    )
    phase = contract.execution_plan.phase(WebExecutionPhase.VALIDATE)
    forged = replace(phase, adapter_action_id="arbitrary.action")
    result = asyncio.run(executor.execute(forged, contract=contract))
    assert result.status.value == "POLICY_BLOCKED"
    assert not (tmp_path / "work").exists()


def test_validation_rechecks_original_tree_and_records_bound_metadata(tmp_path):
    async def scenario():
        executor, contract, store, original = setup_executor(tmp_path)
        result = await executor.execute(
            contract.execution_plan.phase(WebExecutionPhase.VALIDATE), contract=contract
        )
        assert result.status.value == "PASSED"
        metadata = json.loads(store.read(result.artifact_refs[0].storage_key))
        assert metadata["source_tree_hash"] == contract.source_tree_hash
        assert metadata["image_id"] == "sha256:" + "b" * 64
        assert metadata["policy_hash"] == DEFAULT_SANDBOX_EXECUTION_POLICY.content_hash
        await executor.finalize()
        assert (original / "index.html").is_file()

    asyncio.run(scenario())


def test_tampered_source_is_not_executed(tmp_path):
    executor, contract, _, original = setup_executor(
        tmp_path, runtime_factory=lambda **_: pytest.fail("runtime must not be created")
    )
    (original / "index.html").write_text("changed")
    result = asyncio.run(
        executor.execute(
            contract.execution_plan.phase(WebExecutionPhase.VALIDATE), contract=contract
        )
    )
    assert result.status.value == "POLICY_BLOCKED"


def test_browser_phase_requires_the_explicit_evidence_adapter(tmp_path):
    executor, contract, _, _ = setup_executor(tmp_path)
    result = asyncio.run(
        executor.execute(
            contract.execution_plan.phase(WebExecutionPhase.BROWSER_EVIDENCE), contract=contract
        )
    )
    assert result.status.value == "POLICY_BLOCKED"
    assert not result.exit_codes and not result.stdout_refs


def test_unconfirmed_container_cleanup_preserves_its_workspace(tmp_path):
    class UnavailableRuntime:
        async def close(self):
            raise WebPhaseRuntimeError("WEB_CONTAINER_CLEANUP_UNCONFIRMED")

    async def scenario():
        executor, contract, _, _ = setup_executor(tmp_path)
        await executor.execute(
            contract.execution_plan.phase(WebExecutionPhase.VALIDATE), contract=contract
        )
        executor.runtime = UnavailableRuntime()
        try:
            result = await executor.finalize()
            assert result.is_failure
            assert result.failure_code == "WEB_CONTAINER_CLEANUP_UNCONFIRMED"
            assert executor.workspace.path.exists()
        finally:
            # This fake never created a container, so the test owns safe cleanup.
            executor.workspace.close()

    asyncio.run(scenario())
