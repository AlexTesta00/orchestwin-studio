"""Tests for bounded JVM repair revision application."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from orchestwin.artifacts.jvm_change_sets import (
    JvmSourceChange,
    JvmSourceChangeOperation,
    create_jvm_source_change_set,
)
from orchestwin.artifacts.jvm_source_plans import FileSystemJvmSourceContentStore
from orchestwin.artifacts.jvm_sources import (
    JvmSourceFileEntry,
    JvmSourceOrigin,
    JvmSourceProvenanceKind,
    JvmSourceProvenanceReference,
    JvmSourceRevision,
    create_jvm_source_revision,
)
from orchestwin.jvm_execution.evidence import (
    JvmFailureCategory,
    JvmFailureSignature,
)
from orchestwin.jvm_execution.plans import JvmExecutionPhase
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.workflow.jvm_repair import (
    JvmRepairApplicationStatus,
    JvmRepairApprovalReference,
    JvmRepairProposal,
    apply_jvm_repair_revision,
)

PROJECT_ID = UUID("90000000-0000-4000-8000-000000000001")
OWNER_ID = UUID("90000000-0000-4000-8000-000000000002")
BASE_ID = UUID("90000000-0000-4000-8000-000000000003")
CHANGE_SET_ID = UUID("90000000-0000-4000-8000-000000000004")
PROPOSAL_ID = UUID("90000000-0000-4000-8000-000000000005")
REVISION_ID = UUID("90000000-0000-4000-8000-000000000006")
CREATED_AT = datetime(2026, 8, 28, 18, 0, tzinfo=UTC)


def failure() -> JvmFailureSignature:
    return JvmFailureSignature(
        category=JvmFailureCategory.TEST,
        phase=JvmExecutionPhase.TEST,
        failure_code="KOTLIN_TEST_FAILED",
        normalized_message="expected calculator result",
        signature="96174d6836bf6dc763032af2dd1cacc2ad5a209b3f1b988f47b789a85e8d607f",
    )


def base_revision() -> JvmSourceRevision:
    digest = "a" * 64
    return create_jvm_source_revision(
        revision_id=BASE_ID,
        project_id=PROJECT_ID,
        created_by_user_id=OWNER_ID,
        version_number=1,
        based_on=None,
        target=ExecutionTarget.JVM_KOTLIN,
        origin=JvmSourceOrigin.DETERMINISTIC_FIXTURE,
        files=(
            JvmSourceFileEntry(
                normalized_path="src/main/kotlin/example/Calculator.kt",
                sha256_digest=digest,
                size_bytes=5,
                storage_key=f"sha256/{digest[:2]}/{digest}",
                media_type="text/x-kotlin",
            ),
        ),
        provenance_references=(
            JvmSourceProvenanceReference(
                kind=JvmSourceProvenanceKind.SOURCE_PLAN,
                reference_id="source-plan:base",
                version_number=1,
                content_hash="b" * 64,
            ),
        ),
        created_at=CREATED_AT,
    )


def repair_provenance(
    signature: JvmFailureSignature,
) -> tuple[JvmSourceProvenanceReference, ...]:
    return (
        JvmSourceProvenanceReference(
            kind=JvmSourceProvenanceKind.FAILURE_SIGNATURE,
            reference_id="failure-signature:kotlin-test",
            version_number=1,
            content_hash=signature.signature,
        ),
    )


def proposal(
    base: JvmSourceRevision,
    change: JvmSourceChange,
    *,
    attempt_number: int = 1,
    identical_failure_occurrences: int = 1,
) -> JvmRepairProposal:
    signature = failure()
    return JvmRepairProposal(
        id=PROPOSAL_ID,
        project_id=PROJECT_ID,
        created_by_user_id=OWNER_ID,
        base_revision=base.reference,
        failure_signature=signature,
        change_set=create_jvm_source_change_set(
            change_set_id=CHANGE_SET_ID,
            project_id=PROJECT_ID,
            base_revision=base.reference,
            changes=(change,),
            rationale="Apply one bounded repair from normalized JVM evidence.",
            provenance_references=("failure-signature:kotlin-test",),
        ),
        attempt_number=attempt_number,
        identical_failure_occurrences=identical_failure_occurrences,
        provenance_references=repair_provenance(signature),
        created_at=CREATED_AT,
    )


def stored_change(
    store: FileSystemJvmSourceContentStore,
    *,
    path: str,
    content: bytes,
    operation: JvmSourceChangeOperation,
    media_type: str,
) -> JvmSourceChange:
    entry = store.store(
        normalized_path=path,
        content=content,
        media_type=media_type,
    )
    return JvmSourceChange(
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
    store = FileSystemJvmSourceContentStore(tmp_path / "objects")
    repair = proposal(
        base,
        stored_change(
            store,
            path="src/main/kotlin/example/Calculator.kt",
            content=b"ready",
            operation=JvmSourceChangeOperation.REPLACE,
            media_type="text/x-kotlin",
        ),
    )

    result = apply_jvm_repair_revision(
        repair,
        base_revision=base,
        revision_id=REVISION_ID,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
        content_store=store,
    )

    assert result.status is JvmRepairApplicationStatus.APPLIED
    assert result.revision is not None
    assert result.revision.version_number == 2
    assert result.revision.based_on == base.reference
    assert result.revision.related_failure_signature == failure().signature
    assert JvmExecutionPhase.SETUP not in result.required_rerun_phases
    assert JvmExecutionPhase.BUILD in result.required_rerun_phases


def test_high_impact_repair_requires_exact_gate7_approval(tmp_path: Path) -> None:
    base = base_revision()
    store = FileSystemJvmSourceContentStore(tmp_path / "objects")
    repair = proposal(
        base,
        stored_change(
            store,
            path="build.gradle.kts",
            content=b'plugins { kotlin("jvm") }',
            operation=JvmSourceChangeOperation.ADD,
            media_type="text/x-gradle",
        ),
    )

    blocked = apply_jvm_repair_revision(
        repair,
        base_revision=base,
        revision_id=REVISION_ID,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
        content_store=store,
    )
    approval = JvmRepairApprovalReference(
        approval_id=UUID("90000000-0000-4000-8000-000000000007"),
        project_id=PROJECT_ID,
        change_set_id=repair.change_set.id,
        change_set_content_hash=repair.change_set.content_hash,
        base_revision_content_hash=base.content_hash,
        failure_signature=repair.failure_signature.signature,
        approved_by_user_id=OWNER_ID,
    )
    applied = apply_jvm_repair_revision(
        repair,
        base_revision=base,
        revision_id=REVISION_ID,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
        content_store=store,
        approval=approval,
    )

    assert blocked.status is JvmRepairApplicationStatus.REQUIRES_OWNER_APPROVAL
    assert applied.status is JvmRepairApplicationStatus.APPLIED
    assert applied.required_rerun_phases == tuple(JvmExecutionPhase)


def test_repair_limits_pause_for_human_instead_of_creating_revision(
    tmp_path: Path,
) -> None:
    base = base_revision()
    store = FileSystemJvmSourceContentStore(tmp_path / "objects")
    repair = proposal(
        base,
        stored_change(
            store,
            path="src/main/kotlin/example/Calculator.kt",
            content=b"ready",
            operation=JvmSourceChangeOperation.REPLACE,
            media_type="text/x-kotlin",
        ),
        identical_failure_occurrences=3,
    )

    result = apply_jvm_repair_revision(
        repair,
        base_revision=base,
        revision_id=REVISION_ID,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
        content_store=store,
    )

    assert result.status is JvmRepairApplicationStatus.PAUSED_NEEDS_HUMAN
    assert result.revision is None


def test_missing_or_tampered_content_is_not_applied(tmp_path: Path) -> None:
    base = base_revision()
    store = FileSystemJvmSourceContentStore(tmp_path / "objects")
    repair = proposal(
        base,
        JvmSourceChange(
            normalized_path="src/main/kotlin/example/Calculator.kt",
            operation=JvmSourceChangeOperation.REPLACE,
            content_sha256="c" * 64,
            size_bytes=5,
            storage_key="sha256/cc/" + "c" * 64,
            media_type="text/x-kotlin",
        ),
    )

    result = apply_jvm_repair_revision(
        repair,
        base_revision=base,
        revision_id=REVISION_ID,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
        content_store=store,
    )

    assert result.status is JvmRepairApplicationStatus.CONTENT_UNAVAILABLE


def test_test_only_repair_skips_setup_static_checks_and_build(tmp_path: Path) -> None:
    base = base_revision()
    store = FileSystemJvmSourceContentStore(tmp_path / "objects")
    repair = proposal(
        base,
        stored_change(
            store,
            path="src/test/kotlin/example/CalculatorTest.kt",
            content=b"class CalculatorTest",
            operation=JvmSourceChangeOperation.ADD,
            media_type="text/x-kotlin",
        ),
    )

    result = apply_jvm_repair_revision(
        repair,
        base_revision=base,
        revision_id=REVISION_ID,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
        content_store=store,
    )

    assert result.status is JvmRepairApplicationStatus.APPLIED
    assert result.required_rerun_phases == (
        JvmExecutionPhase.VALIDATE,
        JvmExecutionPhase.TEST,
        JvmExecutionPhase.RUN,
        JvmExecutionPhase.COLLECT_ARTIFACTS,
    )
