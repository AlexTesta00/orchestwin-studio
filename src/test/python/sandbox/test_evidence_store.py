"""Tests for content-addressed sandbox evidence storage."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from orchestwin.sandbox.evidence import SandboxLogStream
from orchestwin.sandbox.evidence_store import FileSystemSandboxEvidenceStore

RUN_ID = UUID("00000000-0000-4000-8000-000000007201")


def test_filesystem_store_deduplicates_identical_raw_content(tmp_path: Path) -> None:
    """Reuse one immutable object while preserving distinct evidence metadata."""
    store = FileSystemSandboxEvidenceStore(tmp_path / "evidence")

    stdout = store.store_log(
        run_id=RUN_ID,
        command_id="quality.tests",
        stream=SandboxLogStream.STDOUT,
        content=b"1 passed\n",
    )
    artifact = store.store_artifact(
        run_id=RUN_ID,
        command_id="quality.tests",
        normalized_path="reports/tests.txt",
        content=b"1 passed\n",
        media_type="text/plain",
    )

    assert stdout.storage_key == artifact.storage_key
    assert stdout.sha256_digest == artifact.sha256_digest
    assert store.read(stdout.storage_key) == b"1 passed\n"
    assert artifact.normalized_path == "reports/tests.txt"


def test_filesystem_store_rejects_corrupt_existing_content_address(tmp_path: Path) -> None:
    """Never overwrite bytes that contradict an existing SHA-256 object path."""
    root = tmp_path / "evidence"
    store = FileSystemSandboxEvidenceStore(root)
    reference = store.store_log(
        run_id=RUN_ID,
        command_id="quality.tests",
        stream=SandboxLogStream.STDERR,
        content=b"original",
    )
    target = root.joinpath(*reference.storage_key.split("/"))
    target.write_bytes(b"tampered")

    assert store.read(reference.storage_key) is None
    with pytest.raises(ValueError, match="content address"):
        store.store_log(
            run_id=RUN_ID,
            command_id="quality.tests",
            stream=SandboxLogStream.STDERR,
            content=b"original",
        )


def test_filesystem_store_rejects_invalid_keys_and_non_bytes(tmp_path: Path) -> None:
    """Keep reads inside the object namespace and avoid implicit text conversion."""
    store = FileSystemSandboxEvidenceStore(tmp_path / "evidence")

    assert store.read("../outside") is None
    assert store.read("sha256/aa/not-a-digest") is None

    with pytest.raises(TypeError, match="must be bytes"):
        store.store_log(
            run_id=RUN_ID,
            command_id="quality.tests",
            stream=SandboxLogStream.STDOUT,
            content="text",  # type: ignore[arg-type]
        )


def test_filesystem_store_does_not_follow_a_symlink_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refuse storage redirection without requiring host symlink privileges."""
    destination = tmp_path / "destination"
    destination.mkdir()
    root = tmp_path / "evidence"
    path_type = type(root)
    original_is_symlink = path_type.is_symlink

    def report_configured_root_as_symlink(path: Path) -> bool:
        return path == root or original_is_symlink(path)

    monkeypatch.setattr(path_type, "is_symlink", report_configured_root_as_symlink)

    store = FileSystemSandboxEvidenceStore(root)
    with pytest.raises(OSError, match="prepared safely"):
        store.store_log(
            run_id=RUN_ID,
            command_id="quality.tests",
            stream=SandboxLogStream.STDOUT,
            content=b"not-written",
        )

    assert list(destination.iterdir()) == []
    assert not root.exists()
