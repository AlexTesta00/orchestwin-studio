"""Tests for safe JVM runtime and artifact evidence collection."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from orchestwin.jvm_execution.java_profile import JavaJvmExecutionProfile
from orchestwin.jvm_execution.runtime_artifacts import (
    JvmArtifactCollectionPolicy,
    JvmArtifactKind,
    collect_jvm_artifact_inventory,
    create_jvm_runtime_evidence,
)
from orchestwin.sandbox.evidence import (
    SandboxArtifactReference,
    SandboxCommandEvidence,
    SandboxCommandStatus,
    SandboxLogReference,
    SandboxLogStream,
)
from orchestwin.sandbox.execution_profiles import ExecutionTarget

from .profile_support import (
    declaration_for,
    runner_for,
    snapshot_for,
    source_revision_reference,
)

_RUN_ID = UUID("55555555-5555-4555-8555-555555555555")


class FakeEvidenceStore:
    def store_artifact(
        self,
        *,
        run_id: UUID,
        command_id: str,
        normalized_path: str,
        content: bytes,
        media_type: str,
    ) -> SandboxArtifactReference:
        digest = hashlib.sha256(content).hexdigest()
        return SandboxArtifactReference(
            normalized_path=normalized_path,
            sha256_digest=digest,
            size_bytes=len(content),
            storage_key=f"artifacts/{run_id}/{command_id}/{digest}",
            media_type=media_type,
        )


def _contract():
    profile = JavaJvmExecutionProfile()
    return profile.create_contract(
        snapshot_for(ExecutionTarget.JVM_JAVA),
        declaration_for(ExecutionTarget.JVM_JAVA),
        source_revision=source_revision_reference(),
        runner=runner_for(ExecutionTarget.JVM_JAVA),
    )


def _log(stream: SandboxLogStream, token: str) -> SandboxLogReference:
    content = token.encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    return SandboxLogReference(
        stream=stream,
        sha256_digest=digest,
        size_bytes=len(content),
        storage_key=f"logs/{digest}",
    )


def _command_evidence(
    *,
    command_id: str = "jvm.run.gradle",
    parser_id: str | None = "jvm.gradle",
    status: SandboxCommandStatus = SandboxCommandStatus.SUCCEEDED,
    exit_code: int | None = 0,
    failure_message: str | None = None,
) -> SandboxCommandEvidence:
    started = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    return SandboxCommandEvidence(
        command_id=command_id,
        status=status,
        started_at=started,
        finished_at=started + timedelta(seconds=2),
        exit_code=exit_code,
        stdout_log=_log(SandboxLogStream.STDOUT, "calculator-ready"),
        stderr_log=_log(SandboxLogStream.STDERR, ""),
        artifacts=(),
        output_parser_id=parser_id,
        failure_message=failure_message,
    )


def test_artifact_collector_uses_only_declared_patterns(tmp_path: Path) -> None:
    jar = tmp_path / "build/libs/sample.jar"
    xml = tmp_path / "build/test-results/test/TEST-example.CalculatorTest.xml"
    html = tmp_path / "build/reports/tests/test/index.html"
    ignored = tmp_path / "secrets.txt"
    for path, content in (
        (jar, b"jar"),
        (xml, b"<testsuite />"),
        (html, b"<html></html>"),
        (ignored, b"must-not-be-collected"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    inventory = collect_jvm_artifact_inventory(
        _contract(),
        workspace_path=tmp_path,
        run_id=_RUN_ID,
        command_id="jvm.collect",
        evidence_store=FakeEvidenceStore(),
    )

    assert [item.reference.normalized_path for item in inventory.artifacts] == [
        "build/libs/sample.jar",
        "build/reports/tests/test/index.html",
        "build/test-results/test/TEST-example.CalculatorTest.xml",
    ]
    assert [item.kind for item in inventory.artifacts] == [
        JvmArtifactKind.APPLICATION_JAR,
        JvmArtifactKind.TEST_REPORT,
        JvmArtifactKind.JUNIT_XML,
    ]
    assert "secrets.txt" not in str(inventory.to_snapshot())
    assert len(inventory.content_hash) == 64


def test_artifact_collector_rejects_symlinks_and_size_limit_violations(
    tmp_path: Path,
) -> None:
    target = tmp_path / "real.jar"
    target.write_bytes(b"jar")
    link = tmp_path / "build/libs/link.jar"
    link.parent.mkdir(parents=True)
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("symbolic links are unavailable in this test environment")

    with pytest.raises(ValueError, match="symbolic links"):
        collect_jvm_artifact_inventory(
            _contract(),
            workspace_path=tmp_path,
            run_id=_RUN_ID,
            command_id="jvm.collect",
            evidence_store=FakeEvidenceStore(),
        )

    link.unlink()
    (tmp_path / "build/libs/large.jar").write_bytes(b"x" * 5)
    with pytest.raises(ValueError, match="per-file size limit"):
        collect_jvm_artifact_inventory(
            _contract(),
            workspace_path=tmp_path,
            run_id=_RUN_ID,
            command_id="jvm.collect",
            evidence_store=FakeEvidenceStore(),
            policy=JvmArtifactCollectionPolicy(
                maximum_files=2,
                maximum_file_bytes=4,
                maximum_total_bytes=8,
            ),
        )


def test_runtime_evidence_binds_raw_logs_to_the_exact_profile_contract() -> None:
    evidence = _command_evidence()

    runtime = create_jvm_runtime_evidence(_contract(), evidence)

    assert runtime.is_successful
    assert runtime.duration_seconds == 2
    assert runtime.target is ExecutionTarget.JVM_JAVA
    assert runtime.runner_image_digest == "d" * 64
    assert runtime.command_id == "jvm.run.gradle"
    assert runtime.output_parser_id == "jvm.gradle"
    assert runtime.stdout_ref == evidence.stdout_log
    assert len(runtime.content_hash) == 64


def test_runtime_evidence_preserves_failed_process_details() -> None:
    evidence = _command_evidence(
        status=SandboxCommandStatus.FAILED,
        exit_code=1,
        failure_message="Application exited before completing the fixture scenario.",
    )

    runtime = create_jvm_runtime_evidence(_contract(), evidence)

    assert not runtime.is_successful
    assert runtime.exit_code == 1
    assert runtime.failure_message == evidence.failure_message
    assert runtime.stderr_ref == evidence.stderr_log


@pytest.mark.parametrize(
    ("command_id", "parser_id", "message"),
    [
        ("jvm.test.gradle", "jvm.gradle", "another command"),
        ("jvm.run.gradle", "jvm.sbt", "parser identity"),
    ],
)
def test_runtime_evidence_rejects_evidence_from_another_plan(
    command_id: str,
    parser_id: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        create_jvm_runtime_evidence(
            _contract(),
            _command_evidence(command_id=command_id, parser_id=parser_id),
        )
