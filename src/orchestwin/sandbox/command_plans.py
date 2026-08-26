"""Immutable structured command plans for sandbox execution profiles."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final

_IDENTIFIER_PATTERN: Final = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)*$")
_ENVIRONMENT_KEY_PATTERN: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_WINDOWS_DRIVE_PATTERN: Final = re.compile(r"^[A-Za-z]:")
_VERSION_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_COMMAND_PLAN_SCHEMA_VERSION: Final = 1


class CommandNetworkMode(StrEnum):
    """Network access requested by one structured sandbox command."""

    DISABLED = "DISABLED"
    CONTROLLED = "CONTROLLED"


@dataclass(frozen=True, slots=True)
class SecretReference:
    """Reference to externally resolved secret material, never the secret value."""

    reference_id: str
    environment_key: str

    def __post_init__(self) -> None:
        """Reject ambiguous identifiers and invalid environment destinations."""
        _validate_identifier(self.reference_id, label="secret reference ID")
        _validate_environment_key(self.environment_key)

    def to_snapshot(self) -> dict[str, str]:
        """Return safe metadata without resolving or exposing a secret value."""
        return {
            "reference_id": self.reference_id,
            "environment_key": self.environment_key,
        }


@dataclass(frozen=True, slots=True)
class StructuredCommand:
    """One shell-free process invocation described as validated values."""

    command_id: str
    executable: str
    arguments: tuple[str, ...]
    working_directory: str
    allowed_environment_keys: frozenset[str]
    secret_references: frozenset[SecretReference]
    timeout_seconds: int
    network_mode: CommandNetworkMode
    expected_exit_codes: frozenset[int]
    output_parser_id: str | None
    artifact_patterns: frozenset[str]

    def __post_init__(self) -> None:
        """Protect the structural command boundary before policy evaluation."""
        _validate_identifier(self.command_id, label="command ID")
        _validate_process_value(self.executable, label="command executable", allow_empty=False)
        for argument in self.arguments:
            _validate_process_value(argument, label="command argument", allow_empty=True)

        _validate_relative_path(self.working_directory, label="command working directory")

        for key in self.allowed_environment_keys:
            _validate_environment_key(key)

        secret_environment_keys = {
            reference.environment_key for reference in self.secret_references
        }
        if not secret_environment_keys <= self.allowed_environment_keys:
            raise ValueError(
                "secret reference environment keys must be declared as allowed environment keys"
            )

        if isinstance(self.timeout_seconds, bool) or self.timeout_seconds < 1:
            raise ValueError("command timeout must be a positive integer")

        if not self.expected_exit_codes:
            raise ValueError("command expected exit codes must not be empty")
        for exit_code in self.expected_exit_codes:
            if isinstance(exit_code, bool) or not 0 <= exit_code <= 255:
                raise ValueError("command expected exit codes must be integers from zero to 255")

        if self.output_parser_id is not None:
            _validate_identifier(self.output_parser_id, label="output parser ID")

        for pattern in self.artifact_patterns:
            _validate_artifact_pattern_shape(pattern)

    def to_snapshot(self) -> dict[str, object]:
        """Return canonical command metadata suitable for hashing and persistence."""
        return {
            "command_id": self.command_id,
            "executable": self.executable,
            "arguments": list(self.arguments),
            "working_directory": self.working_directory,
            "allowed_environment_keys": sorted(self.allowed_environment_keys),
            "secret_references": [
                reference.to_snapshot()
                for reference in sorted(
                    self.secret_references,
                    key=lambda item: (item.environment_key, item.reference_id),
                )
            ],
            "timeout_seconds": self.timeout_seconds,
            "network_mode": self.network_mode.value,
            "expected_exit_codes": sorted(self.expected_exit_codes),
            "output_parser_id": self.output_parser_id,
            "artifact_patterns": sorted(self.artifact_patterns),
        }


@dataclass(frozen=True, slots=True)
class CommandPlan:
    """Ordered immutable commands produced by one execution profile version."""

    plan_id: str
    profile_id: str
    profile_version: str
    commands: tuple[StructuredCommand, ...]
    schema_version: int = _COMMAND_PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Reject empty, ambiguous, or internally inconsistent plans."""
        _validate_identifier(self.plan_id, label="command plan ID")
        _validate_identifier(self.profile_id, label="execution profile ID")
        _validate_version(self.profile_version)

        if self.schema_version != _COMMAND_PLAN_SCHEMA_VERSION:
            raise ValueError("unsupported command plan schema version")
        if not self.commands:
            raise ValueError("command plan must contain at least one command")

        command_ids = tuple(command.command_id for command in self.commands)
        if len(command_ids) != len(set(command_ids)):
            raise ValueError("command plan command IDs must be unique")

    @property
    def content_hash(self) -> str:
        """Return a SHA-256 digest of the canonical structured plan content."""
        return hashlib.sha256(_canonical_json_bytes(self._content_snapshot())).hexdigest()

    @property
    def total_timeout_seconds(self) -> int:
        """Return the sequential worst-case command timeout budget."""
        return sum(command.timeout_seconds for command in self.commands)

    def command_by_id(self, command_id: str) -> StructuredCommand | None:
        """Resolve one command without accepting positional ambiguity."""
        return next(
            (command for command in self.commands if command.command_id == command_id),
            None,
        )

    def to_snapshot(self) -> dict[str, object]:
        """Return canonical persisted metadata including its integrity digest."""
        return {
            **self._content_snapshot(),
            "content_hash": self.content_hash,
        }

    def _content_snapshot(self) -> dict[str, object]:
        """Build the exact payload covered by the content hash."""
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "commands": [command.to_snapshot() for command in self.commands],
        }


def _validate_identifier(value: str, *, label: str) -> None:
    """Require stable portable identifiers suitable for public references."""
    if not _IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must be a normalized portable identifier")


def _validate_version(value: str) -> None:
    """Require a compact portable execution-profile version."""
    if not _VERSION_PATTERN.fullmatch(value):
        raise ValueError("execution profile version must be normalized")


def _validate_environment_key(value: str) -> None:
    """Require a portable process-environment key."""
    if not _ENVIRONMENT_KEY_PATTERN.fullmatch(value):
        raise ValueError("allowed environment keys must be portable identifiers")


def _validate_process_value(
    value: str,
    *,
    label: str,
    allow_empty: bool,
) -> None:
    """Reject values that cannot be passed safely through an argument vector."""
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if not allow_empty and not value:
        raise ValueError(f"{label} must not be empty")
    if any(character in value for character in ("\x00", "\r", "\n")):
        raise ValueError(f"{label} must not contain control separators")
    if not allow_empty and value != value.strip():
        raise ValueError(f"{label} must be normalized")


def _validate_relative_path(value: str, *, label: str) -> None:
    """Require one portable relative POSIX path rooted inside a workspace."""
    if (
        not value
        or value != value.strip()
        or value != unicodedata.normalize("NFC", value)
        or "\\" in value
        or "\x00" in value
        or value.startswith("/")
        or value.startswith("//")
        or _WINDOWS_DRIVE_PATTERN.match(value)
    ):
        raise ValueError(f"{label} must be a normalized relative POSIX path")

    if value == ".":
        return

    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{label} must stay inside the workspace")

    if PurePosixPath(value).as_posix() != value:
        raise ValueError(f"{label} must be canonical")


def _validate_artifact_pattern_shape(pattern: str) -> None:
    """Protect serialization shape before security policy validates glob semantics."""
    if (
        not pattern
        or pattern != pattern.strip()
        or pattern != unicodedata.normalize("NFC", pattern)
        or any(character in pattern for character in ("\x00", "\r", "\n", "\\"))
    ):
        raise ValueError("artifact patterns must be normalized POSIX glob values")


def _canonical_json_bytes(value: dict[str, object]) -> bytes:
    """Serialize one snapshot deterministically for integrity hashing."""
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
