"""Safe extraction of source archives that passed complete preflight validation."""

from __future__ import annotations

import hashlib
import shutil
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Final
from uuid import UUID

from orchestwin.sandbox.archive_policy import (
    DEFAULT_SOURCE_ARCHIVE_POLICY,
    SourceArchiveEntryKind,
    SourceArchivePolicy,
)
from orchestwin.sandbox.archive_validation import (
    SourceArchiveValidationReport,
    ValidatedSourceArchiveEntry,
    validate_source_archive,
)

_COPY_CHUNK_SIZE: Final = 1024 * 1024


class SourceArchiveExtractionStatus(StrEnum):
    """Typed outcomes of one source archive extraction attempt."""

    EXTRACTED = "EXTRACTED"
    VALIDATION_REQUIRED = "VALIDATION_REQUIRED"
    ARCHIVE_CHANGED = "ARCHIVE_CHANGED"
    WORKSPACE_CONFLICT = "WORKSPACE_CONFLICT"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"


@dataclass(frozen=True, slots=True)
class SourceArchiveExtractionResult:
    """Inspectable result of materializing one normalized source tree."""

    status: SourceArchiveExtractionStatus
    workspace_path: Path | None
    extracted_paths: tuple[str, ...]
    ignored_paths: tuple[str, ...]
    failure_message: str | None
    cleanup_completed: bool

    def __post_init__(self) -> None:
        """Protect status-dependent result invariants."""
        if self.extracted_paths != tuple(sorted(self.extracted_paths)):
            raise ValueError("source archive extracted paths must use canonical order")
        if self.ignored_paths != tuple(sorted(self.ignored_paths)):
            raise ValueError("source archive ignored paths must use canonical order")

        if self.failure_message is not None and (
            not self.failure_message
            or self.failure_message != " ".join(self.failure_message.split())
        ):
            raise ValueError("source archive extraction failure message must be normalized")

        if self.status is SourceArchiveExtractionStatus.EXTRACTED:
            if self.workspace_path is None or self.failure_message is not None:
                raise ValueError("successful source archive extraction requires a workspace")
            if not self.cleanup_completed:
                raise ValueError("successful source archive extraction must not require cleanup")
        elif self.workspace_path is not None:
            raise ValueError("failed source archive extraction must not expose a workspace")

    @property
    def is_extracted(self) -> bool:
        """Return whether the source tree was materialized successfully."""
        return self.status is SourceArchiveExtractionStatus.EXTRACTED


def extract_validated_source_archive(
    archive_path: Path,
    *,
    validation_report: SourceArchiveValidationReport,
    workspace_root: Path,
    workspace_id: UUID,
    policy: SourceArchivePolicy = DEFAULT_SOURCE_ARCHIVE_POLICY,
) -> SourceArchiveExtractionResult:
    """Extract only entries bound to one accepted and unchanged preflight report."""
    ignored_paths = tuple(entry.normalized_path for entry in validation_report.ignored_entries)

    if not validation_report.is_accepted:
        return _failed_result(
            status=SourceArchiveExtractionStatus.VALIDATION_REQUIRED,
            ignored_paths=ignored_paths,
            message="Source archive must pass validation before extraction.",
        )

    current_report = validate_source_archive(Path(archive_path), policy=policy)
    if current_report != validation_report:
        return _failed_result(
            status=SourceArchiveExtractionStatus.ARCHIVE_CHANGED,
            ignored_paths=ignored_paths,
            message="Source archive changed after validation.",
        )

    workspace, workspace_error = _create_workspace(
        Path(workspace_root),
        workspace_id=workspace_id,
    )
    if workspace is None:
        return _failed_result(
            status=workspace_error,
            ignored_paths=ignored_paths,
            message=(
                "Source archive workspace already exists."
                if workspace_error is SourceArchiveExtractionStatus.WORKSPACE_CONFLICT
                else "Source archive workspace could not be created."
            ),
        )

    try:
        extracted_paths = _extract_entries(
            Path(archive_path),
            validation_report=validation_report,
            workspace=workspace,
        )
    except (KeyError, OSError, RuntimeError, ValueError, zipfile.BadZipFile):
        cleanup_completed = _remove_workspace(workspace)
        return _failed_result(
            status=SourceArchiveExtractionStatus.EXTRACTION_FAILED,
            ignored_paths=ignored_paths,
            message="Source archive could not be extracted safely.",
            cleanup_completed=cleanup_completed,
        )

    return SourceArchiveExtractionResult(
        status=SourceArchiveExtractionStatus.EXTRACTED,
        workspace_path=workspace,
        extracted_paths=extracted_paths,
        ignored_paths=ignored_paths,
        failure_message=None,
        cleanup_completed=True,
    )


def _create_workspace(
    workspace_root: Path,
    *,
    workspace_id: UUID,
) -> tuple[Path | None, SourceArchiveExtractionStatus]:
    """Create one new non-symlink workspace below an approved root."""
    try:
        if workspace_root.is_symlink():
            return None, SourceArchiveExtractionStatus.EXTRACTION_FAILED

        workspace_root.mkdir(parents=True, exist_ok=True)
        if not workspace_root.is_dir() or workspace_root.is_symlink():
            return None, SourceArchiveExtractionStatus.EXTRACTION_FAILED

        resolved_root = workspace_root.resolve(strict=True)
        workspace = resolved_root / str(workspace_id)
        if workspace.exists() or workspace.is_symlink():
            return None, SourceArchiveExtractionStatus.WORKSPACE_CONFLICT

        workspace.mkdir(mode=0o700)
        return workspace, SourceArchiveExtractionStatus.EXTRACTED
    except OSError:
        return None, SourceArchiveExtractionStatus.EXTRACTION_FAILED


def _extract_entries(
    archive_path: Path,
    *,
    validation_report: SourceArchiveValidationReport,
    workspace: Path,
) -> tuple[str, ...]:
    """Copy approved entries using normalized targets and the validated archive bytes."""
    expected_digest = validation_report.archive_sha256
    if expected_digest is None:
        raise ValueError("accepted validation report requires an archive digest")

    extracted_paths: list[str] = []
    with archive_path.open("rb") as archive_file:
        if _hash_open_file(archive_file) != expected_digest:
            raise ValueError("source archive changed before extraction")
        archive_file.seek(0)

        with zipfile.ZipFile(archive_file, mode="r") as archive:
            archive_entries = {entry.filename: entry for entry in archive.infolist()}
            for entry in validation_report.included_entries:
                archive_entry = archive_entries[entry.archive_name]
                _require_matching_entry_metadata(entry, archive_entry)
                target_path = _workspace_target(workspace, entry.normalized_path)

                if entry.kind is SourceArchiveEntryKind.DIRECTORY:
                    target_path.mkdir(parents=True, exist_ok=False)
                else:
                    _copy_file_entry(
                        archive,
                        archive_entry=archive_entry,
                        target_path=target_path,
                        expected_size=entry.uncompressed_size,
                    )

                extracted_paths.append(entry.normalized_path)

    return tuple(sorted(extracted_paths))


def _require_matching_entry_metadata(
    validated_entry: ValidatedSourceArchiveEntry,
    archive_entry: zipfile.ZipInfo,
) -> None:
    """Protect extraction from a report that does not match the open ZIP member."""
    if (
        archive_entry.filename != validated_entry.archive_name
        or archive_entry.compress_size != validated_entry.compressed_size
        or archive_entry.file_size != validated_entry.uncompressed_size
        or validated_entry.crc32 != archive_entry.CRC
    ):
        raise ValueError("source archive entry metadata changed after validation")


def _workspace_target(
    workspace: Path,
    normalized_path: str,
) -> Path:
    """Resolve one normalized relative path and prove workspace containment."""
    target = workspace.joinpath(*PurePosixPath(normalized_path).parts)
    resolved_workspace = workspace.resolve(strict=True)
    resolved_target = target.resolve(strict=False)

    try:
        resolved_target.relative_to(resolved_workspace)
    except ValueError as error:
        raise ValueError("source archive entry leaves the extraction workspace") from error

    return resolved_target


def _copy_file_entry(
    archive: zipfile.ZipFile,
    *,
    archive_entry: zipfile.ZipInfo,
    target_path: Path,
    expected_size: int,
) -> None:
    """Copy one member without preserving archive permissions or following links."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    bytes_written = 0

    with (
        archive.open(archive_entry, mode="r") as source_file,
        target_path.open("xb") as target_file,
    ):
        while chunk := source_file.read(_COPY_CHUNK_SIZE):
            bytes_written += len(chunk)
            if bytes_written > expected_size:
                raise ValueError("source archive entry exceeded its validated size")
            target_file.write(chunk)

    if bytes_written != expected_size:
        raise ValueError("source archive entry did not match its validated size")


def _hash_open_file(
    archive_file: BinaryIO,
) -> str:
    """Hash the exact open file descriptor later consumed by ZipFile."""
    digest = hashlib.sha256()
    archive_file.seek(0)
    for chunk in iter(lambda: archive_file.read(_COPY_CHUNK_SIZE), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _remove_workspace(
    workspace: Path,
) -> bool:
    """Best-effort cleanup with an inspectable completion flag."""
    try:
        shutil.rmtree(workspace)
    except OSError:
        return False
    return not workspace.exists()


def _failed_result(
    *,
    status: SourceArchiveExtractionStatus,
    ignored_paths: tuple[str, ...],
    message: str,
    cleanup_completed: bool = True,
) -> SourceArchiveExtractionResult:
    """Create one consistent failed extraction result."""
    return SourceArchiveExtractionResult(
        status=status,
        workspace_path=None,
        extracted_paths=(),
        ignored_paths=tuple(sorted(ignored_paths)),
        failure_message=message,
        cleanup_completed=cleanup_completed,
    )
