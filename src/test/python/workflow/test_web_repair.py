"""Tests for bounded Web repair revision application."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from orchestwin.artifacts.web_change_sets import (
    WebSourceChange,
    WebSourceChangeOperation,
    create_web_source_change_set,
)
from orchestwin.artifacts.web_source_plans import FileSystemWebSourceContentStore
from orchestwin.artifacts.web_sources import (
    WebSourceFileEntry,
    WebSourceOrigin,
    WebSourceProvenanceKind,
    WebSourceProvenanceReference,
    WebSourceRevision,
    create_web_source_revision,
)
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.reports import (
    WebFailureCategory,
    WebFailureSignature,
)
from orchestwin.web_execution.targets import (
    WebImplementationLanguage,
    WebLanguageConfiguration,
    WebProjectLayout,
)
from orchestwin.workflow.web_repair import (
    WebRepairApplicationStatus,
    WebRepairApprovalReference,
    WebRepairProposal,
    apply_web_repair_revision,
)

PROJECT_ID = UUID("20000000-0000-4000-8000-000000000001")
OWNER_ID = UUID("20000000-0000-4000-8000-000000000002")
BASE_ID = UUID("20000000-0000-4000-8000-000000000003")
CHANGE_SET_ID = UUID("20000000-0000-4000-8000-000000000004")
PROPOSAL_ID = UUID("20000000-0000-4000-8000-000000000005")
REVISION_ID = UUID("20000000-0000-4000-8000-000000000006")
CREATED_AT = datetime(2026, 8, 27, 10, 0, tzinfo=UTC)


def failure() -> WebFailureSignature:
    return WebFailureSignature(
        category=WebFailureCategory.TEST,
        phase=WebExecutionPhase.TEST,
        profile_id="web.static",
        profile_version="1.0.0",
        failure_code="TEST_FAILED",
        normalized_message="expected ready state",
        subject_refs=("tests/site.spec.js",),
    )


def base_revision() -> WebSourceRevision:
    digest = "a" * 64
    return create_web_source_revision(
        revision_id=BASE_ID,
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
        files=(
            WebSourceFileEntry(
                normalized_path="index.html",
                sha256_digest=digest,
                size_bytes=5,
                storage_key=f"sha256/{digest[:2]}/{digest}",
                media_type="text/html",
            ),
        ),
        provenance_references=(
            WebSourceProvenanceReference(
                kind=WebSourceProvenanceKind.SOURCE_PLAN,
                reference_id="source-plan:base",
                version_number=1,
                content_hash="b" * 64,
            ),
        ),
        created_at=CREATED_AT,
    )


def repair_provenance(signature: WebFailureSignature) -> tuple[WebSourceProvenanceReference, ...]:
    return (
        WebSourceProvenanceReference(
            kind=WebSourceProvenanceKind.FAILURE_SIGNATURE,
            reference_id="failure-signature:test",
            version_number=1,
            content_hash=signature.digest,
        ),
    )


def proposal(
    base: WebSourceRevision,
    change: WebSourceChange,
    *,
    attempt_number: int = 1,
    identical_failure_occurrences: int = 1,
) -> WebRepairProposal:
    signature = failure()
    return WebRepairProposal(
        id=PROPOSAL_ID,
        project_id=PROJECT_ID,
        created_by_user_id=OWNER_ID,
        base_revision=base.reference,
        failure_signature=signature,
        change_set=create_web_source_change_set(
            change_set_id=CHANGE_SET_ID,
            project_id=PROJECT_ID,
            base_revision=base.reference,
            changes=(change,),
            rationale="Apply one bounded repair from the normalized failure.",
            provenance_references=("failure-signature:test",),
        ),
        attempt_number=attempt_number,
        identical_failure_occurrences=identical_failure_occurrences,
        provenance_references=repair_provenance(signature),
        created_at=CREATED_AT,
    )


def stored_change(
    store: FileSystemWebSourceContentStore,
    *,
    path: str,
    content: bytes,
    operation: WebSourceChangeOperation,
    media_type: str,
) -> WebSourceChange:
    entry = store.store(
        normalized_path=path,
        content=content,
        media_type=media_type,
    )
    return WebSourceChange(
        normalized_path=path,
        operation=operation,
        content_sha256=entry.sha256_digest,
        size_bytes=entry.size_bytes,
        storage_key=entry.storage_key,
        media_type=entry.media_type,
    )


def test_standard_repair_creates_new_revision_and_minimal_rerun_scope(
    tmp_path: Path,
) -> None:
    base = base_revision()
    store = FileSystemWebSourceContentStore(tmp_path / "objects")
    repair = proposal(
        base,
        stored_change(
            store,
            path="index.html",
            content=b"ready",
            operation=WebSourceChangeOperation.REPLACE,
            media_type="text/html",
        ),
    )

    result = apply_web_repair_revision(
        repair,
        base_revision=base,
        revision_id=REVISION_ID,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
        content_store=store,
    )

    assert result.status is WebRepairApplicationStatus.APPLIED
    assert result.revision is not None
    assert result.revision.version_number == 2
    assert result.revision.based_on == base.reference
    assert result.revision.related_failure_signature == failure().digest
    assert WebExecutionPhase.SETUP not in result.required_rerun_phases
    assert WebExecutionPhase.TEST in result.required_rerun_phases


def test_high_impact_repair_requires_exact_gate7_approval(tmp_path: Path) -> None:
    base = base_revision()
    store = FileSystemWebSourceContentStore(tmp_path / "objects")
    repair = proposal(
        base,
        stored_change(
            store,
            path="package.json",
            content=b'{"name":"fixture"}',
            operation=WebSourceChangeOperation.ADD,
            media_type="application/json",
        ),
    )

    blocked = apply_web_repair_revision(
        repair,
        base_revision=base,
        revision_id=REVISION_ID,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
        content_store=store,
    )
    approval = WebRepairApprovalReference(
        approval_id=UUID("20000000-0000-4000-8000-000000000007"),
        project_id=PROJECT_ID,
        change_set_id=repair.change_set.id,
        change_set_content_hash=repair.change_set.content_hash,
        base_revision_content_hash=base.content_hash,
        failure_signature_digest=repair.failure_signature.digest,
        approved_by_user_id=OWNER_ID,
    )
    applied = apply_web_repair_revision(
        repair,
        base_revision=base,
        revision_id=REVISION_ID,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
        content_store=store,
        approval=approval,
    )

    assert blocked.status is WebRepairApplicationStatus.REQUIRES_OWNER_APPROVAL
    assert applied.status is WebRepairApplicationStatus.APPLIED
    assert applied.required_rerun_phases == tuple(WebExecutionPhase)


def test_repair_limits_pause_for_human_instead_of_creating_revision(
    tmp_path: Path,
) -> None:
    base = base_revision()
    store = FileSystemWebSourceContentStore(tmp_path / "objects")
    repair = proposal(
        base,
        stored_change(
            store,
            path="index.html",
            content=b"ready",
            operation=WebSourceChangeOperation.REPLACE,
            media_type="text/html",
        ),
        identical_failure_occurrences=3,
    )

    result = apply_web_repair_revision(
        repair,
        base_revision=base,
        revision_id=REVISION_ID,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
        content_store=store,
    )

    assert result.status is WebRepairApplicationStatus.PAUSED_NEEDS_HUMAN
    assert result.revision is None


def test_missing_or_tampered_content_is_not_applied(tmp_path: Path) -> None:
    base = base_revision()
    store = FileSystemWebSourceContentStore(tmp_path / "objects")
    repair = proposal(
        base,
        WebSourceChange(
            normalized_path="index.html",
            operation=WebSourceChangeOperation.REPLACE,
            content_sha256="c" * 64,
            size_bytes=5,
            storage_key="sha256/cc/" + "c" * 64,
            media_type="text/html",
        ),
    )

    result = apply_web_repair_revision(
        repair,
        base_revision=base,
        revision_id=REVISION_ID,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
        content_store=store,
    )

    assert result.status is WebRepairApplicationStatus.CONTENT_UNAVAILABLE


def test_test_only_repair_skips_static_check_and_build(tmp_path: Path) -> None:
    base = base_revision()
    store = FileSystemWebSourceContentStore(tmp_path / "objects")
    repair = proposal(
        base,
        stored_change(
            store,
            path="tests/site.spec.js",
            content=b"test('ready', () => true)",
            operation=WebSourceChangeOperation.ADD,
            media_type="text/javascript",
        ),
    )

    result = apply_web_repair_revision(
        repair,
        base_revision=base,
        revision_id=REVISION_ID,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
        content_store=store,
    )

    assert result.status is WebRepairApplicationStatus.APPLIED
    assert WebExecutionPhase.STATIC_CHECK not in result.required_rerun_phases
    assert WebExecutionPhase.BUILD not in result.required_rerun_phases
    assert result.required_rerun_phases[0] is WebExecutionPhase.VALIDATE
