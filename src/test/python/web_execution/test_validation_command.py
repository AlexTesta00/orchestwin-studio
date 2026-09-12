"""Operator entry point keeps campaign files and approval decisions explicit."""

import asyncio
import json
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from orchestwin.sandbox.evidence_store import FileSystemSandboxEvidenceStore
from orchestwin.web_execution.validation_campaign import CampaignError, ValidationCampaign
from orchestwin.web_execution.validation_command import (
    campaign_lock,
    contract_receipt,
    load_configuration,
    read_bytes,
    write_receipt,
)
from orchestwin.web_execution.validation_harvest import _Artifacts, _contract_tests


def test_receipts_cannot_overwrite_different_content(tmp_path):
    path = tmp_path / "receipt.json"
    write_receipt(path, {"value": 1})
    write_receipt(path, {"value": 1})
    with pytest.raises(CampaignError, match="ALREADY_EXISTS"):
        write_receipt(path, {"value": 2})
    assert json.loads(path.read_text()) == {"value": 1}


def test_campaign_lock_rejects_concurrent_run_and_releases_after_error(tmp_path):
    with pytest.raises(RuntimeError, match="body"), campaign_lock(tmp_path):
        with pytest.raises(CampaignError, match="ALREADY_ACTIVE"), campaign_lock(tmp_path):
            pytest.fail("second writer entered")
        raise RuntimeError("body")
    assert (tmp_path / "active.lock").is_file()
    with campaign_lock(tmp_path):
        assert (tmp_path / "active.lock").is_file()
    assert (tmp_path / "active.lock").read_bytes()


def test_campaign_lock_is_released_when_its_process_is_killed(tmp_path):
    child = """
import sys
from pathlib import Path
from orchestwin.web_execution.validation_command import campaign_lock
root = Path(sys.argv[1])
with campaign_lock(root):
    (root / 'lock-ready').write_text('ready', encoding='utf-8')
    sys.stdin.buffer.read(1)
"""
    process = subprocess.Popen(
        [sys.executable, "-B", "-c", child, str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 30
        while not (tmp_path / "lock-ready").exists():
            if process.poll() is not None:
                _, stderr = process.communicate(timeout=5)
                pytest.fail(f"lock test child failed: {stderr.decode(errors='replace')}")
            assert time.monotonic() < deadline, "lock child did not become ready"
            time.sleep(0.02)
        with pytest.raises(CampaignError, match="ALREADY_ACTIVE"), campaign_lock(tmp_path):
            pytest.fail("concurrent process entered the campaign")
        process.kill()
        process.wait(timeout=10)
        with campaign_lock(tmp_path):
            assert (tmp_path / "active.lock").is_file()
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


def test_output_directory_cannot_be_checkout(tmp_path):
    configuration = {
        "repo_root": str(tmp_path / "repo"),
        "runner_manifest": str(tmp_path / "bootstrap.json"),
        "source_root": str(tmp_path / "sources"),
        "evidence_root": str(tmp_path / "objects"),
        "workspaces_root": str(tmp_path / "workspaces"),
        "docker_context": "desktop-linux",
        "controlled_network": None,
        "resources": {},
        "github_repository": "AlexTesta00/orchestwin-studio",
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(configuration), encoding="utf-8")
    with pytest.raises(CampaignError, match="INSIDE_CHECKOUT"):
        load_configuration(path, tmp_path / "repo" / "campaign")


def test_future_or_wrong_hash_decision_cannot_approve_any_operation():
    owner, project, operation_id = uuid4(), uuid4(), uuid4()
    governance = SimpleNamespace(approve=AsyncMock())
    plan = {"owner_user_id": str(owner), "cases": [{"project_id": str(project)}]}
    campaign = ValidationCampaign(
        plan=plan, fixtures=(), governance=governance, runner_identities=(), guard=lambda: None
    )
    operation = SimpleNamespace(id=operation_id, state="PENDING", content_hash="a" * 64)
    campaign._state = AsyncMock(
        return_value=({"owner_user_id": owner, "project_id": project}, (), (operation,))
    )
    for decision in (
        {"operation_id": str(uuid4()), "content_hash": "a" * 64, "event_sequence": 1},
        {"operation_id": str(operation_id), "content_hash": "b" * 64, "event_sequence": 1},
        {"operation_id": str(operation_id), "content_hash": "a" * 64, "event_sequence": True},
    ):
        with pytest.raises(CampaignError):
            asyncio.run(campaign.approve([decision]))
    governance.approve.assert_not_awaited()
    asyncio.run(
        campaign.approve(
            [{"operation_id": str(operation_id), "content_hash": "a" * 64, "event_sequence": 1}]
        )
    )
    governance.approve.assert_awaited_once_with(
        owner_user_id=owner,
        project_id=project,
        operation_id=operation_id,
        expected_hash="a" * 64,
        expected_event_sequence=1,
    )


def test_real_contract_command_collects_junit_and_raw_observed_streams(tmp_path):
    repo = Path(__file__).resolve().parents[4]
    store = FileSystemSandboxEvidenceStore(tmp_path / "objects")
    receipt = asyncio.run(contract_receipt(repo, tmp_path / "contracts", store))
    result = _contract_tests(receipt, _Artifacts(lambda ref: read_bytes(store, ref)))
    assert set(receipt.required_test_ids) <= set(result["observed_test_ids"])
    assert len(result["observed_test_ids"]) > 8


def test_harvest_origin_is_immutable_and_reused_after_restart(tmp_path):
    from orchestwin.web_execution.validation_command import harvest_recorded_at

    completed = datetime.now(UTC) - timedelta(seconds=1)
    first = harvest_recorded_at(tmp_path, campaign_hash="a" * 64, completed_at=completed)
    path = tmp_path / "harvest-origin.json"
    original = path.read_bytes()
    second = harvest_recorded_at(tmp_path, campaign_hash="a" * 64, completed_at=completed)
    assert completed <= first <= datetime.now(UTC)
    assert second == first
    assert first.utcoffset().total_seconds() == 0
    assert path.read_bytes() == original


@pytest.mark.parametrize("change", ["campaign", "before-attempt", "future", "naive", "invalid"])
def test_harvest_origin_cannot_change_campaign_or_execution_chronology(tmp_path, change):
    from orchestwin.web_execution.validation_command import harvest_recorded_at

    completed = datetime.now(UTC) - timedelta(seconds=2)
    origin = harvest_recorded_at(tmp_path, campaign_hash="a" * 64, completed_at=completed)
    path = tmp_path / "harvest-origin.json"
    value = json.loads(path.read_bytes())
    if change == "campaign":
        value["campaign_hash"] = "b" * 64
    elif change == "before-attempt":
        value["recorded_at"] = (completed - timedelta(seconds=1)).isoformat()
    elif change == "future":
        value["recorded_at"] = (origin + timedelta(days=1)).isoformat()
    elif change == "naive":
        value["recorded_at"] = origin.replace(tzinfo=None).isoformat()
    else:
        value["recorded_at"] = "invalid"
    path.write_text(json.dumps(value), encoding="utf-8")
    original = path.read_bytes()
    with pytest.raises(CampaignError, match="HARVEST_ORIGIN"):
        harvest_recorded_at(tmp_path, campaign_hash="a" * 64, completed_at=completed)
    assert path.read_bytes() == original


def test_harvest_origin_is_not_created_before_attempts_complete(tmp_path):
    from orchestwin.web_execution.validation_command import harvest_recorded_at

    with pytest.raises(CampaignError, match="HARVEST_ORIGIN"):
        harvest_recorded_at(
            tmp_path, campaign_hash="a" * 64, completed_at=datetime.now(UTC) + timedelta(days=1)
        )
    assert not (tmp_path / "harvest-origin.json").exists()


def test_promotion_manifest_serializes_the_actual_domain_decision():
    from orchestwin.web_execution.profile_registry import evaluate_sprint08_web_profile_promotions
    from orchestwin.web_execution.validation_command import promotion_decision_snapshot
    from orchestwin.web_execution.validation_evidence import WebProfileValidationEvidenceCatalog

    decision = evaluate_sprint08_web_profile_promotions(WebProfileValidationEvidenceCatalog(()))[0]
    snapshot = promotion_decision_snapshot(decision)
    assert snapshot["profile_id"] == decision.profile_id
    assert snapshot["status"] == decision.status.value
    assert snapshot["missing_requirements"] == list(decision.missing_requirements)
    assert snapshot["baseline_scope_hash"] == decision.baseline_scope_hash
    assert json.loads(json.dumps(snapshot)) == snapshot


def test_runtime_checkout_accepts_only_the_package_loaded_from_the_requested_repo(tmp_path):
    from orchestwin.web_execution.validation_command import verify_runtime_checkout

    repo = Path(__file__).resolve().parents[4]
    verify_runtime_checkout(repo)
    unrelated = tmp_path / "other-repository"
    (unrelated / "src/orchestwin").mkdir(parents=True)
    (unrelated / "src/orchestwin/__init__.py").write_text("", encoding="utf-8")
    with pytest.raises(CampaignError, match="RUNTIME_CHECKOUT_MISMATCH"):
        verify_runtime_checkout(unrelated)


@pytest.mark.parametrize("location", ["foreign-file", "missing-origin"])
def test_runtime_checkout_rejects_foreign_or_unidentified_loaded_submodules(
    tmp_path, monkeypatch, location
):
    from orchestwin.web_execution.validation_command import verify_runtime_checkout

    module = ModuleType("orchestwin.foreign_test_module")
    if location == "foreign-file":
        path = tmp_path / "foreign.py"
        path.write_text("", encoding="utf-8")
        module.__file__ = str(path)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    with pytest.raises(CampaignError, match="RUNTIME_CHECKOUT_MISMATCH"):
        verify_runtime_checkout(Path(__file__).resolve().parents[4])


def test_cli_rejects_a_different_runtime_checkout_before_git_or_database(tmp_path, monkeypatch):
    from orchestwin.web_execution import validation_command

    monkeypatch.setattr(
        validation_command,
        "load_configuration",
        lambda *_: (
            {},
            SimpleNamespace(repo_root=tmp_path / "other-repository"),
            None,
        ),
    )

    def forbidden(*args, **kwargs):
        pytest.fail("unbound runtime reached Git or database")

    monkeypatch.setattr(validation_command, "checked_commit", forbidden)
    monkeypatch.setattr(validation_command, "DatabaseSettings", forbidden)
    with pytest.raises(CampaignError, match="RUNTIME_CHECKOUT_MISMATCH"):
        asyncio.run(
            validation_command.run(
                SimpleNamespace(campaign_dir=tmp_path / "campaign", config=tmp_path / "config")
            )
        )


def test_contract_process_pins_its_package_path_and_disables_ambient_cwd(tmp_path, monkeypatch):
    from orchestwin.sandbox.host_process import BoundedHostProcessResult
    from orchestwin.web_execution import validation_command

    seen = {}

    async def observed(argv, **kwargs):
        seen.update(kwargs)
        return BoundedHostProcessResult("COMPLETED", 0, b"", b"", None)

    monkeypatch.setattr(validation_command, "run_bounded_host_process", observed)
    repo = Path(__file__).resolve().parents[4]
    asyncio.run(
        contract_receipt(
            repo, tmp_path / "contracts", FileSystemSandboxEvidenceStore(tmp_path / "objects")
        )
    )
    environment = seen["environment_overrides"]
    assert environment["PYTHONPATH"] == str(repo / "src")
    assert environment["PYTHONSAFEPATH"] == "1"


def test_ci_repository_format_is_checked_before_database_without_network(tmp_path, monkeypatch):
    from orchestwin.web_execution import validation_command

    repo = Path(__file__).resolve().parents[4]
    monkeypatch.setattr(
        validation_command,
        "load_configuration",
        lambda *_: (
            {"github_repository": "https://github.com/owner/repository"},
            SimpleNamespace(repo_root=repo),
            None,
        ),
    )
    monkeypatch.setattr(validation_command, "checked_commit", lambda *_: "a" * 40)
    monkeypatch.setenv("ORCHESTWIN_DATABASE_URL", "explicit-test-database")

    def forbidden(*args, **kwargs):
        pytest.fail("invalid repository reached database or CI network access")

    monkeypatch.setattr(validation_command, "DatabaseSettings", forbidden)
    monkeypatch.setattr(validation_command.GitHubCiVerifier, "verify", forbidden)
    with pytest.raises(ValueError, match="normalized GitHub"):
        asyncio.run(
            validation_command.run(
                SimpleNamespace(
                    campaign_dir=tmp_path / "campaign",
                    config=tmp_path / "config",
                )
            )
        )
