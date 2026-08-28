"""Tests for typed JVM source plans and safe initial materialization."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from orchestwin.artifacts.jvm_source_plans import (
    FileSystemJvmSourceContentStore,
    JvmSourceMaterializationStatus,
    JvmSourcePlanFile,
    JvmSourcePlanIssueCode,
    create_jvm_source_plan,
    materialize_jvm_source_plan,
    validate_jvm_source_plan,
)
from orchestwin.artifacts.jvm_sources import (
    JvmSourceProvenanceKind,
    JvmSourceProvenanceReference,
)
from orchestwin.jvm_execution.targets import selection_for
from orchestwin.sandbox.execution_profiles import ExecutionTarget

PROJECT_ID = UUID("10000000-0000-4000-8000-000000009701")
OWNER_ID = UUID("10000000-0000-4000-8000-000000009702")
PLAN_ID = UUID("10000000-0000-4000-8000-000000009703")
REVISION_ID = UUID("10000000-0000-4000-8000-000000009704")
CREATED_AT = datetime(2026, 8, 28, 9, 0, tzinfo=UTC)


def provenance() -> JvmSourceProvenanceReference:
    return JvmSourceProvenanceReference(
        kind=JvmSourceProvenanceKind.SOURCE_PLAN,
        reference_id="source-plan.initial",
        version_number=1,
        content_hash="a" * 64,
    )


def plan(*files: JvmSourcePlanFile):
    return create_jvm_source_plan(
        plan_id=PLAN_ID,
        project_id=PROJECT_ID,
        created_by_user_id=OWNER_ID,
        target_selection=selection_for(ExecutionTarget.JVM_KOTLIN),
        files=files,
        rationale="Materialize the approved deterministic JVM source fixture.",
        provenance_references=(provenance(),),
        created_at=CREATED_AT,
    )


def test_materialization_creates_canonical_workspace_store_and_revision(
    tmp_path: Path,
) -> None:
    source_plan = plan(
        JvmSourcePlanFile(
            normalized_path="build.gradle.kts",
            content='plugins { kotlin("jvm") version "2.4.10" }',
            media_type="text/x-gradle",
        ),
        JvmSourcePlanFile(
            normalized_path="src/main/kotlin/example/Main.kt",
            content='package example\nfun main() = println("Ready")\n',
            media_type="text/x-kotlin",
        ),
    )
    store = FileSystemJvmSourceContentStore(tmp_path / "objects")
    workspace = tmp_path / "workspace"

    result = materialize_jvm_source_plan(
        source_plan,
        revision_id=REVISION_ID,
        workspace_path=workspace,
        content_store=store,
        created_at=CREATED_AT,
    )

    assert result.status is JvmSourceMaterializationStatus.MATERIALIZED
    assert result.revision is not None
    assert result.revision.version_number == 1
    assert result.revision.based_on is None
    assert tuple(file.normalized_path for file in result.revision.files) == (
        "build.gradle.kts",
        "src/main/kotlin/example/Main.kt",
    )
    assert (
        (workspace / "src/main/kotlin/example/Main.kt")
        .read_text(encoding="utf-8")
        .startswith("package example")
    )
    first = result.revision.files[0]
    assert store.read(first.storage_key) == source_plan.files[0].content_bytes


def test_plan_rejects_generated_sensitive_and_protected_paths_before_writing(
    tmp_path: Path,
) -> None:
    source_plan = plan(
        JvmSourcePlanFile(
            normalized_path=".git/config",
            content="unsafe",
            media_type="text/plain",
        ),
        JvmSourcePlanFile(
            normalized_path="build/classes/Main.class",
            content="generated",
            media_type="text/plain",
        ),
        JvmSourcePlanFile(
            normalized_path="signing.keystore",
            content="secret",
            media_type="text/plain",
        ),
    )

    validation = validate_jvm_source_plan(source_plan)
    result = materialize_jvm_source_plan(
        source_plan,
        revision_id=REVISION_ID,
        workspace_path=tmp_path / "workspace",
        content_store=FileSystemJvmSourceContentStore(tmp_path / "objects"),
        created_at=CREATED_AT,
    )

    assert {issue.code for issue in validation.issues} == {
        JvmSourcePlanIssueCode.GENERATED_PATH,
        JvmSourcePlanIssueCode.PROTECTED_PATH,
        JvmSourcePlanIssueCode.SENSITIVE_PATH,
    }
    assert result.status is JvmSourceMaterializationStatus.PLAN_REJECTED
    assert not (tmp_path / "workspace").exists()


def test_materialization_never_overwrites_non_empty_workspace(tmp_path: Path) -> None:
    source_plan = plan(
        JvmSourcePlanFile(
            normalized_path="src/main/kotlin/Main.kt",
            content="fun main() = Unit",
            media_type="text/x-kotlin",
        )
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    existing = workspace / "keep.txt"
    existing.write_text("keep", encoding="utf-8")

    result = materialize_jvm_source_plan(
        source_plan,
        revision_id=REVISION_ID,
        workspace_path=workspace,
        content_store=FileSystemJvmSourceContentStore(tmp_path / "objects"),
        created_at=CREATED_AT,
    )

    assert result.status is JvmSourceMaterializationStatus.WORKSPACE_UNSAFE
    assert existing.read_text(encoding="utf-8") == "keep"


def test_content_store_reuses_identical_bytes_without_changing_logical_path(
    tmp_path: Path,
) -> None:
    store = FileSystemJvmSourceContentStore(tmp_path / "objects")

    first = store.store(
        normalized_path="src/main/java/Main.java",
        content=b"class Main {}",
        media_type="text/x-java-source",
    )
    second = store.store(
        normalized_path="src/test/java/MainTest.java",
        content=b"class Main {}",
        media_type="text/x-java-source",
    )

    assert first.sha256_digest == second.sha256_digest
    assert first.storage_key == second.storage_key
    assert first.normalized_path != second.normalized_path
