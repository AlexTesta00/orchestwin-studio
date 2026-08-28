"""Typed source plans and safe materialization into immutable Web revisions."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final, Protocol
from uuid import UUID

from orchestwin.artifacts.web_sources import (
    WebSourceFileEntry,
    WebSourceOrigin,
    WebSourceProvenanceReference,
    WebSourceRevision,
    create_web_source_revision,
)
from orchestwin.web_execution.targets import WebTargetSelection

_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_PROTECTED_COMPONENTS: Final = frozenset({".git", ".orchestwin", ".ssh"})
_GENERATED_COMPONENTS: Final = frozenset(
    {
        ".gradle",
        ".pytest_cache",
        ".venv",
        "build",
        "coverage",
        "dist",
        "node_modules",
        "target",
        "vendor",
    }
)
_SENSITIVE_NAMES: Final = frozenset(
    {
        "credentials.json",
        "id_ed25519",
        "id_rsa",
        "secrets.json",
        "service-account.json",
    }
)
_SENSITIVE_SUFFIXES: Final = (".jks", ".key", ".keystore", ".p12", ".pem", ".pfx")
_ALLOWED_MEDIA_TYPES: Final = frozenset(
    {
        "application/javascript",
        "application/json",
        "application/sql",
        "application/typescript",
        "application/xml",
        "image/svg+xml",
        "text/css",
        "text/html",
        "text/javascript",
        "text/markdown",
        "text/plain",
        "text/x-php",
        "text/xml",
    }
)


class WebSourcePlanValidationStatus(StrEnum):
    """Pure validation result before any source file is written."""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class WebSourcePlanIssueCode(StrEnum):
    """Stable reasons why a generated source plan cannot be materialized."""

    EMPTY_PLAN = "EMPTY_PLAN"
    TOO_MANY_FILES = "TOO_MANY_FILES"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    TOTAL_TOO_LARGE = "TOTAL_TOO_LARGE"
    PROTECTED_PATH = "PROTECTED_PATH"
    GENERATED_PATH = "GENERATED_PATH"
    SENSITIVE_PATH = "SENSITIVE_PATH"
    MEDIA_TYPE_NOT_ALLOWED = "MEDIA_TYPE_NOT_ALLOWED"


class WebSourceMaterializationStatus(StrEnum):
    """Typed imperative-shell result without false success."""

    MATERIALIZED = "MATERIALIZED"
    PLAN_REJECTED = "PLAN_REJECTED"
    WORKSPACE_UNSAFE = "WORKSPACE_UNSAFE"
    STORAGE_ERROR = "STORAGE_ERROR"


@dataclass(frozen=True, slots=True)
class WebSourcePlanPolicy:
    """Bounded source generation limits suitable for small thesis projects."""

    maximum_files: int = 1_000
    maximum_file_size_bytes: int = 1_048_576
    maximum_total_size_bytes: int = 20_971_520
    allowed_media_types: frozenset[str] = _ALLOWED_MEDIA_TYPES

    def __post_init__(self) -> None:
        values = (
            self.maximum_files,
            self.maximum_file_size_bytes,
            self.maximum_total_size_bytes,
        )
        if any(isinstance(value, bool) or value < 1 for value in values):
            raise ValueError("Web source plan limits must be positive integers")
        if self.maximum_file_size_bytes > self.maximum_total_size_bytes:
            raise ValueError("Web source file limit must not exceed the total limit")
        if not self.allowed_media_types or any(
            not media_type or "/" not in media_type for media_type in self.allowed_media_types
        ):
            raise ValueError("Web source plan media types must be explicit")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "maximum_files": self.maximum_files,
            "maximum_file_size_bytes": self.maximum_file_size_bytes,
            "maximum_total_size_bytes": self.maximum_total_size_bytes,
            "allowed_media_types": sorted(self.allowed_media_types),
        }


DEFAULT_WEB_SOURCE_PLAN_POLICY: Final = WebSourcePlanPolicy()


@dataclass(frozen=True, slots=True, order=True)
class WebSourcePlanFile:
    """One complete UTF-8 source file proposed by a typed source plan."""

    normalized_path: str
    content: str
    media_type: str

    def __post_init__(self) -> None:
        _validate_relative_path(self.normalized_path)
        if not isinstance(self.content, str):
            raise TypeError("Web source plan content must be text")
        if "\x00" in self.content:
            raise ValueError("Web source plan content must not contain NUL bytes")
        if not self.media_type or "/" not in self.media_type:
            raise ValueError("Web source plan media type must be normalized")

    @property
    def content_bytes(self) -> bytes:
        return self.content.encode("utf-8")

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.content_bytes).hexdigest()

    @property
    def size_bytes(self) -> int:
        return len(self.content_bytes)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "normalized_path": self.normalized_path,
            "content_sha256": self.content_sha256,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
        }


@dataclass(frozen=True, slots=True)
class WebSourcePlan:
    """Approved provider-independent initial source plan with complete files."""

    id: UUID
    project_id: UUID
    created_by_user_id: UUID
    target_selection: WebTargetSelection
    files: tuple[WebSourcePlanFile, ...]
    rationale: str
    provenance_references: tuple[WebSourceProvenanceReference, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        ordered = tuple(
            sorted(
                self.files,
                key=lambda file: (
                    file.normalized_path.casefold(),
                    file.normalized_path,
                ),
            )
        )
        if self.files != ordered:
            raise ValueError("Web source plan files must use canonical order")
        canonical_paths = tuple(file.normalized_path.casefold() for file in self.files)
        if len(canonical_paths) != len(set(canonical_paths)):
            raise ValueError("Web source plan paths must be canonically unique")
        _validate_normalized_text(self.rationale, label="Web source plan rationale")
        if self.provenance_references != tuple(sorted(self.provenance_references)):
            raise ValueError("Web source plan provenance must use canonical order")
        if len(self.provenance_references) != len(set(self.provenance_references)):
            raise ValueError("Web source plan provenance must be unique")
        if not self.provenance_references:
            raise ValueError("Web source plan requires approved provenance")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Web source plan timestamp must be timezone-aware")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self._content_snapshot())).hexdigest()

    def to_snapshot(self) -> dict[str, object]:
        return {**self._content_snapshot(), "content_hash": self.content_hash}

    def _content_snapshot(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "created_by_user_id": str(self.created_by_user_id),
            "target_selection": self.target_selection.to_snapshot(),
            "files": [file.to_snapshot() for file in self.files],
            "rationale": self.rationale,
            "provenance_references": [
                reference.to_snapshot() for reference in self.provenance_references
            ],
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True, order=True)
class WebSourcePlanIssue:
    """One deterministic source-plan issue tied to an optional path."""

    code: WebSourcePlanIssueCode
    path: str | None
    message: str

    def __post_init__(self) -> None:
        if self.path is not None:
            _validate_relative_path(self.path)
        _validate_normalized_text(self.message, label="Web source plan issue")

    def to_snapshot(self) -> dict[str, str | None]:
        return {"code": self.code.value, "path": self.path, "message": self.message}


@dataclass(frozen=True, slots=True)
class WebSourcePlanValidationReport:
    """Validation decision bound to an exact source plan and policy."""

    plan_content_hash: str
    policy_content_hash: str
    status: WebSourcePlanValidationStatus
    issues: tuple[WebSourcePlanIssue, ...]

    def __post_init__(self) -> None:
        _validate_sha256(self.plan_content_hash, label="Web source plan hash")
        _validate_sha256(self.policy_content_hash, label="Web source plan policy hash")
        ordered = tuple(
            sorted(
                self.issues,
                key=lambda issue: (issue.code.value, issue.path or "", issue.message),
            )
        )
        if self.issues != ordered or len(self.issues) != len(set(self.issues)):
            raise ValueError("Web source plan issues must be canonical and unique")
        if self.status is WebSourcePlanValidationStatus.ACCEPTED:
            if self.issues:
                raise ValueError("accepted Web source plan must be issue-free")
        elif not self.issues:
            raise ValueError("rejected Web source plan requires issues")

    @property
    def is_accepted(self) -> bool:
        return self.status is WebSourcePlanValidationStatus.ACCEPTED


class WebSourceContentStore(Protocol):
    """Content-addressed source storage used by generation and repair."""

    def store(
        self,
        *,
        normalized_path: str,
        content: bytes,
        media_type: str,
    ) -> WebSourceFileEntry: ...

    def read(self, storage_key: str) -> bytes | None: ...


class FileSystemWebSourceContentStore:
    """Immutable SHA-256 source object store under regular directories."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def store(
        self,
        *,
        normalized_path: str,
        content: bytes,
        media_type: str,
    ) -> WebSourceFileEntry:
        _validate_relative_path(normalized_path)
        if not isinstance(content, bytes):
            raise TypeError("Web source store content must be bytes")
        digest = hashlib.sha256(content).hexdigest()
        storage_key = f"sha256/{digest[:2]}/{digest}"
        parent = self._prepare_parent(digest)
        if parent is None:
            raise OSError("Web source content store could not be prepared safely")
        target = parent / digest
        if target.exists() or target.is_symlink():
            _verify_content_object(target, digest=digest, expected=content)
        else:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{digest}.",
                suffix=".tmp",
                dir=parent,
            )
            temporary_path = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as temporary_file:
                    temporary_file.write(content)
                    temporary_file.flush()
                    os.fsync(temporary_file.fileno())
                try:
                    os.link(temporary_path, target)
                except FileExistsError:
                    _verify_content_object(target, digest=digest, expected=content)
            finally:
                with suppress(OSError):
                    temporary_path.unlink()
            _verify_content_object(target, digest=digest, expected=content)
        return WebSourceFileEntry(
            normalized_path=normalized_path,
            sha256_digest=digest,
            size_bytes=len(content),
            storage_key=storage_key,
            media_type=media_type,
        )

    def read(self, storage_key: str) -> bytes | None:
        target = self._safe_target(storage_key)
        if target is None or target.is_symlink() or not target.is_file():
            return None
        try:
            content = target.read_bytes()
        except OSError:
            return None
        if hashlib.sha256(content).hexdigest() != PurePosixPath(storage_key).name:
            return None
        return content

    def _prepare_parent(self, digest: str) -> Path | None:
        try:
            if self._root.is_symlink():
                return None
            self._root.mkdir(parents=True, exist_ok=True)
            if not self._root.is_dir() or self._root.is_symlink():
                return None
            current = self._root
            for part in ("sha256", digest[:2]):
                current = current / part
                if current.is_symlink():
                    return None
                current.mkdir(exist_ok=True)
                if not current.is_dir() or current.is_symlink():
                    return None
            return current
        except OSError:
            return None

    def _safe_target(self, storage_key: str) -> Path | None:
        path = PurePosixPath(storage_key)
        if (
            len(path.parts) != 3
            or path.parts[0] != "sha256"
            or len(path.parts[1]) != 2
            or not _SHA256_PATTERN.fullmatch(path.parts[2])
            or path.parts[1] != path.parts[2][:2]
        ):
            return None
        parents = (
            self._root,
            self._root / "sha256",
            self._root / "sha256" / path.parts[1],
        )
        if any(parent.is_symlink() for parent in parents):
            return None
        return self._root.joinpath(*path.parts)


@dataclass(frozen=True, slots=True)
class WebSourceMaterializationResult:
    """Result of safely creating one initial workspace and immutable revision."""

    status: WebSourceMaterializationStatus
    validation_report: WebSourcePlanValidationReport
    revision: WebSourceRevision | None
    workspace_path: Path | None
    failure_message: str | None

    def __post_init__(self) -> None:
        if self.status is WebSourceMaterializationStatus.MATERIALIZED:
            if (
                not self.validation_report.is_accepted
                or self.revision is None
                or self.workspace_path is None
                or self.failure_message is not None
            ):
                raise ValueError("materialized Web source result requires complete success data")
        elif self.revision is not None or self.workspace_path is not None:
            raise ValueError("failed Web source materialization must not expose a revision")
        if self.failure_message is not None:
            _validate_normalized_text(
                self.failure_message,
                label="Web source materialization failure",
            )


def validate_web_source_plan(
    plan: WebSourcePlan,
    *,
    policy: WebSourcePlanPolicy = DEFAULT_WEB_SOURCE_PLAN_POLICY,
) -> WebSourcePlanValidationReport:
    """Validate all paths, media types, and resource limits before writing."""
    issues: list[WebSourcePlanIssue] = []
    if not plan.files:
        issues.append(
            WebSourcePlanIssue(
                WebSourcePlanIssueCode.EMPTY_PLAN,
                None,
                "Web source plan must contain at least one file.",
            )
        )
    if len(plan.files) > policy.maximum_files:
        issues.append(
            WebSourcePlanIssue(
                WebSourcePlanIssueCode.TOO_MANY_FILES,
                None,
                "Web source plan exceeds the file-count limit.",
            )
        )
    total_size = sum(file.size_bytes for file in plan.files)
    if total_size > policy.maximum_total_size_bytes:
        issues.append(
            WebSourcePlanIssue(
                WebSourcePlanIssueCode.TOTAL_TOO_LARGE,
                None,
                "Web source plan exceeds the total content-size limit.",
            )
        )
    for file in plan.files:
        components = frozenset(
            component.casefold() for component in PurePosixPath(file.normalized_path).parts
        )
        file_name = PurePosixPath(file.normalized_path).name.casefold()
        if components & _PROTECTED_COMPONENTS:
            issues.append(
                _plan_issue(
                    WebSourcePlanIssueCode.PROTECTED_PATH,
                    file.normalized_path,
                    "Web source plan targets a protected workspace path.",
                )
            )
        if components & _GENERATED_COMPONENTS:
            issues.append(
                _plan_issue(
                    WebSourcePlanIssueCode.GENERATED_PATH,
                    file.normalized_path,
                    "Web source plan targets generated dependency or build output.",
                )
            )
        if (
            file_name.startswith(".env")
            or file_name in _SENSITIVE_NAMES
            or file_name.endswith(_SENSITIVE_SUFFIXES)
        ):
            issues.append(
                _plan_issue(
                    WebSourcePlanIssueCode.SENSITIVE_PATH,
                    file.normalized_path,
                    "Web source plan contains a prohibited secret-bearing path.",
                )
            )
        if file.size_bytes > policy.maximum_file_size_bytes:
            issues.append(
                _plan_issue(
                    WebSourcePlanIssueCode.FILE_TOO_LARGE,
                    file.normalized_path,
                    "Web source plan file exceeds the per-file size limit.",
                )
            )
        if file.media_type not in policy.allowed_media_types:
            issues.append(
                _plan_issue(
                    WebSourcePlanIssueCode.MEDIA_TYPE_NOT_ALLOWED,
                    file.normalized_path,
                    "Web source plan media type is outside the allowlist.",
                )
            )
    canonical_issues = tuple(
        sorted(
            set(issues),
            key=lambda issue: (issue.code.value, issue.path or "", issue.message),
        )
    )
    policy_hash = hashlib.sha256(_canonical_json(policy.to_snapshot())).hexdigest()
    return WebSourcePlanValidationReport(
        plan_content_hash=plan.content_hash,
        policy_content_hash=policy_hash,
        status=(
            WebSourcePlanValidationStatus.REJECTED
            if canonical_issues
            else WebSourcePlanValidationStatus.ACCEPTED
        ),
        issues=canonical_issues,
    )


def materialize_web_source_plan(
    plan: WebSourcePlan,
    *,
    revision_id: UUID,
    workspace_path: Path,
    content_store: WebSourceContentStore,
    created_at: datetime,
    policy: WebSourcePlanPolicy = DEFAULT_WEB_SOURCE_PLAN_POLICY,
) -> WebSourceMaterializationResult:
    """Create one fresh workspace and revision without overwriting local content."""
    validation = validate_web_source_plan(plan, policy=policy)
    if not validation.is_accepted:
        return WebSourceMaterializationResult(
            status=WebSourceMaterializationStatus.PLAN_REJECTED,
            validation_report=validation,
            revision=None,
            workspace_path=None,
            failure_message="Web source plan failed deterministic validation.",
        )
    workspace = Path(workspace_path)
    if not workspace.is_absolute() or not _prepare_empty_workspace(workspace):
        return WebSourceMaterializationResult(
            status=WebSourceMaterializationStatus.WORKSPACE_UNSAFE,
            validation_report=validation,
            revision=None,
            workspace_path=None,
            failure_message="Web source workspace must be a fresh regular directory.",
        )
    try:
        entries: list[WebSourceFileEntry] = []
        for file in plan.files:
            content = file.content_bytes
            entry = content_store.store(
                normalized_path=file.normalized_path,
                content=content,
                media_type=file.media_type,
            )
            _write_workspace_file(workspace, file.normalized_path, content)
            entries.append(entry)
        revision = create_web_source_revision(
            revision_id=revision_id,
            project_id=plan.project_id,
            created_by_user_id=plan.created_by_user_id,
            version_number=1,
            based_on=None,
            target=plan.target_selection.target,
            language_configuration=plan.target_selection.language_configuration,
            layout=plan.target_selection.layout,
            origin=WebSourceOrigin.GENERATED_PLAN,
            files=tuple(entries),
            provenance_references=plan.provenance_references,
            created_at=created_at,
        )
    except (OSError, ValueError):
        _remove_workspace(workspace)
        return WebSourceMaterializationResult(
            status=WebSourceMaterializationStatus.STORAGE_ERROR,
            validation_report=validation,
            revision=None,
            workspace_path=None,
            failure_message="Web source content could not be materialized safely.",
        )
    return WebSourceMaterializationResult(
        status=WebSourceMaterializationStatus.MATERIALIZED,
        validation_report=validation,
        revision=revision,
        workspace_path=workspace,
        failure_message=None,
    )


def create_web_source_plan(
    *,
    plan_id: UUID,
    project_id: UUID,
    created_by_user_id: UUID,
    target_selection: WebTargetSelection,
    files: Iterable[WebSourcePlanFile],
    rationale: str,
    provenance_references: Iterable[WebSourceProvenanceReference],
    created_at: datetime,
) -> WebSourcePlan:
    """Canonicalize complete files and provenance before validating a plan."""
    return WebSourcePlan(
        id=plan_id,
        project_id=project_id,
        created_by_user_id=created_by_user_id,
        target_selection=target_selection,
        files=tuple(
            sorted(
                files,
                key=lambda file: (
                    file.normalized_path.casefold(),
                    file.normalized_path,
                ),
            )
        ),
        rationale=rationale,
        provenance_references=tuple(sorted(set(provenance_references))),
        created_at=created_at,
    )


def _prepare_empty_workspace(workspace: Path) -> bool:
    try:
        if workspace.is_symlink():
            return False
        if workspace.exists():
            return workspace.is_dir() and not any(workspace.iterdir())
        parent = workspace.parent
        if parent.is_symlink() or not parent.is_dir():
            return False
        workspace.mkdir()
        return workspace.is_dir() and not workspace.is_symlink()
    except OSError:
        return False


def _write_workspace_file(workspace: Path, normalized_path: str, content: bytes) -> None:
    target = workspace.joinpath(*PurePosixPath(normalized_path).parts)
    current = workspace
    for part in PurePosixPath(normalized_path).parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise OSError("Web source workspace contains a symlink")
        current.mkdir(exist_ok=True)
        if not current.is_dir() or current.is_symlink():
            raise OSError("Web source workspace parent is unsafe")
    if target.exists() or target.is_symlink():
        raise OSError("Web source materialization never overwrites files")
    with target.open("xb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())


def _remove_workspace(workspace: Path) -> None:
    with suppress(OSError):
        if workspace.exists() and not workspace.is_symlink():
            shutil.rmtree(workspace)


def _verify_content_object(target: Path, *, digest: str, expected: bytes) -> None:
    if target.is_symlink() or not target.is_file():
        raise ValueError("Web source content object is not a regular file")
    actual = target.read_bytes()
    if actual != expected or hashlib.sha256(actual).hexdigest() != digest:
        raise ValueError("Web source content object does not match its address")


def _plan_issue(
    code: WebSourcePlanIssueCode,
    path: str,
    message: str,
) -> WebSourcePlanIssue:
    return WebSourcePlanIssue(code=code, path=path, message=message)


def _validate_relative_path(path: str) -> None:
    pure = PurePosixPath(path)
    if (
        not path
        or path != path.strip()
        or pure.is_absolute()
        or "\\" in path
        or pure.as_posix() != path
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ValueError("Web source plan path must be normalized and relative")


def _validate_sha256(value: str, *, label: str) -> None:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase SHA-256")


def _validate_normalized_text(value: str, *, label: str) -> None:
    if not value or value != " ".join(value.split()):
        raise ValueError(f"{label} must be normalized")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
