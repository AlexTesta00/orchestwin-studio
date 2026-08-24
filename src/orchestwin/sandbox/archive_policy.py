"""Immutable policy values for brownfield source archive intake."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

_MEBIBYTE: Final = 1024 * 1024


class SourceArchiveValidationStatus(StrEnum):
    """Outcome of source archive validation."""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class SourceArchiveEntryKind(StrEnum):
    """Supported ZIP entry kinds."""

    FILE = "FILE"
    DIRECTORY = "DIRECTORY"


class SourceArchiveEntryDisposition(StrEnum):
    """Whether a validated entry belongs in the extracted source tree."""

    INCLUDE = "INCLUDE"
    IGNORE = "IGNORE"


class SourceArchiveIgnoreReason(StrEnum):
    """Inspectable reasons for excluding otherwise safe archive entries."""

    GENERATED_PATH = "GENERATED_PATH"
    UNSUPPORTED_FILE = "UNSUPPORTED_FILE"


class SourceArchiveIssueCode(StrEnum):
    """Stable rejection codes returned by archive preflight validation."""

    ARCHIVE_NOT_FOUND = "ARCHIVE_NOT_FOUND"
    ARCHIVE_NOT_REGULAR_FILE = "ARCHIVE_NOT_REGULAR_FILE"
    ARCHIVE_TOO_LARGE = "ARCHIVE_TOO_LARGE"
    INVALID_ZIP = "INVALID_ZIP"
    EMPTY_ARCHIVE = "EMPTY_ARCHIVE"
    TOO_MANY_ENTRIES = "TOO_MANY_ENTRIES"
    ENCRYPTED_ENTRY = "ENCRYPTED_ENTRY"
    UNSAFE_PATH = "UNSAFE_PATH"
    PATH_TOO_LONG = "PATH_TOO_LONG"
    CANONICAL_PATH_COLLISION = "CANONICAL_PATH_COLLISION"
    UNSAFE_ENTRY_TYPE = "UNSAFE_ENTRY_TYPE"
    ENTRY_TOO_LARGE = "ENTRY_TOO_LARGE"
    TOTAL_UNCOMPRESSED_TOO_LARGE = "TOTAL_UNCOMPRESSED_TOO_LARGE"
    COMPRESSION_RATIO_EXCEEDED = "COMPRESSION_RATIO_EXCEEDED"
    SENSITIVE_FILE = "SENSITIVE_FILE"


@dataclass(frozen=True, slots=True)
class SourceArchiveIssue:
    """One typed and user-presentable archive validation problem."""

    code: SourceArchiveIssueCode
    message: str
    entry_path: str | None = None

    def __post_init__(self) -> None:
        """Protect normalized issue details."""
        if not self.message or self.message != " ".join(self.message.split()):
            raise ValueError("source archive issue message must be normalized")

        if self.entry_path is not None and not self.entry_path:
            raise ValueError("source archive issue entry path must not be empty")


@dataclass(frozen=True, slots=True)
class SourceArchivePolicy:
    """Limits and allowlists applied before any ZIP entry is extracted."""

    maximum_archive_size_bytes: int
    maximum_total_uncompressed_bytes: int
    maximum_entry_uncompressed_bytes: int
    maximum_entries: int
    maximum_compression_ratio: float
    maximum_normalized_path_length: int
    ignored_directory_names: frozenset[str]
    allowed_file_extensions: frozenset[str]
    allowed_file_names: frozenset[str]
    sensitive_file_names: frozenset[str]
    sensitive_file_suffixes: frozenset[str]
    environment_template_suffixes: frozenset[str]

    def __post_init__(self) -> None:
        """Reject invalid or ambiguous policy definitions."""
        integer_limits = (
            self.maximum_archive_size_bytes,
            self.maximum_total_uncompressed_bytes,
            self.maximum_entry_uncompressed_bytes,
            self.maximum_entries,
            self.maximum_normalized_path_length,
        )
        if any(isinstance(value, bool) or value < 1 for value in integer_limits):
            raise ValueError("source archive integer limits must be positive")

        if self.maximum_entry_uncompressed_bytes > self.maximum_total_uncompressed_bytes:
            raise ValueError("source archive entry limit must not exceed total limit")

        if self.maximum_compression_ratio < 1:
            raise ValueError("source archive compression ratio must be at least one")

        _validate_lowercase_tokens(
            self.ignored_directory_names,
            label="ignored directory names",
        )
        _validate_extensions(
            self.allowed_file_extensions,
            label="allowed file extensions",
        )
        _validate_lowercase_tokens(
            self.allowed_file_names,
            label="allowed file names",
        )
        _validate_lowercase_tokens(
            self.sensitive_file_names,
            label="sensitive file names",
        )
        _validate_extensions(
            self.sensitive_file_suffixes,
            label="sensitive file suffixes",
        )
        _validate_extensions(
            self.environment_template_suffixes,
            label="environment template suffixes",
        )


def _validate_lowercase_tokens(
    values: frozenset[str],
    *,
    label: str,
) -> None:
    """Require stable lowercase tokens without path separators."""
    if not values:
        raise ValueError(f"{label} must not be empty")

    for value in values:
        if (
            not value
            or value != value.casefold()
            or value != value.strip()
            or "/" in value
            or "\\" in value
        ):
            raise ValueError(f"{label} must contain normalized lowercase tokens")


def _validate_extensions(
    values: frozenset[str],
    *,
    label: str,
) -> None:
    """Require stable lowercase dot-prefixed extensions."""
    _validate_lowercase_tokens(values, label=label)

    if any(not value.startswith(".") or len(value) < 2 for value in values):
        raise ValueError(f"{label} must contain dot-prefixed extensions")


DEFAULT_SOURCE_ARCHIVE_POLICY: Final = SourceArchivePolicy(
    maximum_archive_size_bytes=25 * _MEBIBYTE,
    maximum_total_uncompressed_bytes=250 * _MEBIBYTE,
    maximum_entry_uncompressed_bytes=25 * _MEBIBYTE,
    maximum_entries=10_000,
    maximum_compression_ratio=100.0,
    maximum_normalized_path_length=240,
    ignored_directory_names=frozenset(
        {
            ".dart_tool",
            ".git",
            ".gradle",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            ".venv",
            "__pycache__",
            "build",
            "coverage",
            "dist",
            "node_modules",
            "target",
            "venv",
        }
    ),
    allowed_file_extensions=frozenset(
        {
            ".bat",
            ".c",
            ".cfg",
            ".cjs",
            ".conf",
            ".cpp",
            ".cs",
            ".css",
            ".csv",
            ".dart",
            ".gradle",
            ".graphql",
            ".h",
            ".hpp",
            ".htm",
            ".html",
            ".ini",
            ".java",
            ".js",
            ".json",
            ".jsonc",
            ".jsx",
            ".kt",
            ".kts",
            ".less",
            ".lock",
            ".md",
            ".mjs",
            ".php",
            ".properties",
            ".ps1",
            ".py",
            ".pyi",
            ".rb",
            ".rs",
            ".rst",
            ".sass",
            ".scala",
            ".sc",
            ".scss",
            ".sh",
            ".sql",
            ".svg",
            ".toml",
            ".ts",
            ".tsx",
            ".txt",
            ".vue",
            ".xml",
            ".yaml",
            ".yml",
        }
    ),
    allowed_file_names=frozenset(
        {
            ".dockerignore",
            ".editorconfig",
            ".gitattributes",
            ".gitignore",
            ".npmrc",
            ".nvmrc",
            "dockerfile",
            "gemfile",
            "license",
            "makefile",
            "procfile",
            "rakefile",
            "readme",
        }
    ),
    sensitive_file_names=frozenset(
        {
            "credentials.json",
            "id_dsa",
            "id_ecdsa",
            "id_ed25519",
            "id_rsa",
            "secrets.json",
            "secrets.toml",
            "secrets.yaml",
            "secrets.yml",
            "service-account.json",
        }
    ),
    sensitive_file_suffixes=frozenset(
        {
            ".jks",
            ".key",
            ".keystore",
            ".p12",
            ".pem",
            ".pfx",
        }
    ),
    environment_template_suffixes=frozenset(
        {
            ".dist",
            ".example",
            ".sample",
            ".template",
        }
    ),
)
