"""Canonical, verified snapshots for immutable Jvm repair proposals."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from uuid import UUID

from orchestwin.artifacts.jvm_change_sets import (
    JvmSourceChange,
    JvmSourceChangeOperation,
    JvmSourceChangeSet,
)
from orchestwin.artifacts.jvm_sources import (
    JvmSourceProvenanceKind,
    JvmSourceProvenanceReference,
    JvmSourceRevisionReference,
)
from orchestwin.jvm_execution.evidence import JvmFailureCategory, JvmFailureSignature
from orchestwin.jvm_execution.plans import JvmExecutionPhase
from orchestwin.workflow.jvm_repair import JvmRepairProposal

_HASH = re.compile(r"^[0-9a-f]{64}$")
_MAX_SNAPSHOT_BYTES = 1024 * 1024


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("Jvm repair snapshot is not canonical JSON") from exc
    if len(encoded) > _MAX_SNAPSHOT_BYTES:
        raise ValueError("Jvm repair snapshot exceeds its byte limit")
    return encoded


def jvm_repair_proposal_to_snapshot(proposal: JvmRepairProposal) -> dict[str, object]:
    """Bind the complete proposal, including content references and accounting."""
    body = {
        "schema_version": 1,
        "id": str(proposal.id),
        "project_id": str(proposal.project_id),
        "created_by_user_id": str(proposal.created_by_user_id),
        "base_revision": proposal.base_revision.to_snapshot(),
        "failure_signature": proposal.failure_signature.to_snapshot(),
        "change_set": proposal.change_set.to_snapshot(),
        "attempt_number": proposal.attempt_number,
        "identical_failure_occurrences": proposal.identical_failure_occurrences,
        "provenance_references": [item.to_snapshot() for item in proposal.provenance_references],
        "created_at": proposal.created_at.isoformat(),
    }
    return {**body, "content_hash": hashlib.sha256(_canonical(body)).hexdigest()}


def jvm_repair_proposal_from_snapshot(value: object) -> JvmRepairProposal:
    """Hydrate only exact schemas whose embedded and complete hashes all match."""
    data = _object(
        value,
        "schema_version id project_id created_by_user_id base_revision failure_signature "
        "change_set attempt_number identical_failure_occurrences provenance_references "
        "created_at content_hash",
    )
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported Jvm repair snapshot schema")
    expected = _hash(data["content_hash"])
    body = {key: item for key, item in data.items() if key != "content_hash"}
    if hashlib.sha256(_canonical(body)).hexdigest() != expected:
        raise ValueError("Jvm repair proposal hash mismatch")
    created_at = datetime.fromisoformat(_text(data["created_at"]))
    if created_at.isoformat() != data["created_at"]:
        raise ValueError("Jvm repair timestamp is not canonical")
    proposal = JvmRepairProposal(
        id=_uuid(data["id"]),
        project_id=_uuid(data["project_id"]),
        created_by_user_id=_uuid(data["created_by_user_id"]),
        base_revision=_reference(data["base_revision"]),
        failure_signature=_failure(data["failure_signature"]),
        change_set=_change_set(data["change_set"]),
        attempt_number=_positive(data["attempt_number"]),
        identical_failure_occurrences=_positive(data["identical_failure_occurrences"]),
        provenance_references=tuple(
            _provenance(item) for item in _array(data["provenance_references"], maximum=1000)
        ),
        created_at=created_at,
    )
    if _canonical(jvm_repair_proposal_to_snapshot(proposal)) != _canonical(data):
        raise ValueError("Jvm repair proposal snapshot is inconsistent")
    return proposal


def _reference(value: object) -> JvmSourceRevisionReference:
    data = _object(value, "revision_id project_id version_number content_hash source_tree_hash")
    return JvmSourceRevisionReference(
        revision_id=_uuid(data["revision_id"]),
        project_id=_uuid(data["project_id"]),
        version_number=_positive(data["version_number"]),
        content_hash=_hash(data["content_hash"]),
        source_tree_hash=_hash(data["source_tree_hash"]),
    )


def _failure(value: object) -> JvmFailureSignature:
    data = _object(value, "category phase failure_code normalized_message signature")
    return JvmFailureSignature(
        category=JvmFailureCategory(_text(data["category"])),
        phase=JvmExecutionPhase(_text(data["phase"])),
        failure_code=_text(data["failure_code"]),
        normalized_message=_text(data["normalized_message"]),
        signature=_hash(data["signature"]),
    )


def _change_set(value: object) -> JvmSourceChangeSet:
    data = _object(
        value, "id project_id base_revision changes rationale provenance_references content_hash"
    )
    change_set = JvmSourceChangeSet(
        id=_uuid(data["id"]),
        project_id=_uuid(data["project_id"]),
        base_revision=_reference(data["base_revision"]),
        changes=tuple(_change(item) for item in _array(data["changes"], maximum=128)),
        rationale=_text(data["rationale"]),
        provenance_references=tuple(
            _text(item) for item in _array(data["provenance_references"], maximum=1000)
        ),
    )
    if change_set.content_hash != _hash(data["content_hash"]):
        raise ValueError("Jvm repair change-set hash mismatch")
    return change_set


def _change(value: object) -> JvmSourceChange:
    data = _object(
        value, "normalized_path operation content_sha256 size_bytes storage_key media_type"
    )
    operation = JvmSourceChangeOperation(_text(data["operation"]))
    digest = data["content_sha256"]
    size = data["size_bytes"]
    storage_key = data["storage_key"]
    media_type = data["media_type"]
    if operation is not JvmSourceChangeOperation.DELETE:
        digest = _hash(digest)
        if type(size) is not int or size < 0:
            raise ValueError("Jvm repair content size must be a nonnegative integer")
        if _text(storage_key) != f"sha256/{digest[:2]}/{digest}":
            raise ValueError("Jvm repair content key does not match its digest")
        media_type = _text(media_type)
    return JvmSourceChange(
        normalized_path=_text(data["normalized_path"]),
        operation=operation,
        content_sha256=digest,
        size_bytes=size,
        storage_key=storage_key,
        media_type=media_type,
    )


def _provenance(value: object) -> JvmSourceProvenanceReference:
    data = _object(value, "kind reference_id version_number content_hash")
    return JvmSourceProvenanceReference(
        kind=JvmSourceProvenanceKind(_text(data["kind"])),
        reference_id=_text(data["reference_id"]),
        version_number=_positive(data["version_number"]),
        content_hash=_hash(data["content_hash"]),
    )


def _object(value: object, fields: str) -> dict:
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        raise ValueError("Jvm repair snapshot fields are invalid")
    return value


def _array(value: object, *, maximum: int) -> list:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError("Jvm repair snapshot array is invalid")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Jvm repair snapshot text is invalid")
    return value


def _hash(value: object) -> str:
    if not _HASH.fullmatch(_text(value)):
        raise ValueError("Jvm repair snapshot digest is invalid")
    return value


def _uuid(value: object) -> UUID:
    result = UUID(_text(value))
    if str(result) != value:
        raise ValueError("Jvm repair snapshot UUID is not canonical")
    return result


def _positive(value: object) -> int:
    if type(value) is not int or value < 1:
        raise ValueError("Jvm repair accounting requires positive integers")
    return value
