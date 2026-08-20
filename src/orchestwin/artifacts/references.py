"""Shared exact references for governed design and architecture artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from orchestwin.projects.requirements_primitives import (
    validate_positive_integer,
    validate_sha256,
)


class ArtifactKind(StrEnum):
    """Stable kinds of versioned artifacts used after Requirements approval."""

    REQUIREMENTS_SPECIFICATION = "REQUIREMENTS_SPECIFICATION"
    AGENT_TEAM = "AGENT_TEAM"
    USER_MODELING = "USER_MODELING"
    DESIGN_PACKAGE = "DESIGN_PACKAGE"
    DECLARATIVE_PROTOTYPE = "DECLARATIVE_PROTOTYPE"
    ARCHITECTURE_PACKAGE = "ARCHITECTURE_PACKAGE"


@dataclass(frozen=True, slots=True)
class VersionedArtifactReference:
    """Exact identity, version, and hash of one governed artifact."""

    kind: ArtifactKind
    artifact_id: UUID
    version_number: int
    content_hash: str

    def __post_init__(self) -> None:
        """Protect exact artifact metadata."""
        validate_positive_integer(
            self.version_number,
            label="artifact reference version number",
        )
        validate_sha256(
            self.content_hash,
            label="artifact reference content hash",
        )

    @property
    def sort_key(self) -> tuple[str, str, int, str]:
        """Return deterministic ordering metadata."""
        return (
            self.kind.value,
            self.artifact_id.hex,
            self.version_number,
            self.content_hash,
        )

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic exact-reference snapshot."""
        return {
            "kind": self.kind.value,
            "artifact_id": str(self.artifact_id),
            "version_number": self.version_number,
            "content_hash": self.content_hash,
        }


def require_artifact_kind(
    reference: VersionedArtifactReference,
    *,
    expected: ArtifactKind,
    label: str,
) -> None:
    """Require a reference to identify the expected artifact kind."""
    if reference.kind is not expected:
        raise ValueError(f"{label} must reference {expected.value}")


__all__ = [
    "ArtifactKind",
    "VersionedArtifactReference",
    "require_artifact_kind",
]
