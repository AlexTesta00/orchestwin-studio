"""Security tests for ZIP preflight validation."""

from __future__ import annotations

import stat
import struct
import zipfile
from dataclasses import replace
from pathlib import Path

from orchestwin.sandbox.archive_policy import (
    DEFAULT_SOURCE_ARCHIVE_POLICY,
    SourceArchiveEntryDisposition,
    SourceArchiveIgnoreReason,
    SourceArchiveIssueCode,
)
from orchestwin.sandbox.archive_validation import validate_source_archive


def write_zip(
    path: Path,
    entries: dict[str, bytes],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
) -> Path:
    """Create one small test ZIP."""
    with zipfile.ZipFile(path, mode="w", compression=compression) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return path


def issue_codes(path: Path, **kwargs) -> set[SourceArchiveIssueCode]:
    """Return stable issue codes for one validation report."""
    return {issue.code for issue in validate_source_archive(path, **kwargs).issues}


def test_valid_archive_is_normalized_hashed_and_canonically_ordered(tmp_path: Path) -> None:
    """Accept safe source text without writing an extraction directory."""
    archive_path = write_zip(
        tmp_path / "source.zip",
        {
            "src\\app.py": b"print('hello')\n",
            "README.md": b"# Example\n",
            "assets/logo.png": b"not extracted",
            "node_modules/package/index.js": b"generated",
        },
    )

    report = validate_source_archive(archive_path)

    assert report.is_accepted
    assert len(report.archive_sha256 or "") == 64
    assert tuple(entry.normalized_path for entry in report.entries) == (
        "README.md",
        "assets/logo.png",
        "node_modules/package/index.js",
        "src/app.py",
    )
    dispositions = {
        entry.normalized_path: (entry.disposition, entry.ignore_reason)
        for entry in report.entries
    }
    assert dispositions["src/app.py"] == (SourceArchiveEntryDisposition.INCLUDE, None)
    assert dispositions["assets/logo.png"] == (
        SourceArchiveEntryDisposition.IGNORE,
        SourceArchiveIgnoreReason.UNSUPPORTED_FILE,
    )
    assert dispositions["node_modules/package/index.js"] == (
        SourceArchiveEntryDisposition.IGNORE,
        SourceArchiveIgnoreReason.GENERATED_PATH,
    )
    assert set(tmp_path.iterdir()) == {archive_path}


def test_missing_non_zip_and_oversized_archives_are_rejected(tmp_path: Path) -> None:
    """Fail before entry inspection when the archive boundary is invalid."""
    missing = tmp_path / "missing.zip"
    invalid = tmp_path / "invalid.zip"
    invalid.write_bytes(b"not a zip")

    assert issue_codes(missing) == {SourceArchiveIssueCode.ARCHIVE_NOT_FOUND}
    assert issue_codes(invalid) == {SourceArchiveIssueCode.INVALID_ZIP}

    small_policy = replace(
        DEFAULT_SOURCE_ARCHIVE_POLICY,
        maximum_archive_size_bytes=8,
    )
    assert issue_codes(invalid, policy=small_policy) == {
        SourceArchiveIssueCode.ARCHIVE_TOO_LARGE
    }


def test_traversal_absolute_drive_unc_and_reserved_paths_are_rejected(tmp_path: Path) -> None:
    """Reject paths that are unsafe or ambiguous across target hosts."""
    unsafe_names = (
        "../outside.py",
        "/absolute.py",
        "C:/drive.py",
        "\\\\server\\share.py",
        "src/CON.txt",
        "src/file.py.",
        "src/name:stream.py",
        "src//double.py",
    )

    for index, unsafe_name in enumerate(unsafe_names):
        archive_path = write_zip(
            tmp_path / f"unsafe-{index}.zip",
            {unsafe_name: b"unsafe"},
        )
        assert SourceArchiveIssueCode.UNSAFE_PATH in issue_codes(archive_path)


def test_control_characters_and_portable_path_limit_are_rejected(tmp_path: Path) -> None:
    """Keep issue paths display-safe and bounded."""
    control_path = write_zip(
        tmp_path / "control.zip",
        {"src/bad\n.py": b"unsafe"},
    )
    long_path = write_zip(
        tmp_path / "long.zip",
        {f"src/{'a' * 80}.py": b"long"},
    )
    short_path_policy = replace(
        DEFAULT_SOURCE_ARCHIVE_POLICY,
        maximum_normalized_path_length=40,
    )

    assert SourceArchiveIssueCode.UNSAFE_PATH in issue_codes(control_path)
    assert issue_codes(long_path, policy=short_path_policy) == {
        SourceArchiveIssueCode.PATH_TOO_LONG
    }


def test_case_and_unicode_normalization_collisions_are_rejected(tmp_path: Path) -> None:
    """Prevent two ZIP entries from targeting one portable filesystem path."""
    case_collision = write_zip(
        tmp_path / "case.zip",
        {
            "Src/App.py": b"first",
            "src/app.py": b"second",
        },
    )
    unicode_collision = write_zip(
        tmp_path / "unicode.zip",
        {
            "src/cafe\u0301.py": b"first",
            "src/caf\u00e9.py": b"second",
        },
    )

    assert SourceArchiveIssueCode.CANONICAL_PATH_COLLISION in issue_codes(case_collision)
    assert SourceArchiveIssueCode.CANONICAL_PATH_COLLISION in issue_codes(unicode_collision)


def test_symlinks_and_special_entries_are_rejected(tmp_path: Path) -> None:
    """Do not import filesystem indirections or device-like entries."""
    archive_path = tmp_path / "links.zip"
    symlink = zipfile.ZipInfo("src/link.py")
    symlink.create_system = 3
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16

    with zipfile.ZipFile(archive_path, mode="w") as archive:
        archive.writestr(symlink, "target.py")

    assert issue_codes(archive_path) == {SourceArchiveIssueCode.UNSAFE_ENTRY_TYPE}


def test_encrypted_entry_flag_is_rejected(tmp_path: Path) -> None:
    """Reject encrypted members whose contents cannot be preflighted."""
    archive_path = write_zip(
        tmp_path / "encrypted.zip",
        {"src/app.py": b"print('hello')"},
        compression=zipfile.ZIP_STORED,
    )
    archive_bytes = bytearray(archive_path.read_bytes())

    local_header = archive_bytes.index(b"PK\x03\x04")
    local_flags = struct.unpack_from("<H", archive_bytes, local_header + 6)[0]
    struct.pack_into("<H", archive_bytes, local_header + 6, local_flags | 0x1)

    central_header = archive_bytes.index(b"PK\x01\x02")
    central_flags = struct.unpack_from("<H", archive_bytes, central_header + 8)[0]
    struct.pack_into("<H", archive_bytes, central_header + 8, central_flags | 0x1)
    archive_path.write_bytes(archive_bytes)

    assert SourceArchiveIssueCode.ENCRYPTED_ENTRY in issue_codes(archive_path)


def test_entry_total_and_compression_limits_are_enforced(tmp_path: Path) -> None:
    """Reject oversized and suspiciously compressed content before extraction."""
    archive_path = write_zip(
        tmp_path / "limits.zip",
        {
            "src/first.py": b"A" * 4096,
            "src/second.py": b"B" * 4096,
        },
    )
    policy = replace(
        DEFAULT_SOURCE_ARCHIVE_POLICY,
        maximum_entry_uncompressed_bytes=2048,
        maximum_total_uncompressed_bytes=5000,
        maximum_compression_ratio=2.0,
    )

    codes = issue_codes(archive_path, policy=policy)

    assert SourceArchiveIssueCode.ENTRY_TOO_LARGE in codes
    assert SourceArchiveIssueCode.TOTAL_UNCOMPRESSED_TOO_LARGE in codes
    assert SourceArchiveIssueCode.COMPRESSION_RATIO_EXCEEDED in codes


def test_entry_count_limit_is_enforced(tmp_path: Path) -> None:
    """Bound central-directory work before per-entry validation."""
    archive_path = write_zip(
        tmp_path / "many.zip",
        {
            "src/one.py": b"one",
            "src/two.py": b"two",
        },
    )
    policy = replace(
        DEFAULT_SOURCE_ARCHIVE_POLICY,
        maximum_entries=1,
    )

    assert issue_codes(archive_path, policy=policy) == {
        SourceArchiveIssueCode.TOO_MANY_ENTRIES
    }


def test_active_secrets_are_rejected_but_environment_templates_are_allowed(
    tmp_path: Path,
) -> None:
    """Prevent accidental credential intake without blocking safe templates."""
    secret_archive = write_zip(
        tmp_path / "secret.zip",
        {
            ".env": b"TOKEN=secret",
            "config/private.key": b"secret",
        },
    )
    template_archive = write_zip(
        tmp_path / "template.zip",
        {".env.example": b"TOKEN=replace-me"},
    )

    assert issue_codes(secret_archive) == {SourceArchiveIssueCode.SENSITIVE_FILE}

    template_report = validate_source_archive(template_archive)
    assert template_report.is_accepted
    assert template_report.entries[0].disposition is SourceArchiveEntryDisposition.INCLUDE
