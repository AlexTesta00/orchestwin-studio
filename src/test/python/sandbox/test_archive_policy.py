"""Tests for source archive safety policy values."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from orchestwin.sandbox.archive_policy import (
    DEFAULT_SOURCE_ARCHIVE_POLICY,
    SourceArchiveIssue,
    SourceArchiveIssueCode,
    SourceArchivePolicy,
)


def test_default_policy_matches_the_brownfield_intake_limits() -> None:
    """Keep the approved archive limits explicit and inspectable."""
    policy = DEFAULT_SOURCE_ARCHIVE_POLICY

    assert policy.maximum_archive_size_bytes == 25 * 1024 * 1024
    assert policy.maximum_total_uncompressed_bytes == 250 * 1024 * 1024
    assert policy.maximum_entry_uncompressed_bytes == 25 * 1024 * 1024
    assert policy.maximum_entries == 10_000
    assert policy.maximum_compression_ratio == 100.0
    assert policy.maximum_normalized_path_length == 240
    assert {".git", "node_modules", "build", "dist"} <= policy.ignored_directory_names
    assert {".py", ".js", ".ts", ".vue", ".php", ".java", ".kt", ".scala"} <= (
        policy.allowed_file_extensions
    )


def test_policy_is_immutable() -> None:
    """Prevent runtime code from weakening archive limits in place."""
    with pytest.raises(FrozenInstanceError):
        DEFAULT_SOURCE_ARCHIVE_POLICY.maximum_entries = 20_000  # type: ignore[misc]


def test_policy_rejects_non_positive_or_incoherent_limits() -> None:
    """Reject configurations that cannot enforce bounded intake."""
    with pytest.raises(ValueError, match="integer limits must be positive"):
        replace(
            DEFAULT_SOURCE_ARCHIVE_POLICY,
            maximum_entries=0,
        )

    with pytest.raises(ValueError, match="entry limit must not exceed total limit"):
        replace(
            DEFAULT_SOURCE_ARCHIVE_POLICY,
            maximum_entry_uncompressed_bytes=300 * 1024 * 1024,
        )

    with pytest.raises(ValueError, match="compression ratio must be at least one"):
        replace(
            DEFAULT_SOURCE_ARCHIVE_POLICY,
            maximum_compression_ratio=0.5,
        )


def test_policy_rejects_ambiguous_allowlist_tokens() -> None:
    """Keep matching rules canonical across supported host platforms."""
    with pytest.raises(ValueError, match="normalized lowercase tokens"):
        replace(
            DEFAULT_SOURCE_ARCHIVE_POLICY,
            ignored_directory_names=frozenset({"Node_Modules"}),
        )

    with pytest.raises(ValueError, match="dot-prefixed extensions"):
        replace(
            DEFAULT_SOURCE_ARCHIVE_POLICY,
            allowed_file_extensions=frozenset({"py"}),
        )


def test_validation_issue_requires_normalized_human_readable_text() -> None:
    """Return stable issue details suitable for API and UI presentation."""
    issue = SourceArchiveIssue(
        code=SourceArchiveIssueCode.UNSAFE_PATH,
        message="Archive entry leaves the workspace.",
        entry_path="../outside.py",
    )

    assert issue.code is SourceArchiveIssueCode.UNSAFE_PATH

    with pytest.raises(ValueError, match="message must be normalized"):
        SourceArchiveIssue(
            code=SourceArchiveIssueCode.UNSAFE_PATH,
            message=" Archive   entry leaves the workspace. ",
        )


def test_custom_policy_preserves_frozen_set_contracts() -> None:
    """Allow explicit safe policy variants without mutable collections."""
    policy = SourceArchivePolicy(
        maximum_archive_size_bytes=1024,
        maximum_total_uncompressed_bytes=4096,
        maximum_entry_uncompressed_bytes=2048,
        maximum_entries=10,
        maximum_compression_ratio=10.0,
        maximum_normalized_path_length=120,
        ignored_directory_names=frozenset({"build"}),
        allowed_file_extensions=frozenset({".py"}),
        allowed_file_names=frozenset({"dockerfile"}),
        sensitive_file_names=frozenset({"id_rsa"}),
        sensitive_file_suffixes=frozenset({".key"}),
        environment_template_suffixes=frozenset({".example"}),
    )

    assert policy.allowed_file_extensions == frozenset({".py"})
