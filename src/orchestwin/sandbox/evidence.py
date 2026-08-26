"""Immutable sandbox run, raw-log, and artifact evidence models."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from itertools import pairwise
from pathlib import PurePosixPath
from typing import Final, Protocol
from uuid import UUID

from orchestwin.sandbox.command_plans import CommandPlan

_IDENTIFIER_PATTERN: Final = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)*$")
_SANDBOX_EVIDENCE_SCHEMA_VERSION: Final = 1


class SandboxLogStream(StrEnum):
    """Raw process streams retained as separate content references."""

    STDOUT = "STDOUT"
    STDERR = "STDERR"


class SandboxCommandStatus(StrEnum):
    """Terminal outcome of one structured command invocation."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    RESOURCE_LIMIT_EXCEEDED = "RESOURCE_LIMIT_EXCEEDED"
    CANCELLED = "CANCELLED"
    RUNTIME_ERROR = "RUNTIME_ERROR"


class SandboxRunStatus(StrEnum):
    """Terminal outcome of one immutable command-plan execution."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    RESOURCE_LIMIT_EXCEEDED = "RESOURCE_LIMIT_EXCEEDED"
    CANCELLED = "CANCELLED"
    RUNTIME_ERROR = "RUNTIME_ERROR"


@dataclass(frozen=True, slots=True)
class SandboxLogReference:
    """Content-addressed reference to one complete raw process stream."""

    stream: SandboxLogStream
    sha256_digest: str
    size_bytes: int
    storage_key: str

    def __post_init__(self) -> None:
        """Protect digest, size, and storage-key metadata."""
        _validate_sha256(self.sha256_digest, label="sandbox log digest")
        _validate_non_negative_size(self.size_bytes, label="sandbox log size")
        _validate_storage_key(self.storage_key, label="sandbox log storage key")

    def to_snapshot(self) -> dict[str, object]:
        """Return metadata only; raw content remains in the evidence store."""
        return {
            "stream": self.stream.value,
            "sha256_digest": self.sha256_digest,
            "size_bytes": self.size_bytes,
            "storage_key": self.storage_key,
        }


@dataclass(frozen=True, slots=True)
class SandboxArtifactReference:
    """Content-addressed reference to one collected workspace artifact."""

    normalized_path: str
    sha256_digest: str
    size_bytes: int
    storage_key: str
    media_type: str

    def __post_init__(self) -> None:
        """Protect workspace-relative and content-addressed artifact metadata."""
        _validate_relative_path(self.normalized_path, label="sandbox artifact path")
        _validate_sha256(self.sha256_digest, label="sandbox artifact digest")
        _validate_non_negative_size(self.size_bytes, label="sandbox artifact size")
        _validate_storage_key(self.storage_key, label="sandbox artifact storage key")
        _validate_normalized_text(self.media_type, label="sandbox artifact media type")

    def to_snapshot(self) -> dict[str, object]:
        """Return stable artifact metadata without exposing host paths."""
        return {
            "normalized_path": self.normalized_path,
            "sha256_digest": self.sha256_digest,
            "size_bytes": self.size_bytes,
            "storage_key": self.storage_key,
            "media_type": self.media_type,
        }


@dataclass(frozen=True, slots=True)
class SandboxCommandEvidence:
    """Complete terminal evidence for one structured command."""

    command_id: str
    status: SandboxCommandStatus
    started_at: datetime
    finished_at: datetime
    exit_code: int | None
    stdout_log: SandboxLogReference
    stderr_log: SandboxLogReference
    artifacts: tuple[SandboxArtifactReference, ...]
    output_parser_id: str | None
    failure_message: str | None

    def __post_init__(self) -> None:
        """Protect terminal shapes, timestamps, logs, and artifact uniqueness."""
        _validate_identifier(self.command_id, label="sandbox evidence command ID")
        _validate_time_range(self.started_at, self.finished_at)

        if self.stdout_log.stream is not SandboxLogStream.STDOUT:
            raise ValueError("sandbox command stdout reference has the wrong stream")
        if self.stderr_log.stream is not SandboxLogStream.STDERR:
            raise ValueError("sandbox command stderr reference has the wrong stream")

        artifact_paths = tuple(artifact.normalized_path for artifact in self.artifacts)
        if len(artifact_paths) != len(set(artifact_paths)):
            raise ValueError("sandbox command artifact paths must be unique")

        if self.output_parser_id is not None:
            _validate_identifier(self.output_parser_id, label="sandbox output parser ID")

        if self.failure_message is not None:
            _validate_normalized_text(
                self.failure_message,
                label="sandbox command failure message",
            )

        if self.status is SandboxCommandStatus.SUCCEEDED:
            if self.exit_code is None or self.failure_message is not None:
                raise ValueError(
                    "successful sandbox command requires an exit code and no failure message"
                )
        elif self.status is SandboxCommandStatus.FAILED:
            if self.exit_code is None or self.failure_message is None:
                raise ValueError("failed sandbox command requires an exit code and failure message")
        elif self.exit_code is not None or self.failure_message is None:
            raise ValueError("non-process sandbox command failure requires only a failure message")

        if self.exit_code is not None and (
            isinstance(self.exit_code, bool) or not 0 <= self.exit_code <= 255
        ):
            raise ValueError("sandbox command exit code must be from zero to 255")

    @property
    def duration_seconds(self) -> float:
        """Return measured wall-clock duration for reporting."""
        return (self.finished_at - self.started_at).total_seconds()

    def to_snapshot(self) -> dict[str, object]:
        """Return deterministic command evidence including raw-log references."""
        return {
            "command_id": self.command_id,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "duration_seconds": self.duration_seconds,
            "exit_code": self.exit_code,
            "stdout_log": self.stdout_log.to_snapshot(),
            "stderr_log": self.stderr_log.to_snapshot(),
            "artifacts": [artifact.to_snapshot() for artifact in self.artifacts],
            "output_parser_id": self.output_parser_id,
            "failure_message": self.failure_message,
        }


@dataclass(frozen=True, slots=True)
class SandboxRunEvidence:
    """Terminal evidence bound to one exact plan, profile, image, and runtime."""

    run_id: UUID
    plan_id: str
    plan_content_hash: str
    profile_id: str
    profile_version: str
    image_reference: str
    runtime_reference: str
    status: SandboxRunStatus
    started_at: datetime
    finished_at: datetime
    planned_command_ids: tuple[str, ...]
    command_evidence: tuple[SandboxCommandEvidence, ...]
    failure_message: str | None
    schema_version: int = _SANDBOX_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Protect exact-plan binding and sequential terminal evidence."""
        if self.schema_version != _SANDBOX_EVIDENCE_SCHEMA_VERSION:
            raise ValueError("unsupported sandbox evidence schema version")

        _validate_identifier(self.plan_id, label="sandbox evidence plan ID")
        _validate_sha256(self.plan_content_hash, label="sandbox evidence plan hash")
        _validate_identifier(self.profile_id, label="sandbox evidence profile ID")
        _validate_normalized_text(
            self.profile_version,
            label="sandbox evidence profile version",
        )
        _validate_normalized_text(
            self.image_reference,
            label="sandbox evidence image reference",
        )
        _validate_normalized_text(
            self.runtime_reference,
            label="sandbox evidence runtime reference",
        )
        _validate_time_range(self.started_at, self.finished_at)

        if not self.planned_command_ids:
            raise ValueError("sandbox run must reference at least one planned command")
        for command_id in self.planned_command_ids:
            _validate_identifier(command_id, label="sandbox planned command ID")
        if len(self.planned_command_ids) != len(set(self.planned_command_ids)):
            raise ValueError("sandbox planned command IDs must be unique")

        evidence_ids = tuple(evidence.command_id for evidence in self.command_evidence)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("sandbox command evidence IDs must be unique")
        if evidence_ids != self.planned_command_ids[: len(evidence_ids)]:
            raise ValueError("sandbox command evidence must be a sequential plan prefix")

        if any(
            evidence.started_at < self.started_at or evidence.finished_at > self.finished_at
            for evidence in self.command_evidence
        ):
            raise ValueError("sandbox command evidence must stay inside the run time range")
        if any(
            current.started_at < previous.finished_at
            for previous, current in pairwise(self.command_evidence)
        ):
            raise ValueError("sandbox command evidence time ranges must be sequential")

        if self.failure_message is not None:
            _validate_normalized_text(
                self.failure_message,
                label="sandbox run failure message",
            )

        if self.status is SandboxRunStatus.SUCCEEDED:
            if (
                evidence_ids != self.planned_command_ids
                or not self.command_evidence
                or any(
                    evidence.status is not SandboxCommandStatus.SUCCEEDED
                    for evidence in self.command_evidence
                )
                or self.failure_message is not None
            ):
                raise ValueError(
                    "successful sandbox run requires all commands and no failure message"
                )
        else:
            if self.failure_message is None:
                raise ValueError("failed sandbox run requires a failure message")
            _validate_terminal_status_alignment(
                self.status,
                command_evidence=self.command_evidence,
            )

    @property
    def duration_seconds(self) -> float:
        """Return measured wall-clock duration for reporting."""
        return (self.finished_at - self.started_at).total_seconds()

    def to_snapshot(self) -> dict[str, object]:
        """Return deterministic evidence metadata without raw content."""
        return {
            "schema_version": self.schema_version,
            "run_id": str(self.run_id),
            "plan_id": self.plan_id,
            "plan_content_hash": self.plan_content_hash,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "image_reference": self.image_reference,
            "runtime_reference": self.runtime_reference,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "duration_seconds": self.duration_seconds,
            "planned_command_ids": list(self.planned_command_ids),
            "command_evidence": [evidence.to_snapshot() for evidence in self.command_evidence],
            "failure_message": self.failure_message,
        }


class SandboxEvidenceStore(Protocol):
    """Port for retaining raw logs and collected files behind safe references."""

    def store_log(
        self,
        *,
        run_id: UUID,
        command_id: str,
        stream: SandboxLogStream,
        content: bytes,
    ) -> SandboxLogReference:
        """Store one complete raw stream and return its immutable reference."""
        ...

    def store_artifact(
        self,
        *,
        run_id: UUID,
        command_id: str,
        normalized_path: str,
        content: bytes,
        media_type: str,
    ) -> SandboxArtifactReference:
        """Store one collected file and return its immutable reference."""
        ...


def create_sandbox_run_evidence(
    *,
    run_id: UUID,
    plan: CommandPlan,
    image_reference: str,
    runtime_reference: str,
    started_at: datetime,
    finished_at: datetime,
    command_evidence: tuple[SandboxCommandEvidence, ...],
    failure_message: str | None = None,
) -> SandboxRunEvidence:
    """Derive a run outcome from ordered command evidence without false success."""
    planned_command_ids = tuple(command.command_id for command in plan.commands)
    for index, evidence in enumerate(command_evidence):
        if index >= len(plan.commands):
            break
        command = plan.commands[index]
        if (
            evidence.status is SandboxCommandStatus.SUCCEEDED
            and evidence.exit_code not in command.expected_exit_codes
        ):
            raise ValueError("successful command evidence contradicts expected exit codes")
        if evidence.output_parser_id != command.output_parser_id:
            raise ValueError("command evidence output parser does not match the plan")

    status = _derive_run_status(
        planned_command_ids=planned_command_ids,
        command_evidence=command_evidence,
    )

    resolved_failure = failure_message
    if status is not SandboxRunStatus.SUCCEEDED and resolved_failure is None:
        if command_evidence and command_evidence[-1].failure_message is not None:
            resolved_failure = command_evidence[-1].failure_message
        else:
            resolved_failure = "Sandbox runtime stopped before completing the command plan."

    return SandboxRunEvidence(
        run_id=run_id,
        plan_id=plan.plan_id,
        plan_content_hash=plan.content_hash,
        profile_id=plan.profile_id,
        profile_version=plan.profile_version,
        image_reference=image_reference,
        runtime_reference=runtime_reference,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        planned_command_ids=planned_command_ids,
        command_evidence=command_evidence,
        failure_message=resolved_failure,
    )


def _derive_run_status(
    *,
    planned_command_ids: tuple[str, ...],
    command_evidence: tuple[SandboxCommandEvidence, ...],
) -> SandboxRunStatus:
    """Map the final observed command state to one honest run outcome."""
    evidence_ids = tuple(evidence.command_id for evidence in command_evidence)
    if (
        evidence_ids == planned_command_ids
        and command_evidence
        and all(evidence.status is SandboxCommandStatus.SUCCEEDED for evidence in command_evidence)
    ):
        return SandboxRunStatus.SUCCEEDED

    if not command_evidence:
        return SandboxRunStatus.RUNTIME_ERROR

    return {
        SandboxCommandStatus.SUCCEEDED: SandboxRunStatus.RUNTIME_ERROR,
        SandboxCommandStatus.FAILED: SandboxRunStatus.FAILED,
        SandboxCommandStatus.TIMED_OUT: SandboxRunStatus.TIMED_OUT,
        SandboxCommandStatus.RESOURCE_LIMIT_EXCEEDED: (SandboxRunStatus.RESOURCE_LIMIT_EXCEEDED),
        SandboxCommandStatus.CANCELLED: SandboxRunStatus.CANCELLED,
        SandboxCommandStatus.RUNTIME_ERROR: SandboxRunStatus.RUNTIME_ERROR,
    }[command_evidence[-1].status]


def _validate_terminal_status_alignment(
    status: SandboxRunStatus,
    *,
    command_evidence: tuple[SandboxCommandEvidence, ...],
) -> None:
    """Prevent run status from contradicting its final command evidence."""
    if not command_evidence:
        if status is not SandboxRunStatus.RUNTIME_ERROR:
            raise ValueError("sandbox run without commands must be a runtime error")
        return

    expected_run_status = {
        SandboxCommandStatus.SUCCEEDED: SandboxRunStatus.RUNTIME_ERROR,
        SandboxCommandStatus.FAILED: SandboxRunStatus.FAILED,
        SandboxCommandStatus.TIMED_OUT: SandboxRunStatus.TIMED_OUT,
        SandboxCommandStatus.RESOURCE_LIMIT_EXCEEDED: (SandboxRunStatus.RESOURCE_LIMIT_EXCEEDED),
        SandboxCommandStatus.CANCELLED: SandboxRunStatus.CANCELLED,
        SandboxCommandStatus.RUNTIME_ERROR: SandboxRunStatus.RUNTIME_ERROR,
    }[command_evidence[-1].status]
    if status is not expected_run_status:
        raise ValueError("sandbox run status contradicts final command evidence")


def _validate_identifier(value: str, *, label: str) -> None:
    """Require the same stable portable identifiers as command plans."""
    if not _IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must be a normalized portable identifier")


def _validate_sha256(value: str, *, label: str) -> None:
    """Require one lowercase hexadecimal SHA-256 digest."""
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} must be lowercase SHA-256")


def _validate_non_negative_size(value: int, *, label: str) -> None:
    """Require a byte count rather than a boolean or negative value."""
    if isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must not be negative")


def _validate_normalized_text(value: str, *, label: str) -> None:
    """Require compact human- or machine-readable metadata."""
    if (
        not value
        or value != value.strip()
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        raise ValueError(f"{label} must be normalized")


def _validate_relative_path(value: str, *, label: str) -> None:
    """Require a canonical POSIX path inside the workspace namespace."""
    if (
        not value
        or value != value.strip()
        or "\\" in value
        or value.startswith("/")
        or ":" in value
    ):
        raise ValueError(f"{label} must be a relative POSIX path")

    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{label} must stay inside the workspace")
    if PurePosixPath(value).as_posix() != value:
        raise ValueError(f"{label} must be canonical")


def _validate_storage_key(value: str, *, label: str) -> None:
    """Require an adapter-relative storage key with no traversal."""
    _validate_relative_path(value, label=label)


def _validate_time_range(started_at: datetime, finished_at: datetime) -> None:
    """Require UTC-aware monotonic evidence timestamps."""
    if started_at.tzinfo is None or started_at.utcoffset() != UTC.utcoffset(started_at):
        raise ValueError("sandbox evidence start time must be UTC-aware")
    if finished_at.tzinfo is None or finished_at.utcoffset() != UTC.utcoffset(finished_at):
        raise ValueError("sandbox evidence finish time must be UTC-aware")
    if finished_at < started_at:
        raise ValueError("sandbox evidence finish time must not precede start time")
