"""Executable QLoRA smoke requests must be explicit, immutable, and bounded."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid5

import pytest

from orchestwin.training.qlora_smoke_requests import (
    QLORA_SMOKE_REQUEST_NAMESPACE,
    QloraSmokeRequestError,
    build_request,
    canonical_json,
    load_request,
    sha256_bytes,
    snapshot_hash,
    verify_request_bindings,
    write_request,
)


def _request() -> dict[str, object]:
    value = {
        "request_id": "",
        "schema_version": 1,
        "policy_id": "qlora-eight-step-owner-request-v1",
        "created_at": "2026-09-05T12:00:00+00:00",
        "repository_head": "a" * 40,
        "runtime_id": "unsloth-eight-step-smoke-v1",
        "candidate_id": "model-candidate-qwen3-4b-instruct-2507",
        "base_model_repository": "Qwen/Qwen3-4B-Instruct-2507",
        "base_model_revision": "abcc171021d4f320b2e7f47c6f0deca67ded870c",
        "configuration_content_hash": "9a302b90a891744a959b2a9b771e3b42f792a99d72274738286745fbbe362df7",
        "scope": "LOCAL_EIGHT_STEP_SMOKE_ONLY",
        "execution_policy": {
            "optimizer_steps": 8,
            "max_sequence_length": 1536,
            "offline_required": True,
            "network_authorized": False,
            "redistribution_authorized": False,
            "full_training_authorized": False,
            "model_selected": False,
        },
        "owner_declarations": {
            "owner_id": "owner",
            "fixture_review": "OWNER_APPROVED_FOR_PIPELINE_SMOKE",
            "model_license_review": "OWNER_APPROVED_FOR_LOCAL_SMOKE",
            "local_training": "OWNER_APPROVED_EIGHT_STEP_SMOKE",
            "redistribution_authorized": False,
            "full_training_authorized": False,
            "model_selected": False,
        },
        "references": {},
        "anchor_sha256": {},
        "license_audit_content_hash": "b" * 64,
        "collator_report_content_hash": "c" * 64,
        "tokenization_content_hash": "d" * 64,
        "preparation_content_hash": "e" * 64,
        "source_evidence_content_hash": "f" * 64,
    }
    core = dict(value)
    core.pop("request_id")
    value["request_id"] = str(uuid5(QLORA_SMOKE_REQUEST_NAMESPACE, snapshot_hash(core)))
    value["request_sha256"] = snapshot_hash(value)
    return value


def _rehash(request: dict[str, object]) -> None:
    core = dict(request)
    core.pop("request_id", None)
    core.pop("request_sha256", None)
    request["request_id"] = str(uuid5(QLORA_SMOKE_REQUEST_NAMESPACE, snapshot_hash(core)))
    request["request_sha256"] = snapshot_hash(
        {k: v for k, v in request.items() if k != "request_sha256"}
    )


def test_request_loader_preserves_bounded_offline_policy(tmp_path: Path) -> None:
    request = _request()
    path = tmp_path / "request.json"
    path.write_text(canonical_json(request), encoding="utf-8")
    observed = load_request(path)
    assert observed["execution_policy"]["optimizer_steps"] == 8
    assert observed["execution_policy"]["offline_required"] is True
    assert observed["execution_policy"]["network_authorized"] is False
    assert observed["owner_declarations"]["full_training_authorized"] is False
    assert observed["owner_declarations"]["model_selected"] is False


def test_request_loader_rejects_modified_step_budget(tmp_path: Path) -> None:
    request = _request()
    request["execution_policy"]["optimizer_steps"] = 9
    _rehash(request)
    path = tmp_path / "request.json"
    path.write_text(canonical_json(request), encoding="utf-8")
    with pytest.raises(QloraSmokeRequestError, match="execution policy"):
        load_request(path)


def test_request_loader_rejects_missing_owner_approval(tmp_path: Path) -> None:
    request = _request()
    request["owner_declarations"]["model_license_review"] = "PENDING"
    _rehash(request)
    path = tmp_path / "request.json"
    path.write_text(canonical_json(request), encoding="utf-8")
    with pytest.raises(QloraSmokeRequestError, match="owner declarations"):
        load_request(path)


def test_request_loader_rejects_noncanonical_json(tmp_path: Path) -> None:
    request = _request()
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request, indent=2), encoding="utf-8")
    with pytest.raises(QloraSmokeRequestError, match="canonical"):
        load_request(path)


def test_request_loader_rejects_rehashed_identity_change(tmp_path: Path) -> None:
    request = _request()
    request["base_model_revision"] = "f" * 40
    _rehash(request)
    path = tmp_path / "request.json"
    path.write_text(canonical_json(request), encoding="utf-8")
    with pytest.raises(QloraSmokeRequestError, match="identity differs"):
        load_request(path)


def test_request_loader_rejects_request_id_not_derived_from_content(tmp_path: Path) -> None:
    request = _request()
    request["request_id"] = "00000000-0000-4000-8000-000000000000"
    request["request_sha256"] = snapshot_hash(
        {k: v for k, v in request.items() if k != "request_sha256"}
    )
    path = tmp_path / "request.json"
    path.write_text(canonical_json(request), encoding="utf-8")
    with pytest.raises(QloraSmokeRequestError, match="content-derived"):
        load_request(path)


def _snapshot(path: Path, value: dict[str, object]) -> bytes:
    payload = dict(value)
    payload["content_hash"] = snapshot_hash(payload)
    raw = canonical_json(payload).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def _bound_fixture(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    repo = tmp_path / "repo"
    artifacts = repo / "environments/training/artifacts"
    runner = repo / "environments/training/run_qlora_smoke.py"
    lock = repo / "environments/training/uv.lock"
    environment = artifacts / "environment.json"
    runner.parent.mkdir(parents=True, exist_ok=True)
    runner.write_text("# frozen smoke runner\n", encoding="utf-8")
    lock.write_bytes(b"locked-training-environment\n")
    environment.parent.mkdir(parents=True, exist_ok=True)
    environment.write_bytes(b'{"complete":true}')

    prepared = artifacts / "prepared"
    tokenized = artifacts / "tokenized"
    source = artifacts / "source/evidence.json"
    collator = artifacts / "preflight/collator-report.json"
    license_audit = artifacts / "preflight/license-audit.json"

    _snapshot(
        prepared / "preparation.json",
        {
            "candidate_id": "model-candidate-qwen3-4b-instruct-2507",
            "configuration_content_hash": (
                "9a302b90a891744a959b2a9b771e3b42f792a99d72274738286745fbbe362df7"
            ),
            "status": "PREPARED_NOT_AUTHORIZED",
            "training_executed": False,
            "package_lock_sha256": sha256_bytes(lock.read_bytes()),
            "environment_sha256": sha256_bytes(environment.read_bytes()),
        },
    )
    tokenization_raw = _snapshot(
        tokenized / "tokenization-report.json",
        {
            "candidate_id": "model-candidate-qwen3-4b-instruct-2507",
            "configuration_content_hash": (
                "9a302b90a891744a959b2a9b771e3b42f792a99d72274738286745fbbe362df7"
            ),
            "status": "TOKENIZATION_VERIFIED_NOT_AUTHORIZED",
            "training_executed": False,
        },
    )
    source_raw = _snapshot(
        source,
        {
            "candidate_id": "model-candidate-qwen3-4b-instruct-2507",
            "repository_id": "Qwen/Qwen3-4B-Instruct-2507",
            "requested_revision": "abcc171021d4f320b2e7f47c6f0deca67ded870c",
            "resolved_revision": "abcc171021d4f320b2e7f47c6f0deca67ded870c",
            "complete": True,
        },
    )
    tokenization_value = json.loads(tokenization_raw)
    _snapshot(
        collator,
        {
            "status": "COLLATOR_VERIFIED_NOT_AUTHORIZED",
            "training_executed": False,
            "inputs": {
                "candidate_id": "model-candidate-qwen3-4b-instruct-2507",
                "configuration_content_hash": (
                    "9a302b90a891744a959b2a9b771e3b42f792a99d72274738286745fbbe362df7"
                ),
                "tokenization_content_hash": tokenization_value["content_hash"],
            },
        },
    )
    _snapshot(
        license_audit,
        {
            "candidate_id": "model-candidate-qwen3-4b-instruct-2507",
            "repository_id": "Qwen/Qwen3-4B-Instruct-2507",
            "revision": "abcc171021d4f320b2e7f47c6f0deca67ded870c",
            "evidence_status": "VERIFIED",
            "owner_approval_status": "NOT_RECORDED",
            "legal_conclusion": "NOT_PERFORMED",
            "training_executed": False,
            "source_evidence_sha256": sha256_bytes(source_raw),
        },
    )

    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
    return repo, {
        "prepared": prepared,
        "tokenized": tokenized,
        "source": source,
        "collator": collator,
        "license": license_audit,
        "runner": runner,
    }


def test_materialized_request_binds_head_and_every_runtime_anchor(tmp_path: Path) -> None:
    repo, paths = _bound_fixture(tmp_path)
    request = build_request(
        repository_root=repo,
        prepared_root=paths["prepared"],
        tokenized_root=paths["tokenized"],
        source_evidence_path=paths["source"],
        collator_report_path=paths["collator"],
        license_audit_path=paths["license"],
        owner_id="owner",
        approve_fixtures=True,
        approve_model_license=True,
        approve_local_training=True,
        created_at=datetime(2026, 9, 5, tzinfo=UTC),
    )
    output = repo / "environments/training/artifacts/request.json"
    write_request(output, request)
    loaded = load_request(output)
    bindings = verify_request_bindings(repo, loaded)
    assert bindings["runner"] == paths["runner"]
    assert loaded["execution_policy"]["optimizer_steps"] == 8
    assert loaded["owner_declarations"]["full_training_authorized"] is False

    paths["runner"].write_text("# changed after authorization\n", encoding="utf-8")
    with pytest.raises(QloraSmokeRequestError, match="anchor changed"):
        verify_request_bindings(repo, loaded)


def test_materializer_cannot_create_executable_request_without_all_owner_decisions(
    tmp_path: Path,
) -> None:
    repo, paths = _bound_fixture(tmp_path)
    with pytest.raises(QloraSmokeRequestError, match="all three owner approvals"):
        build_request(
            repository_root=repo,
            prepared_root=paths["prepared"],
            tokenized_root=paths["tokenized"],
            source_evidence_path=paths["source"],
            collator_report_path=paths["collator"],
            license_audit_path=paths["license"],
            owner_id="owner",
            approve_fixtures=True,
            approve_model_license=True,
            approve_local_training=False,
            created_at=datetime(2026, 9, 5, tzinfo=UTC),
        )


def test_executor_refuses_without_training_gate_before_creating_output(tmp_path: Path) -> None:
    root = Path(__file__).parents[4]
    script = root / "environments/training/execute_qlora_smoke_request.py"
    request_path = tmp_path / "request.json"
    request_path.write_text(canonical_json(_request()), encoding="utf-8")
    output = tmp_path / "execution"
    environment = dict(os.environ)
    environment.pop("ORCHESTWIN_QLORA_SMOKE_ALLOW_TRAINING", None)
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--request",
            str(request_path),
            "--output-root",
            str(output),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 22
    assert "ORCHESTWIN_QLORA_SMOKE_ALLOW_TRAINING" in completed.stderr
    assert not output.exists()
