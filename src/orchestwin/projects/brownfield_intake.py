"""Immutable brownfield source-intake snapshots and version identities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from orchestwin.projects.execution_capabilities import CapabilityNegotiationResult
from orchestwin.projects.requirements_primitives import (
    canonical_json,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.sandbox.archive_policy import (
    SourceArchiveEntryKind,
    SourceArchivePolicy,
)
from orchestwin.sandbox.archive_store import StoredSourceArchive
from orchestwin.sandbox.archive_validation import SourceArchiveValidationReport
from orchestwin.sandbox.source_inventory import SourceTreeInventory

BROWNFIELD_INTAKE_SCHEMA_VERSION: Final = 1
SOURCE_ARCHIVE_POLICY_SCHEMA_VERSION: Final = 1


@dataclass(frozen=True, slots=True)
class SourceArchiveValidationEvidence:
    """Stable evidence that an exact archive passed one exact intake policy."""

    archive_sha256: str
    archive_size_bytes: int
    total_uncompressed_bytes: int
    included_entry_count: int
    ignored_entry_count: int
    policy_content_hash: str
    report_content_hash: str

    def __post_init__(self) -> None:
        """Protect report identity, sizes, counts, and policy binding."""
        validate_sha256(
            self.archive_sha256,
            label="source archive validation digest",
        )
        validate_sha256(
            self.policy_content_hash,
            label="source archive policy content hash",
        )
        validate_sha256(
            self.report_content_hash,
            label="source archive validation report hash",
        )

        integer_values = (
            self.archive_size_bytes,
            self.total_uncompressed_bytes,
            self.included_entry_count,
            self.ignored_entry_count,
        )
        if any(isinstance(value, bool) or value < 0 for value in integer_values):
            raise ValueError("source archive validation sizes and counts must not be negative")
        if self.included_entry_count < 1:
            raise ValueError("source archive validation requires at least one included entry")

    def to_snapshot(self) -> dict[str, object]:
        """Return deterministic evidence without archive contents or host paths."""
        return {
            "archive_sha256": self.archive_sha256,
            "archive_size_bytes": self.archive_size_bytes,
            "total_uncompressed_bytes": self.total_uncompressed_bytes,
            "included_entry_count": self.included_entry_count,
            "ignored_entry_count": self.ignored_entry_count,
            "policy_content_hash": self.policy_content_hash,
            "report_content_hash": self.report_content_hash,
        }


@dataclass(frozen=True, slots=True)
class BrownfieldIntakeSnapshot:
    """Exact validated archive, source inventory, and capability assessment."""

    project_id: UUID
    validation: SourceArchiveValidationEvidence
    archive: StoredSourceArchive
    inventory: SourceTreeInventory
    capability: CapabilityNegotiationResult
    schema_version: int = BROWNFIELD_INTAKE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Bind every nested artifact to the same archive and source inventory."""
        if self.schema_version != BROWNFIELD_INTAKE_SCHEMA_VERSION:
            raise ValueError("unsupported brownfield intake schema version")
        if self.archive.sha256_digest != self.validation.archive_sha256:
            raise ValueError("brownfield stored archive does not match validation evidence")
        if self.archive.size_bytes != self.validation.archive_size_bytes:
            raise ValueError("brownfield stored archive size does not match validation evidence")
        if self.inventory.archive_sha256 != self.validation.archive_sha256:
            raise ValueError("brownfield inventory does not match the validated archive")
        if self.capability.inventory_content_hash != self.inventory.content_hash:
            raise ValueError("brownfield capability result targets another source inventory")

        included_count = len(self.inventory.included_entries)
        included_file_count = sum(
            entry.kind is not SourceArchiveEntryKind.DIRECTORY
            for entry in self.inventory.included_entries
        )
        ignored_count = len(self.inventory.excluded_entries)
        if not (included_file_count <= self.validation.included_entry_count <= included_count):
            raise ValueError("brownfield inventory included count differs from validation evidence")
        if ignored_count != self.validation.ignored_entry_count:
            raise ValueError("brownfield inventory ignored count differs from validation evidence")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic, safe brownfield intake snapshot."""
        return {
            "schema_version": self.schema_version,
            "project_id": str(self.project_id),
            "validation": self.validation.to_snapshot(),
            "archive": self.archive.to_snapshot(),
            "inventory": self.inventory.to_snapshot(),
            "capability": self.capability.to_snapshot(),
        }

    def canonical_json(self) -> str:
        """Serialize the full intake snapshot deterministically."""
        return canonical_json(self.to_snapshot())

    @property
    def content_hash(self) -> str:
        """Return the immutable SHA-256 identity of this intake snapshot."""
        return snapshot_content_hash(self.to_snapshot())


@dataclass(frozen=True, slots=True)
class BrownfieldIntakeReference:
    """Exact version/hash tuple suitable for traceability and stale checks."""

    intake_id: UUID
    project_id: UUID
    version_number: int
    content_hash: str

    def __post_init__(self) -> None:
        validate_positive_integer(
            self.version_number,
            label="brownfield intake reference version",
        )
        validate_sha256(
            self.content_hash,
            label="brownfield intake reference content hash",
        )

    def to_snapshot(self) -> dict[str, object]:
        """Return stable reference metadata."""
        return {
            "intake_id": str(self.intake_id),
            "project_id": str(self.project_id),
            "version_number": self.version_number,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class BrownfieldIntakeVersion:
    """One append-only version of a project's brownfield source intake."""

    id: UUID
    project_id: UUID
    version_number: int
    based_on_version_number: int | None
    snapshot: BrownfieldIntakeSnapshot
    content_hash: str
    created_by_user_id: UUID
    created_at: datetime

    def __post_init__(self) -> None:
        """Protect project binding, linear lineage, hash identity, and time."""
        validate_positive_integer(
            self.version_number,
            label="brownfield intake version number",
        )
        validate_sha256(
            self.content_hash,
            label="brownfield intake version content hash",
        )
        if self.snapshot.project_id != self.project_id:
            raise ValueError("brownfield intake snapshot belongs to another project")
        if self.content_hash != self.snapshot.content_hash:
            raise ValueError("brownfield intake version hash must match its snapshot")

        if self.version_number == 1:
            if self.based_on_version_number is not None:
                raise ValueError("first brownfield intake version cannot have a predecessor")
        elif self.based_on_version_number != self.version_number - 1:
            raise ValueError("brownfield intake versions require linear lineage")

        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("brownfield intake creation timestamp must be timezone-aware")

    @property
    def reference(self) -> BrownfieldIntakeReference:
        """Return the exact immutable reference for this version."""
        return BrownfieldIntakeReference(
            intake_id=self.id,
            project_id=self.project_id,
            version_number=self.version_number,
            content_hash=self.content_hash,
        )

    def to_snapshot(self) -> dict[str, object]:
        """Return persisted version metadata plus the exact intake content."""
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "version_number": self.version_number,
            "based_on_version_number": self.based_on_version_number,
            "content_hash": self.content_hash,
            "snapshot": self.snapshot.to_snapshot(),
            "created_by_user_id": str(self.created_by_user_id),
            "created_at": self.created_at.isoformat(),
        }


def source_archive_policy_snapshot(policy: SourceArchivePolicy) -> dict[str, object]:
    """Return a stable representation of every archive-safety policy input."""
    return {
        "schema_version": SOURCE_ARCHIVE_POLICY_SCHEMA_VERSION,
        "maximum_archive_size_bytes": policy.maximum_archive_size_bytes,
        "maximum_total_uncompressed_bytes": policy.maximum_total_uncompressed_bytes,
        "maximum_entry_uncompressed_bytes": policy.maximum_entry_uncompressed_bytes,
        "maximum_entries": policy.maximum_entries,
        "maximum_compression_ratio": policy.maximum_compression_ratio,
        "maximum_normalized_path_length": policy.maximum_normalized_path_length,
        "ignored_directory_names": sorted(policy.ignored_directory_names),
        "allowed_file_extensions": sorted(policy.allowed_file_extensions),
        "allowed_file_names": sorted(policy.allowed_file_names),
        "sensitive_file_names": sorted(policy.sensitive_file_names),
        "sensitive_file_suffixes": sorted(policy.sensitive_file_suffixes),
        "environment_template_suffixes": sorted(policy.environment_template_suffixes),
    }


def source_archive_policy_content_hash(policy: SourceArchivePolicy) -> str:
    """Hash every archive-safety policy input for later reproducibility."""
    return snapshot_content_hash(source_archive_policy_snapshot(policy))


def create_source_archive_validation_evidence(
    report: SourceArchiveValidationReport,
    *,
    policy: SourceArchivePolicy,
) -> SourceArchiveValidationEvidence:
    """Bind one accepted preflight report to the policy that produced it."""
    if not report.is_accepted or report.archive_sha256 is None:
        raise ValueError("brownfield validation evidence requires an accepted archive report")

    report_snapshot = {
        "archive_size_bytes": report.archive_size_bytes,
        "archive_sha256": report.archive_sha256,
        "total_uncompressed_bytes": report.total_uncompressed_bytes,
        "entries": [
            {
                "archive_name": entry.archive_name,
                "normalized_path": entry.normalized_path,
                "canonical_path": entry.canonical_path,
                "kind": entry.kind.value,
                "disposition": entry.disposition.value,
                "ignore_reason": (
                    None if entry.ignore_reason is None else entry.ignore_reason.value
                ),
                "compressed_size": entry.compressed_size,
                "uncompressed_size": entry.uncompressed_size,
                "crc32": entry.crc32,
            }
            for entry in report.entries
        ],
    }
    return SourceArchiveValidationEvidence(
        archive_sha256=report.archive_sha256,
        archive_size_bytes=report.archive_size_bytes,
        total_uncompressed_bytes=report.total_uncompressed_bytes,
        included_entry_count=len(report.included_entries),
        ignored_entry_count=len(report.ignored_entries),
        policy_content_hash=source_archive_policy_content_hash(policy),
        report_content_hash=snapshot_content_hash(report_snapshot),
    )
