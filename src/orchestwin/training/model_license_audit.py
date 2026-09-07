"""Offline, evidence-bound license audit for the Qwen QLoRA smoke candidate."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Final

LICENSE_AUDIT_SCHEMA_VERSION: Final = 1
LICENSE_AUDIT_POLICY_PATH: Final = Path(
    "experiments/model-spike/qwen3-4b-instruct-2507-license-audit-v1.json"
)
LICENSE_AUDIT_RESULT_SCHEMA_VERSION: Final = 1
EXPECTED_POLICY_ID: Final = "qwen3-4b-instruct-2507-license-audit-v1"
EXPECTED_CANDIDATE_ID: Final = "model-candidate-qwen3-4b-instruct-2507"
EXPECTED_REPOSITORY_ID: Final = "Qwen/Qwen3-4B-Instruct-2507"
EXPECTED_REVISION: Final = "abcc171021d4f320b2e7f47c6f0deca67ded870c"
EXPECTED_DECLARED_LICENSE_ID: Final = "apache-2.0"
EXPECTED_LICENSE_FAMILY: Final = "APACHE-2.0"
_MAX_JSON_BYTES: Final = 1_000_000
_MAX_TEXT_BYTES: Final = 2_000_000


class ModelLicenseAuditError(ValueError):
    """Raised when frozen license evidence is absent, altered, or internally inconsistent."""


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def snapshot_hash(value: Mapping[str, object]) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def _checked_regular_file(path: Path, *, maximum_bytes: int) -> Path:
    path = path.absolute()
    if path.is_symlink() or not path.is_file():
        raise ModelLicenseAuditError(f"expected regular file: {path}")
    if path.stat().st_size > maximum_bytes:
        raise ModelLicenseAuditError(f"file exceeds audit size limit: {path.name}")
    return path


def read_json_object(
    path: Path, *, maximum_bytes: int = _MAX_JSON_BYTES
) -> tuple[dict[str, Any], bytes]:
    path = _checked_regular_file(path, maximum_bytes=maximum_bytes)
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelLicenseAuditError(f"expected UTF-8 JSON: {path.name}") from error
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ModelLicenseAuditError(f"expected JSON object: {path.name}")
    return value, raw


def _validate_content_hash(value: Mapping[str, object], *, label: str) -> None:
    observed = value.get("content_hash")
    if not isinstance(observed, str) or len(observed) != 64:
        raise ModelLicenseAuditError(f"{label} content hash is missing")
    semantic = dict(value)
    semantic.pop("content_hash", None)
    if snapshot_hash(semantic) != observed:
        raise ModelLicenseAuditError(f"{label} content hash changed")


def load_policy(repository_root: Path) -> dict[str, Any]:
    path = repository_root.absolute() / LICENSE_AUDIT_POLICY_PATH
    policy, _ = read_json_object(path)
    _validate_content_hash(policy, label="license audit policy")
    if policy.get("schema_version") != LICENSE_AUDIT_SCHEMA_VERSION:
        raise ModelLicenseAuditError("unsupported license audit policy schema version")
    expected_identity = (
        EXPECTED_POLICY_ID,
        EXPECTED_CANDIDATE_ID,
        EXPECTED_REPOSITORY_ID,
        EXPECTED_REVISION,
    )
    observed_identity = (
        policy.get("policy_id"),
        policy.get("candidate_id"),
        policy.get("repository_id"),
        policy.get("revision"),
    )
    if observed_identity != expected_identity:
        raise ModelLicenseAuditError(
            "license policy identity differs from the frozen Qwen candidate"
        )
    model_card = policy.get("model_card")
    license_file = policy.get("license_file")
    if (
        not isinstance(model_card, dict)
        or model_card.get("declared_license_id") != EXPECTED_DECLARED_LICENSE_ID
        or not isinstance(license_file, dict)
        or license_file.get("expected_family") != EXPECTED_LICENSE_FAMILY
    ):
        raise ModelLicenseAuditError(
            "license policy may not weaken the frozen Apache-2.0 expectation"
        )
    if policy.get("owner_approval_required") is not True:
        raise ModelLicenseAuditError("license policy must require owner approval")
    if policy.get("legal_conclusion") != "NOT_ENCODED":
        raise ModelLicenseAuditError("license policy must not encode a legal conclusion")
    return policy


def _relative_file(root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ModelLicenseAuditError("evidence file path must be relative POSIX syntax")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ModelLicenseAuditError("evidence file path is unsafe")
    path = root.joinpath(*pure.parts).absolute()
    if root.absolute() not in path.parents:
        raise ModelLicenseAuditError("evidence file escaped its source directory")
    return path


def _file_record(evidence: Mapping[str, object], role: str) -> Mapping[str, object]:
    files = evidence.get("files")
    if not isinstance(files, list):
        raise ModelLicenseAuditError("source evidence files are missing")
    matches = []
    for raw in files:
        if not isinstance(raw, dict):
            raise ModelLicenseAuditError("source evidence file entry must be an object")
        roles = raw.get("roles")
        if isinstance(roles, list) and role in roles:
            matches.append(raw)
    if len(matches) != 1:
        raise ModelLicenseAuditError(f"source evidence must contain exactly one {role} file")
    return matches[0]


def _read_evidence_file(source_root: Path, record: Mapping[str, object]) -> tuple[Path, bytes]:
    relative = record.get("relative_path")
    path = _relative_file(source_root / "files", relative)
    raw = _checked_regular_file(path, maximum_bytes=_MAX_TEXT_BYTES).read_bytes()
    if record.get("size_bytes") != len(raw) or record.get("sha256") != sha256_bytes(raw):
        raise ModelLicenseAuditError(f"captured source file changed: {relative}")
    return path, raw


def _front_matter(markdown: str) -> dict[str, str]:
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ModelLicenseAuditError("model card lacks YAML-style front matter")
    result: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return result
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key in result:
            raise ModelLicenseAuditError(f"duplicate model-card front-matter key: {key}")
        result[key] = value
    raise ModelLicenseAuditError("model card front matter is not terminated")


def _apache_2_text_is_observed(raw: bytes) -> bool:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    normalized = "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n"))
    markers = (
        "Apache License",
        "Version 2.0, January 2004",
        "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION",
        "2. Grant of Copyright License.",
        "3. Grant of Patent License.",
        "END OF TERMS AND CONDITIONS",
    )
    return all(marker in normalized for marker in markers)


def audit_model_license(
    *,
    repository_root: Path,
    source_evidence_path: Path,
    created_at: datetime,
) -> dict[str, object]:
    """Audit the exact captured license files without network access or legal inference."""
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ModelLicenseAuditError("audit timestamp must be timezone-aware")
    policy = load_policy(repository_root)
    evidence, evidence_raw = read_json_object(source_evidence_path)
    _validate_content_hash(evidence, label="source evidence")
    if sha256_bytes(evidence_raw) != policy.get("source_evidence_sha256"):
        raise ModelLicenseAuditError("source evidence file differs from the frozen license policy")
    expected_identity = (
        policy.get("candidate_id"),
        policy.get("repository_id"),
        policy.get("revision"),
        policy.get("revision"),
        True,
    )
    observed_identity = (
        evidence.get("candidate_id"),
        evidence.get("repository_id"),
        evidence.get("requested_revision"),
        evidence.get("resolved_revision"),
        evidence.get("complete"),
    )
    if observed_identity != expected_identity:
        raise ModelLicenseAuditError("source evidence identity differs from the frozen candidate")
    if evidence.get("content_hash") != policy.get("source_evidence_content_hash"):
        raise ModelLicenseAuditError("source evidence semantic identity differs from policy")

    license_record = _file_record(evidence, "LICENSE")
    model_card_record = _file_record(evidence, "MODEL_CARD")
    source_root = source_evidence_path.absolute().parent
    _, license_raw = _read_evidence_file(source_root, license_record)
    _, model_card_raw = _read_evidence_file(source_root, model_card_record)

    policy_license = policy.get("license_file")
    policy_card = policy.get("model_card")
    if not isinstance(policy_license, dict) or not isinstance(policy_card, dict):
        raise ModelLicenseAuditError("license policy file records are invalid")
    if (
        license_record.get("relative_path") != policy_license.get("relative_path")
        or license_record.get("sha256") != policy_license.get("sha256")
        or model_card_record.get("relative_path") != policy_card.get("relative_path")
        or model_card_record.get("sha256") != policy_card.get("sha256")
    ):
        raise ModelLicenseAuditError("captured license/model-card digest differs from policy")
    if policy_license.get("expected_family") != EXPECTED_LICENSE_FAMILY:
        raise ModelLicenseAuditError("license policy family changed")
    if not _apache_2_text_is_observed(license_raw):
        raise ModelLicenseAuditError(
            "captured LICENSE does not match the expected Apache-2.0 family"
        )
    try:
        card_text = model_card_raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ModelLicenseAuditError("captured model card is not UTF-8") from error
    front_matter = _front_matter(card_text)
    declared = front_matter.get("license")
    if declared != policy_card.get("declared_license_id"):
        raise ModelLicenseAuditError("model-card license declaration differs from policy")

    result: dict[str, object] = {
        "schema_version": LICENSE_AUDIT_RESULT_SCHEMA_VERSION,
        "policy_id": policy["policy_id"],
        "policy_content_hash": policy["content_hash"],
        "candidate_id": policy["candidate_id"],
        "repository_id": policy["repository_id"],
        "revision": policy["revision"],
        "created_at": created_at.isoformat(),
        "source_evidence_sha256": sha256_bytes(evidence_raw),
        "source_evidence_content_hash": evidence["content_hash"],
        "model_card_sha256": sha256_bytes(model_card_raw),
        "license_file_sha256": sha256_bytes(license_raw),
        "declared_license_id": declared,
        "observed_license_family": "APACHE-2.0",
        "evidence_status": "VERIFIED",
        "review_scope": policy["review_scope"],
        "local_smoke_owner_review_status": "READY_FOR_OWNER_DECISION",
        "owner_approval_status": "NOT_RECORDED",
        "public_adapter_release_review": policy["public_adapter_release_review"],
        "legal_conclusion": "NOT_PERFORMED",
        "network_used": False,
        "training_executed": False,
        "model_selected": False,
    }
    result["content_hash"] = snapshot_hash(result)
    return result


def write_audit(path: Path, payload: Mapping[str, object]) -> None:
    path = path.absolute()
    if path.exists() or path.is_symlink():
        raise ModelLicenseAuditError("license audit output must be a new regular file path")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(payload).encode("utf-8"))
