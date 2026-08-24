"""Tests for deterministic source-tree inventory snapshots."""

from __future__ import annotations

import zipfile
from pathlib import Path
from uuid import UUID

from orchestwin.sandbox.archive_extraction import extract_validated_source_archive
from orchestwin.sandbox.archive_policy import SourceArchiveEntryDisposition
from orchestwin.sandbox.archive_validation import validate_source_archive
from orchestwin.sandbox.source_inventory import (
    SourceInventoryClassification,
    SourceTreeInventoryBuildStatus,
    build_source_tree_inventory,
)

FIRST_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000741")
SECOND_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000742")


def write_zip(path: Path, entries: tuple[tuple[str, bytes], ...]) -> Path:
    """Create one ZIP while preserving the supplied member order."""
    with zipfile.ZipFile(path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return path


def extract_workspace(
    tmp_path: Path,
    *,
    archive_name: str,
    entries: tuple[tuple[str, bytes], ...],
    workspace_id: UUID,
):
    """Validate and extract one test source tree."""
    archive_path = write_zip(tmp_path / archive_name, entries)
    report = validate_source_archive(archive_path)
    extraction = extract_validated_source_archive(
        archive_path,
        validation_report=report,
        workspace_root=tmp_path / "workspaces",
        workspace_id=workspace_id,
    )
    assert extraction.workspace_path is not None
    return report, extraction.workspace_path


def test_inventory_classifies_hashes_and_preserves_exclusions(tmp_path: Path) -> None:
    """Create one canonical snapshot for source, tests, metadata, and ignored paths."""
    report, workspace = extract_workspace(
        tmp_path,
        archive_name="source.zip",
        workspace_id=FIRST_WORKSPACE_ID,
        entries=(
            ("README.md", b"# Example\n"),
            ("pyproject.toml", b"[project]\nname='example'\n"),
            ("src/app.py", b"print('hello')\n"),
            ("tests/test_app.py", b"def test_app(): pass\n"),
            ("data/sample.json", b'{"value":1}\n'),
            ("assets/logo.svg", b"<svg></svg>\n"),
            ("assets/logo.png", b"ignored binary"),
            ("node_modules/pkg/index.js", b"ignored generated"),
        ),
    )

    result = build_source_tree_inventory(workspace, validation_report=report)

    assert result.is_created
    assert result.inventory is not None
    inventory = result.inventory
    by_path = {entry.normalized_path: entry for entry in inventory.entries}

    assert by_path["README.md"].classification is SourceInventoryClassification.DOCUMENTATION
    assert by_path["pyproject.toml"].classification is (SourceInventoryClassification.CONFIGURATION)
    assert by_path["src/app.py"].classification is SourceInventoryClassification.SOURCE
    assert by_path["tests/test_app.py"].classification is SourceInventoryClassification.TEST
    assert by_path["data/sample.json"].classification is SourceInventoryClassification.DATA
    assert by_path["assets/logo.svg"].classification is SourceInventoryClassification.ASSET
    assert by_path["src"].classification is SourceInventoryClassification.DIRECTORY
    assert by_path["assets/logo.png"].classification is (SourceInventoryClassification.UNSUPPORTED)
    assert by_path["node_modules/pkg/index.js"].classification is (
        SourceInventoryClassification.GENERATED
    )
    assert by_path["src/app.py"].sha256_digest is not None
    assert by_path["assets/logo.png"].sha256_digest is None
    assert by_path["assets/logo.png"].disposition is SourceArchiveEntryDisposition.IGNORE
    assert len(inventory.content_hash) == 64
    assert inventory.to_snapshot()["content_hash"] == inventory.content_hash


def test_equivalent_trees_share_an_inventory_hash_despite_zip_order(tmp_path: Path) -> None:
    """Hash normalized source content rather than ZIP central-directory ordering."""
    entries = (
        ("src/app.js", b"console.log('hello');\n"),
        ("package.json", b'{"name":"example"}\n'),
    )
    first_report, first_workspace = extract_workspace(
        tmp_path,
        archive_name="first.zip",
        entries=entries,
        workspace_id=FIRST_WORKSPACE_ID,
    )
    second_report, second_workspace = extract_workspace(
        tmp_path,
        archive_name="second.zip",
        entries=tuple(reversed(entries)),
        workspace_id=SECOND_WORKSPACE_ID,
    )

    first_result = build_source_tree_inventory(
        first_workspace,
        validation_report=first_report,
    )
    second_result = build_source_tree_inventory(
        second_workspace,
        validation_report=second_report,
    )

    assert first_result.inventory is not None
    assert second_result.inventory is not None
    assert first_result.inventory.archive_sha256 != second_result.inventory.archive_sha256
    assert first_result.inventory.content_hash == second_result.inventory.content_hash
    assert first_result.inventory.canonical_content_json() == (
        second_result.inventory.canonical_content_json()
    )


def test_workspace_with_unexpected_or_resized_content_is_rejected(tmp_path: Path) -> None:
    """Do not inventory a tree that no longer matches the extraction manifest."""
    report, workspace = extract_workspace(
        tmp_path,
        archive_name="source.zip",
        entries=(("src/app.py", b"safe"),),
        workspace_id=FIRST_WORKSPACE_ID,
    )
    unexpected = workspace / "unexpected.py"
    unexpected.write_text("new", encoding="utf-8")

    unexpected_result = build_source_tree_inventory(workspace, validation_report=report)
    assert unexpected_result.status is SourceTreeInventoryBuildStatus.WORKSPACE_CHANGED

    unexpected.unlink()
    (workspace / "src" / "app.py").write_text("changed-size", encoding="utf-8")
    resized_result = build_source_tree_inventory(workspace, validation_report=report)
    assert resized_result.status is SourceTreeInventoryBuildStatus.WORKSPACE_CHANGED


def test_same_size_content_change_produces_a_new_inventory_hash(tmp_path: Path) -> None:
    """Capture actual source content even when its byte length stays unchanged."""
    report, workspace = extract_workspace(
        tmp_path,
        archive_name="source.zip",
        entries=(("src/app.py", b"first"),),
        workspace_id=FIRST_WORKSPACE_ID,
    )
    first_result = build_source_tree_inventory(workspace, validation_report=report)
    assert first_result.inventory is not None

    (workspace / "src" / "app.py").write_bytes(b"other")
    second_result = build_source_tree_inventory(workspace, validation_report=report)
    assert second_result.inventory is not None

    assert first_result.inventory.content_hash != second_result.inventory.content_hash


def test_symlink_and_missing_workspace_are_rejected(tmp_path: Path) -> None:
    """Never follow a workspace symlink while constructing an inventory."""
    report, workspace = extract_workspace(
        tmp_path,
        archive_name="source.zip",
        entries=(("src/app.py", b"safe"),),
        workspace_id=FIRST_WORKSPACE_ID,
    )
    target = workspace / "src" / "app.py"
    link = workspace / "src" / "link.py"

    try:
        link.symlink_to(target)
    except OSError:
        pass
    else:
        result = build_source_tree_inventory(workspace, validation_report=report)
        assert result.status is SourceTreeInventoryBuildStatus.WORKSPACE_CHANGED

    missing_result = build_source_tree_inventory(
        tmp_path / "missing",
        validation_report=report,
    )
    assert missing_result.status is SourceTreeInventoryBuildStatus.WORKSPACE_NOT_FOUND


def test_rejected_archive_report_cannot_create_an_inventory(tmp_path: Path) -> None:
    """Keep inventory creation behind the archive validation boundary."""
    archive_path = write_zip(
        tmp_path / "unsafe.zip",
        (("../outside.py", b"unsafe"),),
    )
    report = validate_source_archive(archive_path)

    result = build_source_tree_inventory(tmp_path, validation_report=report)

    assert result.status is SourceTreeInventoryBuildStatus.VALIDATION_REQUIRED
    assert result.inventory is None
