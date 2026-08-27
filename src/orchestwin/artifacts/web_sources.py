"""Immutable, content-addressed Web source revisions and provenance."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final
from uuid import UUID

from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.web_execution.targets import (
    WebLanguageConfiguration,
    WebProjectLayout,
    WebTargetSelection,
    web_scope_for,
)

_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_STORAGE_KEY_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,1023}$")
_PROVENANCE_ID_PATTERN: Final = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:[._:-][A-Za-z0-9]+)*$")


class WebSourceOrigin(StrEnum):
    """Inspectable origin of one immutable source-tree version."""

    GENERATED_PLAN = "GENERATED_PLAN"
    IMPORTED_BROWNFIELD = "IMPORTED_BROWNFIELD"
    REPAIR_CHANGE_SET = "REPAIR_CHANGE_SET"
    DETERMINISTIC_FIXTURE = "DETERMINISTIC_FIXTURE"


class WebSourceProvenanceKind(StrEnum):
    """Artifact families that may justify a source revision."""

    PROJECT_BRIEF = "PROJECT_BRIEF"
    REQUIREMENTS = "REQUIREMENTS"
    DESIGN = "DESIGN"
    ARCHITECTURE = "ARCHITECTURE"
    TEST_PLAN = "TEST_PLAN"
    SOURCE_PLAN = "SOURCE_PLAN"
    FAILURE_SIGNATURE = "FAILURE_SIGNATURE"
    OWNER_DECISION = "OWNER_DECISION"


@dataclass(frozen=True, slots=True, order=True)
class WebSourceFileEntry:
    """One source file represented through immutable content-addressed metadata."""

    normalized_path: str
    sha256_digest: str
    size_bytes: int
    storage_key: str
    media_type: str

    def __post_init__(self) -> None:
        _validate_relative_path(self.normalized_path)
        _validate_sha256(self.sha256_digest, label="Web source file digest")
        if isinstance(self.size_bytes, bool) or self.size_bytes < 0:
            raise ValueError("Web source file size must not be negative")
        if not _STORAGE_KEY_PATTERN.fullmatch(self.storage_key):
            raise ValueError("Web source file storage key must be normalized")
        _validate_normalized_text(self.media_type, label="Web source file media type")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "normalized_path": self.normalized_path,
            "sha256_digest": self.sha256_digest,
            "size_bytes": self.size_bytes,
            "storage_key": self.storage_key,
            "media_type": self.media_type,
        }


@dataclass(frozen=True, slots=True, order=True)
class WebSourceProvenanceReference:
    """Exact approved artifact or decision referenced by a source revision."""

    kind: WebSourceProvenanceKind
    reference_id: str
    version_number: int
    content_hash: str

    def __post_init__(self) -> None:
        if not _PROVENANCE_ID_PATTERN.fullmatch(self.reference_id):
            raise ValueError("Web source provenance ID must be normalized")
        if isinstance(self.version_number, bool) or self.version_number < 1:
            raise ValueError("Web source provenance version must be positive")
        _validate_sha256(self.content_hash, label="Web source provenance hash")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "reference_id": self.reference_id,
            "version_number": self.version_number,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class WebSourceRevisionReference:
    """Exact immutable source revision tuple for execution and repair binding."""

    revision_id: UUID
    project_id: UUID
    version_number: int
    content_hash: str
    source_tree_hash: str

    def __post_init__(self) -> None:
        if isinstance(self.version_number, bool) or self.version_number < 1:
            raise ValueError("Web source revision reference version must be positive")
        _validate_sha256(self.content_hash, label="Web source revision reference hash")
        _validate_sha256(self.source_tree_hash, label="Web source tree reference hash")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "revision_id": str(self.revision_id),
            "project_id": str(self.project_id),
            "version_number": self.version_number,
            "content_hash": self.content_hash,
            "source_tree_hash": self.source_tree_hash,
        }


@dataclass(frozen=True, slots=True)
class WebSourceRevision:
    """Append-only source-tree version with exact lineage and provenance."""

    id: UUID
    project_id: UUID
    created_by_user_id: UUID
    version_number: int
    based_on: WebSourceRevisionReference | None
    target_selection: WebTargetSelection
    validation_scope_hash: str
    origin: WebSourceOrigin
    files: tuple[WebSourceFileEntry, ...]
    provenance_references: tuple[WebSourceProvenanceReference, ...]
    related_failure_signature: str | None
    created_at: datetime

    def __post_init__(self) -> None:
        if isinstance(self.version_number, bool) or self.version_number < 1:
            raise ValueError("Web source revision version must be positive")
        self.target_selection.validate_against(web_scope_for(self.target_selection.target))
        _validate_sha256(self.validation_scope_hash, label="Web validation scope hash")
        _require_canonical_files(self.files)
        if not self.files:
            raise ValueError("Web source revision requires at least one file")
        _require_canonical_provenance(self.provenance_references)
        if not self.provenance_references:
            raise ValueError("Web source revision requires provenance")
        if self.related_failure_signature is not None:
            _validate_sha256(
                self.related_failure_signature,
                label="Web source failure signature",
            )
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Web source revision timestamp must be timezone-aware")
        _validate_lineage(self)
        if self.origin is WebSourceOrigin.REPAIR_CHANGE_SET:
            if self.based_on is None or self.related_failure_signature is None:
                raise ValueError("repair revision requires a predecessor and failure signature")
        elif self.related_failure_signature is not None:
            raise ValueError("only repair revisions may reference a failure signature")

    @property
    def source_tree_hash(self) -> str:
        """Hash only the canonical path/content projection of the source tree."""
        return hashlib.sha256(
            _canonical_json(
                {
                    "files": [
                        {
                            "normalized_path": file.normalized_path,
                            "sha256_digest": file.sha256_digest,
                            "size_bytes": file.size_bytes,
                        }
                        for file in self.files
                    ]
                }
            )
        ).hexdigest()

    @property
    def content_hash(self) -> str:
        """Hash revision identity, lineage, scope, files, and provenance."""
        return hashlib.sha256(_canonical_json(self._content_snapshot())).hexdigest()

    @property
    def reference(self) -> WebSourceRevisionReference:
        return WebSourceRevisionReference(
            revision_id=self.id,
            project_id=self.project_id,
            version_number=self.version_number,
            content_hash=self.content_hash,
            source_tree_hash=self.source_tree_hash,
        )

    def file_by_path(self, normalized_path: str) -> WebSourceFileEntry | None:
        return next(
            (file for file in self.files if file.normalized_path == normalized_path),
            None,
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            **self._content_snapshot(),
            "source_tree_hash": self.source_tree_hash,
            "content_hash": self.content_hash,
        }

    def _content_snapshot(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "created_by_user_id": str(self.created_by_user_id),
            "version_number": self.version_number,
            "based_on": None if self.based_on is None else self.based_on.to_snapshot(),
            "target_selection": self.target_selection.to_snapshot(),
            "validation_scope_hash": self.validation_scope_hash,
            "origin": self.origin.value,
            "files": [file.to_snapshot() for file in self.files],
            "provenance_references": [
                reference.to_snapshot() for reference in self.provenance_references
            ],
            "related_failure_signature": self.related_failure_signature,
            "created_at": self.created_at.isoformat(),
        }


def create_web_source_revision(
    *,
    revision_id: UUID,
    project_id: UUID,
    created_by_user_id: UUID,
    version_number: int,
    based_on: WebSourceRevisionReference | None,
    target: ExecutionTarget,
    language_configuration: WebLanguageConfiguration,
    layout: WebProjectLayout,
    origin: WebSourceOrigin,
    files: tuple[WebSourceFileEntry, ...],
    provenance_references: tuple[WebSourceProvenanceReference, ...],
    created_at: datetime,
    related_failure_signature: str | None = None,
) -> WebSourceRevision:
    """Create one revision bound to the current target validation-scope hash."""
    selection = WebTargetSelection(
        target=target,
        language_configuration=language_configuration,
        layout=layout,
    )
    scope = web_scope_for(target)
    selection.validate_against(scope)
    return WebSourceRevision(
        id=revision_id,
        project_id=project_id,
        created_by_user_id=created_by_user_id,
        version_number=version_number,
        based_on=based_on,
        target_selection=selection,
        validation_scope_hash=scope.content_hash,
        origin=origin,
        files=files,
        provenance_references=provenance_references,
        related_failure_signature=related_failure_signature,
        created_at=created_at,
    )


def _validate_lineage(revision: WebSourceRevision) -> None:
    if revision.version_number == 1:
        if revision.based_on is not None:
            raise ValueError("first Web source revision cannot have a predecessor")
        return
    if revision.based_on is None:
        raise ValueError("later Web source revision requires a predecessor")
    if revision.based_on.project_id != revision.project_id:
        raise ValueError("Web source revision predecessor belongs to another project")
    if revision.based_on.version_number != revision.version_number - 1:
        raise ValueError("Web source revision lineage must be linear")


def _require_canonical_files(files: tuple[WebSourceFileEntry, ...]) -> None:
    ordered = tuple(
        sorted(files, key=lambda item: (item.normalized_path.casefold(), item.normalized_path))
    )
    if files != ordered:
        raise ValueError("Web source files must use canonical path order")
    canonical_paths = tuple(file.normalized_path.casefold() for file in files)
    if len(canonical_paths) != len(set(canonical_paths)):
        raise ValueError("Web source file paths must be canonically unique")


def _require_canonical_provenance(
    references: tuple[WebSourceProvenanceReference, ...],
) -> None:
    ordered = tuple(
        sorted(
            references,
            key=lambda item: (item.kind.value, item.reference_id, item.version_number),
        )
    )
    if references != ordered or len(references) != len(set(references)):
        raise ValueError("Web source provenance must be canonical and unique")


def _validate_relative_path(path: str) -> None:
    if (
        not path
        or path != path.strip()
        or "\\" in path
        or path.startswith("/")
        or PurePosixPath(path).is_absolute()
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        raise ValueError("Web source file path must be a normalized relative POSIX path")


def _validate_sha256(value: str, *, label: str) -> None:
    if not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must be lowercase SHA-256")


def _validate_normalized_text(value: str, *, label: str) -> None:
    if not value or value != value.strip() or any(character in value for character in "\r\n\x00"):
        raise ValueError(f"{label} must be normalized")


def _canonical_json(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
