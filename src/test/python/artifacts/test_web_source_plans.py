"""Tests for typed source plans and safe initial source materialization."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from orchestwin.artifacts.web_source_plans import (
    FileSystemWebSourceContentStore,
    WebSourceMaterializationStatus,
    WebSourcePlanFile,
    WebSourcePlanIssueCode,
    create_web_source_plan,
    materialize_web_source_plan,
    validate_web_source_plan,
)
from orchestwin.artifacts.web_sources import (
    WebSourceProvenanceKind,
    WebSourceProvenanceReference,
)
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.web_execution.targets import (
    WebImplementationLanguage,
    WebLanguageConfiguration,
    WebProjectLayout,
    WebTargetSelection,
)

PROJECT_ID = UUID("10000000-0000-4000-8000-000000000001")
OWNER_ID = UUID("10000000-0000-4000-8000-000000000002")
PLAN_ID = UUID("10000000-0000-4000-8000-000000000003")
REVISION_ID = UUID("10000000-0000-4000-8000-000000000004")
CREATED_AT = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)


def provenance() -> WebSourceProvenanceReference:
    return WebSourceProvenanceReference(
        kind=WebSourceProvenanceKind.SOURCE_PLAN,
        reference_id="source-plan.initial",
        version_number=1,
        content_hash="a" * 64,
    )


def selection() -> WebTargetSelection:
    return WebTargetSelection(
        target=ExecutionTarget.WEB_STATIC,
        language_configuration=WebLanguageConfiguration(
            frontend=WebImplementationLanguage.STATIC_ASSETS,
            backend=None,
        ),
        layout=WebProjectLayout.SINGLE_ROOT,
    )


def plan(*files: WebSourcePlanFile):
    return create_web_source_plan(
        plan_id=PLAN_ID,
        project_id=PROJECT_ID,
        created_by_user_id=OWNER_ID,
        target_selection=selection(),
        files=files,
        rationale="Materialize the approved deterministic source fixture.",
        provenance_references=(provenance(),),
        created_at=CREATED_AT,
    )


def test_materialization_creates_canonical_workspace_store_and_revision(
    tmp_path: Path,
) -> None:
    source_plan = plan(
        WebSourcePlanFile(
            normalized_path="index.html",
            content="<!doctype html><title>Ready</title>",
            media_type="text/html",
        ),
        WebSourcePlanFile(
            normalized_path="assets/site.css",
            content="body { font-family: sans-serif; }",
            media_type="text/css",
        ),
    )
    store = FileSystemWebSourceContentStore(tmp_path / "objects")
    workspace = tmp_path / "workspace"

    result = materialize_web_source_plan(
        source_plan,
        revision_id=REVISION_ID,
        workspace_path=workspace,
        content_store=store,
        created_at=CREATED_AT,
    )

    assert result.status is WebSourceMaterializationStatus.MATERIALIZED
    assert result.revision is not None
    assert result.revision.version_number == 1
    assert result.revision.based_on is None
    assert tuple(file.normalized_path for file in result.revision.files) == (
        "assets/site.css",
        "index.html",
    )
    assert (workspace / "index.html").read_text(encoding="utf-8").startswith("<!doctype html>")
    first = result.revision.files[0]
    assert store.read(first.storage_key) == b"body { font-family: sans-serif; }"


def test_plan_rejects_generated_sensitive_and_protected_paths_before_writing(
    tmp_path: Path,
) -> None:
    source_plan = plan(
        WebSourcePlanFile(
            normalized_path=".git/config",
            content="unsafe",
            media_type="text/plain",
        ),
        WebSourcePlanFile(
            normalized_path="node_modules/pkg/index.js",
            content="generated",
            media_type="text/javascript",
        ),
        WebSourcePlanFile(
            normalized_path=".env",
            content="TOKEN=secret",
            media_type="text/plain",
        ),
    )

    validation = validate_web_source_plan(source_plan)
    result = materialize_web_source_plan(
        source_plan,
        revision_id=REVISION_ID,
        workspace_path=tmp_path / "workspace",
        content_store=FileSystemWebSourceContentStore(tmp_path / "objects"),
        created_at=CREATED_AT,
    )

    assert {issue.code for issue in validation.issues} == {
        WebSourcePlanIssueCode.GENERATED_PATH,
        WebSourcePlanIssueCode.PROTECTED_PATH,
        WebSourcePlanIssueCode.SENSITIVE_PATH,
    }
    assert result.status is WebSourceMaterializationStatus.PLAN_REJECTED
    assert not (tmp_path / "workspace").exists()


def test_materialization_never_overwrites_non_empty_workspace(tmp_path: Path) -> None:
    source_plan = plan(
        WebSourcePlanFile(
            normalized_path="index.html",
            content="<!doctype html>",
            media_type="text/html",
        )
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    existing = workspace / "keep.txt"
    existing.write_text("keep", encoding="utf-8")

    result = materialize_web_source_plan(
        source_plan,
        revision_id=REVISION_ID,
        workspace_path=workspace,
        content_store=FileSystemWebSourceContentStore(tmp_path / "objects"),
        created_at=CREATED_AT,
    )

    assert result.status is WebSourceMaterializationStatus.WORKSPACE_UNSAFE
    assert existing.read_text(encoding="utf-8") == "keep"


def test_content_store_reuses_identical_bytes_without_changing_logical_path(
    tmp_path: Path,
) -> None:
    store = FileSystemWebSourceContentStore(tmp_path / "objects")

    first = store.store(
        normalized_path="index.html",
        content=b"ready",
        media_type="text/html",
    )
    second = store.store(
        normalized_path="copy.html",
        content=b"ready",
        media_type="text/html",
    )

    assert first.sha256_digest == second.sha256_digest
    assert first.storage_key == second.storage_key
    assert first.normalized_path != second.normalized_path
