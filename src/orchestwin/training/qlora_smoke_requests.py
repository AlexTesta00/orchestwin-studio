"""Immutable owner-authorized requests for the bounded QLoRA smoke run."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Final
from uuid import UUID, uuid5

QLORA_SMOKE_REQUEST_SCHEMA_VERSION: Final = 1
QLORA_SMOKE_REQUEST_POLICY_ID: Final = "qlora-eight-step-owner-request-v1"
QLORA_SMOKE_REQUEST_NAMESPACE: Final = UUID("2b099a9d-b0b0-4cb3-944d-bafc902ea96d")
EXPECTED_CANDIDATE_ID: Final = "model-candidate-qwen3-4b-instruct-2507"
EXPECTED_REPOSITORY: Final = "Qwen/Qwen3-4B-Instruct-2507"
EXPECTED_REVISION: Final = "abcc171021d4f320b2e7f47c6f0deca67ded870c"
EXPECTED_CONFIGURATION_HASH: Final = (
    "9a302b90a891744a959b2a9b771e3b42f792a99d72274738286745fbbe362df7"
)
EXPECTED_RUNTIME_ID: Final = "unsloth-eight-step-smoke-v1"
_MAX_JSON_BYTES: Final = 2_000_000


class QloraSmokeRequestError(ValueError):
    """Raised when a smoke request is incomplete, stale, unsafe, or not explicitly approved."""


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def snapshot_hash(value: dict[str, object]) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    path = path.absolute()
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_JSON_BYTES:
        raise QloraSmokeRequestError(f"expected bounded regular JSON file: {path}")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise QloraSmokeRequestError(f"invalid UTF-8 JSON: {path.name}") from error
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise QloraSmokeRequestError(f"expected JSON object: {path.name}")
    return value, raw


def _validate_snapshot(value: dict[str, Any], *, label: str) -> None:
    observed = value.get("content_hash")
    semantic = dict(value)
    semantic.pop("content_hash", None)
    if not isinstance(observed, str) or snapshot_hash(semantic) != observed:
        raise QloraSmokeRequestError(f"{label} content hash changed")


def _relative_to_repository(repository: Path, path: Path, *, label: str) -> str:
    repository = repository.absolute()
    path = path.absolute()
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != path):
        raise QloraSmokeRequestError(f"{label} cannot traverse symbolic links")
    try:
        relative = path.relative_to(repository)
    except ValueError as error:
        raise QloraSmokeRequestError(f"{label} must remain inside the repository") from error
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise QloraSmokeRequestError(f"{label} relative path is invalid")
    return relative.as_posix()


def _resolve_reference(repository: Path, reference: object, *, label: str) -> Path:
    if not isinstance(reference, str) or not reference or "\\" in reference:
        raise QloraSmokeRequestError(f"{label} must use relative POSIX syntax")
    pure = PurePosixPath(reference)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise QloraSmokeRequestError(f"{label} is unsafe")
    path = repository.absolute().joinpath(*pure.parts).absolute()
    if repository.absolute() not in path.parents:
        raise QloraSmokeRequestError(f"{label} escapes the repository")
    return path


def _git_head(repository: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise QloraSmokeRequestError("could not resolve repository HEAD") from error
    value = completed.stdout.strip()
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise QloraSmokeRequestError("repository HEAD is not a lowercase Git SHA")
    return value


def _require_owner_approval(
    *,
    owner_id: str,
    approve_fixtures: bool,
    approve_model_license: bool,
    approve_local_training: bool,
) -> dict[str, str | bool]:
    owner = owner_id.strip() if isinstance(owner_id, str) else ""
    if not owner or len(owner) > 128 or any(character in "\r\n\0" for character in owner):
        raise QloraSmokeRequestError(
            "owner identifier must be normalized and at most 128 characters"
        )
    if not all((approve_fixtures, approve_model_license, approve_local_training)):
        raise QloraSmokeRequestError(
            "all three owner approvals are required for an executable request"
        )
    return {
        "owner_id": owner,
        "fixture_review": "OWNER_APPROVED_FOR_PIPELINE_SMOKE",
        "model_license_review": "OWNER_APPROVED_FOR_LOCAL_SMOKE",
        "local_training": "OWNER_APPROVED_EIGHT_STEP_SMOKE",
        "redistribution_authorized": False,
        "full_training_authorized": False,
        "model_selected": False,
    }


def build_request(
    *,
    repository_root: Path,
    prepared_root: Path,
    tokenized_root: Path,
    source_evidence_path: Path,
    collator_report_path: Path,
    license_audit_path: Path,
    owner_id: str,
    approve_fixtures: bool,
    approve_model_license: bool,
    approve_local_training: bool,
    created_at: datetime,
) -> dict[str, object]:
    """Bind exact code, model, data, preflight evidence, and owner declarations."""
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise QloraSmokeRequestError("request timestamp must be timezone-aware")
    repository = repository_root.absolute()
    artifacts = repository / "environments/training/artifacts"
    bindings = {
        "prepared_root": prepared_root.absolute(),
        "tokenized_root": tokenized_root.absolute(),
        "source_evidence": source_evidence_path.absolute(),
        "collator_report": collator_report_path.absolute(),
        "license_audit": license_audit_path.absolute(),
        "runner": repository / "environments/training/run_qlora_smoke.py",
        "uv_lock": repository / "environments/training/uv.lock",
        "environment": artifacts / "environment.json",
    }
    for label, path in bindings.items():
        if label.endswith("_root"):
            if path.is_symlink() or not path.is_dir():
                raise QloraSmokeRequestError(f"{label} must be an existing regular directory")
        elif path.is_symlink() or not path.is_file():
            raise QloraSmokeRequestError(f"{label} must be an existing regular file")
    for label in (
        "prepared_root",
        "tokenized_root",
        "source_evidence",
        "collator_report",
        "license_audit",
    ):
        path = bindings[label]
        if artifacts != path and artifacts not in path.parents:
            raise QloraSmokeRequestError(f"{label} must remain inside training artifacts")

    preparation, preparation_raw = _read_json(bindings["prepared_root"] / "preparation.json")
    tokenization, tokenization_raw = _read_json(
        bindings["tokenized_root"] / "tokenization-report.json"
    )
    collator, collator_raw = _read_json(bindings["collator_report"])
    license_audit, license_raw = _read_json(bindings["license_audit"])
    source_evidence, source_raw = _read_json(bindings["source_evidence"])
    for value, label in (
        (preparation, "preparation"),
        (tokenization, "tokenization report"),
        (collator, "collator report"),
        (license_audit, "license audit"),
        (source_evidence, "source evidence"),
    ):
        _validate_snapshot(value, label=label)

    if any(
        (
            preparation.get("candidate_id") != EXPECTED_CANDIDATE_ID,
            preparation.get("configuration_content_hash") != EXPECTED_CONFIGURATION_HASH,
            preparation.get("status") != "PREPARED_NOT_AUTHORIZED",
            preparation.get("training_executed") is not False,
            tokenization.get("candidate_id") != EXPECTED_CANDIDATE_ID,
            tokenization.get("configuration_content_hash") != EXPECTED_CONFIGURATION_HASH,
            tokenization.get("status") != "TOKENIZATION_VERIFIED_NOT_AUTHORIZED",
            tokenization.get("training_executed") is not False,
            collator.get("status") != "COLLATOR_VERIFIED_NOT_AUTHORIZED",
            collator.get("training_executed") is not False,
            license_audit.get("candidate_id") != EXPECTED_CANDIDATE_ID,
            license_audit.get("repository_id") != EXPECTED_REPOSITORY,
            license_audit.get("revision") != EXPECTED_REVISION,
            license_audit.get("evidence_status") != "VERIFIED",
            license_audit.get("owner_approval_status") != "NOT_RECORDED",
            license_audit.get("legal_conclusion") != "NOT_PERFORMED",
            license_audit.get("training_executed") is not False,
            source_evidence.get("candidate_id") != EXPECTED_CANDIDATE_ID,
            source_evidence.get("repository_id") != EXPECTED_REPOSITORY,
            source_evidence.get("requested_revision") != EXPECTED_REVISION,
            source_evidence.get("resolved_revision") != EXPECTED_REVISION,
            source_evidence.get("complete") is not True,
        )
    ):
        raise QloraSmokeRequestError(
            "smoke evidence does not describe the frozen exact-revision candidate"
        )
    if license_audit.get("source_evidence_sha256") != sha256_bytes(source_raw):
        raise QloraSmokeRequestError("license audit belongs to different source evidence")
    collator_inputs = collator.get("inputs")
    if not isinstance(collator_inputs, dict) or any(
        (
            collator_inputs.get("candidate_id") != EXPECTED_CANDIDATE_ID,
            collator_inputs.get("configuration_content_hash") != EXPECTED_CONFIGURATION_HASH,
            collator_inputs.get("tokenization_content_hash") != tokenization.get("content_hash"),
        )
    ):
        raise QloraSmokeRequestError("collator report belongs to different tokenized inputs")

    approvals = _require_owner_approval(
        owner_id=owner_id,
        approve_fixtures=approve_fixtures,
        approve_model_license=approve_model_license,
        approve_local_training=approve_local_training,
    )
    references = {
        label: _relative_to_repository(repository, path, label=label)
        for label, path in bindings.items()
    }
    anchors = {
        "preparation.json": sha256_bytes(preparation_raw),
        "tokenization-report.json": sha256_bytes(tokenization_raw),
        "source-evidence.json": sha256_bytes(source_raw),
        "collator-report.json": sha256_bytes(collator_raw),
        "license-audit.json": sha256_bytes(license_raw),
        "run_qlora_smoke.py": sha256_bytes(bindings["runner"].read_bytes()),
        "uv.lock": sha256_bytes(bindings["uv_lock"].read_bytes()),
        "environment.json": sha256_bytes(bindings["environment"].read_bytes()),
    }
    if anchors["uv.lock"] != preparation.get("package_lock_sha256"):
        raise QloraSmokeRequestError("training lock changed since smoke preparation")
    if anchors["environment.json"] != preparation.get("environment_sha256"):
        raise QloraSmokeRequestError("environment manifest changed since smoke preparation")

    core: dict[str, object] = {
        "schema_version": QLORA_SMOKE_REQUEST_SCHEMA_VERSION,
        "policy_id": QLORA_SMOKE_REQUEST_POLICY_ID,
        "created_at": created_at.isoformat(),
        "repository_head": _git_head(repository),
        "runtime_id": EXPECTED_RUNTIME_ID,
        "candidate_id": EXPECTED_CANDIDATE_ID,
        "base_model_repository": EXPECTED_REPOSITORY,
        "base_model_revision": EXPECTED_REVISION,
        "configuration_content_hash": EXPECTED_CONFIGURATION_HASH,
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
        "owner_declarations": approvals,
        "references": references,
        "anchor_sha256": anchors,
        "license_audit_content_hash": license_audit["content_hash"],
        "collator_report_content_hash": collator["content_hash"],
        "tokenization_content_hash": tokenization["content_hash"],
        "preparation_content_hash": preparation["content_hash"],
        "source_evidence_content_hash": source_evidence["content_hash"],
    }
    request_id = uuid5(QLORA_SMOKE_REQUEST_NAMESPACE, snapshot_hash(core))
    payload = {"request_id": str(request_id), **core}
    payload["request_sha256"] = snapshot_hash(payload)
    return payload


def write_request(path: Path, request: dict[str, object]) -> None:
    path = path.absolute()
    if path.exists() or path.is_symlink():
        raise QloraSmokeRequestError("request output must be a new file")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(request).encode("utf-8"))


def load_request(path: Path) -> dict[str, Any]:
    request, raw = _read_json(path)
    if raw != canonical_json(request).encode("utf-8"):
        raise QloraSmokeRequestError("smoke request must use canonical JSON")
    if request.get("schema_version") != QLORA_SMOKE_REQUEST_SCHEMA_VERSION:
        raise QloraSmokeRequestError("unsupported smoke request schema version")
    if request.get("policy_id") != QLORA_SMOKE_REQUEST_POLICY_ID:
        raise QloraSmokeRequestError("unexpected smoke request policy")
    observed = request.get("request_sha256")
    semantic = dict(request)
    semantic.pop("request_sha256", None)
    if not isinstance(observed, str) or snapshot_hash(semantic) != observed:
        raise QloraSmokeRequestError("smoke request digest changed")
    try:
        observed_request_id = UUID(str(request.get("request_id")))
    except ValueError as error:
        raise QloraSmokeRequestError("smoke request ID is invalid") from error
    core = dict(request)
    core.pop("request_id", None)
    core.pop("request_sha256", None)
    expected_request_id = uuid5(QLORA_SMOKE_REQUEST_NAMESPACE, snapshot_hash(core))
    if observed_request_id != expected_request_id:
        raise QloraSmokeRequestError("smoke request ID is not content-derived")
    expected_identity = (
        QLORA_SMOKE_REQUEST_POLICY_ID,
        EXPECTED_RUNTIME_ID,
        EXPECTED_CANDIDATE_ID,
        EXPECTED_REPOSITORY,
        EXPECTED_REVISION,
        EXPECTED_CONFIGURATION_HASH,
        "LOCAL_EIGHT_STEP_SMOKE_ONLY",
    )
    observed_identity = (
        request.get("policy_id"),
        request.get("runtime_id"),
        request.get("candidate_id"),
        request.get("base_model_repository"),
        request.get("base_model_revision"),
        request.get("configuration_content_hash"),
        request.get("scope"),
    )
    if observed_identity != expected_identity:
        raise QloraSmokeRequestError("smoke request identity differs from the frozen Qwen smoke")
    policy = request.get("execution_policy")
    if not isinstance(policy, dict) or policy != {
        "optimizer_steps": 8,
        "max_sequence_length": 1536,
        "offline_required": True,
        "network_authorized": False,
        "redistribution_authorized": False,
        "full_training_authorized": False,
        "model_selected": False,
    }:
        raise QloraSmokeRequestError("smoke execution policy changed")
    approvals = request.get("owner_declarations")
    if not isinstance(approvals, dict) or any(
        (
            not isinstance(approvals.get("owner_id"), str),
            not str(approvals.get("owner_id", "")).strip(),
            approvals.get("fixture_review") != "OWNER_APPROVED_FOR_PIPELINE_SMOKE",
            approvals.get("model_license_review") != "OWNER_APPROVED_FOR_LOCAL_SMOKE",
            approvals.get("local_training") != "OWNER_APPROVED_EIGHT_STEP_SMOKE",
            approvals.get("redistribution_authorized") is not False,
            approvals.get("full_training_authorized") is not False,
            approvals.get("model_selected") is not False,
        )
    ):
        raise QloraSmokeRequestError("smoke owner declarations are incomplete")
    for key in (
        "license_audit_content_hash",
        "collator_report_content_hash",
        "tokenization_content_hash",
        "preparation_content_hash",
        "source_evidence_content_hash",
    ):
        value = request.get(key)
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise QloraSmokeRequestError(f"smoke request {key} is not lowercase SHA-256")
    if not isinstance(request.get("references"), dict) or not isinstance(
        request.get("anchor_sha256"), dict
    ):
        raise QloraSmokeRequestError("smoke request bindings are missing")
    return request


def verify_request_bindings(repository_root: Path, request: dict[str, Any]) -> dict[str, Path]:
    """Re-resolve every bound input and compare its exact digest before execution."""
    repository = repository_root.absolute()
    if _git_head(repository) != request.get("repository_head"):
        raise QloraSmokeRequestError("repository HEAD differs from the authorized request")
    references = request.get("references")
    anchors = request.get("anchor_sha256")
    if not isinstance(references, dict) or not isinstance(anchors, dict):
        raise QloraSmokeRequestError("request bindings are missing")
    paths = {
        label: _resolve_reference(repository, reference, label=label)
        for label, reference in references.items()
    }
    required = {
        "prepared_root",
        "tokenized_root",
        "source_evidence",
        "collator_report",
        "license_audit",
        "runner",
        "uv_lock",
        "environment",
    }
    if set(paths) != required:
        raise QloraSmokeRequestError("request references differ from the required set")
    files = {
        "preparation.json": paths["prepared_root"] / "preparation.json",
        "tokenization-report.json": paths["tokenized_root"] / "tokenization-report.json",
        "source-evidence.json": paths["source_evidence"],
        "collator-report.json": paths["collator_report"],
        "license-audit.json": paths["license_audit"],
        "run_qlora_smoke.py": paths["runner"],
        "uv.lock": paths["uv_lock"],
        "environment.json": paths["environment"],
    }
    if set(anchors) != set(files):
        raise QloraSmokeRequestError("request anchor set changed")
    for label, path in files.items():
        if path.is_symlink() or not path.is_file():
            raise QloraSmokeRequestError(f"request anchor is missing: {label}")
        if sha256_bytes(path.read_bytes()) != anchors[label]:
            raise QloraSmokeRequestError(f"request anchor changed: {label}")
    return paths
