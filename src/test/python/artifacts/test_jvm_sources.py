"""Tests for immutable JVM source revisions and lineage."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.artifacts.jvm_sources import (
    JvmSourceFileEntry,
    JvmSourceOrigin,
    JvmSourceProvenanceKind,
    JvmSourceProvenanceReference,
    create_jvm_source_revision,
)
from orchestwin.sandbox.execution_profiles import ExecutionTarget

PROJECT_ID = UUID("00000000-0000-4000-8000-000000009401")
OWNER_ID = UUID("00000000-0000-4000-8000-000000009402")
REVISION_ONE_ID = UUID("00000000-0000-4000-8000-000000009403")
REVISION_TWO_ID = UUID("00000000-0000-4000-8000-000000009404")
NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def file(path: str, digest: str) -> JvmSourceFileEntry:
    return JvmSourceFileEntry(
        normalized_path=path,
        sha256_digest=digest,
        size_bytes=12,
        storage_key=f"sha256/{digest[:2]}/{digest}",
        media_type="text/plain",
    )


def provenance() -> tuple[JvmSourceProvenanceReference, ...]:
    return (
        JvmSourceProvenanceReference(
            kind=JvmSourceProvenanceKind.SOURCE_PLAN,
            reference_id="source-plan:fixture",
            version_number=1,
            content_hash="a" * 64,
        ),
    )


def first_revision():
    return create_jvm_source_revision(
        revision_id=REVISION_ONE_ID,
        project_id=PROJECT_ID,
        created_by_user_id=OWNER_ID,
        version_number=1,
        based_on=None,
        target=ExecutionTarget.JVM_KOTLIN,
        origin=JvmSourceOrigin.DETERMINISTIC_FIXTURE,
        files=(file("src/main/kotlin/example/Main.kt", "b" * 64),),
        provenance_references=provenance(),
        created_at=NOW,
    )


def test_first_revision_has_content_and_source_tree_identities() -> None:
    revision = first_revision()

    assert len(revision.content_hash) == 64
    assert len(revision.source_tree_hash) == 64
    assert revision.reference.version_number == 1
    assert revision.file_by_path("src/main/kotlin/example/Main.kt") == revision.files[0]
    assert revision.to_snapshot()["validation_scope_hash"] == revision.validation_scope_hash


def test_repair_revision_requires_exact_linear_lineage_and_failure() -> None:
    previous = first_revision()
    repaired = create_jvm_source_revision(
        revision_id=REVISION_TWO_ID,
        project_id=PROJECT_ID,
        created_by_user_id=OWNER_ID,
        version_number=2,
        based_on=previous.reference,
        target=ExecutionTarget.JVM_KOTLIN,
        origin=JvmSourceOrigin.REPAIR_CHANGE_SET,
        files=(file("src/main/kotlin/example/Main.kt", "c" * 64),),
        provenance_references=(
            JvmSourceProvenanceReference(
                kind=JvmSourceProvenanceKind.FAILURE_SIGNATURE,
                reference_id="failure:fixture",
                version_number=1,
                content_hash="d" * 64,
            ),
        ),
        related_failure_signature="d" * 64,
        created_at=NOW,
    )

    assert repaired.based_on == previous.reference
    assert repaired.source_tree_hash != previous.source_tree_hash
    assert repaired.content_hash != previous.content_hash


def test_later_revision_cannot_skip_a_predecessor() -> None:
    previous = first_revision()

    with pytest.raises(ValueError, match="lineage must be linear"):
        create_jvm_source_revision(
            revision_id=REVISION_TWO_ID,
            project_id=PROJECT_ID,
            created_by_user_id=OWNER_ID,
            version_number=3,
            based_on=previous.reference,
            target=ExecutionTarget.JVM_KOTLIN,
            origin=JvmSourceOrigin.DETERMINISTIC_FIXTURE,
            files=previous.files,
            provenance_references=provenance(),
            created_at=NOW,
        )


def test_casefold_colliding_paths_are_rejected() -> None:
    with pytest.raises(ValueError, match="canonically unique"):
        create_jvm_source_revision(
            revision_id=REVISION_ONE_ID,
            project_id=PROJECT_ID,
            created_by_user_id=OWNER_ID,
            version_number=1,
            based_on=None,
            target=ExecutionTarget.JVM_JAVA,
            origin=JvmSourceOrigin.DETERMINISTIC_FIXTURE,
            files=(file("Main.java", "a" * 64), file("main.java", "b" * 64)),
            provenance_references=provenance(),
            created_at=NOW,
        )


def test_android_target_is_rejected_by_source_revision_factory() -> None:
    with pytest.raises(ValueError, match="outside the Sprint 09 JVM scope"):
        create_jvm_source_revision(
            revision_id=REVISION_ONE_ID,
            project_id=PROJECT_ID,
            created_by_user_id=OWNER_ID,
            version_number=1,
            based_on=None,
            target=ExecutionTarget.ANDROID_KOTLIN,
            origin=JvmSourceOrigin.DETERMINISTIC_FIXTURE,
            files=(file("Main.kt", "a" * 64),),
            provenance_references=provenance(),
            created_at=NOW,
        )
