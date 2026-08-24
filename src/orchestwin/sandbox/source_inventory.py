"""Deterministic inventory snapshots for safely extracted source trees."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final

from orchestwin.sandbox.archive_policy import (
    SourceArchiveEntryDisposition,
    SourceArchiveEntryKind,
    SourceArchiveIgnoreReason,
)
from orchestwin.sandbox.archive_validation import SourceArchiveValidationReport

_INVENTORY_SCHEMA_VERSION: Final = 1
_HASH_CHUNK_SIZE: Final = 1024 * 1024
_TEST_DIRECTORY_NAMES: Final = frozenset({"__tests__", "spec", "specs", "test", "tests"})
_DOCUMENTATION_DIRECTORY_NAMES: Final = frozenset({"doc", "docs", "documentation"})
_DOCUMENTATION_FILE_NAMES: Final = frozenset(
    {
        "changelog",
        "contributing",
        "license",
        "readme",
        "security",
    }
)
_CONFIGURATION_FILE_NAMES: Final = frozenset(
    {
        ".dockerignore",
        ".editorconfig",
        ".gitattributes",
        ".gitignore",
        ".npmrc",
        ".nvmrc",
        "build.gradle",
        "build.gradle.kts",
        "composer.json",
        "composer.lock",
        "dockerfile",
        "makefile",
        "package-lock.json",
        "package.json",
        "pom.xml",
        "pyproject.toml",
        "settings.gradle",
        "settings.gradle.kts",
        "tsconfig.json",
        "vite.config.js",
        "vite.config.ts",
    }
)
_CONFIGURATION_SUFFIXES: Final = frozenset(
    {
        ".cfg",
        ".conf",
        ".gradle",
        ".ini",
        ".lock",
        ".properties",
        ".toml",
        ".yaml",
        ".yml",
    }
)
_DOCUMENTATION_SUFFIXES: Final = frozenset({".md", ".rst"})
_DATA_SUFFIXES: Final = frozenset({".csv", ".json", ".jsonc", ".xml"})
_ASSET_SUFFIXES: Final = frozenset({".svg"})
_SOURCE_SUFFIXES: Final = frozenset(
    {
        ".bat",
        ".c",
        ".cjs",
        ".cpp",
        ".cs",
        ".css",
        ".dart",
        ".graphql",
        ".h",
        ".hpp",
        ".htm",
        ".html",
        ".java",
        ".js",
        ".jsx",
        ".kt",
        ".kts",
        ".less",
        ".mjs",
        ".php",
        ".ps1",
        ".py",
        ".pyi",
        ".rb",
        ".rs",
        ".sass",
        ".sc",
        ".scala",
        ".scss",
        ".sh",
        ".sql",
        ".ts",
        ".tsx",
        ".vue",
    }
)


class SourceInventoryClassification(StrEnum):
    """Semantic classifications used by later stack detection."""

    DIRECTORY = "DIRECTORY"
    SOURCE = "SOURCE"
    TEST = "TEST"
    CONFIGURATION = "CONFIGURATION"
    DOCUMENTATION = "DOCUMENTATION"
    DATA = "DATA"
    ASSET = "ASSET"
    OTHER = "OTHER"
    GENERATED = "GENERATED"
    UNSUPPORTED = "UNSUPPORTED"


class SourceTreeInventoryBuildStatus(StrEnum):
    """Typed outcomes of one source inventory attempt."""

    CREATED = "CREATED"
    VALIDATION_REQUIRED = "VALIDATION_REQUIRED"
    WORKSPACE_NOT_FOUND = "WORKSPACE_NOT_FOUND"
    WORKSPACE_CHANGED = "WORKSPACE_CHANGED"


@dataclass(frozen=True, slots=True)
class SourceInventoryEntry:
    """One canonical included or excluded source-tree entry."""

    normalized_path: str
    kind: SourceArchiveEntryKind
    classification: SourceInventoryClassification
    size_bytes: int
    sha256_digest: str | None
    disposition: SourceArchiveEntryDisposition
    disposition_reason: SourceArchiveIgnoreReason | None

    def __post_init__(self) -> None:
        """Protect portable paths, hashes, and disposition semantics."""
        _validate_normalized_relative_path(self.normalized_path)

        if self.size_bytes < 0:
            raise ValueError("source inventory entry size must not be negative")

        if self.sha256_digest is not None and not _is_sha256(self.sha256_digest):
            raise ValueError("source inventory entry digest must be lowercase SHA-256")

        if self.kind is SourceArchiveEntryKind.DIRECTORY and self.sha256_digest is not None:
            raise ValueError("source inventory directory must not have a content digest")

        if self.disposition is SourceArchiveEntryDisposition.INCLUDE:
            if self.disposition_reason is not None:
                raise ValueError("included source inventory entry must not have a reason")
            if self.kind is SourceArchiveEntryKind.FILE and self.sha256_digest is None:
                raise ValueError("included source inventory file requires a content digest")
        elif self.disposition_reason is None:
            raise ValueError("ignored source inventory entry requires a reason")

    def to_snapshot(self) -> dict[str, object]:
        """Return deterministic JSON-compatible entry content."""
        return {
            "normalized_path": self.normalized_path,
            "kind": self.kind.value,
            "classification": self.classification.value,
            "size_bytes": self.size_bytes,
            "sha256_digest": self.sha256_digest,
            "disposition": self.disposition.value,
            "disposition_reason": (
                None if self.disposition_reason is None else self.disposition_reason.value
            ),
        }


@dataclass(frozen=True, slots=True)
class SourceTreeInventory:
    """Canonical source-tree snapshot independent from ZIP member ordering."""

    archive_sha256: str
    entries: tuple[SourceInventoryEntry, ...]
    schema_version: int = _INVENTORY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Protect digest identity and canonical entry order."""
        if not _is_sha256(self.archive_sha256):
            raise ValueError("source inventory archive digest must be lowercase SHA-256")
        if self.schema_version != _INVENTORY_SCHEMA_VERSION:
            raise ValueError("unsupported source inventory schema version")
        if not self.entries:
            raise ValueError("source inventory must contain at least one entry")

        ordered_entries = tuple(
            sorted(
                self.entries,
                key=lambda entry: (entry.normalized_path.casefold(), entry.normalized_path),
            )
        )
        if self.entries != ordered_entries:
            raise ValueError("source inventory entries must use canonical order")

        canonical_paths = tuple(entry.normalized_path.casefold() for entry in self.entries)
        if len(canonical_paths) != len(set(canonical_paths)):
            raise ValueError("source inventory paths must be canonically unique")

    @property
    def included_entries(self) -> tuple[SourceInventoryEntry, ...]:
        """Return materialized source-tree entries."""
        return tuple(
            entry
            for entry in self.entries
            if entry.disposition is SourceArchiveEntryDisposition.INCLUDE
        )

    @property
    def excluded_entries(self) -> tuple[SourceInventoryEntry, ...]:
        """Return archive entries omitted with an inspectable reason."""
        return tuple(
            entry
            for entry in self.entries
            if entry.disposition is SourceArchiveEntryDisposition.IGNORE
        )

    @property
    def content_hash(self) -> str:
        """Hash normalized tree content independently from ZIP container ordering."""
        return hashlib.sha256(self.canonical_content_json().encode("utf-8")).hexdigest()

    def canonical_content_json(self) -> str:
        """Serialize only canonical tree content for equivalence checks."""
        return json.dumps(
            {
                "schema_version": self.schema_version,
                "entries": [entry.to_snapshot() for entry in self.entries],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def to_snapshot(self) -> dict[str, object]:
        """Return deterministic inventory metadata and content."""
        return {
            "schema_version": self.schema_version,
            "archive_sha256": self.archive_sha256,
            "content_hash": self.content_hash,
            "entries": [entry.to_snapshot() for entry in self.entries],
        }


@dataclass(frozen=True, slots=True)
class SourceTreeInventoryBuildResult:
    """Typed result for inventory construction at the filesystem boundary."""

    status: SourceTreeInventoryBuildStatus
    inventory: SourceTreeInventory | None
    failure_message: str | None

    def __post_init__(self) -> None:
        """Protect success and failure result shapes."""
        if self.failure_message is not None and (
            not self.failure_message
            or self.failure_message != " ".join(self.failure_message.split())
        ):
            raise ValueError("source inventory failure message must be normalized")

        if self.status is SourceTreeInventoryBuildStatus.CREATED:
            if self.inventory is None or self.failure_message is not None:
                raise ValueError("created source inventory result requires an inventory")
        elif self.inventory is not None or self.failure_message is None:
            raise ValueError("failed source inventory result requires only a message")

    @property
    def is_created(self) -> bool:
        """Return whether a canonical inventory is available."""
        return self.status is SourceTreeInventoryBuildStatus.CREATED


def build_source_tree_inventory(
    workspace_path: Path,
    *,
    validation_report: SourceArchiveValidationReport,
) -> SourceTreeInventoryBuildResult:
    """Inventory one extracted workspace and preserve archive exclusions."""
    if not validation_report.is_accepted or validation_report.archive_sha256 is None:
        return _failed_build(
            SourceTreeInventoryBuildStatus.VALIDATION_REQUIRED,
            "Source archive must pass validation before inventory construction.",
        )

    workspace = Path(workspace_path)
    if workspace.is_symlink() or not workspace.is_dir():
        return _failed_build(
            SourceTreeInventoryBuildStatus.WORKSPACE_NOT_FOUND,
            "Source inventory workspace does not exist as a regular directory.",
        )

    try:
        actual_entries = _scan_workspace(workspace)
        expected_entries = _expected_workspace_entries(validation_report)
        if actual_entries != expected_entries:
            return _failed_build(
                SourceTreeInventoryBuildStatus.WORKSPACE_CHANGED,
                "Source inventory workspace differs from the validated extraction manifest.",
            )

        inventory_entries = _create_inventory_entries(
            workspace,
            validation_report=validation_report,
            actual_entries=actual_entries,
        )
    except (OSError, ValueError):
        return _failed_build(
            SourceTreeInventoryBuildStatus.WORKSPACE_CHANGED,
            "Source inventory workspace could not be inspected safely.",
        )

    return SourceTreeInventoryBuildResult(
        status=SourceTreeInventoryBuildStatus.CREATED,
        inventory=SourceTreeInventory(
            archive_sha256=validation_report.archive_sha256,
            entries=inventory_entries,
        ),
        failure_message=None,
    )


def _scan_workspace(
    workspace: Path,
) -> dict[str, SourceArchiveEntryKind]:
    """Scan without following symlinks or accepting special files."""
    entries: dict[str, SourceArchiveEntryKind] = {}

    def visit(directory: Path) -> None:
        for child in sorted(directory.iterdir(), key=lambda path: path.name.casefold()):
            if child.is_symlink():
                raise ValueError("source inventory workspace contains a symlink")

            normalized_path = child.relative_to(workspace).as_posix()
            _validate_normalized_relative_path(normalized_path)

            if child.is_dir():
                entries[normalized_path] = SourceArchiveEntryKind.DIRECTORY
                visit(child)
            elif child.is_file():
                entries[normalized_path] = SourceArchiveEntryKind.FILE
            else:
                raise ValueError("source inventory workspace contains a special file")

    visit(workspace)
    return entries


def _expected_workspace_entries(
    validation_report: SourceArchiveValidationReport,
) -> dict[str, SourceArchiveEntryKind]:
    """Derive explicit entries and implicit parent directories from preflight."""
    expected: dict[str, SourceArchiveEntryKind] = {}

    for entry in validation_report.included_entries:
        path = PurePosixPath(entry.normalized_path)
        for parent in reversed(path.parents):
            if str(parent) == ".":
                continue
            expected.setdefault(parent.as_posix(), SourceArchiveEntryKind.DIRECTORY)
        expected[entry.normalized_path] = entry.kind

    return expected


def _create_inventory_entries(
    workspace: Path,
    *,
    validation_report: SourceArchiveValidationReport,
    actual_entries: dict[str, SourceArchiveEntryKind],
) -> tuple[SourceInventoryEntry, ...]:
    """Hash included files and preserve excluded archive metadata."""
    explicit_entries = {entry.normalized_path: entry for entry in validation_report.entries}
    inventory_entries: list[SourceInventoryEntry] = []

    for normalized_path, kind in actual_entries.items():
        target = workspace.joinpath(*PurePosixPath(normalized_path).parts)
        explicit_entry = explicit_entries.get(normalized_path)
        size_bytes = 0 if kind is SourceArchiveEntryKind.DIRECTORY else target.stat().st_size

        if explicit_entry is not None and size_bytes != explicit_entry.uncompressed_size:
            raise ValueError("source inventory file size changed after extraction")

        inventory_entries.append(
            SourceInventoryEntry(
                normalized_path=normalized_path,
                kind=kind,
                classification=_classify_included_entry(normalized_path, kind=kind),
                size_bytes=size_bytes,
                sha256_digest=(
                    None if kind is SourceArchiveEntryKind.DIRECTORY else _hash_file(target)
                ),
                disposition=SourceArchiveEntryDisposition.INCLUDE,
                disposition_reason=None,
            )
        )

    for entry in validation_report.ignored_entries:
        inventory_entries.append(
            SourceInventoryEntry(
                normalized_path=entry.normalized_path,
                kind=entry.kind,
                classification=_classify_ignored_entry(entry.ignore_reason),
                size_bytes=entry.uncompressed_size,
                sha256_digest=None,
                disposition=SourceArchiveEntryDisposition.IGNORE,
                disposition_reason=entry.ignore_reason,
            )
        )

    return tuple(
        sorted(
            inventory_entries,
            key=lambda entry: (entry.normalized_path.casefold(), entry.normalized_path),
        )
    )


def _classify_included_entry(
    normalized_path: str,
    *,
    kind: SourceArchiveEntryKind,
) -> SourceInventoryClassification:
    """Classify one materialized entry using deterministic path indicators."""
    path = PurePosixPath(normalized_path)
    compared_parts = tuple(part.casefold() for part in path.parts)
    file_name = compared_parts[-1]
    suffix = path.suffix.casefold()

    if _is_test_path(compared_parts, file_name=file_name):
        return SourceInventoryClassification.TEST
    if kind is SourceArchiveEntryKind.DIRECTORY:
        return SourceInventoryClassification.DIRECTORY
    if _is_documentation_path(compared_parts, file_name=file_name, suffix=suffix):
        return SourceInventoryClassification.DOCUMENTATION
    if _is_configuration_file(file_name, suffix=suffix):
        return SourceInventoryClassification.CONFIGURATION
    if suffix in _SOURCE_SUFFIXES:
        return SourceInventoryClassification.SOURCE
    if suffix in _DATA_SUFFIXES:
        return SourceInventoryClassification.DATA
    if suffix in _ASSET_SUFFIXES:
        return SourceInventoryClassification.ASSET
    return SourceInventoryClassification.OTHER


def _classify_ignored_entry(
    ignore_reason: SourceArchiveIgnoreReason | None,
) -> SourceInventoryClassification:
    """Map archive exclusions to stable inventory classifications."""
    if ignore_reason is SourceArchiveIgnoreReason.GENERATED_PATH:
        return SourceInventoryClassification.GENERATED
    if ignore_reason is SourceArchiveIgnoreReason.UNSUPPORTED_FILE:
        return SourceInventoryClassification.UNSUPPORTED
    raise ValueError("ignored source archive entry requires a supported reason")


def _is_test_path(
    compared_parts: tuple[str, ...],
    *,
    file_name: str,
) -> bool:
    """Recognize conventional test directories and file names."""
    if any(part in _TEST_DIRECTORY_NAMES for part in compared_parts[:-1]):
        return True

    stem = PurePosixPath(file_name).stem
    return (
        file_name.startswith("test_")
        or stem.endswith("_test")
        or ".spec." in file_name
        or ".test." in file_name
    )


def _is_documentation_path(
    compared_parts: tuple[str, ...],
    *,
    file_name: str,
    suffix: str,
) -> bool:
    """Recognize documentation directories and conventional documents."""
    if any(part in _DOCUMENTATION_DIRECTORY_NAMES for part in compared_parts[:-1]):
        return True
    if suffix in _DOCUMENTATION_SUFFIXES:
        return True
    base_name = file_name.removesuffix(suffix)
    return base_name in _DOCUMENTATION_FILE_NAMES


def _is_configuration_file(
    file_name: str,
    *,
    suffix: str,
) -> bool:
    """Recognize project and tool configuration artifacts."""
    return (
        file_name in _CONFIGURATION_FILE_NAMES
        or file_name.startswith(".env")
        or suffix in _CONFIGURATION_SUFFIXES
    )


def _hash_file(
    path: Path,
) -> str:
    """Hash one included source file without loading it into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(_HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_normalized_relative_path(
    normalized_path: str,
) -> None:
    """Require one non-ambiguous portable relative path."""
    path = PurePosixPath(normalized_path)
    if (
        not normalized_path
        or path.is_absolute()
        or "\\" in normalized_path
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != normalized_path
    ):
        raise ValueError("source inventory path must be normalized and relative")


def _is_sha256(
    value: str,
) -> bool:
    """Return whether a value is one lowercase SHA-256 digest."""
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _failed_build(
    status: SourceTreeInventoryBuildStatus,
    message: str,
) -> SourceTreeInventoryBuildResult:
    """Create one consistent failed inventory result."""
    return SourceTreeInventoryBuildResult(
        status=status,
        inventory=None,
        failure_message=message,
    )
