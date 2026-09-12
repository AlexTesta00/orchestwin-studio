"""Opt-in development integration; never profile promotion or a formal attempt."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from orchestwin.artifacts.web_sources import (
    WebSourceFileEntry,
    WebSourceOrigin,
    WebSourceProvenanceKind,
    WebSourceProvenanceReference,
    create_web_source_revision,
)
from orchestwin.sandbox.evidence_store import FileSystemSandboxEvidenceStore
from orchestwin.sandbox.execution_policy import (
    DEFAULT_SANDBOX_EXECUTION_POLICY,
    DEFAULT_SANDBOX_RESOURCE_LIMITS,
)
from orchestwin.web_execution.detection import detect_web_project
from orchestwin.web_execution.lockfiles import validate_web_dependency_locks
from orchestwin.web_execution.phase_executor import GovernedWebPhaseExecutor
from orchestwin.web_execution.phase_runner import load_phase_runner_identity
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.profile_contracts import WebProfileRunnerSet
from orchestwin.web_execution.profile_registry import create_sprint08_web_profile_registry
from orchestwin.web_execution.workspaces import materialize_web_source_snapshot

from .test_profile_fixture_matrix import detection_snapshot, fixture_files

MANIFEST = os.environ.get("ORCHESTWIN_WEB_PHASE_TEST_BOOTSTRAP_MANIFEST")
pytestmark = pytest.mark.skipif(
    not MANIFEST, reason="explicit Web runner Docker integration is disabled"
)


def test_real_static_phases_preserve_source_health_logs_and_cleanup(tmp_path: Path):
    async def scenario():
        repository = Path(__file__).parents[4]
        manifest_path = Path(MANIFEST)
        identity = load_phase_runner_identity(manifest_path, repo_root=repository, kind="NODE")
        manifest = json.loads(manifest_path.read_bytes())
        browser = next(
            row["image_id"].removeprefix("sha256:")
            for row in manifest["runners"]
            if row["kind"] == "BROWSER"
        )
        files = fixture_files("web-static-js-valid")
        snapshot = detection_snapshot(files)
        selection = detect_web_project(snapshot).selected.selection
        lock = validate_web_dependency_locks(snapshot, selection=selection)
        source_store = FileSystemSandboxEvidenceStore(tmp_path / "sources")
        source_files = []
        for path, text in sorted(files.items()):
            entry = source_store.store_artifact(
                run_id=uuid4(),
                command_id="fixture.import",
                normalized_path=path,
                content=text.encode(),
                media_type="text/plain",
            )
            source_files.append(
                WebSourceFileEntry(
                    path, entry.sha256_digest, entry.size_bytes, entry.storage_key, entry.media_type
                )
            )
        provenance = hashlib.sha256(
            json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        revision = create_web_source_revision(
            revision_id=uuid4(),
            project_id=uuid4(),
            created_by_user_id=uuid4(),
            version_number=1,
            based_on=None,
            target=selection.target,
            language_configuration=selection.language_configuration,
            layout=selection.layout,
            origin=WebSourceOrigin.DETERMINISTIC_FIXTURE,
            files=tuple(source_files),
            provenance_references=(
                WebSourceProvenanceReference(
                    WebSourceProvenanceKind.SOURCE_PLAN, "unit5.static.fixture", 1, provenance
                ),
            ),
            created_at=datetime.now(UTC),
        )
        prepared = materialize_web_source_snapshot(
            revision.to_snapshot(),
            content_root=tmp_path / "sources",
            workspaces_root=tmp_path / "prepared",
        )
        profile = create_sprint08_web_profile_registry().find("web.static", "1.0.0")
        contract = profile.create_contract(
            snapshot,
            selection=selection,
            lock_report=lock,
            source_revision_content_hash=revision.content_hash,
            source_tree_hash=revision.source_tree_hash,
            runners=WebProfileRunnerSet(identity.image_id.removeprefix("sha256:"), browser),
        )
        store = FileSystemSandboxEvidenceStore(tmp_path / "evidence")
        executor = GovernedWebPhaseExecutor(
            contract=contract,
            prepared_workspace=prepared,
            snapshot=snapshot,
            lock_report=lock,
            runner_identity=identity,
            execution_policy=DEFAULT_SANDBOX_EXECUTION_POLICY,
            resources=DEFAULT_SANDBOX_RESOURCE_LIMITS,
            workspaces_root=tmp_path / "mutable",
            evidence_store=store,
            docker_context=manifest["environment"]["docker_context"],
        )
        results = []
        try:
            for phase in contract.execution_plan.phases:
                result = await executor.execute(phase, contract=contract)
                results.append(result)
                if phase.phase is WebExecutionPhase.BROWSER_EVIDENCE:
                    assert result.status.value == "POLICY_BLOCKED"
                    assert result.failure_code == "WEB_BROWSER_EVIDENCE_ADAPTER_UNAVAILABLE"
                    break
                assert result.status.value in {"PASSED", "SKIPPED"}, result.to_snapshot()
                if phase.phase is WebExecutionPhase.RUN:
                    isolation = await executor.runtime.invoke(
                        (
                            "node",
                            "-e",
                            'console.log(JSON.stringify({uid:process.getuid(),external:Object.values(require("node:os").networkInterfaces()).flat().filter(x=>!x.internal)}))',
                        ),
                        timeout_seconds=3,
                    )
                    assert isolation.exit_code == 0
                    assert json.loads(isolation.stdout) == {"uid": 65532, "external": []}
        finally:
            final = await executor.finalize()
            if final is not None:
                results.append(final)
            payload = {
                "purpose": "UNIT5_DEVELOPMENT_INTEGRATION",
                "formal_run_started": False,
                "level_d_validated": False,
                "source_revision": revision.to_snapshot(),
                "contract_hash": contract.content_hash,
                "bootstrap_manifest_hash": identity.bootstrap_manifest_hash,
                "phase_results": [result.to_snapshot() for result in results],
            }
            (tmp_path / "development-results.json").write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
        assert final.status.value == "PASSED", final.to_snapshot()
        final_manifest = json.loads(store.read(final.artifact_refs[0].storage_key))
        assert final_manifest["observations"]["cleanup_confirmed"] is True
        assert len(final_manifest["observations"]["processes"]) == 2
        assert all(
            row["terminated_by_controller"] for row in final_manifest["observations"]["processes"]
        )
        assert (prepared.path / "index.html").read_text() == files["index.html"]
        assert not executor.workspace.path.exists()
        for result in results:
            for ref in (*result.stdout_refs, *result.stderr_refs, *result.artifact_refs):
                data = store.read(ref.storage_key)
                assert data is not None and len(data) == ref.size_bytes
                assert hashlib.sha256(data).hexdigest() == ref.sha256_digest

    asyncio.run(scenario())
