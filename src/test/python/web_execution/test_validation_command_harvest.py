"""Exercise the operator harvest path against complete adapter receipts and real CAS.

The transport/CI/contract receipts are explicit test fixtures, not platform evidence.
"""

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from orchestwin.sandbox.evidence_store import FileSystemSandboxEvidenceStore
from orchestwin.sandbox.execution_policy import SandboxResourceLimits
from orchestwin.web_execution.validation_ci import CiVerificationStatus
from orchestwin.web_execution.validation_command import harvest, store_bytes
from orchestwin.web_execution.validation_harvest import verify_validation_harvest
from src.test.python.web_execution.test_validation_harvest import (
    complete_campaign as complete_campaign,
)


@pytest.mark.parametrize("ci_passed", (True, False))
def test_harvest_writes_complete_inspectable_manifest(
    complete_campaign, monkeypatch, tmp_path, ci_passed
):
    objects, request, read = complete_campaign
    retained = dict(objects.values)

    def capture(reference):
        body = read(reference)
        retained[reference.storage_key] = body
        return body

    verify_validation_harvest(request, read_artifact=capture)
    root = tmp_path / "bootstrap"
    root.mkdir()
    manifest = json.loads(objects.read(request.bootstrap_manifest_ref))
    (root / "manifest.json").write_bytes(objects.read(request.bootstrap_manifest_ref))
    for item in manifest["artifacts"]:
        (root / item["path"]).write_bytes(
            objects.values[f"sha256/{item['sha256'][:2]}/{item['sha256']}"]
        )
    evidence_root = tmp_path / "objects"
    store = FileSystemSandboxEvidenceStore(evidence_root)
    for body in retained.values():
        store_bytes(store, body)
    identities = {item.kind: item for item in request.runner_identities}
    monkeypatch.setattr(
        "orchestwin.web_execution.validation_command.load_phase_runner_identity",
        lambda *args, kind, **kwargs: identities[kind],
    )
    monkeypatch.setattr(
        "orchestwin.web_execution.validation_command.contract_receipt",
        AsyncMock(return_value=request.contract_tests),
    )
    ci = (
        request.ci_observation
        if ci_passed
        else replace(
            request.ci_observation,
            status=CiVerificationStatus.INCOMPLETE,
            issue_codes=("CI_TEST_PENDING",),
        )
    )
    monkeypatch.setattr(
        "orchestwin.web_execution.validation_command.GitHubCiVerifier",
        lambda *args, **kwargs: SimpleNamespace(verify=lambda: ci),
    )
    fixtures = {}
    for item in request.fixtures:
        fixtures[item.fixture_id] = SimpleNamespace(
            fixture_id=item.fixture_id,
            profile_id=item.profile_id,
            profile_version=item.profile_version,
            selection=SimpleNamespace(language_configuration=item.language_configuration),
            source_tree_hash=lambda *, defective=False, fixture=item: (
                fixture.failure_source_tree_hash if defective else fixture.valid_source_tree_hash
            ),
            expected_failure_phase=item.failure_phase,
            fixture_bundle_hash=item.fixture_bundle_hash,
            expected_failure_marker=item.expected_failure_marker,
        )
    cases, states, receipts, repairs = [], {}, {}, {}
    for journey in request.journeys:
        for role in ("valid", "repeated", "failed"):
            observed = getattr(journey, role)
            operations = [observed.operation]
            receipts[observed.attempt.id] = observed
            if role == "failed":
                operations += [journey.repair_operation, journey.rerun.operation]
                receipts[journey.rerun.attempt.id] = journey.rerun
                repairs[journey.repair_operation.id] = (
                    journey.repair_operation,
                    journey.repair_gate,
                    journey.repair_approval_event,
                )
            row = {
                "fixture_id": journey.fixture_id,
                "role": role,
                "project_id": str(observed.source.project_id),
            }
            cases.append(row)
            states[row["project_id"]] = (
                {
                    "owner_user_id": observed.source.created_by_user_id,
                    "project_id": observed.source.project_id,
                },
                (),
                operations,
            )
    governance = SimpleNamespace(
        harvest_attempt=AsyncMock(side_effect=lambda *, attempt_id, **kwargs: receipts[attempt_id]),
        harvest_repair=AsyncMock(
            side_effect=lambda *, operation_id, **kwargs: repairs[operation_id]
        ),
    )
    campaign = SimpleNamespace(
        guard=lambda: None,
        fixtures=fixtures,
        governance=governance,
        plan={"cases": cases, "platform_commit": request.platform_commit, "content_hash": "a" * 64},
        _state=AsyncMock(side_effect=lambda row: states[row["project_id"]]),
    )
    directory = tmp_path / "campaign"
    result = asyncio.run(
        harvest(
            campaign,
            config={"evidence_root": str(evidence_root), "github_repository": ci.repository},
            runtime=SimpleNamespace(repo_root=tmp_path, runner_manifest=root / "manifest.json"),
            resources=SandboxResourceLimits(2, 4096, 256, 512),
            sessions=None,
            directory=directory,
            publish=False,
        )
    )
    output = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert result["status"] == ("ELIGIBLE" if ci_passed else "INCOMPLETE")
    assert result["published"] is False
    assert output["published"] is False
    assert len(output["evidence"]) == (52 if ci_passed else 47)
    assert len(output["promotion_decisions"]) == 5
    assert all(
        row["status"] == ("ELIGIBLE" if ci_passed else "INCOMPLETE")
        for row in output["promotion_decisions"]
    )
    for reference in output["artifacts"]:
        assert store.read(reference["storage_key"]) is not None
