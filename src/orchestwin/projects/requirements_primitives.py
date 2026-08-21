"""Shared immutable primitives for project requirements artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

_MAX_SOURCE_ID_LENGTH: Final = 256
_MAX_SOURCE_LOCATOR_LENGTH: Final = 512
_MAX_USER_TWIN_NAME_LENGTH: Final = 200
_SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}")


def normalize_required_text(
    value: str,
    *,
    label: str,
    maximum_length: int,
) -> str:
    """Normalize one required human-readable value."""
    normalized = " ".join(value.split())

    if not normalized:
        raise ValueError(f"{label} must not be empty")

    if len(normalized) > maximum_length:
        raise ValueError(f"{label} exceeds maximum length")

    return normalized


def normalize_optional_text(
    value: str | None,
    *,
    label: str,
    maximum_length: int,
) -> str | None:
    """Normalize optional text when supplied."""
    if value is None:
        return None

    return normalize_required_text(
        value,
        label=label,
        maximum_length=maximum_length,
    )


def normalize_text_items(
    values: Iterable[str],
    *,
    label: str,
    maximum_item_length: int,
    require_items: bool,
    require_unique: bool = True,
) -> tuple[str, ...]:
    """Normalize an ordered collection of human-readable items."""
    normalized = tuple(
        normalize_required_text(
            value,
            label=label,
            maximum_length=maximum_item_length,
        )
        for value in values
    )

    if require_items and not normalized:
        raise ValueError(f"{label} must not be empty")

    if require_unique and len(normalized) != len(set(normalized)):
        raise ValueError(f"{label} must be unique")

    return normalized


def validate_positive_integer(
    value: int,
    *,
    label: str,
) -> None:
    """Require one positive non-boolean integer."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be positive")


def validate_sha256(
    value: str,
    *,
    label: str,
) -> None:
    """Require a lowercase SHA-256 digest."""
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


def validate_display_code(
    value: str,
    *,
    prefix: str,
    label: str,
) -> None:
    """Require a stable human-readable artifact code."""
    if (
        re.fullmatch(
            rf"{re.escape(prefix)}-[0-9]{{3,6}}",
            value,
        )
        is None
    ):
        raise ValueError(f"{label} must use the {prefix}-NNN format")


def canonical_uuid_tuple(
    values: Iterable[UUID],
    *,
    label: str,
    require_items: bool,
) -> tuple[UUID, ...]:
    """Return unique UUIDs in canonical hexadecimal order."""
    items = tuple(values)

    if len(items) != len(set(items)):
        raise ValueError(f"{label} must be unique")

    ordered = tuple(
        sorted(
            items,
            key=lambda value: value.hex,
        )
    )

    if require_items and not ordered:
        raise ValueError(f"{label} must not be empty")

    return ordered


def canonical_json(
    payload: dict[str, object],
) -> str:
    """Serialize a JSON-compatible payload deterministically."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def snapshot_content_hash(
    payload: dict[str, object],
) -> str:
    """Return a SHA-256 hash for deterministic snapshot content."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class RequirementsContextKind(StrEnum):
    """Governed inputs grounding a requirements specification."""

    PROJECT_BRIEF = "PROJECT_BRIEF"
    AGENT_TEAM = "AGENT_TEAM"
    USER_MODELING = "USER_MODELING"


class RequirementSourceKind(StrEnum):
    """Inspectable origins of an individual requirement or risk."""

    PROJECT_BRIEF = "PROJECT_BRIEF"
    USER_TWIN = "USER_TWIN"
    OWNER_INPUT = "OWNER_INPUT"
    MODEL_PROPOSAL = "MODEL_PROPOSAL"
    SYSTEM_ARTIFACT = "SYSTEM_ARTIFACT"


@dataclass(frozen=True, slots=True)
class RequirementsContextReference:
    """Exact reference to one governed project input."""

    kind: RequirementsContextKind
    artifact_id: UUID
    version_number: int
    content_hash: str

    def __post_init__(self) -> None:
        """Protect exact artifact identity metadata."""
        validate_positive_integer(
            self.version_number,
            label="requirements context version number",
        )
        validate_sha256(
            self.content_hash,
            label="requirements context content hash",
        )

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic context-reference snapshot."""
        return {
            "kind": self.kind.value,
            "artifact_id": str(self.artifact_id),
            "version_number": self.version_number,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class RequirementSourceReference:
    """One inspectable source supporting a requirement artifact."""

    kind: RequirementSourceKind
    source_id: str
    source_version: int | None = None
    content_hash: str | None = None
    locator: str | None = None

    def __post_init__(self) -> None:
        """Protect normalized and auditable source metadata."""
        normalized_source_id = normalize_required_text(
            self.source_id,
            label="requirement source ID",
            maximum_length=_MAX_SOURCE_ID_LENGTH,
        )

        if normalized_source_id != self.source_id:
            raise ValueError("requirement source ID must be normalized")

        if self.source_version is not None:
            validate_positive_integer(
                self.source_version,
                label="requirement source version",
            )

        if self.content_hash is not None:
            validate_sha256(
                self.content_hash,
                label="requirement source content hash",
            )

        if self.locator is not None:
            normalized_locator = normalize_required_text(
                self.locator,
                label="requirement source locator",
                maximum_length=_MAX_SOURCE_LOCATOR_LENGTH,
            )

            if normalized_locator != self.locator:
                raise ValueError("requirement source locator must be normalized")

    @property
    def sort_key(
        self,
    ) -> tuple[str, str, int, str, str]:
        """Return the deterministic source ordering key."""
        return (
            self.kind.value,
            self.source_id,
            self.source_version or 0,
            self.content_hash or "",
            self.locator or "",
        )

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic source-reference snapshot."""
        return {
            "kind": self.kind.value,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "content_hash": self.content_hash,
            "locator": self.locator,
        }


@dataclass(frozen=True, slots=True)
class UserTwinVersionReference:
    """Exact User Twin version used by requirements artifacts."""

    twin_id: UUID
    version_number: int
    content_hash: str
    name: str

    def __post_init__(self) -> None:
        """Protect exact User Twin identity and readable metadata."""
        validate_positive_integer(
            self.version_number,
            label="User Twin version number",
        )
        validate_sha256(
            self.content_hash,
            label="User Twin content hash",
        )

        normalized_name = normalize_required_text(
            self.name,
            label="User Twin name",
            maximum_length=_MAX_USER_TWIN_NAME_LENGTH,
        )

        if normalized_name != self.name:
            raise ValueError("User Twin name must be normalized")

    @property
    def sort_key(
        self,
    ) -> tuple[str, int, str]:
        """Return the deterministic User Twin ordering key."""
        return (
            self.twin_id.hex,
            self.version_number,
            self.content_hash,
        )

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic User Twin reference snapshot."""
        return {
            "twin_id": str(self.twin_id),
            "version_number": self.version_number,
            "content_hash": self.content_hash,
            "name": self.name,
        }


def canonical_requirement_sources(
    values: Iterable[RequirementSourceReference],
    *,
    require_items: bool,
) -> tuple[RequirementSourceReference, ...]:
    """Return unique sources in deterministic order."""
    sources = tuple(values)

    if len(sources) != len(set(sources)):
        raise ValueError("requirement sources must be unique")

    ordered = tuple(
        sorted(
            sources,
            key=lambda value: value.sort_key,
        )
    )

    if require_items and not ordered:
        raise ValueError("requirement sources must not be empty")

    return ordered


def canonical_user_twin_references(
    values: Iterable[UserTwinVersionReference],
    *,
    require_items: bool,
) -> tuple[UserTwinVersionReference, ...]:
    """Return unique User Twin references in deterministic order."""
    references = tuple(values)

    if len(references) != len(set(references)):
        raise ValueError("User Twin references must be unique")

    ordered = tuple(
        sorted(
            references,
            key=lambda value: value.sort_key,
        )
    )

    if require_items and not ordered:
        raise ValueError("User Twin references must not be empty")

    return ordered
