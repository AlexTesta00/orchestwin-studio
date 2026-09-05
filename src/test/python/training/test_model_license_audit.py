"""License audit must bind the exact captured source without authorizing training."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from orchestwin.training.model_license_audit import (
    LICENSE_AUDIT_POLICY_PATH,
    ModelLicenseAuditError,
    audit_model_license,
    canonical_json,
    snapshot_hash,
)


def _write_json(path: Path, value: dict[str, object]) -> bytes:
    raw = canonical_json(value).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    source = tmp_path / "source"
    license_raw = b"""Apache License\nVersion 2.0, January 2004\nTERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION\n2. Grant of Copyright License.\n3. Grant of Patent License.\nEND OF TERMS AND CONDITIONS\n"""
    card_raw = b"---\nlicense: apache-2.0\n---\n# Model\n"
    (source / "files").mkdir(parents=True)
    (source / "files/LICENSE").write_bytes(license_raw)
    (source / "files/README.md").write_bytes(card_raw)
    evidence = {
        "schema_version": 1,
        "candidate_id": "model-candidate-qwen3-4b-instruct-2507",
        "repository_id": "Qwen/Qwen3-4B-Instruct-2507",
        "requested_revision": "abcc171021d4f320b2e7f47c6f0deca67ded870c",
        "resolved_revision": "abcc171021d4f320b2e7f47c6f0deca67ded870c",
        "complete": True,
        "files": [
            {
                "relative_path": "LICENSE",
                "roles": ["LICENSE"],
                "sha256": hashlib.sha256(license_raw).hexdigest(),
                "size_bytes": len(license_raw),
            },
            {
                "relative_path": "README.md",
                "roles": ["MODEL_CARD"],
                "sha256": hashlib.sha256(card_raw).hexdigest(),
                "size_bytes": len(card_raw),
            },
        ],
    }
    evidence["content_hash"] = snapshot_hash(evidence)
    evidence_raw = _write_json(source / "evidence.json", evidence)
    policy = {
        "schema_version": 1,
        "policy_id": "qwen3-4b-instruct-2507-license-audit-v1",
        "candidate_id": "model-candidate-qwen3-4b-instruct-2507",
        "repository_id": "Qwen/Qwen3-4B-Instruct-2507",
        "revision": "abcc171021d4f320b2e7f47c6f0deca67ded870c",
        "source_evidence_sha256": hashlib.sha256(evidence_raw).hexdigest(),
        "source_evidence_content_hash": evidence["content_hash"],
        "model_card": {
            "relative_path": "README.md",
            "sha256": hashlib.sha256(card_raw).hexdigest(),
            "declared_license_id": "apache-2.0",
        },
        "license_file": {
            "relative_path": "LICENSE",
            "sha256": hashlib.sha256(license_raw).hexdigest(),
            "expected_family": "APACHE-2.0",
        },
        "review_scope": "LOCAL_QLORA_SMOKE_EVIDENCE",
        "owner_approval_required": True,
        "public_adapter_release_review": "DEFERRED",
        "legal_conclusion": "NOT_ENCODED",
    }
    policy["content_hash"] = snapshot_hash(policy)
    _write_json(repo / LICENSE_AUDIT_POLICY_PATH, policy)
    return repo, source / "evidence.json"


def test_audit_verifies_evidence_without_granting_owner_approval(tmp_path: Path) -> None:
    repo, evidence = _fixture(tmp_path)
    result = audit_model_license(
        repository_root=repo,
        source_evidence_path=evidence,
        created_at=datetime(2026, 9, 5, tzinfo=UTC),
    )
    assert result["evidence_status"] == "VERIFIED"
    assert result["declared_license_id"] == "apache-2.0"
    assert result["owner_approval_status"] == "NOT_RECORDED"
    assert result["legal_conclusion"] == "NOT_PERFORMED"
    assert result["training_executed"] is False
    assert result["model_selected"] is False


def test_audit_rejects_tampered_license_bytes(tmp_path: Path) -> None:
    repo, evidence = _fixture(tmp_path)
    (evidence.parent / "files/LICENSE").write_text("Apache License\nchanged\n", encoding="utf-8")
    with pytest.raises(ModelLicenseAuditError, match="changed"):
        audit_model_license(
            repository_root=repo,
            source_evidence_path=evidence,
            created_at=datetime(2026, 9, 5, tzinfo=UTC),
        )


def test_audit_rejects_model_card_license_mismatch(tmp_path: Path) -> None:
    repo, evidence = _fixture(tmp_path)
    card = evidence.parent / "files/README.md"
    raw = card.read_bytes().replace(b"apache-2.0", b"mit")
    card.write_bytes(raw)
    payload = json.loads(evidence.read_text())
    for item in payload["files"]:
        if item["relative_path"] == "README.md":
            item["sha256"] = hashlib.sha256(raw).hexdigest()
            item["size_bytes"] = len(raw)
    payload.pop("content_hash")
    payload["content_hash"] = snapshot_hash(payload)
    evidence_raw = _write_json(evidence, payload)
    policy_path = repo / LICENSE_AUDIT_POLICY_PATH
    policy = json.loads(policy_path.read_text())
    policy["source_evidence_sha256"] = hashlib.sha256(evidence_raw).hexdigest()
    policy["source_evidence_content_hash"] = payload["content_hash"]
    policy["model_card"]["sha256"] = hashlib.sha256(raw).hexdigest()
    policy.pop("content_hash")
    policy["content_hash"] = snapshot_hash(policy)
    _write_json(policy_path, policy)
    with pytest.raises(ModelLicenseAuditError, match="license declaration"):
        audit_model_license(
            repository_root=repo,
            source_evidence_path=evidence,
            created_at=datetime(2026, 9, 5, tzinfo=UTC),
        )


def test_audit_policy_cannot_be_rehashed_to_weaken_expected_license_family(tmp_path: Path) -> None:
    repo, evidence = _fixture(tmp_path)
    policy_path = repo / LICENSE_AUDIT_POLICY_PATH
    policy = json.loads(policy_path.read_text())
    policy["license_file"]["expected_family"] = "MIT"
    policy.pop("content_hash")
    policy["content_hash"] = snapshot_hash(policy)
    _write_json(policy_path, policy)
    with pytest.raises(ModelLicenseAuditError, match="may not weaken"):
        audit_model_license(
            repository_root=repo,
            source_evidence_path=evidence,
            created_at=datetime(2026, 9, 5, tzinfo=UTC),
        )
