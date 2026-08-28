"""Tests for safe typed JVM source change-set validation."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.artifacts.jvm_change_sets import (
    JvmSourceChange,
    JvmSourceChangeIssueCode,
    JvmSourceChangeOperation,
    JvmSourceChangeValidationStatus,
    create_jvm_source_change_set,
    validate_jvm_source_change_set,
)
from orchestwin.artifacts.jvm_sources import (
    JvmSourceFileEntry,
    JvmSourceOrigin,
    JvmSourceProvenanceKind,
    JvmSourceProvenanceReference,
    create_jvm_source_revision,
)
from orchestwin.sandbox.execution_profiles import ExecutionTarget

PROJECT_ID = UUID("00000000-0000-4000-8000-000000009601")
OWNER_ID = UUID("00000000-0000-4000-8000-000000009602")


def entry(path: str, digest: str) -> JvmSourceFileEntry:
    return JvmSourceFileEntry(
        normalized_path=path,
        sha256_digest=digest,
        size_bytes=10,
        storage_key=f"sha256/{digest[:2]}/{digest}",
        media_type="text/plain",
    )


def base_revision():
    return create_jvm_source_revision(
        revision_id=UUID("00000000-0000-4000-8000-000000009603"),
        project_id=PROJECT_ID,
        created_by_user_id=OWNER_ID,
        version_number=1,
        based_on=None,
        target=ExecutionTarget.JVM_KOTLIN,
        origin=JvmSourceOrigin.DETERMINISTIC_FIXTURE,
        files=(entry("src/main/kotlin/example/Main.kt", "a" * 64),),
        provenance_references=(
            JvmSourceProvenanceReference(
                kind=JvmSourceProvenanceKind.SOURCE_PLAN,
                reference_id="source-plan:base",
                version_number=1,
                content_hash="b" * 64,
            ),
        ),
        created_at=datetime(2026, 8, 28, 14, 0, tzinfo=UTC),
    )


def change(
    path: str,
    operation: JvmSourceChangeOperation,
    digest: str | None = "c" * 64,
) -> JvmSourceChange:
    return JvmSourceChange(
        normalized_path=path,
        operation=operation,
        content_sha256=None if operation is JvmSourceChangeOperation.DELETE else digest,
        size_bytes=None if operation is JvmSourceChangeOperation.DELETE else 12,
        storage_key=(
            None
            if operation is JvmSourceChangeOperation.DELETE
            else f"sha256/{digest[:2]}/{digest}"
        ),
        media_type=None if operation is JvmSourceChangeOperation.DELETE else "text/plain",
    )


def change_set(*changes: JvmSourceChange, base=None):
    revision = base_revision() if base is None else base
    return create_jvm_source_change_set(
        change_set_id=UUID("00000000-0000-4000-8000-000000009604"),
        project_id=PROJECT_ID,
        base_revision=revision.reference,
        changes=changes,
        rationale="Apply one bounded JVM source correction.",
        provenance_references=("repair-proposal:1",),
    )


def test_standard_add_is_applicable_without_gate7() -> None:
    base = base_revision()
    report = validate_jvm_source_change_set(
        change_set(
            change("src/test/kotlin/example/MainTest.kt", JvmSourceChangeOperation.ADD),
            base=base,
        ),
        base_revision=base,
    )

    assert report.status is JvmSourceChangeValidationStatus.ACCEPTED
    assert report.is_applicable
    assert report.issues == ()


def test_build_and_wrapper_changes_require_gate7() -> None:
    base = base_revision()
    report = validate_jvm_source_change_set(
        change_set(
            change("build.gradle.kts", JvmSourceChangeOperation.ADD),
            change(
                "gradle/wrapper/gradle-wrapper.properties",
                JvmSourceChangeOperation.ADD,
            ),
            base=base,
        ),
        base_revision=base,
    )

    assert report.status is JvmSourceChangeValidationStatus.REQUIRES_OWNER_APPROVAL
    assert {issue.code for issue in report.issues} == {JvmSourceChangeIssueCode.HIGH_IMPACT_FILE}


def test_protected_and_generated_paths_are_rejected() -> None:
    base = base_revision()
    report = validate_jvm_source_change_set(
        change_set(
            change(".git/config", JvmSourceChangeOperation.ADD),
            change("build/classes/Main.class", JvmSourceChangeOperation.ADD),
            change("target/scala-3/classes/Main.class", JvmSourceChangeOperation.ADD),
            base=base,
        ),
        base_revision=base,
    )

    assert report.status is JvmSourceChangeValidationStatus.REJECTED
    assert {issue.code for issue in report.issues} == {
        JvmSourceChangeIssueCode.GENERATED_PATH,
        JvmSourceChangeIssueCode.PROTECTED_PATH,
    }


def test_operation_semantics_reject_existing_add_and_missing_delete() -> None:
    base = base_revision()
    report = validate_jvm_source_change_set(
        change_set(
            change("src/main/kotlin/example/Main.kt", JvmSourceChangeOperation.ADD),
            change("missing.kt", JvmSourceChangeOperation.DELETE),
            base=base,
        ),
        base_revision=base,
    )

    assert report.status is JvmSourceChangeValidationStatus.REJECTED
    assert {issue.code for issue in report.issues} == {
        JvmSourceChangeIssueCode.TARGET_ALREADY_EXISTS,
        JvmSourceChangeIssueCode.TARGET_NOT_FOUND,
    }


def test_change_set_cannot_target_a_stale_base_revision() -> None:
    base = base_revision()
    candidate = change_set(
        change("src/test/kotlin/example/MainTest.kt", JvmSourceChangeOperation.ADD),
        base=base,
    )
    other = create_jvm_source_revision(
        revision_id=UUID("00000000-0000-4000-8000-000000009605"),
        project_id=PROJECT_ID,
        created_by_user_id=OWNER_ID,
        version_number=1,
        based_on=None,
        target=ExecutionTarget.JVM_KOTLIN,
        origin=JvmSourceOrigin.DETERMINISTIC_FIXTURE,
        files=(entry("src/main/kotlin/example/Main.kt", "d" * 64),),
        provenance_references=base.provenance_references,
        created_at=base.created_at,
    )

    report = validate_jvm_source_change_set(candidate, base_revision=other)

    assert report.status is JvmSourceChangeValidationStatus.REJECTED
    assert JvmSourceChangeIssueCode.BASE_REVISION_MISMATCH in {
        issue.code for issue in report.issues
    }


def test_casefold_colliding_change_paths_are_rejected() -> None:
    base = base_revision()

    with pytest.raises(ValueError, match="canonically unique"):
        create_jvm_source_change_set(
            change_set_id=UUID("00000000-0000-4000-8000-000000009606"),
            project_id=PROJECT_ID,
            base_revision=base.reference,
            changes=(
                change("src/Main.kt", JvmSourceChangeOperation.ADD),
                change("src/main.kt", JvmSourceChangeOperation.ADD),
            ),
            rationale="Attempt a colliding JVM change.",
            provenance_references=("repair-proposal:2",),
        )
