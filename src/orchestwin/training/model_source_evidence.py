"""Immutable evidence for exact upstream model and tokenizer source files."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final

from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash
from orchestwin.training.model_candidate_matrix_files import (
    FROZEN_MODEL_CANDIDATE_MATRIX_CONTENT_HASH,
    FROZEN_MODEL_CANDIDATE_MATRIX_SHA256,
    FrozenModelCandidateMatrix,
    FrozenModelCandidatePreflight,
)

MODEL_SOURCE_EVIDENCE_SCHEMA_VERSION: Final = 1
_MAX_SOURCE_FILE_BYTES: Final = 100_000_000
_MAX_EVIDENCE_BYTES: Final = 2_000_000
_REPOSITORY_PATTERN: Final = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
)
_REVISION_PATTERN: Final = re.compile(r"[0-9a-f]{40,64}")
_SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}")


class ModelSourceEvidenceError(ValueError):
    """Raised when captured source evidence is incomplete, unsafe, or inconsistent."""


class ModelSourceCaptureMode(StrEnum):
    """Whether the bytes came from an existing cache or an authorized network fetch."""

    CACHE_ONLY = "CACHE_ONLY"
    NETWORK_AUTHORIZED = "NETWORK_AUTHORIZED"


class ModelSourceFileRole(StrEnum):
    """The frozen candidate field supported by one captured upstream file."""

    LICENSE = "LICENSE"
    MODEL_CARD = "MODEL_CARD"
    TOKENIZER_CONFIGURATION = "TOKENIZER_CONFIGURATION"
    TOKENIZER_VOCABULARY = "TOKENIZER_VOCABULARY"


@dataclass(frozen=True, slots=True)
class CapturedModelSourceFile:
    """Content-addressed metadata for one exact file at the candidate revision."""

    relative_path: str
    roles: tuple[ModelSourceFileRole, ...]
    sha256: str
    size_bytes: int
    media_type: str

    def __post_init__(self) -> None:
        _validate_relative_path(self.relative_path, label="captured model source path")
        if self.roles != tuple(sorted(set(self.roles), key=lambda item: item.value)):
            raise ModelSourceEvidenceError("captured source roles must be canonical and unique")
        if not self.roles:
            raise ModelSourceEvidenceError("captured source file requires at least one role")
        _validate_sha256(self.sha256, label="captured model source digest")
        if isinstance(self.size_bytes, bool) or not 0 <= self.size_bytes <= _MAX_SOURCE_FILE_BYTES:
            raise ModelSourceEvidenceError("captured model source size is outside the limit")
        if self.media_type not in {
            "application/json",
            "text/markdown; charset=utf-8",
            "text/plain; charset=utf-8",
        }:
            raise ModelSourceEvidenceError("captured model source media type is unsupported")

    @property
    def sort_key(self) -> str:
        return self.relative_path

    def to_snapshot(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "roles": [role.value for role in self.roles],
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
        }


@dataclass(frozen=True, slots=True)
class CapturedModelSourceEvidence:
    """Complete local evidence for the small upstream files required by one candidate."""

    candidate_id: str
    repository_id: str
    requested_revision: str
    resolved_revision: str
    candidate_matrix_sha256: str
    candidate_matrix_content_hash: str
    capture_mode: ModelSourceCaptureMode
    files: tuple[CapturedModelSourceFile, ...]
    captured_at: datetime
    complete: bool
    content_hash: str
    schema_version: int = MODEL_SOURCE_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MODEL_SOURCE_EVIDENCE_SCHEMA_VERSION:
            raise ModelSourceEvidenceError("unsupported model source evidence schema")
        if _REPOSITORY_PATTERN.fullmatch(self.repository_id) is None:
            raise ModelSourceEvidenceError("captured source repository must use owner/name")
        _validate_revision(self.requested_revision, label="requested model source revision")
        _validate_revision(self.resolved_revision, label="resolved model source revision")
        if self.resolved_revision != self.requested_revision:
            raise ModelSourceEvidenceError("captured source revision differs from the request")
        if self.candidate_matrix_sha256 != FROZEN_MODEL_CANDIDATE_MATRIX_SHA256:
            raise ModelSourceEvidenceError("captured source references a different matrix file")
        if self.candidate_matrix_content_hash != FROZEN_MODEL_CANDIDATE_MATRIX_CONTENT_HASH:
            raise ModelSourceEvidenceError("captured source references different matrix content")
        if self.files != tuple(sorted(self.files, key=lambda item: item.sort_key)):
            raise ModelSourceEvidenceError("captured model source files must use canonical order")
        if len({item.relative_path for item in self.files}) != len(self.files):
            raise ModelSourceEvidenceError("captured model source paths must be unique")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ModelSourceEvidenceError("captured model source timestamp must be timezone-aware")
        if self.complete is not True:
            raise ModelSourceEvidenceError("accepted model source evidence must be complete")
        _validate_sha256(self.content_hash, label="model source evidence content hash")
        if self.content_hash != snapshot_content_hash(self._semantic_snapshot()):
            raise ModelSourceEvidenceError("model source evidence content hash is inconsistent")

    def _semantic_snapshot(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "repository_id": self.repository_id,
            "requested_revision": self.requested_revision,
            "resolved_revision": self.resolved_revision,
            "candidate_matrix_sha256": self.candidate_matrix_sha256,
            "candidate_matrix_content_hash": self.candidate_matrix_content_hash,
            "capture_mode": self.capture_mode.value,
            "files": [item.to_snapshot() for item in self.files],
            "captured_at": self.captured_at.isoformat(),
            "complete": self.complete,
        }

    def to_snapshot(self) -> dict[str, object]:
        return {**self._semantic_snapshot(), "content_hash": self.content_hash}

    def file_for_role(self, role: ModelSourceFileRole) -> CapturedModelSourceFile:
        matches = [item for item in self.files if role in item.roles]
        if len(matches) != 1:
            raise ModelSourceEvidenceError(f"expected one captured source for role {role.value}")
        return matches[0]


def expected_candidate_source_roles(
    candidate: FrozenModelCandidatePreflight,
) -> dict[str, tuple[ModelSourceFileRole, ...]]:
    """Return the exact path-to-role contract frozen in the candidate matrix."""
    roles_by_path: dict[str, set[ModelSourceFileRole]] = {}

    def add(path: str, role: ModelSourceFileRole) -> None:
        _validate_relative_path(path, label="candidate source path")
        roles_by_path.setdefault(path, set()).add(role)

    add(candidate.artifact_capture.model_card_path, ModelSourceFileRole.MODEL_CARD)
    add(candidate.license.artifact_path, ModelSourceFileRole.LICENSE)
    add(
        candidate.artifact_capture.tokenizer_configuration_path,
        ModelSourceFileRole.TOKENIZER_CONFIGURATION,
    )
    for path in candidate.artifact_capture.tokenizer_vocabulary_paths:
        add(path, ModelSourceFileRole.TOKENIZER_VOCABULARY)
    return {
        path: tuple(sorted(roles, key=lambda item: item.value))
        for path, roles in sorted(roles_by_path.items())
    }


def create_captured_model_source_evidence(
    *,
    candidate: FrozenModelCandidatePreflight,
    captured_files: Mapping[str, bytes],
    capture_mode: ModelSourceCaptureMode,
    captured_at: datetime,
    resolved_revision: str,
) -> CapturedModelSourceEvidence:
    """Bind exact captured bytes to one frozen candidate without network side effects."""
    expected = expected_candidate_source_roles(candidate)
    if set(captured_files) != set(expected):
        missing = sorted(set(expected) - set(captured_files))
        unexpected = sorted(set(captured_files) - set(expected))
        raise ModelSourceEvidenceError(
            f"captured source path set changed; missing={missing}, unexpected={unexpected}"
        )
    files = tuple(
        _captured_file(path=path, roles=expected[path], content=captured_files[path])
        for path in sorted(expected)
    )
    semantic = {
        "schema_version": MODEL_SOURCE_EVIDENCE_SCHEMA_VERSION,
        "candidate_id": candidate.candidate_id,
        "repository_id": candidate.repository_id,
        "requested_revision": candidate.revision,
        "resolved_revision": resolved_revision,
        "candidate_matrix_sha256": FROZEN_MODEL_CANDIDATE_MATRIX_SHA256,
        "candidate_matrix_content_hash": FROZEN_MODEL_CANDIDATE_MATRIX_CONTENT_HASH,
        "capture_mode": capture_mode.value,
        "files": [item.to_snapshot() for item in files],
        "captured_at": captured_at.isoformat(),
        "complete": True,
    }
    evidence = CapturedModelSourceEvidence(
        candidate_id=candidate.candidate_id,
        repository_id=candidate.repository_id,
        requested_revision=candidate.revision,
        resolved_revision=resolved_revision,
        candidate_matrix_sha256=FROZEN_MODEL_CANDIDATE_MATRIX_SHA256,
        candidate_matrix_content_hash=FROZEN_MODEL_CANDIDATE_MATRIX_CONTENT_HASH,
        capture_mode=capture_mode,
        files=files,
        captured_at=captured_at,
        complete=True,
        content_hash=snapshot_content_hash(semantic),
    )
    validate_captured_model_source_evidence(evidence=evidence, candidate=candidate)
    return evidence


def parse_captured_model_source_evidence(
    payload: Mapping[str, object],
    *,
    matrix: FrozenModelCandidateMatrix,
) -> CapturedModelSourceEvidence:
    """Parse a strict canonical evidence snapshot and validate its frozen candidate link."""
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "candidate_id",
            "repository_id",
            "requested_revision",
            "resolved_revision",
            "candidate_matrix_sha256",
            "candidate_matrix_content_hash",
            "capture_mode",
            "files",
            "captured_at",
            "complete",
            "content_hash",
        },
        label="model source evidence",
    )
    raw_files = payload.get("files")
    if not isinstance(raw_files, list):
        raise ModelSourceEvidenceError("model source evidence files must be an array")
    files = tuple(_parse_source_file(item) for item in raw_files)
    captured_at_raw = _required_string(payload, "captured_at")
    try:
        captured_at = datetime.fromisoformat(captured_at_raw)
    except ValueError as error:
        raise ModelSourceEvidenceError("captured_at must use ISO-8601") from error
    complete = payload.get("complete")
    if not isinstance(complete, bool):
        raise ModelSourceEvidenceError("model source complete must be boolean")
    try:
        capture_mode = ModelSourceCaptureMode(_required_string(payload, "capture_mode"))
    except ValueError as error:
        raise ModelSourceEvidenceError("unsupported model source capture mode") from error
    evidence = CapturedModelSourceEvidence(
        schema_version=_required_integer(payload, "schema_version"),
        candidate_id=_required_string(payload, "candidate_id"),
        repository_id=_required_string(payload, "repository_id"),
        requested_revision=_required_string(payload, "requested_revision"),
        resolved_revision=_required_string(payload, "resolved_revision"),
        candidate_matrix_sha256=_required_string(payload, "candidate_matrix_sha256"),
        candidate_matrix_content_hash=_required_string(payload, "candidate_matrix_content_hash"),
        capture_mode=capture_mode,
        files=files,
        captured_at=captured_at,
        complete=complete,
        content_hash=_required_string(payload, "content_hash"),
    )
    try:
        candidate = matrix.candidate(evidence.candidate_id)
    except StopIteration as error:
        raise ModelSourceEvidenceError("captured source candidate is not frozen") from error
    validate_captured_model_source_evidence(evidence=evidence, candidate=candidate)
    if evidence.to_snapshot() != dict(payload):
        raise ModelSourceEvidenceError("model source evidence is not a canonical snapshot")
    return evidence


def load_captured_model_source_evidence(
    path: Path,
    *,
    matrix: FrozenModelCandidateMatrix,
) -> CapturedModelSourceEvidence:
    """Load a bounded regular UTF-8 JSON evidence file."""
    if path.is_symlink() or not path.is_file():
        raise ModelSourceEvidenceError("model source evidence path must be a regular file")
    raw = path.read_bytes()
    if len(raw) > _MAX_EVIDENCE_BYTES:
        raise ModelSourceEvidenceError("model source evidence exceeds the size limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelSourceEvidenceError("model source evidence must be UTF-8 JSON") from error
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        raise ModelSourceEvidenceError("model source evidence must contain a JSON object")
    return parse_captured_model_source_evidence(payload, matrix=matrix)


def serialize_captured_model_source_evidence(evidence: CapturedModelSourceEvidence) -> bytes:
    """Serialize one evidence snapshot canonically for content-addressed storage."""
    return canonical_json(evidence.to_snapshot()).encode("utf-8")


def validate_captured_model_source_evidence(
    *,
    evidence: CapturedModelSourceEvidence,
    candidate: FrozenModelCandidatePreflight,
) -> None:
    """Require exact candidate identity, expected files, and role coverage."""
    if (
        evidence.candidate_id,
        evidence.repository_id,
        evidence.requested_revision,
        evidence.resolved_revision,
    ) != (
        candidate.candidate_id,
        candidate.repository_id,
        candidate.revision,
        candidate.revision,
    ):
        raise ModelSourceEvidenceError("captured source identity differs from frozen candidate")
    observed_roles = {item.relative_path: item.roles for item in evidence.files}
    if observed_roles != expected_candidate_source_roles(candidate):
        raise ModelSourceEvidenceError("captured source files do not satisfy the frozen plan")


def _captured_file(
    *,
    path: str,
    roles: tuple[ModelSourceFileRole, ...],
    content: bytes,
) -> CapturedModelSourceFile:
    if not isinstance(content, bytes):
        raise ModelSourceEvidenceError("captured model source content must be bytes")
    if len(content) > _MAX_SOURCE_FILE_BYTES:
        raise ModelSourceEvidenceError("captured model source file exceeds the size limit")
    return CapturedModelSourceFile(
        relative_path=path,
        roles=roles,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        media_type=_media_type(path),
    )


def _media_type(path: str) -> str:
    suffix = PurePosixPath(path).suffix.casefold()
    if suffix == ".json":
        return "application/json"
    if suffix in {".md", ".markdown"}:
        return "text/markdown; charset=utf-8"
    return "text/plain; charset=utf-8"


def _parse_source_file(value: object) -> CapturedModelSourceFile:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ModelSourceEvidenceError("captured source file must be an object")
    _require_exact_keys(
        value,
        {"relative_path", "roles", "sha256", "size_bytes", "media_type"},
        label="captured source file",
    )
    raw_roles = value.get("roles")
    if not isinstance(raw_roles, list) or not all(isinstance(item, str) for item in raw_roles):
        raise ModelSourceEvidenceError("captured source roles must be an array of strings")
    try:
        roles = tuple(ModelSourceFileRole(item) for item in raw_roles)
    except ValueError as error:
        raise ModelSourceEvidenceError("captured source role is unsupported") from error
    return CapturedModelSourceFile(
        relative_path=_required_string(value, "relative_path"),
        roles=roles,
        sha256=_required_string(value, "sha256"),
        size_bytes=_required_integer(value, "size_bytes"),
        media_type=_required_string(value, "media_type"),
    )


def _validate_relative_path(value: str, *, label: str) -> None:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ModelSourceEvidenceError(f"{label} must be a relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ModelSourceEvidenceError(f"{label} must be traversal-free")


def _validate_revision(value: str, *, label: str) -> None:
    if _REVISION_PATTERN.fullmatch(value) is None:
        raise ModelSourceEvidenceError(f"{label} must be an exact lowercase revision")


def _validate_sha256(value: str, *, label: str) -> None:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ModelSourceEvidenceError(f"{label} must use lowercase SHA-256")


def _require_exact_keys(
    payload: Mapping[str, object],
    expected: set[str],
    *,
    label: str,
) -> None:
    if set(payload) != expected:
        raise ModelSourceEvidenceError(f"{label} fields do not match schema version 1")


def _required_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ModelSourceEvidenceError(f"{key} must be a normalized string")
    return value


def _required_integer(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ModelSourceEvidenceError(f"{key} must be an integer")
    return value
