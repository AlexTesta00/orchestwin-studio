"""Tests for immutable brownfield source-intake snapshots."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.projects.brownfield_intake import (
    BrownfieldIntakeSnapshot,
    BrownfieldIntakeVersion,
    create_source_archive_validation_evidence,
    source_archive_policy_content_hash,
    source_archive_policy_snapshot,
)
from orchestwin.projects.execution_capabilities import (
    CapabilityNegotiationRequest,
    CapabilityNegotiationStatus,
    negotiate_execution_capability,
)
from orchestwin.sandbox.archive_policy import (
    DEFAULT_SOURCE_ARCHIVE_POLICY,
    SourceArchiveEntryDisposition,
    SourceArchiveEntryKind,
    SourceArchiveIgnoreReason,
    SourceArchiveIssue,
    SourceArchiveIssueCode,
    SourceArchiveValidationStatus,
)
from orchestwin.sandbox.archive_store import StoredSourceArchive
from orchestwin.sandbox.archive_validation import (
    SourceArchiveValidationReport,
    ValidatedSourceArchiveEntry,
)
from orchestwin.sandbox.builtin_execution_profiles import (
    create_builtin_execution_profile_registry,
)
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.sandbox.source_inventory import (
    SourceInventoryClassification,
    SourceInventoryEntry,
    SourceTreeInventory,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000007401")
OWNER_ID = UUID("00000000-0000-4000-8000-000000007402")
INTAKE_ID = UUID("00000000-0000-4000-8000-000000007403")
ARCHIVE_DIGEST = "a" * 64
FILE_DIGEST = "b" * 64
CREATED_AT = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)


def _validation_report() -> SourceArchiveValidationReport:
    entries = (
        ValidatedSourceArchiveEntry(
            archive_name="index.html",
            normalized_path="index.html",
            canonical_path="index.html",
            kind=SourceArchiveEntryKind.FILE,
            disposition=SourceArchiveEntryDisposition.INCLUDE,
            ignore_reason=None,
            compressed_size=12,
            uncompressed_size=18,
            crc32=1,
        ),
        ValidatedSourceArchiveEntry(
            archive_name="node_modules/pkg/index.js",
            normalized_path="node_modules/pkg/index.js",
            canonical_path="node_modules/pkg/index.js",
            kind=SourceArchiveEntryKind.FILE,
            disposition=SourceArchiveEntryDisposition.IGNORE,
            ignore_reason=SourceArchiveIgnoreReason.GENERATED_PATH,
            compressed_size=10,
            uncompressed_size=20,
            crc32=2,
        ),
    )
    return SourceArchiveValidationReport(
        status=SourceArchiveValidationStatus.ACCEPTED,
        archive_size_bytes=64,
        archive_sha256=ARCHIVE_DIGEST,
        total_uncompressed_bytes=38,
        entries=entries,
        issues=(),
    )


def _inventory() -> SourceTreeInventory:
    entries = (
        SourceInventoryEntry(
            normalized_path="index.html",
            kind=SourceArchiveEntryKind.FILE,
            classification=SourceInventoryClassification.SOURCE,
            size_bytes=18,
            sha256_digest=FILE_DIGEST,
            disposition=SourceArchiveEntryDisposition.INCLUDE,
            disposition_reason=None,
        ),
        SourceInventoryEntry(
            normalized_path="node_modules/pkg/index.js",
            kind=SourceArchiveEntryKind.FILE,
            classification=SourceInventoryClassification.GENERATED,
            size_bytes=20,
            sha256_digest=None,
            disposition=SourceArchiveEntryDisposition.IGNORE,
            disposition_reason=SourceArchiveIgnoreReason.GENERATED_PATH,
        ),
    )
    return SourceTreeInventory(
        archive_sha256=ARCHIVE_DIGEST,
        entries=entries,
    )


def _snapshot() -> BrownfieldIntakeSnapshot:
    report = _validation_report()
    inventory = _inventory()
    capability = negotiate_execution_capability(
        inventory,
        registry=create_builtin_execution_profile_registry(),
        request=CapabilityNegotiationRequest(
            requested_target=ExecutionTarget.WEB_STATIC,
            available_runners=(),
            approved_experimental_profiles=(),
        ),
    )
    return BrownfieldIntakeSnapshot(
        project_id=PROJECT_ID,
        validation=create_source_archive_validation_evidence(
            report,
            policy=DEFAULT_SOURCE_ARCHIVE_POLICY,
        ),
        archive=StoredSourceArchive(
            sha256_digest=ARCHIVE_DIGEST,
            size_bytes=64,
            storage_key=f"sha256/aa/{ARCHIVE_DIGEST}.zip",
        ),
        inventory=inventory,
        capability=capability,
    )


def test_policy_snapshot_and_hash_are_stable_and_complete() -> None:
    """Bind validation evidence to every configured archive-safety input."""
    snapshot = source_archive_policy_snapshot(DEFAULT_SOURCE_ARCHIVE_POLICY)

    assert snapshot["schema_version"] == 1
    assert snapshot["maximum_archive_size_bytes"] == 25 * 1024 * 1024
    assert "node_modules" in snapshot["ignored_directory_names"]
    assert "credentials.json" in snapshot["sensitive_file_names"]
    assert source_archive_policy_content_hash(DEFAULT_SOURCE_ARCHIVE_POLICY) == (
        source_archive_policy_content_hash(DEFAULT_SOURCE_ARCHIVE_POLICY)
    )


def test_validation_evidence_rejects_rejected_reports() -> None:
    """Never persist a rejected preflight result as accepted intake evidence."""
    rejected = replace(
        _validation_report(),
        status=SourceArchiveValidationStatus.REJECTED,
        issues=(
            SourceArchiveIssue(
                code=SourceArchiveIssueCode.INVALID_ZIP,
                message="Archive is invalid.",
            ),
        ),
    )

    with pytest.raises(ValueError):
        create_source_archive_validation_evidence(
            rejected,
            policy=DEFAULT_SOURCE_ARCHIVE_POLICY,
        )


def test_intake_snapshot_binds_archive_inventory_and_capability_exactly() -> None:
    """Create one canonical snapshot whose nested digests all agree."""
    snapshot = _snapshot()

    assert snapshot.capability.status is (CapabilityNegotiationStatus.HUMAN_DECISION_REQUIRED)
    assert snapshot.inventory.content_hash == snapshot.capability.inventory_content_hash
    assert snapshot.validation.archive_sha256 == snapshot.archive.sha256_digest
    assert snapshot.content_hash == snapshot.content_hash
    assert snapshot.canonical_json().count("index.html") >= 1


def test_intake_snapshot_rejects_mismatched_archive_inventory_or_capability() -> None:
    """Prevent cross-archive or stale capability evidence from being combined."""
    snapshot = _snapshot()

    with pytest.raises(ValueError, match="stored archive"):
        replace(
            snapshot,
            archive=StoredSourceArchive(
                sha256_digest="c" * 64,
                size_bytes=64,
                storage_key=f"sha256/cc/{'c' * 64}.zip",
            ),
        )

    with pytest.raises(ValueError, match="inventory"):
        replace(
            snapshot,
            inventory=replace(snapshot.inventory, archive_sha256="d" * 64),
        )

    with pytest.raises(ValueError, match="capability"):
        replace(
            snapshot,
            capability=replace(snapshot.capability, inventory_content_hash="e" * 64),
        )


def test_intake_snapshot_rejects_validation_entry_count_drift() -> None:
    """Detect a stored inventory that omits validation-report dispositions."""
    snapshot = _snapshot()

    with pytest.raises(ValueError, match="included count"):
        replace(
            snapshot,
            validation=replace(snapshot.validation, included_entry_count=2),
        )


def test_intake_version_requires_exact_hash_and_linear_lineage() -> None:
    """Make every project intake version immutable and append-only."""
    snapshot = _snapshot()
    version = BrownfieldIntakeVersion(
        id=INTAKE_ID,
        project_id=PROJECT_ID,
        version_number=1,
        based_on_version_number=None,
        snapshot=snapshot,
        content_hash=snapshot.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )

    assert version.reference.content_hash == snapshot.content_hash
    assert version.reference.version_number == 1

    with pytest.raises(ValueError, match="hash"):
        replace(version, content_hash="f" * 64)
    with pytest.raises(ValueError, match="predecessor"):
        replace(version, based_on_version_number=1)


def test_intake_version_rejects_cross_project_and_naive_time() -> None:
    """Preserve owner-scoped project identity and reproducible UTC metadata."""
    snapshot = _snapshot()
    version = BrownfieldIntakeVersion(
        id=INTAKE_ID,
        project_id=PROJECT_ID,
        version_number=1,
        based_on_version_number=None,
        snapshot=snapshot,
        content_hash=snapshot.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )

    with pytest.raises(ValueError, match="another project"):
        replace(version, project_id=UUID("00000000-0000-4000-8000-000000007499"))
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(version, created_at=datetime(2026, 8, 25, 9, 0))
