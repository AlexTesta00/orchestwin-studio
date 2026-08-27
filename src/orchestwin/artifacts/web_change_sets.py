"""Typed, workspace-confined Web source change-set validation."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final
from uuid import UUID

from orchestwin.artifacts.web_sources import (
    WebSourceFileEntry,
    WebSourceRevision,
    WebSourceRevisionReference,
)

_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_MAX_CHANGE_COUNT: Final = 1_000
_MAX_FILE_SIZE_BYTES: Final = 25 * 1024 * 1024
_PROTECTED_COMPONENTS: Final = frozenset({".git", ".orchestwin", ".ssh"})
_GENERATED_COMPONENTS: Final = frozenset({"build", "coverage", "dist", "node_modules", "vendor"})
_HIGH_IMPACT_NAMES: Final = frozenset(
    {
        ".npmrc",
        "composer.json",
        "composer.lock",
        "compose.yaml",
        "compose.yml",
        "docker-compose.yaml",
        "docker-compose.yml",
        "dockerfile",
        "package-lock.json",
        "package.json",
        "tsconfig.json",
        "vite.config.js",
        "vite.config.mjs",
        "vite.config.ts",
    }
)


class WebSourceChangeOperation(StrEnum):
    """Allowed source-tree operations; directory mutations are implicit."""

    ADD = "ADD"
    REPLACE = "REPLACE"
    DELETE = "DELETE"


class WebSourceChangeImpact(StrEnum):
    """Governance impact of one validated complete change set."""

    STANDARD = "STANDARD"
    REQUIRES_GATE_7 = "REQUIRES_GATE_7"
    FORBIDDEN = "FORBIDDEN"


class WebSourceChangeValidationStatus(StrEnum):
    """Typed outcome used before any filesystem materialization."""

    ACCEPTED = "ACCEPTED"
    REQUIRES_OWNER_APPROVAL = "REQUIRES_OWNER_APPROVAL"
    REJECTED = "REJECTED"


class WebSourceChangeIssueCode(StrEnum):
    """Stable source-change validation reasons."""

    BASE_REVISION_MISMATCH = "BASE_REVISION_MISMATCH"
    PROTECTED_PATH = "PROTECTED_PATH"
    GENERATED_PATH = "GENERATED_PATH"
    TARGET_ALREADY_EXISTS = "TARGET_ALREADY_EXISTS"
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    REPLACEMENT_UNCHANGED = "REPLACEMENT_UNCHANGED"
    HIGH_IMPACT_FILE = "HIGH_IMPACT_FILE"


@dataclass(frozen=True, slots=True, order=True)
class WebSourceChange:
    """One typed file operation containing content metadata, never raw bytes."""

    normalized_path: str
    operation: WebSourceChangeOperation
    content_sha256: str | None
    size_bytes: int | None
    storage_key: str | None
    media_type: str | None

    def __post_init__(self) -> None:
        _validate_relative_path(self.normalized_path)
        if self.operation is WebSourceChangeOperation.DELETE:
            if any(
                value is not None
                for value in (
                    self.content_sha256,
                    self.size_bytes,
                    self.storage_key,
                    self.media_type,
                )
            ):
                raise ValueError("delete Web source change must not carry replacement content")
            return
        if self.content_sha256 is None or not _SHA256_PATTERN.fullmatch(self.content_sha256):
            raise ValueError("add or replace Web source change requires a SHA-256 digest")
        if (
            self.size_bytes is None
            or isinstance(self.size_bytes, bool)
            or not 0 <= self.size_bytes <= _MAX_FILE_SIZE_BYTES
        ):
            raise ValueError("add or replace Web source change requires a bounded file size")
        if self.storage_key is None or not self.storage_key.startswith("sha256/"):
            raise ValueError("add or replace Web source change requires a storage key")
        if self.media_type is None or "/" not in self.media_type:
            raise ValueError("add or replace Web source change requires a media type")
        if self.media_type != self.media_type.strip():
            raise ValueError("Web source change media type must be normalized")

    @property
    def targets_protected_path(self) -> bool:
        return bool(_path_components(self.normalized_path) & _PROTECTED_COMPONENTS)

    @property
    def targets_generated_path(self) -> bool:
        return bool(_path_components(self.normalized_path) & _GENERATED_COMPONENTS)

    @property
    def is_high_impact(self) -> bool:
        name = PurePosixPath(self.normalized_path).name.casefold()
        return (
            name in _HIGH_IMPACT_NAMES
            or name.startswith(".env")
            or self.normalized_path.startswith("infra/web-runners/")
        )

    def to_file_entry(self) -> WebSourceFileEntry:
        """Project add/replace metadata into a future immutable source entry."""
        if self.operation is WebSourceChangeOperation.DELETE:
            raise ValueError("delete Web source change has no future file entry")
        assert self.content_sha256 is not None
        assert self.size_bytes is not None
        assert self.storage_key is not None
        assert self.media_type is not None
        return WebSourceFileEntry(
            normalized_path=self.normalized_path,
            sha256_digest=self.content_sha256,
            size_bytes=self.size_bytes,
            storage_key=self.storage_key,
            media_type=self.media_type,
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "normalized_path": self.normalized_path,
            "operation": self.operation.value,
            "content_sha256": self.content_sha256,
            "size_bytes": self.size_bytes,
            "storage_key": self.storage_key,
            "media_type": self.media_type,
        }


@dataclass(frozen=True, slots=True)
class WebSourceChangeSet:
    """Immutable source proposal bound to one exact base revision."""

    id: UUID
    project_id: UUID
    base_revision: WebSourceRevisionReference
    changes: tuple[WebSourceChange, ...]
    rationale: str
    provenance_references: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.project_id != self.base_revision.project_id:
            raise ValueError("Web source change set and base revision projects differ")
        if not self.changes:
            raise ValueError("Web source change set requires at least one operation")
        if len(self.changes) > _MAX_CHANGE_COUNT:
            raise ValueError("Web source change set exceeds the operation limit")
        ordered = tuple(
            sorted(
                self.changes,
                key=lambda item: (item.normalized_path.casefold(), item.normalized_path),
            )
        )
        if self.changes != ordered:
            raise ValueError("Web source changes must use canonical path order")
        canonical_paths = tuple(change.normalized_path.casefold() for change in self.changes)
        if len(canonical_paths) != len(set(canonical_paths)):
            raise ValueError("Web source change paths must be canonically unique")
        _validate_normalized_text(self.rationale, label="Web source change rationale")
        _require_canonical_text(
            self.provenance_references,
            label="Web source change provenance",
        )
        if not self.provenance_references:
            raise ValueError("Web source change set requires provenance")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self._content_snapshot())).hexdigest()

    def to_snapshot(self) -> dict[str, object]:
        return {**self._content_snapshot(), "content_hash": self.content_hash}

    def _content_snapshot(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "base_revision": self.base_revision.to_snapshot(),
            "changes": [change.to_snapshot() for change in self.changes],
            "rationale": self.rationale,
            "provenance_references": list(self.provenance_references),
        }


@dataclass(frozen=True, slots=True, order=True)
class WebSourceChangeIssue:
    """One deterministic validation issue tied to an optional path."""

    code: WebSourceChangeIssueCode
    path: str | None
    message: str

    def __post_init__(self) -> None:
        if self.path is not None:
            _validate_relative_path(self.path)
        _validate_normalized_text(self.message, label="Web source change issue")

    def to_snapshot(self) -> dict[str, str | None]:
        return {"code": self.code.value, "path": self.path, "message": self.message}


@dataclass(frozen=True, slots=True)
class WebSourceChangeValidationReport:
    """Decision for one exact change-set/base-revision tuple."""

    change_set_content_hash: str
    base_revision_content_hash: str
    status: WebSourceChangeValidationStatus
    impact: WebSourceChangeImpact
    issues: tuple[WebSourceChangeIssue, ...]

    def __post_init__(self) -> None:
        _validate_sha256(self.change_set_content_hash, label="Web change-set hash")
        _validate_sha256(self.base_revision_content_hash, label="Web base revision hash")
        ordered = tuple(sorted(self.issues, key=lambda item: (item.code.value, item.path or "")))
        if self.issues != ordered or len(self.issues) != len(set(self.issues)):
            raise ValueError("Web source change issues must be canonical and unique")
        if self.status is WebSourceChangeValidationStatus.ACCEPTED:
            if self.issues or self.impact is not WebSourceChangeImpact.STANDARD:
                raise ValueError("accepted source change report must be standard and issue-free")
        elif self.status is WebSourceChangeValidationStatus.REQUIRES_OWNER_APPROVAL:
            if self.impact is not WebSourceChangeImpact.REQUIRES_GATE_7:
                raise ValueError("owner approval report must represent Gate 7 impact")
            if any(
                issue.code is not WebSourceChangeIssueCode.HIGH_IMPACT_FILE for issue in self.issues
            ):
                raise ValueError("owner approval report must not hide rejection issues")
        elif self.impact is not WebSourceChangeImpact.FORBIDDEN or not self.issues:
            raise ValueError("rejected source change report requires forbidden issues")

    @property
    def is_applicable(self) -> bool:
        return self.status is not WebSourceChangeValidationStatus.REJECTED


def create_web_source_change_set(
    *,
    change_set_id: UUID,
    project_id: UUID,
    base_revision: WebSourceRevisionReference,
    changes: Iterable[WebSourceChange],
    rationale: str,
    provenance_references: Iterable[str],
) -> WebSourceChangeSet:
    """Canonicalize caller collections before deterministic validation."""
    return WebSourceChangeSet(
        id=change_set_id,
        project_id=project_id,
        base_revision=base_revision,
        changes=tuple(
            sorted(
                changes,
                key=lambda item: (item.normalized_path.casefold(), item.normalized_path),
            )
        ),
        rationale=rationale,
        provenance_references=tuple(sorted(set(provenance_references))),
    )


def validate_web_source_change_set(
    change_set: WebSourceChangeSet,
    *,
    base_revision: WebSourceRevision,
) -> WebSourceChangeValidationReport:
    """Validate path safety, exact base binding, and file operation semantics."""
    issues: list[WebSourceChangeIssue] = []
    if change_set.base_revision != base_revision.reference:
        issues.append(
            WebSourceChangeIssue(
                code=WebSourceChangeIssueCode.BASE_REVISION_MISMATCH,
                path=None,
                message="Source change set targets another base revision.",
            )
        )
    current_files = {file.normalized_path: file for file in base_revision.files}
    for change in change_set.changes:
        if change.targets_protected_path:
            issues.append(
                WebSourceChangeIssue(
                    code=WebSourceChangeIssueCode.PROTECTED_PATH,
                    path=change.normalized_path,
                    message="Source change targets a protected workspace path.",
                )
            )
            continue
        if change.targets_generated_path:
            issues.append(
                WebSourceChangeIssue(
                    code=WebSourceChangeIssueCode.GENERATED_PATH,
                    path=change.normalized_path,
                    message="Source change targets generated dependency or build output.",
                )
            )
            continue
        current = current_files.get(change.normalized_path)
        if change.operation is WebSourceChangeOperation.ADD and current is not None:
            issues.append(
                WebSourceChangeIssue(
                    code=WebSourceChangeIssueCode.TARGET_ALREADY_EXISTS,
                    path=change.normalized_path,
                    message="ADD operation targets an existing source file.",
                )
            )
        elif (
            change.operation
            in {
                WebSourceChangeOperation.REPLACE,
                WebSourceChangeOperation.DELETE,
            }
            and current is None
        ):
            issues.append(
                WebSourceChangeIssue(
                    code=WebSourceChangeIssueCode.TARGET_NOT_FOUND,
                    path=change.normalized_path,
                    message="REPLACE or DELETE operation targets a missing source file.",
                )
            )
        elif (
            change.operation is WebSourceChangeOperation.REPLACE
            and current is not None
            and change.content_sha256 == current.sha256_digest
        ):
            issues.append(
                WebSourceChangeIssue(
                    code=WebSourceChangeIssueCode.REPLACEMENT_UNCHANGED,
                    path=change.normalized_path,
                    message="REPLACE operation does not change the source content.",
                )
            )
        if change.is_high_impact:
            issues.append(
                WebSourceChangeIssue(
                    code=WebSourceChangeIssueCode.HIGH_IMPACT_FILE,
                    path=change.normalized_path,
                    message="Source change modifies dependency, runtime, or network configuration.",
                )
            )
    canonical_issues = tuple(
        sorted(set(issues), key=lambda item: (item.code.value, item.path or ""))
    )
    rejection_codes = {
        WebSourceChangeIssueCode.BASE_REVISION_MISMATCH,
        WebSourceChangeIssueCode.PROTECTED_PATH,
        WebSourceChangeIssueCode.GENERATED_PATH,
        WebSourceChangeIssueCode.TARGET_ALREADY_EXISTS,
        WebSourceChangeIssueCode.TARGET_NOT_FOUND,
        WebSourceChangeIssueCode.REPLACEMENT_UNCHANGED,
    }
    if any(issue.code in rejection_codes for issue in canonical_issues):
        status = WebSourceChangeValidationStatus.REJECTED
        impact = WebSourceChangeImpact.FORBIDDEN
    elif canonical_issues:
        status = WebSourceChangeValidationStatus.REQUIRES_OWNER_APPROVAL
        impact = WebSourceChangeImpact.REQUIRES_GATE_7
    else:
        status = WebSourceChangeValidationStatus.ACCEPTED
        impact = WebSourceChangeImpact.STANDARD
    return WebSourceChangeValidationReport(
        change_set_content_hash=change_set.content_hash,
        base_revision_content_hash=base_revision.content_hash,
        status=status,
        impact=impact,
        issues=canonical_issues,
    )


def _path_components(path: str) -> frozenset[str]:
    return frozenset(component.casefold() for component in PurePosixPath(path).parts)


def _validate_relative_path(path: str) -> None:
    pure_path = PurePosixPath(path)
    if (
        not path
        or path != path.strip()
        or pure_path.is_absolute()
        or "\\" in path
        or pure_path.as_posix() != path
        or any(part in {"", ".", ".."} for part in pure_path.parts)
    ):
        raise ValueError("Web source change path must be normalized and relative")


def _validate_sha256(value: str, *, label: str) -> None:
    if not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must be lowercase SHA-256")


def _validate_normalized_text(value: str, *, label: str) -> None:
    if not value or value != " ".join(value.split()):
        raise ValueError(f"{label} must be normalized")


def _require_canonical_text(values: tuple[str, ...], *, label: str) -> None:
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError(f"{label} must be canonical and unique")
    for value in values:
        _validate_normalized_text(value, label=label)


def _canonical_json(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
