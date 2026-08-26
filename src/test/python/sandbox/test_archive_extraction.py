"""Security tests for extracting preflighted source archives."""

from __future__ import annotations

import zipfile
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from orchestwin.sandbox.archive_extraction import (
    SourceArchiveExtractionStatus,
    extract_validated_source_archive,
)
from orchestwin.sandbox.archive_policy import SourceArchiveIssueCode
from orchestwin.sandbox.archive_validation import (
    ValidatedSourceArchiveEntry,
    validate_source_archive,
)

WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000701")


def write_zip(path: Path, entries: dict[str, bytes]) -> Path:
    """Create one small deflated source archive."""
    with zipfile.ZipFile(path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return path


def test_extracts_only_included_entries_into_a_generated_workspace(tmp_path: Path) -> None:
    """Materialize normalized source text without generated or binary content."""
    archive_path = write_zip(
        tmp_path / "source.zip",
        {
            "src\\app.py": b"print('hello')\n",
            "README.md": b"# Example\n",
            "assets/logo.png": b"ignored binary",
            "node_modules/package/index.js": b"ignored generated file",
        },
    )
    report = validate_source_archive(archive_path)
    workspace_root = tmp_path / "workspaces"

    result = extract_validated_source_archive(
        archive_path,
        validation_report=report,
        workspace_root=workspace_root,
        workspace_id=WORKSPACE_ID,
    )

    assert result.is_extracted
    assert result.workspace_path == workspace_root.resolve() / str(WORKSPACE_ID)
    assert result.extracted_paths == ("README.md", "src/app.py")
    assert result.ignored_paths == (
        "assets/logo.png",
        "node_modules/package/index.js",
    )
    assert (result.workspace_path / "src" / "app.py").read_bytes() == b"print('hello')\n"
    assert not (result.workspace_path / "assets").exists()
    assert not (result.workspace_path / "node_modules").exists()


def test_rejected_archive_cannot_create_a_workspace(tmp_path: Path) -> None:
    """Require complete preflight success before any extraction side effect."""
    archive_path = write_zip(
        tmp_path / "unsafe.zip",
        {"../outside.py": b"unsafe"},
    )
    report = validate_source_archive(archive_path)

    result = extract_validated_source_archive(
        archive_path,
        validation_report=report,
        workspace_root=tmp_path / "workspaces",
        workspace_id=WORKSPACE_ID,
    )

    assert {issue.code for issue in report.issues} == {SourceArchiveIssueCode.UNSAFE_PATH}
    assert result.status is SourceArchiveExtractionStatus.VALIDATION_REQUIRED
    assert not (tmp_path / "workspaces").exists()
    assert not (tmp_path / "outside.py").exists()


def test_archive_change_after_validation_is_detected_before_workspace_creation(
    tmp_path: Path,
) -> None:
    """Bind extraction to the exact digest and metadata accepted by preflight."""
    archive_path = write_zip(
        tmp_path / "source.zip",
        {"src/app.py": b"first"},
    )
    report = validate_source_archive(archive_path)
    write_zip(
        archive_path,
        {"src/app.py": b"changed"},
    )

    result = extract_validated_source_archive(
        archive_path,
        validation_report=report,
        workspace_root=tmp_path / "workspaces",
        workspace_id=WORKSPACE_ID,
    )

    assert result.status is SourceArchiveExtractionStatus.ARCHIVE_CHANGED
    assert not (tmp_path / "workspaces").exists()


def test_forged_validation_entry_cannot_redirect_archive_content(tmp_path: Path) -> None:
    """Reject an accepted-looking report that differs from deterministic preflight."""
    archive_path = write_zip(
        tmp_path / "source.zip",
        {"src/app.py": b"safe"},
    )
    report = validate_source_archive(archive_path)
    original_entry = report.entries[0]
    redirected_entry = ValidatedSourceArchiveEntry(
        archive_name=original_entry.archive_name,
        normalized_path="../outside.py",
        canonical_path="../outside.py",
        kind=original_entry.kind,
        disposition=original_entry.disposition,
        ignore_reason=original_entry.ignore_reason,
        compressed_size=original_entry.compressed_size,
        uncompressed_size=original_entry.uncompressed_size,
        crc32=original_entry.crc32,
    )
    forged_report = replace(report, entries=(redirected_entry,))

    result = extract_validated_source_archive(
        archive_path,
        validation_report=forged_report,
        workspace_root=tmp_path / "workspaces",
        workspace_id=WORKSPACE_ID,
    )

    assert result.status is SourceArchiveExtractionStatus.ARCHIVE_CHANGED
    assert not (tmp_path / "outside.py").exists()


def test_existing_workspace_is_never_reused_or_overwritten(tmp_path: Path) -> None:
    """Make every extraction workspace fresh and non-overwriting."""
    archive_path = write_zip(
        tmp_path / "source.zip",
        {"src/app.py": b"safe"},
    )
    report = validate_source_archive(archive_path)
    workspace = tmp_path / "workspaces" / str(WORKSPACE_ID)
    workspace.mkdir(parents=True)
    sentinel = workspace / "sentinel.txt"
    sentinel.write_text("preserve", encoding="utf-8")

    result = extract_validated_source_archive(
        archive_path,
        validation_report=report,
        workspace_root=tmp_path / "workspaces",
        workspace_id=WORKSPACE_ID,
    )

    assert result.status is SourceArchiveExtractionStatus.WORKSPACE_CONFLICT
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert not (workspace / "src" / "app.py").exists()


def test_partial_workspace_is_removed_when_copy_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Avoid exposing a partially extracted source tree after an I/O failure."""
    archive_path = write_zip(
        tmp_path / "source.zip",
        {"src/app.py": b"safe"},
    )
    report = validate_source_archive(archive_path)
    workspace = tmp_path / "workspaces" / str(WORKSPACE_ID)

    def fail_copy(*args, **kwargs) -> None:
        raise OSError("simulated copy failure")

    monkeypatch.setattr(
        "orchestwin.sandbox.archive_extraction._copy_file_entry",
        fail_copy,
    )

    result = extract_validated_source_archive(
        archive_path,
        validation_report=report,
        workspace_root=tmp_path / "workspaces",
        workspace_id=WORKSPACE_ID,
    )

    assert result.status is SourceArchiveExtractionStatus.EXTRACTION_FAILED
    assert result.cleanup_completed
    assert not workspace.exists()
