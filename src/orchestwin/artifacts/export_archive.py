"""Secure deterministic assembly and verification of final export archives."""

from __future__ import annotations

import hashlib
import io
import stat
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

from orchestwin.artifacts.export_manifest import FinalExportManifest, validate_export_path
from orchestwin.projects.requirements_primitives import canonical_json, validate_sha256
from orchestwin.workflow.runs import WorkflowRun, WorkflowRunStatus, WorkflowStage

_MANIFEST_PATH: Final = "manifest.json"
_FIXED_ZIP_TIMESTAMP: Final = (1980, 1, 1, 0, 0, 0)
_DEFAULT_MAX_ENTRY_BYTES: Final = 25 * 1024 * 1024
_DEFAULT_MAX_ARCHIVE_BYTES: Final = 100 * 1024 * 1024
_DEFAULT_MAX_ENTRY_COUNT: Final = 1_000


@dataclass(frozen=True, slots=True)
class BuiltFinalExportArchive:
    """One deterministic ZIP bound to an exact manifest and content set."""

    id: UUID
    manifest: FinalExportManifest
    archive_bytes: bytes
    archive_hash: str
    size_bytes: int
    created_at: datetime

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("export archive timestamp must be timezone-aware")
        validate_sha256(self.archive_hash, label="export archive content hash")
        if self.size_bytes != len(self.archive_bytes):
            raise ValueError("export archive size does not match its bytes")
        if hashlib.sha256(self.archive_bytes).hexdigest() != self.archive_hash:
            raise ValueError("export archive content hash is inconsistent")


@dataclass(frozen=True, slots=True)
class ExportArchiveLimits:
    """Explicit archive boundaries used by assembly and verification."""

    maximum_entry_bytes: int = _DEFAULT_MAX_ENTRY_BYTES
    maximum_archive_bytes: int = _DEFAULT_MAX_ARCHIVE_BYTES
    maximum_entry_count: int = _DEFAULT_MAX_ENTRY_COUNT

    def __post_init__(self) -> None:
        values = (
            self.maximum_entry_bytes,
            self.maximum_archive_bytes,
            self.maximum_entry_count,
        )
        if any(isinstance(value, bool) or value < 1 for value in values):
            raise ValueError("export archive limits must be positive integers")


def assemble_final_export_archive(
    manifest: FinalExportManifest,
    *,
    content_by_path: Mapping[str, bytes],
    archive_id: UUID | None = None,
    created_at: datetime,
    limits: ExportArchiveLimits | None = None,
) -> BuiltFinalExportArchive:
    """Build a byte-reproducible archive after exact digest and size validation."""
    if limits is None:
        limits = ExportArchiveLimits()
    expected_paths = {entry.path for entry in manifest.entries}
    supplied_paths = set(content_by_path)
    if supplied_paths != expected_paths:
        missing = sorted(expected_paths - supplied_paths)
        unexpected = sorted(supplied_paths - expected_paths)
        raise ValueError(
            f"export content paths do not match manifest: missing={missing}, "
            f"unexpected={unexpected}"
        )
    if len(manifest.entries) + 1 > limits.maximum_entry_count:
        raise ValueError("export archive entry count exceeds the configured limit")

    validated_content: dict[str, bytes] = {}
    total_uncompressed = 0
    entries_by_path = {entry.path: entry for entry in manifest.entries}
    for path in sorted(supplied_paths):
        validate_export_path(path)
        content = content_by_path[path]
        if not isinstance(content, bytes):
            raise TypeError("export content values must be bytes")
        entry = entries_by_path[path]
        if len(content) != entry.size_bytes:
            raise ValueError(f"export content size does not match manifest for {path}")
        if hashlib.sha256(content).hexdigest() != entry.content_hash:
            raise ValueError(f"export content hash does not match manifest for {path}")
        if len(content) > limits.maximum_entry_bytes:
            raise ValueError(f"export entry exceeds the configured size limit: {path}")
        total_uncompressed += len(content)
        validated_content[path] = content

    manifest_bytes = _manifest_bytes(manifest)
    total_uncompressed += len(manifest_bytes)
    if total_uncompressed > limits.maximum_archive_bytes:
        raise ValueError("export archive uncompressed content exceeds the configured limit")

    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        _write_deterministic_entry(archive, _MANIFEST_PATH, manifest_bytes)
        for path in sorted(validated_content):
            _write_deterministic_entry(archive, path, validated_content[path])
    archive_bytes = output.getvalue()
    if len(archive_bytes) > limits.maximum_archive_bytes:
        raise ValueError("export archive compressed size exceeds the configured limit")

    validate_final_export_archive(
        manifest,
        archive_bytes=archive_bytes,
        limits=limits,
    )
    return BuiltFinalExportArchive(
        id=archive_id or uuid4(),
        manifest=manifest,
        archive_bytes=archive_bytes,
        archive_hash=hashlib.sha256(archive_bytes).hexdigest(),
        size_bytes=len(archive_bytes),
        created_at=created_at,
    )


def validate_final_export_archive(
    manifest: FinalExportManifest,
    *,
    archive_bytes: bytes,
    limits: ExportArchiveLimits | None = None,
) -> None:
    """Verify safe paths, regular files, exact membership, hashes, and limits."""
    if not isinstance(archive_bytes, bytes):
        raise TypeError("export archive must be supplied as bytes")
    if limits is None:
        limits = ExportArchiveLimits()
    if len(archive_bytes) > limits.maximum_archive_bytes:
        raise ValueError("export archive compressed size exceeds the configured limit")

    expected = {_MANIFEST_PATH, *(entry.path for entry in manifest.entries)}
    entries_by_path = {entry.path: entry for entry in manifest.entries}
    total_uncompressed = 0
    with zipfile.ZipFile(io.BytesIO(archive_bytes), mode="r") as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ValueError("export archive contains duplicate paths")
        if len(names) > limits.maximum_entry_count:
            raise ValueError("export archive entry count exceeds the configured limit")
        if set(names) != expected:
            raise ValueError("export archive membership does not match the manifest")

        for info in infos:
            _validate_archive_info(info)
            if info.file_size > limits.maximum_entry_bytes and info.filename != _MANIFEST_PATH:
                raise ValueError("export archive entry exceeds the configured size limit")
            total_uncompressed += info.file_size
            content = archive.read(info)
            if info.filename == _MANIFEST_PATH:
                if content != _manifest_bytes(manifest):
                    raise ValueError("export archive manifest content is inconsistent")
                continue
            entry = entries_by_path[info.filename]
            if len(content) != entry.size_bytes:
                raise ValueError("export archive entry size is inconsistent")
            if hashlib.sha256(content).hexdigest() != entry.content_hash:
                raise ValueError("export archive entry hash is inconsistent")
    if total_uncompressed > limits.maximum_archive_bytes:
        raise ValueError("export archive uncompressed content exceeds the configured limit")


def complete_workflow_after_export(
    run: WorkflowRun,
    *,
    archive: BuiltFinalExportArchive,
    occurred_at: datetime,
) -> WorkflowRun:
    """Mark a run approved only after its exact final archive has been assembled."""
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ValueError("export completion timestamp must be timezone-aware")
    if occurred_at < run.updated_at:
        raise ValueError("export completion timestamp must not move backwards")
    if run.project_id != archive.manifest.project_id or run.id != archive.manifest.workflow_run_id:
        raise ValueError("export archive does not belong to the workflow run")
    if run.owner_user_id != archive.manifest.owner_user_id:
        raise ValueError("export archive does not belong to the workflow owner")
    if run.current_stage is not WorkflowStage.EXPORT or run.status is not WorkflowRunStatus.RUNNING:
        raise ValueError("workflow must be actively exporting before final approval completion")
    return replace(
        run,
        status=WorkflowRunStatus.APPROVED,
        state_version=run.state_version + 1,
        updated_at=occurred_at,
        completed_at=occurred_at,
    )


def _write_deterministic_entry(
    archive: zipfile.ZipFile,
    path: str,
    content: bytes,
) -> None:
    info = zipfile.ZipInfo(path, date_time=_FIXED_ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.flag_bits = 0
    archive.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _validate_archive_info(info: zipfile.ZipInfo) -> None:
    if info.filename == _MANIFEST_PATH:
        path = info.filename
    else:
        validate_export_path(info.filename)
        path = info.filename
    if info.is_dir() or path.endswith("/"):
        raise ValueError("export archive must contain regular files only")
    mode = (info.external_attr >> 16) & 0xFFFF
    if stat.S_ISLNK(mode):
        raise ValueError("export archive must not contain symbolic links")
    if mode and not stat.S_ISREG(mode):
        raise ValueError("export archive must contain regular files only")


def _manifest_bytes(manifest: FinalExportManifest) -> bytes:
    # canonical_json is the repository-wide deterministic JSON contract.
    return canonical_json(manifest.to_snapshot()).encode("utf-8")
