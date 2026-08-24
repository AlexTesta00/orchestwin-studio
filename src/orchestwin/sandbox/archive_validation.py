"""Preflight validation for untrusted brownfield ZIP archives."""

from __future__ import annotations

import hashlib
import re
import stat
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final

from orchestwin.sandbox.archive_policy import (
    DEFAULT_SOURCE_ARCHIVE_POLICY,
    SourceArchiveEntryDisposition,
    SourceArchiveEntryKind,
    SourceArchiveIgnoreReason,
    SourceArchiveIssue,
    SourceArchiveIssueCode,
    SourceArchivePolicy,
    SourceArchiveValidationStatus,
)

_WINDOWS_DRIVE_PATTERN: Final = re.compile(r"^[A-Za-z]:")
_WINDOWS_RESERVED_NAMES: Final = frozenset(
    {
        "aux",
        "con",
        "nul",
        "prn",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }
)
_HASH_CHUNK_SIZE: Final = 1024 * 1024


@dataclass(frozen=True, slots=True)
class ValidatedSourceArchiveEntry:
    """One safe and normalized entry discovered during ZIP preflight."""

    archive_name: str
    normalized_path: str
    canonical_path: str
    kind: SourceArchiveEntryKind
    disposition: SourceArchiveEntryDisposition
    ignore_reason: SourceArchiveIgnoreReason | None
    compressed_size: int
    uncompressed_size: int
    crc32: int

    def __post_init__(self) -> None:
        """Protect normalized entry metadata used by extraction."""
        if not self.archive_name or not self.normalized_path or not self.canonical_path:
            raise ValueError("validated source archive paths must not be empty")

        if self.normalized_path != unicodedata.normalize("NFC", self.normalized_path):
            raise ValueError("validated source archive path must use NFC normalization")

        if self.canonical_path != self.normalized_path.casefold():
            raise ValueError("validated source archive canonical path is inconsistent")

        if self.compressed_size < 0 or self.uncompressed_size < 0 or self.crc32 < 0:
            raise ValueError("validated source archive sizes and CRC must not be negative")

        if self.disposition is SourceArchiveEntryDisposition.INCLUDE:
            if self.ignore_reason is not None:
                raise ValueError("included source archive entry must not have an ignore reason")
        elif self.ignore_reason is None:
            raise ValueError("ignored source archive entry requires an ignore reason")


@dataclass(frozen=True, slots=True)
class SourceArchiveValidationReport:
    """Complete preflight result produced without extracting any entry."""

    status: SourceArchiveValidationStatus
    archive_size_bytes: int
    archive_sha256: str | None
    total_uncompressed_bytes: int
    entries: tuple[ValidatedSourceArchiveEntry, ...]
    issues: tuple[SourceArchiveIssue, ...]

    def __post_init__(self) -> None:
        """Protect result consistency and deterministic ordering."""
        if self.archive_size_bytes < 0 or self.total_uncompressed_bytes < 0:
            raise ValueError("source archive report sizes must not be negative")

        if self.archive_sha256 is not None and not _is_sha256(self.archive_sha256):
            raise ValueError("source archive report digest must be lowercase SHA-256")

        if self.entries != tuple(sorted(self.entries, key=lambda entry: entry.normalized_path)):
            raise ValueError("source archive report entries must use canonical order")

        if self.status is SourceArchiveValidationStatus.ACCEPTED:
            if self.issues:
                raise ValueError("accepted source archive report must not contain issues")
            if self.archive_sha256 is None:
                raise ValueError("accepted source archive report requires a digest")
        elif not self.issues:
            raise ValueError("rejected source archive report requires at least one issue")

    @property
    def is_accepted(self) -> bool:
        """Return whether extraction may consume this report."""
        return self.status is SourceArchiveValidationStatus.ACCEPTED

    @property
    def included_entries(self) -> tuple[ValidatedSourceArchiveEntry, ...]:
        """Return entries approved for the normalized source tree."""
        return tuple(
            entry
            for entry in self.entries
            if entry.disposition is SourceArchiveEntryDisposition.INCLUDE
        )

    @property
    def ignored_entries(self) -> tuple[ValidatedSourceArchiveEntry, ...]:
        """Return safe entries intentionally excluded from intake."""
        return tuple(
            entry
            for entry in self.entries
            if entry.disposition is SourceArchiveEntryDisposition.IGNORE
        )


def validate_source_archive(
    archive_path: Path,
    *,
    policy: SourceArchivePolicy = DEFAULT_SOURCE_ARCHIVE_POLICY,
) -> SourceArchiveValidationReport:
    """Validate one ZIP completely before any extraction is attempted."""
    path = Path(archive_path)

    try:
        file_status = path.lstat()
    except FileNotFoundError:
        return _rejected_report(
            issue=SourceArchiveIssue(
                code=SourceArchiveIssueCode.ARCHIVE_NOT_FOUND,
                message="Source archive does not exist.",
            )
        )
    except OSError:
        return _rejected_report(
            issue=SourceArchiveIssue(
                code=SourceArchiveIssueCode.ARCHIVE_NOT_REGULAR_FILE,
                message="Source archive metadata could not be read.",
            )
        )

    if path.is_symlink() or not stat.S_ISREG(file_status.st_mode):
        return _rejected_report(
            issue=SourceArchiveIssue(
                code=SourceArchiveIssueCode.ARCHIVE_NOT_REGULAR_FILE,
                message="Source archive must be a regular non-symlink file.",
            )
        )

    archive_size = file_status.st_size
    if archive_size > policy.maximum_archive_size_bytes:
        return _rejected_report(
            archive_size_bytes=archive_size,
            issue=SourceArchiveIssue(
                code=SourceArchiveIssueCode.ARCHIVE_TOO_LARGE,
                message="Source archive exceeds the compressed size limit.",
            ),
        )

    try:
        archive_sha256 = _hash_file(path)
    except OSError:
        return _rejected_report(
            archive_size_bytes=archive_size,
            issue=SourceArchiveIssue(
                code=SourceArchiveIssueCode.INVALID_ZIP,
                message="Source archive could not be read.",
            ),
        )

    try:
        with zipfile.ZipFile(path, mode="r") as archive:
            return _validate_open_archive(
                archive,
                archive_size_bytes=archive_size,
                archive_sha256=archive_sha256,
                policy=policy,
            )
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
        return _rejected_report(
            archive_size_bytes=archive_size,
            archive_sha256=archive_sha256,
            issue=SourceArchiveIssue(
                code=SourceArchiveIssueCode.INVALID_ZIP,
                message="Source archive is not a readable ZIP file.",
            ),
        )


def _validate_open_archive(
    archive: zipfile.ZipFile,
    *,
    archive_size_bytes: int,
    archive_sha256: str,
    policy: SourceArchivePolicy,
) -> SourceArchiveValidationReport:
    """Inspect one already-open archive without reading entry contents."""
    archive_entries = archive.infolist()

    if not archive_entries:
        return _rejected_report(
            archive_size_bytes=archive_size_bytes,
            archive_sha256=archive_sha256,
            issue=SourceArchiveIssue(
                code=SourceArchiveIssueCode.EMPTY_ARCHIVE,
                message="Source archive must contain at least one entry.",
            ),
        )

    if len(archive_entries) > policy.maximum_entries:
        return _rejected_report(
            archive_size_bytes=archive_size_bytes,
            archive_sha256=archive_sha256,
            issue=SourceArchiveIssue(
                code=SourceArchiveIssueCode.TOO_MANY_ENTRIES,
                message="Source archive exceeds the entry-count limit.",
            ),
        )

    entries: list[ValidatedSourceArchiveEntry] = []
    issues: list[SourceArchiveIssue] = []
    canonical_paths: dict[str, str] = {}
    total_uncompressed_bytes = 0

    for archive_entry in archive_entries:
        normalized_path, path_issue = _normalize_archive_path(
            archive_entry.filename,
            maximum_length=policy.maximum_normalized_path_length,
        )
        if path_issue is not None:
            issues.append(path_issue)
            continue

        canonical_path = normalized_path.casefold()
        previous_path = canonical_paths.get(canonical_path)
        if previous_path is not None:
            issues.append(
                SourceArchiveIssue(
                    code=SourceArchiveIssueCode.CANONICAL_PATH_COLLISION,
                    message="Source archive contains colliding normalized paths.",
                    entry_path=normalized_path,
                )
            )
            continue
        canonical_paths[canonical_path] = normalized_path

        entry_kind = _classify_entry_kind(archive_entry)
        if entry_kind is None:
            issues.append(
                SourceArchiveIssue(
                    code=SourceArchiveIssueCode.UNSAFE_ENTRY_TYPE,
                    message="Source archive contains a symlink or special file.",
                    entry_path=normalized_path,
                )
            )
            continue

        if archive_entry.flag_bits & 0x1:
            issues.append(
                SourceArchiveIssue(
                    code=SourceArchiveIssueCode.ENCRYPTED_ENTRY,
                    message="Source archive contains an encrypted entry.",
                    entry_path=normalized_path,
                )
            )

        if archive_entry.file_size > policy.maximum_entry_uncompressed_bytes:
            issues.append(
                SourceArchiveIssue(
                    code=SourceArchiveIssueCode.ENTRY_TOO_LARGE,
                    message="Source archive entry exceeds the uncompressed size limit.",
                    entry_path=normalized_path,
                )
            )

        total_uncompressed_bytes += archive_entry.file_size

        if _compression_ratio(archive_entry) > policy.maximum_compression_ratio:
            issues.append(
                SourceArchiveIssue(
                    code=SourceArchiveIssueCode.COMPRESSION_RATIO_EXCEEDED,
                    message="Source archive entry exceeds the compression-ratio limit.",
                    entry_path=normalized_path,
                )
            )

        if entry_kind is SourceArchiveEntryKind.FILE and _is_sensitive_file(
            normalized_path,
            policy=policy,
        ):
            issues.append(
                SourceArchiveIssue(
                    code=SourceArchiveIssueCode.SENSITIVE_FILE,
                    message="Source archive contains a prohibited sensitive file.",
                    entry_path=normalized_path,
                )
            )

        disposition, ignore_reason = _entry_disposition(
            normalized_path,
            kind=entry_kind,
            policy=policy,
        )
        entries.append(
            ValidatedSourceArchiveEntry(
                archive_name=archive_entry.filename,
                normalized_path=normalized_path,
                canonical_path=canonical_path,
                kind=entry_kind,
                disposition=disposition,
                ignore_reason=ignore_reason,
                compressed_size=archive_entry.compress_size,
                uncompressed_size=archive_entry.file_size,
                crc32=archive_entry.CRC,
            )
        )

    if total_uncompressed_bytes > policy.maximum_total_uncompressed_bytes:
        issues.append(
            SourceArchiveIssue(
                code=SourceArchiveIssueCode.TOTAL_UNCOMPRESSED_TOO_LARGE,
                message="Source archive exceeds the total uncompressed size limit.",
            )
        )

    ordered_entries = tuple(sorted(entries, key=lambda entry: entry.normalized_path))
    if issues:
        return SourceArchiveValidationReport(
            status=SourceArchiveValidationStatus.REJECTED,
            archive_size_bytes=archive_size_bytes,
            archive_sha256=archive_sha256,
            total_uncompressed_bytes=total_uncompressed_bytes,
            entries=ordered_entries,
            issues=tuple(issues),
        )

    return SourceArchiveValidationReport(
        status=SourceArchiveValidationStatus.ACCEPTED,
        archive_size_bytes=archive_size_bytes,
        archive_sha256=archive_sha256,
        total_uncompressed_bytes=total_uncompressed_bytes,
        entries=ordered_entries,
        issues=(),
    )


def _normalize_archive_path(
    archive_name: str,
    *,
    maximum_length: int,
) -> tuple[str, SourceArchiveIssue | None]:
    """Normalize one portable relative ZIP path or return a typed issue."""
    display_path = _safe_display_path(archive_name)

    has_control_character = any(
        ord(character) < 32 or ord(character) == 127 for character in archive_name
    )
    if not archive_name or has_control_character:
        return "", _unsafe_path_issue(display_path)

    if archive_name.startswith(("/", "\\")) or _WINDOWS_DRIVE_PATTERN.match(archive_name):
        return "", _unsafe_path_issue(display_path)

    portable_path = archive_name.replace("\\", "/")
    if portable_path.startswith("//"):
        return "", _unsafe_path_issue(display_path)

    without_directory_marker = portable_path[:-1] if portable_path.endswith("/") else portable_path
    raw_parts = without_directory_marker.split("/")
    if not without_directory_marker or any(part in {"", ".", ".."} for part in raw_parts):
        return "", _unsafe_path_issue(display_path)

    normalized_parts: list[str] = []
    for raw_part in raw_parts:
        normalized_part = unicodedata.normalize("NFC", raw_part)
        if (
            normalized_part.endswith((" ", "."))
            or ":" in normalized_part
            or _is_windows_reserved_name(normalized_part)
        ):
            return "", _unsafe_path_issue(display_path)
        normalized_parts.append(normalized_part)

    normalized_path = "/".join(normalized_parts)
    if len(normalized_path) > maximum_length:
        return "", SourceArchiveIssue(
            code=SourceArchiveIssueCode.PATH_TOO_LONG,
            message="Source archive entry path exceeds the portable length limit.",
            entry_path=display_path,
        )

    return normalized_path, None


def _classify_entry_kind(
    archive_entry: zipfile.ZipInfo,
) -> SourceArchiveEntryKind | None:
    """Accept only regular files and directories."""
    declared_mode = (archive_entry.external_attr >> 16) & 0xFFFF
    declared_type = stat.S_IFMT(declared_mode)
    directory_marker = archive_entry.is_dir()

    if declared_type == stat.S_IFLNK:
        return None

    if declared_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
        return None

    if directory_marker:
        if declared_type == stat.S_IFREG:
            return None
        return SourceArchiveEntryKind.DIRECTORY

    if declared_type == stat.S_IFDIR:
        return None

    return SourceArchiveEntryKind.FILE


def _entry_disposition(
    normalized_path: str,
    *,
    kind: SourceArchiveEntryKind,
    policy: SourceArchivePolicy,
) -> tuple[SourceArchiveEntryDisposition, SourceArchiveIgnoreReason | None]:
    """Apply generated-directory and textual-file allowlists."""
    parts = PurePosixPath(normalized_path).parts
    compared_parts = tuple(part.casefold() for part in parts)
    if any(part in policy.ignored_directory_names for part in compared_parts):
        return (
            SourceArchiveEntryDisposition.IGNORE,
            SourceArchiveIgnoreReason.GENERATED_PATH,
        )

    if kind is SourceArchiveEntryKind.DIRECTORY:
        return SourceArchiveEntryDisposition.INCLUDE, None

    file_name = compared_parts[-1]
    suffix = PurePosixPath(file_name).suffix.casefold()
    if (
        file_name in policy.allowed_file_names
        or suffix in policy.allowed_file_extensions
        or _is_environment_template(file_name, policy=policy)
    ):
        return SourceArchiveEntryDisposition.INCLUDE, None

    return (
        SourceArchiveEntryDisposition.IGNORE,
        SourceArchiveIgnoreReason.UNSUPPORTED_FILE,
    )


def _is_sensitive_file(
    normalized_path: str,
    *,
    policy: SourceArchivePolicy,
) -> bool:
    """Reject active environment files, credentials, and private-key containers."""
    file_name = PurePosixPath(normalized_path).name.casefold()

    if _is_environment_template(file_name, policy=policy):
        return False

    return (
        file_name.startswith(".env")
        or file_name in policy.sensitive_file_names
        or any(file_name.endswith(suffix) for suffix in policy.sensitive_file_suffixes)
    )


def _is_environment_template(
    file_name: str,
    *,
    policy: SourceArchivePolicy,
) -> bool:
    """Allow clearly named environment templates while rejecting active values."""
    return file_name.startswith(".env") and any(
        file_name.endswith(suffix) for suffix in policy.environment_template_suffixes
    )


def _compression_ratio(
    archive_entry: zipfile.ZipInfo,
) -> float:
    """Return a bounded ratio without dividing by zero."""
    if archive_entry.file_size == 0:
        return 0.0
    if archive_entry.compress_size == 0:
        return float("inf")
    return archive_entry.file_size / archive_entry.compress_size


def _is_windows_reserved_name(
    path_part: str,
) -> bool:
    """Reject device names that are unsafe on Windows filesystems."""
    base_name = path_part.split(".", maxsplit=1)[0].casefold()
    return base_name in _WINDOWS_RESERVED_NAMES


def _unsafe_path_issue(
    display_path: str,
) -> SourceArchiveIssue:
    """Create the shared unsafe-path issue."""
    return SourceArchiveIssue(
        code=SourceArchiveIssueCode.UNSAFE_PATH,
        message="Source archive entry path is not a safe portable relative path.",
        entry_path=display_path or "<empty>",
    )


def _safe_display_path(
    archive_name: str,
) -> str:
    """Escape control characters before returning a path in an issue."""
    return archive_name.encode("unicode_escape").decode("ascii")


def _hash_file(
    path: Path,
) -> str:
    """Calculate one streaming SHA-256 digest."""
    digest = hashlib.sha256()
    with path.open("rb") as archive_file:
        for chunk in iter(lambda: archive_file.read(_HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(
    value: str,
) -> bool:
    """Return whether a value is one lowercase SHA-256 digest."""
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _rejected_report(
    *,
    issue: SourceArchiveIssue,
    archive_size_bytes: int = 0,
    archive_sha256: str | None = None,
) -> SourceArchiveValidationReport:
    """Create a minimal rejected preflight report."""
    return SourceArchiveValidationReport(
        status=SourceArchiveValidationStatus.REJECTED,
        archive_size_bytes=archive_size_bytes,
        archive_sha256=archive_sha256,
        total_uncompressed_bytes=0,
        entries=(),
        issues=(issue,),
    )
