"""Safe JVM runtime observations and content-addressed artifact collection."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Final
from uuid import UUID

from orchestwin.jvm_execution.plans import JvmExecutionPhase
from orchestwin.jvm_execution.profile_contracts import JvmProfileContract
from orchestwin.sandbox.evidence import (
    SandboxArtifactReference,
    SandboxCommandEvidence,
    SandboxCommandStatus,
    SandboxEvidenceStore,
    SandboxLogReference,
)
from orchestwin.sandbox.execution_profiles import ExecutionTarget

_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_JVM_TARGETS: Final = frozenset(
    {
        ExecutionTarget.JVM_JAVA,
        ExecutionTarget.JVM_KOTLIN,
        ExecutionTarget.JVM_SCALA,
    }
)


class JvmArtifactKind(StrEnum):
    """Portable JVM artifact categories retained for API and thesis evidence."""

    APPLICATION_JAR = "APPLICATION_JAR"
    JUNIT_XML = "JUNIT_XML"
    TEST_REPORT = "TEST_REPORT"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class JvmArtifactCollectionPolicy:
    """Bounded filesystem limits for one artifact collection operation."""

    maximum_files: int = 128
    maximum_file_bytes: int = 16 * 1024 * 1024
    maximum_total_bytes: int = 64 * 1024 * 1024

    def __post_init__(self) -> None:
        values = (self.maximum_files, self.maximum_file_bytes, self.maximum_total_bytes)
        if any(isinstance(value, bool) or value < 1 for value in values):
            raise ValueError("JVM artifact collection limits must be positive integers")
        if self.maximum_file_bytes > self.maximum_total_bytes:
            raise ValueError("JVM artifact file limit must not exceed the total limit")


@dataclass(frozen=True, slots=True, order=True)
class JvmCollectedArtifact:
    """One content-addressed artifact with a normalized semantic kind."""

    kind: JvmArtifactKind
    reference: SandboxArtifactReference

    def to_snapshot(self) -> dict[str, object]:
        return {"kind": self.kind.value, "reference": self.reference.to_snapshot()}


@dataclass(frozen=True, slots=True)
class JvmArtifactInventory:
    """Exact artifact inventory bound to source, plan, target, and runner digest."""

    target: ExecutionTarget
    source_revision_content_hash: str
    execution_plan_content_hash: str
    runner_image_digest: str
    artifacts: tuple[JvmCollectedArtifact, ...]

    def __post_init__(self) -> None:
        if self.target not in _JVM_TARGETS:
            raise ValueError("JVM artifact inventory requires a Sprint 09 JVM target")
        _validate_sha256(
            self.source_revision_content_hash,
            label="JVM artifact source revision hash",
        )
        _validate_sha256(
            self.execution_plan_content_hash,
            label="JVM artifact execution plan hash",
        )
        _validate_sha256(self.runner_image_digest, label="JVM artifact runner digest")
        ordered = tuple(sorted(self.artifacts, key=lambda item: item.reference.normalized_path))
        if self.artifacts != ordered:
            raise ValueError("JVM artifacts must use canonical path order")
        paths = tuple(item.reference.normalized_path for item in self.artifacts)
        if len(paths) != len(set(paths)):
            raise ValueError("JVM artifacts must have unique normalized paths")
        if not self.artifacts:
            raise ValueError("JVM artifact inventory requires collected files")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self._content_snapshot())).hexdigest()

    def to_snapshot(self) -> dict[str, object]:
        return {**self._content_snapshot(), "content_hash": self.content_hash}

    def _content_snapshot(self) -> dict[str, object]:
        return {
            "target": self.target.value,
            "source_revision_content_hash": self.source_revision_content_hash,
            "execution_plan_content_hash": self.execution_plan_content_hash,
            "runner_image_digest": self.runner_image_digest,
            "artifacts": [artifact.to_snapshot() for artifact in self.artifacts],
        }


@dataclass(frozen=True, slots=True)
class JvmRuntimeEvidence:
    """Run-phase observation retaining exact raw stdout and stderr references."""

    target: ExecutionTarget
    source_revision_content_hash: str
    execution_plan_content_hash: str
    run_command_plan_hash: str
    runner_image_digest: str
    command_id: str
    output_parser_id: str | None
    status: SandboxCommandStatus
    exit_code: int | None
    stdout_ref: SandboxLogReference
    stderr_ref: SandboxLogReference
    started_at: datetime
    finished_at: datetime
    failure_message: str | None

    def __post_init__(self) -> None:
        if self.target not in _JVM_TARGETS:
            raise ValueError("JVM runtime evidence requires a Sprint 09 JVM target")
        for value, label in (
            (self.source_revision_content_hash, "JVM runtime source revision hash"),
            (self.execution_plan_content_hash, "JVM runtime execution plan hash"),
            (self.run_command_plan_hash, "JVM runtime command plan hash"),
            (self.runner_image_digest, "JVM runtime runner digest"),
        ):
            _validate_sha256(value, label=label)
        if not self.command_id or self.command_id != self.command_id.strip():
            raise ValueError("JVM runtime command ID must be normalized")
        if self.output_parser_id is not None and (
            not self.output_parser_id or self.output_parser_id != self.output_parser_id.strip()
        ):
            raise ValueError("JVM runtime output parser ID must be normalized")
        if self.finished_at < self.started_at:
            raise ValueError("JVM runtime completion cannot precede its start")
        if self.status is SandboxCommandStatus.SUCCEEDED:
            if self.exit_code != 0 or self.failure_message is not None:
                raise ValueError(
                    "successful JVM runtime evidence requires exit code zero and no failure"
                )
        elif self.failure_message is None:
            raise ValueError("failed JVM runtime evidence requires a failure message")
        if self.exit_code is not None and (
            isinstance(self.exit_code, bool) or not 0 <= self.exit_code <= 255
        ):
            raise ValueError("JVM runtime exit code must be from zero to 255")

    @property
    def duration_seconds(self) -> float:
        duration = (self.finished_at - self.started_at).total_seconds()
        if not math.isfinite(duration):
            raise ValueError("JVM runtime duration must be finite")
        return duration

    @property
    def is_successful(self) -> bool:
        return self.status is SandboxCommandStatus.SUCCEEDED

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_snapshot())).hexdigest()

    def to_snapshot(self) -> dict[str, object]:
        return {
            "target": self.target.value,
            "source_revision_content_hash": self.source_revision_content_hash,
            "execution_plan_content_hash": self.execution_plan_content_hash,
            "run_command_plan_hash": self.run_command_plan_hash,
            "runner_image_digest": self.runner_image_digest,
            "command_id": self.command_id,
            "output_parser_id": self.output_parser_id,
            "status": self.status.value,
            "exit_code": self.exit_code,
            "stdout_ref": self.stdout_ref.to_snapshot(),
            "stderr_ref": self.stderr_ref.to_snapshot(),
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "duration_seconds": self.duration_seconds,
            "failure_message": self.failure_message,
        }


def collect_jvm_artifact_inventory(
    contract: JvmProfileContract,
    *,
    workspace_path: Path,
    run_id: UUID,
    command_id: str,
    evidence_store: SandboxEvidenceStore,
    policy: JvmArtifactCollectionPolicy | None = None,
) -> JvmArtifactInventory:
    """Collect only files matching artifact patterns declared by the profile plan."""
    if policy is None:
        policy = JvmArtifactCollectionPolicy()
    workspace = Path(workspace_path)
    if not workspace.is_absolute() or workspace.is_symlink() or not workspace.is_dir():
        raise ValueError("JVM artifact workspace must be an absolute regular directory")
    if not command_id or command_id != command_id.strip():
        raise ValueError("JVM artifact collection command ID must be normalized")

    workspace_resolved = workspace.resolve(strict=True)
    candidates: dict[str, Path] = {}
    for pattern in _artifact_patterns(contract):
        for candidate in workspace.glob(pattern):
            if candidate.is_dir():
                continue
            _reject_unsafe_artifact_path(workspace, workspace_resolved, candidate)
            relative = candidate.relative_to(workspace).as_posix()
            candidates[relative] = candidate

    if not candidates:
        raise ValueError("JVM artifact collection found no declared files")
    if len(candidates) > policy.maximum_files:
        raise ValueError("JVM artifact collection exceeds the file-count limit")

    total_bytes = 0
    collected: list[JvmCollectedArtifact] = []
    for relative, candidate in sorted(candidates.items()):
        try:
            content = candidate.read_bytes()
        except OSError as error:
            raise ValueError("JVM artifact file could not be read") from error
        if len(content) > policy.maximum_file_bytes:
            raise ValueError("JVM artifact exceeds the per-file size limit")
        total_bytes += len(content)
        if total_bytes > policy.maximum_total_bytes:
            raise ValueError("JVM artifacts exceed the aggregate size limit")
        reference = evidence_store.store_artifact(
            run_id=run_id,
            command_id=command_id,
            normalized_path=relative,
            content=content,
            media_type=_media_type(relative),
        )
        collected.append(JvmCollectedArtifact(kind=_artifact_kind(relative), reference=reference))

    return JvmArtifactInventory(
        target=contract.validation.target,
        source_revision_content_hash=contract.source_revision.content_hash,
        execution_plan_content_hash=contract.execution_plan.content_hash,
        runner_image_digest=contract.runner.image.digest,
        artifacts=tuple(collected),
    )


def create_jvm_runtime_evidence(
    contract: JvmProfileContract,
    command_evidence: SandboxCommandEvidence,
) -> JvmRuntimeEvidence:
    """Bind run-command evidence to the exact source, plan, and runner identity."""
    run_phase = contract.execution_plan.phase(JvmExecutionPhase.RUN)
    command_plan = run_phase.command_plan
    if len(command_plan.commands) != 1:
        raise ValueError("JVM runtime phase requires exactly one planned command")
    expected_command = command_plan.commands[0]
    if command_evidence.command_id != expected_command.command_id:
        raise ValueError("JVM runtime command evidence targets another command")
    if command_evidence.output_parser_id != expected_command.output_parser_id:
        raise ValueError("JVM runtime parser identity differs from the execution plan")
    if command_evidence.status is SandboxCommandStatus.SUCCEEDED and (
        command_evidence.exit_code not in expected_command.expected_exit_codes
    ):
        raise ValueError("successful JVM runtime evidence contradicts expected exit codes")
    return JvmRuntimeEvidence(
        target=contract.validation.target,
        source_revision_content_hash=contract.source_revision.content_hash,
        execution_plan_content_hash=contract.execution_plan.content_hash,
        run_command_plan_hash=command_plan.content_hash,
        runner_image_digest=contract.runner.image.digest,
        command_id=command_evidence.command_id,
        output_parser_id=command_evidence.output_parser_id,
        status=command_evidence.status,
        exit_code=command_evidence.exit_code,
        stdout_ref=command_evidence.stdout_log,
        stderr_ref=command_evidence.stderr_log,
        started_at=command_evidence.started_at,
        finished_at=command_evidence.finished_at,
        failure_message=command_evidence.failure_message,
    )


def _artifact_patterns(contract: JvmProfileContract) -> tuple[str, ...]:
    patterns = {
        pattern
        for phase in (
            JvmExecutionPhase.BUILD,
            JvmExecutionPhase.TEST,
            JvmExecutionPhase.COLLECT_ARTIFACTS,
        )
        for command in contract.execution_plan.phase(phase).command_plan.commands
        for pattern in command.artifact_patterns
    }
    if not patterns:
        raise ValueError("JVM profile plan declares no artifact patterns")
    return tuple(sorted(patterns))


def _reject_unsafe_artifact_path(
    workspace: Path,
    workspace_resolved: Path,
    candidate: Path,
) -> None:
    current = candidate
    while current != workspace:
        if current.is_symlink():
            raise ValueError("JVM artifact collection rejects symbolic links")
        if workspace not in current.parents:
            raise ValueError("JVM artifact escaped the workspace")
        current = current.parent
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise ValueError("JVM artifact path could not be resolved") from error
    if resolved != workspace_resolved and workspace_resolved not in resolved.parents:
        raise ValueError("JVM artifact escaped the workspace")
    if not resolved.is_file():
        raise ValueError("JVM artifact collection requires regular files")


def _artifact_kind(path: str) -> JvmArtifactKind:
    lowered = path.casefold()
    if lowered.endswith(".jar"):
        return JvmArtifactKind.APPLICATION_JAR
    if lowered.endswith(".xml") and (
        "/test-results/" in f"/{lowered}" or "/test-reports/" in f"/{lowered}"
    ):
        return JvmArtifactKind.JUNIT_XML
    if "/reports/" in f"/{lowered}" or lowered.endswith((".html", ".css", ".js")):
        return JvmArtifactKind.TEST_REPORT
    return JvmArtifactKind.OTHER


def _media_type(path: str) -> str:
    lowered = path.casefold()
    if lowered.endswith(".jar"):
        return "application/java-archive"
    if lowered.endswith(".xml"):
        return "application/xml"
    if lowered.endswith(".html"):
        return "text/html"
    if lowered.endswith(".css"):
        return "text/css"
    if lowered.endswith(".js"):
        return "text/javascript"
    return "application/octet-stream"


def _validate_sha256(value: str, *, label: str) -> None:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase SHA-256")


def _canonical_json(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
