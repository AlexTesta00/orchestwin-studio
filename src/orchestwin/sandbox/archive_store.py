"""Content-addressed storage port and local filesystem adapter for source archives."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final, Protocol

from orchestwin.sandbox.archive_validation import SourceArchiveValidationReport

_HASH_CHUNK_SIZE: Final = 1024 * 1024


class SourceArchiveStoreStatus(StrEnum):
    """Typed outcomes of storing one validated source archive."""

    STORED = "STORED"
    ALREADY_PRESENT = "ALREADY_PRESENT"
    VALIDATION_REQUIRED = "VALIDATION_REQUIRED"
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    SOURCE_CHANGED = "SOURCE_CHANGED"
    CORRUPT_EXISTING_OBJECT = "CORRUPT_EXISTING_OBJECT"
    STORAGE_ERROR = "STORAGE_ERROR"


@dataclass(frozen=True, slots=True)
class StoredSourceArchive:
    """Stable content-addressed reference to one immutable ZIP object."""

    sha256_digest: str
    size_bytes: int
    storage_key: str

    def __post_init__(self) -> None:
        """Protect digest, size, and storage-key consistency."""
        if not _is_sha256(self.sha256_digest):
            raise ValueError("stored source archive digest must be lowercase SHA-256")
        if self.size_bytes < 0:
            raise ValueError("stored source archive size must not be negative")
        if self.storage_key != _storage_key(self.sha256_digest):
            raise ValueError("stored source archive key must match its digest")

    def to_snapshot(self) -> dict[str, object]:
        """Return deterministic metadata without exposing an absolute host path."""
        return {
            "sha256_digest": self.sha256_digest,
            "size_bytes": self.size_bytes,
            "storage_key": self.storage_key,
            "media_type": "application/zip",
        }


@dataclass(frozen=True, slots=True)
class SourceArchiveStoreResult:
    """Inspectable result of one content-addressed store operation."""

    status: SourceArchiveStoreStatus
    archive: StoredSourceArchive | None
    failure_message: str | None

    def __post_init__(self) -> None:
        """Protect success and failure result shapes."""
        if self.failure_message is not None and (
            not self.failure_message
            or self.failure_message != " ".join(self.failure_message.split())
        ):
            raise ValueError("source archive store failure message must be normalized")

        if self.status in {
            SourceArchiveStoreStatus.STORED,
            SourceArchiveStoreStatus.ALREADY_PRESENT,
        }:
            if self.archive is None or self.failure_message is not None:
                raise ValueError("successful source archive store result requires an archive")
        elif self.archive is not None or self.failure_message is None:
            raise ValueError("failed source archive store result requires only a message")

    @property
    def is_available(self) -> bool:
        """Return whether an immutable stored archive reference is available."""
        return self.status in {
            SourceArchiveStoreStatus.STORED,
            SourceArchiveStoreStatus.ALREADY_PRESENT,
        }


class SourceArchiveStore(Protocol):
    """Port for storing and resolving immutable validated source archives."""

    def store(
        self,
        source_path: Path,
        *,
        validation_report: SourceArchiveValidationReport,
    ) -> SourceArchiveStoreResult:
        """Store the exact archive accepted by one validation report."""
        ...

    def find(
        self,
        sha256_digest: str,
    ) -> StoredSourceArchive | None:
        """Return one verified stored archive reference when present."""
        ...


class FileSystemSourceArchiveStore:
    """Filesystem adapter using immutable SHA-256 object paths."""

    def __init__(
        self,
        root: Path,
    ) -> None:
        """Bind the adapter to one local artifact-store root."""
        self._root = Path(root)

    def store(
        self,
        source_path: Path,
        *,
        validation_report: SourceArchiveValidationReport,
    ) -> SourceArchiveStoreResult:
        """Copy one accepted ZIP into its content-addressed immutable location."""
        if not validation_report.is_accepted or validation_report.archive_sha256 is None:
            return _failed_store(
                SourceArchiveStoreStatus.VALIDATION_REQUIRED,
                "Source archive must pass validation before storage.",
            )

        source = Path(source_path)
        if source.is_symlink() or not source.is_file():
            return _failed_store(
                SourceArchiveStoreStatus.SOURCE_NOT_FOUND,
                "Validated source archive is no longer a regular file.",
            )

        expected_digest = validation_report.archive_sha256
        target_parent = self._prepare_target_parent(expected_digest)
        if target_parent is None:
            return _failed_store(
                SourceArchiveStoreStatus.STORAGE_ERROR,
                "Source archive storage root could not be prepared safely.",
            )

        target = target_parent / f"{expected_digest}.zip"
        existing_result = self._existing_result(target, expected_digest=expected_digest)
        if existing_result is not None:
            return existing_result

        temp_result = _copy_source_to_verified_temp(
            source,
            target_parent=target_parent,
            expected_digest=expected_digest,
            expected_size=validation_report.archive_size_bytes,
        )
        if isinstance(temp_result, SourceArchiveStoreResult):
            return temp_result

        temp_path, size_bytes = temp_result
        try:
            return self._install_verified_temp(
                temp_path,
                target=target,
                expected_digest=expected_digest,
                size_bytes=size_bytes,
            )
        finally:
            _remove_file(temp_path)

    def find(
        self,
        sha256_digest: str,
    ) -> StoredSourceArchive | None:
        """Resolve only an existing regular object with matching bytes."""
        if not _is_sha256(sha256_digest):
            return None

        if self._root.is_symlink():
            return None

        key_parts = PurePosixPath(_storage_key(sha256_digest)).parts
        target = self._root.joinpath(*key_parts)
        storage_parents = (
            self._root,
            self._root / "sha256",
            self._root / "sha256" / sha256_digest[:2],
        )
        if any(parent.is_symlink() for parent in storage_parents):
            return None
        if target.is_symlink() or not target.is_file():
            return None

        try:
            actual_digest, size_bytes = _hash_file(target)
        except OSError:
            return None

        if actual_digest != sha256_digest:
            return None

        return StoredSourceArchive(
            sha256_digest=sha256_digest,
            size_bytes=size_bytes,
            storage_key=_storage_key(sha256_digest),
        )

    def path_for(
        self,
        archive: StoredSourceArchive,
    ) -> Path:
        """Return the adapter-local path for a validated stored reference."""
        return self._root.joinpath(*PurePosixPath(archive.storage_key).parts)

    def _prepare_target_parent(
        self,
        sha256_digest: str,
    ) -> Path | None:
        """Create only regular directories under a non-symlink root."""
        try:
            if self._root.is_symlink():
                return None
            self._root.mkdir(parents=True, exist_ok=True)
            if not self._root.is_dir() or self._root.is_symlink():
                return None

            current = self._root
            for part in ("sha256", sha256_digest[:2]):
                current = current / part
                if current.is_symlink():
                    return None
                current.mkdir(exist_ok=True)
                if not current.is_dir() or current.is_symlink():
                    return None
            return current
        except OSError:
            return None

    def _existing_result(
        self,
        target: Path,
        *,
        expected_digest: str,
    ) -> SourceArchiveStoreResult | None:
        """Return an idempotent or corruption result for an existing object."""
        if not target.exists() and not target.is_symlink():
            return None

        if target.is_symlink() or not target.is_file():
            return _failed_store(
                SourceArchiveStoreStatus.CORRUPT_EXISTING_OBJECT,
                "Content-addressed source archive path is not a regular file.",
            )

        try:
            actual_digest, size_bytes = _hash_file(target)
        except OSError:
            return _failed_store(
                SourceArchiveStoreStatus.STORAGE_ERROR,
                "Existing source archive object could not be read.",
            )

        if actual_digest != expected_digest:
            return _failed_store(
                SourceArchiveStoreStatus.CORRUPT_EXISTING_OBJECT,
                "Existing source archive object does not match its content address.",
            )

        return SourceArchiveStoreResult(
            status=SourceArchiveStoreStatus.ALREADY_PRESENT,
            archive=StoredSourceArchive(
                sha256_digest=expected_digest,
                size_bytes=size_bytes,
                storage_key=_storage_key(expected_digest),
            ),
            failure_message=None,
        )

    def _install_verified_temp(
        self,
        temp_path: Path,
        *,
        target: Path,
        expected_digest: str,
        size_bytes: int,
    ) -> SourceArchiveStoreResult:
        """Install verified bytes without overwriting a concurrent object."""
        target_created = False
        try:
            with temp_path.open("rb") as source_file, target.open("xb") as target_file:
                target_created = True
                shutil.copyfileobj(source_file, target_file, length=_HASH_CHUNK_SIZE)
                target_file.flush()
                os.fsync(target_file.fileno())
            target.chmod(0o600)
        except FileExistsError:
            existing_result = self._existing_result(
                target,
                expected_digest=expected_digest,
            )
            if existing_result is not None:
                return existing_result
            return _failed_store(
                SourceArchiveStoreStatus.STORAGE_ERROR,
                "Source archive object appeared but could not be verified.",
            )
        except OSError:
            if target_created:
                _remove_file(target)
            return _failed_store(
                SourceArchiveStoreStatus.STORAGE_ERROR,
                "Source archive object could not be installed.",
            )

        return SourceArchiveStoreResult(
            status=SourceArchiveStoreStatus.STORED,
            archive=StoredSourceArchive(
                sha256_digest=expected_digest,
                size_bytes=size_bytes,
                storage_key=_storage_key(expected_digest),
            ),
            failure_message=None,
        )


def _copy_source_to_verified_temp(
    source: Path,
    *,
    target_parent: Path,
    expected_digest: str,
    expected_size: int,
) -> tuple[Path, int] | SourceArchiveStoreResult:
    """Copy and verify source bytes before creating the immutable object."""
    temp_path: Path | None = None
    try:
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{expected_digest}.",
            suffix=".tmp",
            dir=target_parent,
        )
        temp_path = Path(temp_name)
        digest = hashlib.sha256()
        size_bytes = 0

        with os.fdopen(descriptor, mode="wb") as temp_file:
            with source.open("rb") as source_file:
                while chunk := source_file.read(_HASH_CHUNK_SIZE):
                    size_bytes += len(chunk)
                    digest.update(chunk)
                    temp_file.write(chunk)
            temp_file.flush()
            os.fsync(temp_file.fileno())
    except OSError:
        if temp_path is not None:
            _remove_file(temp_path)
        return _failed_store(
            SourceArchiveStoreStatus.STORAGE_ERROR,
            "Validated source archive could not be copied into temporary storage.",
        )

    if size_bytes != expected_size or digest.hexdigest() != expected_digest:
        _remove_file(temp_path)
        return _failed_store(
            SourceArchiveStoreStatus.SOURCE_CHANGED,
            "Source archive changed after validation.",
        )

    if temp_path is None:
        return _failed_store(
            SourceArchiveStoreStatus.STORAGE_ERROR,
            "Validated source archive temporary path was not created.",
        )

    return temp_path, size_bytes


def _hash_file(
    path: Path,
) -> tuple[str, int]:
    """Return the streaming digest and size of one regular file."""
    digest = hashlib.sha256()
    size_bytes = 0
    with path.open("rb") as source_file:
        while chunk := source_file.read(_HASH_CHUNK_SIZE):
            size_bytes += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size_bytes


def _storage_key(
    sha256_digest: str,
) -> str:
    """Return the portable content-addressed key for one ZIP object."""
    return f"sha256/{sha256_digest[:2]}/{sha256_digest}.zip"


def _is_sha256(
    value: str,
) -> bool:
    """Return whether a value is one lowercase SHA-256 digest."""
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _remove_file(
    path: Path,
) -> None:
    """Remove one adapter-owned temporary or partial file when present."""
    with suppress(OSError):
        path.unlink(missing_ok=True)


def _failed_store(
    status: SourceArchiveStoreStatus,
    message: str,
) -> SourceArchiveStoreResult:
    """Create one consistent failed storage result."""
    return SourceArchiveStoreResult(
        status=status,
        archive=None,
        failure_message=message,
    )
