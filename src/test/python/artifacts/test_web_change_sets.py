"""Tests for safe typed Web source change-set validation."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.artifacts.web_change_sets import (
    WebSourceChange,
    WebSourceChangeIssueCode,
    WebSourceChangeOperation,
    WebSourceChangeValidationStatus,
    create_web_source_change_set,
    validate_web_source_change_set,
)
from orchestwin.artifacts.web_sources import (
    WebSourceFileEntry,
    WebSourceOrigin,
    WebSourceProvenanceKind,
    WebSourceProvenanceReference,
    create_web_source_revision,
)
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.web_execution.targets import (
    WebImplementationLanguage,
    WebLanguageConfiguration,
    WebProjectLayout,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000008601")
OWNER_ID = UUID("00000000-0000-4000-8000-000000008602")


def entry(path: str, digest: str) -> WebSourceFileEntry:
    return WebSourceFileEntry(
        normalized_path=path,
        sha256_digest=digest,
        size_bytes=10,
        storage_key=f"sha256/{digest[:2]}/{digest}",
        media_type="text/plain",
    )


def base_revision():
    return create_web_source_revision(
        revision_id=UUID("00000000-0000-4000-8000-000000008603"),
        project_id=PROJECT_ID,
        created_by_user_id=OWNER_ID,
        version_number=1,
        based_on=None,
        target=ExecutionTarget.WEB_STATIC,
        language_configuration=WebLanguageConfiguration(
            frontend=WebImplementationLanguage.STATIC_ASSETS,
            backend=None,
        ),
        layout=WebProjectLayout.SINGLE_ROOT,
        origin=WebSourceOrigin.DETERMINISTIC_FIXTURE,
        files=(entry("index.html", "a" * 64),),
        provenance_references=(
            WebSourceProvenanceReference(
                kind=WebSourceProvenanceKind.SOURCE_PLAN,
                reference_id="source-plan:base",
                version_number=1,
                content_hash="b" * 64,
            ),
        ),
        created_at=datetime(2026, 8, 26, 14, 0, tzinfo=UTC),
    )


def change(
    path: str,
    operation: WebSourceChangeOperation,
    digest: str | None = "c" * 64,
) -> WebSourceChange:
    return WebSourceChange(
        normalized_path=path,
        operation=operation,
        content_sha256=None if operation is WebSourceChangeOperation.DELETE else digest,
        size_bytes=None if operation is WebSourceChangeOperation.DELETE else 12,
        storage_key=(
            None
            if operation is WebSourceChangeOperation.DELETE
            else f"sha256/{digest[:2]}/{digest}"
        ),
        media_type=None if operation is WebSourceChangeOperation.DELETE else "text/plain",
    )


def change_set(*changes: WebSourceChange, base=None):
    revision = base_revision() if base is None else base
    return create_web_source_change_set(
        change_set_id=UUID("00000000-0000-4000-8000-000000008604"),
        project_id=PROJECT_ID,
        base_revision=revision.reference,
        changes=changes,
        rationale="Apply one bounded source correction.",
        provenance_references=("repair-proposal:1",),
    )


def test_standard_add_is_applicable_without_gate7() -> None:
    base = base_revision()
    report = validate_web_source_change_set(
        change_set(change("site.js", WebSourceChangeOperation.ADD), base=base),
        base_revision=base,
    )

    assert report.status is WebSourceChangeValidationStatus.ACCEPTED
    assert report.is_applicable
    assert report.issues == ()


def test_dependency_manifest_change_requires_gate7() -> None:
    base = base_revision()
    report = validate_web_source_change_set(
        change_set(change("package.json", WebSourceChangeOperation.ADD), base=base),
        base_revision=base,
    )

    assert report.status is WebSourceChangeValidationStatus.REQUIRES_OWNER_APPROVAL
    assert {issue.code for issue in report.issues} == {WebSourceChangeIssueCode.HIGH_IMPACT_FILE}


def test_protected_and_generated_paths_are_rejected() -> None:
    base = base_revision()
    report = validate_web_source_change_set(
        change_set(
            change(".git/config", WebSourceChangeOperation.ADD),
            change("node_modules/pkg/index.js", WebSourceChangeOperation.ADD),
            base=base,
        ),
        base_revision=base,
    )

    assert report.status is WebSourceChangeValidationStatus.REJECTED
    assert {issue.code for issue in report.issues} == {
        WebSourceChangeIssueCode.GENERATED_PATH,
        WebSourceChangeIssueCode.PROTECTED_PATH,
    }


def test_operation_semantics_reject_existing_add_and_missing_delete() -> None:
    base = base_revision()
    report = validate_web_source_change_set(
        change_set(
            change("index.html", WebSourceChangeOperation.ADD),
            change("missing.js", WebSourceChangeOperation.DELETE),
            base=base,
        ),
        base_revision=base,
    )

    assert report.status is WebSourceChangeValidationStatus.REJECTED
    assert {issue.code for issue in report.issues} == {
        WebSourceChangeIssueCode.TARGET_ALREADY_EXISTS,
        WebSourceChangeIssueCode.TARGET_NOT_FOUND,
    }


def test_change_set_cannot_target_a_stale_base_revision() -> None:
    base = base_revision()
    candidate = change_set(change("site.js", WebSourceChangeOperation.ADD), base=base)
    other = create_web_source_revision(
        revision_id=UUID("00000000-0000-4000-8000-000000008605"),
        project_id=PROJECT_ID,
        created_by_user_id=OWNER_ID,
        version_number=1,
        based_on=None,
        target=ExecutionTarget.WEB_STATIC,
        language_configuration=base.target_selection.language_configuration,
        layout=WebProjectLayout.SINGLE_ROOT,
        origin=WebSourceOrigin.DETERMINISTIC_FIXTURE,
        files=(entry("index.html", "d" * 64),),
        provenance_references=base.provenance_references,
        created_at=base.created_at,
    )

    report = validate_web_source_change_set(candidate, base_revision=other)

    assert report.status is WebSourceChangeValidationStatus.REJECTED
    assert WebSourceChangeIssueCode.BASE_REVISION_MISMATCH in {
        issue.code for issue in report.issues
    }


def test_casefold_colliding_change_paths_are_rejected() -> None:
    base = base_revision()

    with pytest.raises(ValueError, match="canonically unique"):
        create_web_source_change_set(
            change_set_id=UUID("00000000-0000-4000-8000-000000008606"),
            project_id=PROJECT_ID,
            base_revision=base.reference,
            changes=(
                change("Site.js", WebSourceChangeOperation.ADD),
                change("site.js", WebSourceChangeOperation.ADD),
            ),
            rationale="Attempt a colliding change.",
            provenance_references=("repair-proposal:2",),
        )
