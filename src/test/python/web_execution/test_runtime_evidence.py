"""Tests for bounded health checks, runtime evidence, and artifact collection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from orchestwin.web_execution.reports import WebEvidenceReference
from orchestwin.web_execution.runtime_evidence import (
    WebArtifactCollectionIssueCode,
    WebArtifactCollectionPolicy,
    WebArtifactCollectionStatus,
    WebHealthCheckAttempt,
    WebHealthCheckResult,
    WebHealthCheckSpec,
    WebHealthCheckStatus,
    WebRuntimeEvidence,
    WebRuntimeProcessEvidence,
    collect_web_artifacts,
)

OBSERVED_AT = datetime(2026, 8, 26, 15, 0, tzinfo=UTC)


def evidence(key: str, character: str) -> WebEvidenceReference:
    return WebEvidenceReference(
        storage_key=key,
        sha256_digest=character * 64,
        size_bytes=4,
        media_type="text/plain",
    )


def health_spec() -> WebHealthCheckSpec:
    return WebHealthCheckSpec(
        check_id="frontend.root",
        host="127.0.0.1",
        port=4173,
        path="/",
        expected_status_codes=(200, 204),
        request_timeout_seconds=2,
        maximum_attempts=5,
        interval_milliseconds=250,
    )


def test_health_checks_reject_external_hosts_and_require_terminal_consistency() -> None:
    with pytest.raises(ValueError, match="loopback hosts"):
        WebHealthCheckSpec(
            check_id="external",
            host="example.com",
            port=443,
            path="/",
            expected_status_codes=(200,),
            request_timeout_seconds=2,
            maximum_attempts=2,
            interval_milliseconds=100,
        )

    result = WebHealthCheckResult(
        spec=health_spec(),
        status=WebHealthCheckStatus.HEALTHY,
        attempts=(
            WebHealthCheckAttempt(
                attempt_number=1,
                observed_at=OBSERVED_AT,
                latency_milliseconds=12,
                status_code=200,
                error_code=None,
            ),
        ),
    )

    assert result.status is WebHealthCheckStatus.HEALTHY
    assert len(result.spec.content_hash) == 64


def test_artifact_collection_hashes_regular_files_in_canonical_order(tmp_path: Path) -> None:
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "index.html").write_text("ready", encoding="utf-8")
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "test.json").write_text("{}", encoding="utf-8")

    result = collect_web_artifacts(
        tmp_path,
        patterns=("dist/**", "reports/**"),
    )

    assert result.status is WebArtifactCollectionStatus.COLLECTED
    assert tuple(artifact.normalized_path for artifact in result.artifacts) == (
        "dist/index.html",
        "reports/test.json",
    )
    assert all(len(artifact.sha256_digest) == 64 for artifact in result.artifacts)


def test_artifact_collection_rejects_symlinks_without_following_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "dist").mkdir()
    target = tmp_path / "dist" / "target.txt"
    target.write_text("safe", encoding="utf-8")
    link = tmp_path / "dist" / "link.txt"
    link.write_text("placeholder", encoding="utf-8")
    original_is_symlink = Path.is_symlink

    def simulated_is_symlink(path: Path) -> bool:
        return path == link or original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", simulated_is_symlink)

    result = collect_web_artifacts(tmp_path, patterns=("dist/**",))

    assert result.status is WebArtifactCollectionStatus.REJECTED
    assert {issue.code for issue in result.issues} == {
        WebArtifactCollectionIssueCode.SYMLINK_FORBIDDEN
    }
    assert tuple(artifact.normalized_path for artifact in result.artifacts) == ("dist/target.txt",)


def test_artifact_collection_pauses_at_explicit_resource_limits(tmp_path: Path) -> None:
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "large.bin").write_bytes(b"12345")

    result = collect_web_artifacts(
        tmp_path,
        patterns=("dist/**",),
        policy=WebArtifactCollectionPolicy(
            maximum_files=2,
            maximum_file_size_bytes=4,
            maximum_total_size_bytes=8,
        ),
    )

    assert result.status is WebArtifactCollectionStatus.LIMIT_EXCEEDED
    assert result.issues[0].code is WebArtifactCollectionIssueCode.FILE_TOO_LARGE


def test_runtime_evidence_binds_process_health_and_artifacts() -> None:
    process = WebRuntimeProcessEvidence(
        process_id="frontend",
        command_plan_hash="a" * 64,
        started_at=OBSERVED_AT,
        completed_at=OBSERVED_AT + timedelta(seconds=1),
        exit_code=0,
        terminated_by_controller=True,
        stdout_ref=evidence("logs/frontend.stdout", "b"),
        stderr_ref=evidence("logs/frontend.stderr", "c"),
    )
    health = WebHealthCheckResult(
        spec=health_spec(),
        status=WebHealthCheckStatus.HEALTHY,
        attempts=(
            WebHealthCheckAttempt(
                attempt_number=1,
                observed_at=OBSERVED_AT,
                latency_milliseconds=10,
                status_code=200,
                error_code=None,
            ),
        ),
    )
    empty_collection = collect_web_artifacts(
        Path.cwd(),
        patterns=("this-path-does-not-exist/**",),
    )

    runtime = WebRuntimeEvidence(
        source_revision_content_hash="d" * 64,
        source_tree_hash="e" * 64,
        runner_image_digest="f" * 64,
        processes=(process,),
        health_results=(health,),
        artifact_collection=empty_collection,
    )

    assert empty_collection.status is WebArtifactCollectionStatus.COLLECTED
    assert len(runtime.content_hash) == 64
