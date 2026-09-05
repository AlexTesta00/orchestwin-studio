"""Recovery verification contracts do not add optimizer steps or trust mutable artifacts."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestwin.training.qlora_smoke_recovery import (
    REQUIRED_RESUME_FILES,
    SmokeRecoveryError,
    _validate_result_contract,
    resolve_historical_bindings,
    verify_inventory,
)

ROOT = Path(__file__).resolve().parents[4]


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def test_inventory_requires_exact_paths_sizes_and_hashes(tmp_path):
    root = tmp_path / "artifacts"
    root.mkdir()
    (root / "adapter_config.json").write_bytes(b"{}")
    (root / "adapter_model.safetensors").write_bytes(b"weights")
    recorded = [
        {
            "path": path.name,
            "size_bytes": path.stat().st_size,
            "sha256": digest(path.read_bytes()),
        }
        for path in sorted(root.iterdir())
    ]

    parsed = verify_inventory(root, recorded)
    assert set(parsed) == {"adapter_config.json", "adapter_model.safetensors"}

    (root / "adapter_model.safetensors").write_bytes(b"changed")
    with pytest.raises(SmokeRecoveryError, match="changed"):
        verify_inventory(root, recorded)


def test_inventory_rejects_unrecorded_files_and_links(tmp_path):
    root = tmp_path / "checkpoint"
    root.mkdir()
    file = root / "trainer_state.json"
    file.write_bytes(b"{}")
    recorded = [
        {
            "path": file.name,
            "size_bytes": file.stat().st_size,
            "sha256": digest(file.read_bytes()),
        }
    ]

    (root / "unexpected.txt").write_text("x")
    with pytest.raises(SmokeRecoveryError, match="file set"):
        verify_inventory(root, recorded)
    (root / "unexpected.txt").unlink()

    link = root / "linked"
    try:
        link.symlink_to(file)
    except OSError:
        pytest.skip("symbolic links unavailable")
    with pytest.raises((SmokeRecoveryError, ValueError)):
        verify_inventory(root, recorded)


def test_completed_result_contract_binds_request_execution_and_eight_steps():
    request = {
        "request_id": "request",
        "request_sha256": "a" * 64,
        "repository_head": "b" * 40,
        "runtime_id": "unsloth-eight-step-smoke-v1",
        "anchor_sha256": {"run_qlora_smoke.py": "c" * 64},
    }
    execution = {
        "status": "RUNNER_COMPLETED",
        "runner_exit_code": 0,
        "training_executed": True,
        "runner_result_present": True,
        "runner_result_sha256": "d" * 64,
        "request_id": "request",
        "request_sha256": "a" * 64,
        "repository_head": "b" * 40,
        "runtime_id": "unsloth-eight-step-smoke-v1",
    }
    result = {
        "runtime_id": "unsloth-eight-step-smoke-v1",
        "status": "SMOKE_TRAINING_COMPLETED_RELOAD_PENDING",
        "training_executed": True,
        "model_weights_loaded": True,
        "model_selected": False,
        "full_training_approved": False,
        "network_authorized": False,
        "implementation_sha256": "c" * 64,
        "observations": {
            "global_step": 8,
            "adapter_exported": True,
            "adapter_reload_status": "NOT_RUN",
            "checkpoint_restore_status": "NOT_RUN",
            "quality_improvement_measured": False,
            "serving_validated": False,
        },
    }

    _validate_result_contract(
        request=request,
        execution=execution,
        result=result,
        result_sha256="d" * 64,
    )

    result["observations"]["global_step"] = 9
    with pytest.raises(SmokeRecoveryError, match="recovery verification pending"):
        _validate_result_contract(
            request=request,
            execution=execution,
            result=result,
            result_sha256="d" * 64,
        )


def test_historical_bindings_allow_new_head_but_require_exact_anchor_bytes(tmp_path):
    repository = tmp_path / "repo"
    prepared = repository / "artifacts/prepared"
    tokenized = repository / "artifacts/tokenized"
    sources = repository / "artifacts/source"
    for directory in (prepared, tokenized, sources):
        directory.mkdir(parents=True)

    files = {
        "preparation.json": prepared / "preparation.json",
        "tokenization-report.json": tokenized / "tokenization-report.json",
        "source-evidence.json": sources / "evidence.json",
        "collator-report.json": repository / "artifacts/collator.json",
        "license-audit.json": repository / "artifacts/license.json",
        "run_qlora_smoke.py": repository / "runner.py",
        "uv.lock": repository / "uv.lock",
        "environment.json": repository / "environment.json",
    }
    for index, path in enumerate(files.values()):
        path.write_text(str(index))

    request = {
        "references": {
            "prepared_root": "artifacts/prepared",
            "tokenized_root": "artifacts/tokenized",
            "source_evidence": "artifacts/source/evidence.json",
            "collator_report": "artifacts/collator.json",
            "license_audit": "artifacts/license.json",
            "runner": "runner.py",
            "uv_lock": "uv.lock",
            "environment": "environment.json",
        },
        "anchor_sha256": {label: digest(path.read_bytes()) for label, path in files.items()},
        "repository_head": "historical-head-is-not-consulted",
    }

    resolved = resolve_historical_bindings(repository, request)
    assert resolved["runner"] == repository / "runner.py"

    files["run_qlora_smoke.py"].write_text("changed")
    with pytest.raises(SmokeRecoveryError, match="anchor changed"):
        resolve_historical_bindings(repository, request)


def test_checkpoint_resume_contract_requires_optimizer_scheduler_and_rng_state():
    assert {
        "trainer_state.json",
        "adapter_config.json",
        "adapter_model.safetensors",
        "optimizer.pt",
        "scheduler.pt",
        "rng_state.pth",
    } == set(REQUIRED_RESUME_FILES)


def cli_module():
    path = ROOT / "environments/training/verify_qlora_smoke_recovery.py"
    spec = importlib.util.spec_from_file_location("recovery_cli_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_no_step_callback_fails_before_any_additional_optimizer_step():
    module = cli_module()
    callback = module._no_step_callback(object)
    assert callback.optimizer_step_attempts == 0
    with pytest.raises(RuntimeError, match="beyond step 8"):
        callback.on_step_begin(None, SimpleNamespace(global_step=8), None)
    assert callback.optimizer_step_attempts == 1


def test_restore_method_wrapper_records_actual_runtime_calls():
    module = cli_module()
    calls = {"restore": 0}

    class Trainer:
        def restore(self, value):
            return value + 1

    trainer = Trainer()
    module._wrap_restore_method(trainer, "restore", calls)
    assert trainer.restore(4) == 5
    assert calls["restore"] == 1


def test_cli_keeps_gpu_imports_lazy_and_never_sets_training_gate():
    source = (ROOT / "environments/training/verify_qlora_smoke_recovery.py").read_text()
    assert "environment.pop(TRAINING_GATE, None)" in source
    assert 'ORCHESTWIN_QLORA_SMOKE_ALLOW_TRAINING", "1"' not in source
    assert "runner.load_dependencies()" in source
    assert "trainer.train(resume_from_checkpoint=str(bundle.checkpoint8))" in source


def test_report_payloads_are_json_serializable():
    payload = {
        "status": "QLORA_SMOKE_RECOVERY_VERIFIED",
        "optimizer_steps_added": 0,
        "verification_training_executed": False,
        "scheduler_state": {"last_epoch": 8},
    }
    json.dumps(payload)
