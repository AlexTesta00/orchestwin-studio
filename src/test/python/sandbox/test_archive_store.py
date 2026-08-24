"""Tests for content-addressed source archive storage."""

from __future__ import annotations

import zipfile
from pathlib import Path

from orchestwin.sandbox.archive_store import (
    FileSystemSourceArchiveStore,
    SourceArchiveStoreStatus,
)
from orchestwin.sandbox.archive_validation import validate_source_archive


def write_zip(path: Path, content: bytes = b"print('hello')\n") -> Path:
    """Create one validated source archive fixture."""
    with zipfile.ZipFile(path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("src/app.py", content)
    return path


def test_stores_validated_archive_under_its_sha256_content_address(tmp_path: Path) -> None:
    """Persist immutable bytes without exposing an absolute path in metadata."""
    archive_path = write_zip(tmp_path / "source.zip")
    report = validate_source_archive(archive_path)
    store = FileSystemSourceArchiveStore(tmp_path / "artifacts")

    result = store.store(archive_path, validation_report=report)

    assert result.status is SourceArchiveStoreStatus.STORED
    assert result.archive is not None
    expected_key = f"sha256/{result.archive.sha256_digest[:2]}/{result.archive.sha256_digest}.zip"
    assert result.archive.storage_key == expected_key
    stored_path = store.path_for(result.archive)
    assert stored_path.read_bytes() == archive_path.read_bytes()
    assert result.archive.to_snapshot()["media_type"] == "application/zip"
    assert store.find(result.archive.sha256_digest) == result.archive


def test_duplicate_content_is_idempotent_across_different_source_paths(tmp_path: Path) -> None:
    """Reuse one verified object for equal ZIP bytes."""
    first_path = write_zip(tmp_path / "first.zip")
    second_path = tmp_path / "second.zip"
    second_path.write_bytes(first_path.read_bytes())
    first_report = validate_source_archive(first_path)
    second_report = validate_source_archive(second_path)
    store = FileSystemSourceArchiveStore(tmp_path / "artifacts")

    first_result = store.store(first_path, validation_report=first_report)
    second_result = store.store(second_path, validation_report=second_report)

    assert first_result.status is SourceArchiveStoreStatus.STORED
    assert second_result.status is SourceArchiveStoreStatus.ALREADY_PRESENT
    assert second_result.archive == first_result.archive
    assert len(tuple((tmp_path / "artifacts" / "sha256").rglob("*.zip"))) == 1


def test_rejected_or_missing_source_is_not_stored(tmp_path: Path) -> None:
    """Keep storage behind validation and regular-file boundaries."""
    unsafe_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(unsafe_path, mode="w") as archive:
        archive.writestr("../outside.py", b"unsafe")
    unsafe_report = validate_source_archive(unsafe_path)
    store = FileSystemSourceArchiveStore(tmp_path / "artifacts")

    rejected_result = store.store(unsafe_path, validation_report=unsafe_report)
    missing_result = store.store(
        tmp_path / "missing.zip",
        validation_report=validate_source_archive(write_zip(tmp_path / "valid.zip")),
    )

    assert rejected_result.status is SourceArchiveStoreStatus.VALIDATION_REQUIRED
    assert missing_result.status is SourceArchiveStoreStatus.SOURCE_NOT_FOUND
    assert not (tmp_path / "artifacts").exists()


def test_source_change_after_validation_leaves_no_object_or_temp_file(tmp_path: Path) -> None:
    """Reject bytes that no longer match the accepted digest and size."""
    archive_path = write_zip(tmp_path / "source.zip", b"first")
    report = validate_source_archive(archive_path)
    write_zip(archive_path, b"changed")
    store_root = tmp_path / "artifacts"
    store = FileSystemSourceArchiveStore(store_root)

    result = store.store(archive_path, validation_report=report)

    assert result.status is SourceArchiveStoreStatus.SOURCE_CHANGED
    assert not tuple(store_root.rglob("*.zip"))
    assert not tuple(store_root.rglob("*.tmp"))


def test_corrupt_existing_object_is_never_overwritten(tmp_path: Path) -> None:
    """Surface content-address corruption rather than silently replacing evidence."""
    archive_path = write_zip(tmp_path / "source.zip")
    report = validate_source_archive(archive_path)
    assert report.archive_sha256 is not None
    store_root = tmp_path / "artifacts"
    target = store_root / "sha256" / report.archive_sha256[:2] / f"{report.archive_sha256}.zip"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"corrupt")
    store = FileSystemSourceArchiveStore(store_root)

    result = store.store(archive_path, validation_report=report)

    assert result.status is SourceArchiveStoreStatus.CORRUPT_EXISTING_OBJECT
    assert target.read_bytes() == b"corrupt"
    assert store.find(report.archive_sha256) is None


def test_invalid_digest_lookup_and_symlink_root_are_not_followed(tmp_path: Path) -> None:
    """Reject malformed references and adapter roots that redirect storage."""
    store = FileSystemSourceArchiveStore(tmp_path / "artifacts")
    assert store.find("../not-a-digest") is None

    archive_path = write_zip(tmp_path / "source.zip")
    report = validate_source_archive(archive_path)
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    symlink_root = tmp_path / "linked-root"

    try:
        symlink_root.symlink_to(real_root, target_is_directory=True)
    except OSError:
        return

    linked_store = FileSystemSourceArchiveStore(symlink_root)
    result = linked_store.store(archive_path, validation_report=report)

    assert result.status is SourceArchiveStoreStatus.STORAGE_ERROR
    assert not tuple(real_root.rglob("*.zip"))
