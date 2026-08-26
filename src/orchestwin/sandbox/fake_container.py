"""Deterministic in-memory container runtime for ordinary tests and CI."""

from __future__ import annotations

import fnmatch
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import PurePosixPath
from types import MappingProxyType
from uuid import UUID

from orchestwin.sandbox.command_plans import StructuredCommand
from orchestwin.sandbox.container_runtime import (
    ContainerExecutionRequest,
    ContainerRuntimePort,
)
from orchestwin.sandbox.evidence import (
    SandboxArtifactReference,
    SandboxCommandEvidence,
    SandboxCommandStatus,
    SandboxEvidenceStore,
    SandboxLogReference,
    SandboxLogStream,
    SandboxRunEvidence,
    create_sandbox_run_evidence,
)


class FakeCommandOutcomeKind(StrEnum):
    """Deterministic boundary outcomes configurable without launching a process."""

    PROCESS_EXIT = "PROCESS_EXIT"
    TIMED_OUT = "TIMED_OUT"
    RESOURCE_LIMIT_EXCEEDED = "RESOURCE_LIMIT_EXCEEDED"
    CANCELLED = "CANCELLED"
    RUNTIME_ERROR = "RUNTIME_ERROR"


@dataclass(frozen=True, slots=True)
class FakeArtifactOutput:
    """Raw fake artifact content retained through the evidence-store port."""

    normalized_path: str
    content: bytes
    media_type: str

    def __post_init__(self) -> None:
        """Reject invalid fake fixture metadata before execution."""
        _validate_relative_path(self.normalized_path)
        if not isinstance(self.content, bytes):
            raise TypeError("fake artifact content must be bytes")
        if not self.media_type or self.media_type != self.media_type.strip():
            raise ValueError("fake artifact media type must be normalized")


@dataclass(frozen=True, slots=True)
class FakeCommandOutcome:
    """One deterministic process or runtime result for a command ID."""

    kind: FakeCommandOutcomeKind
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    duration: timedelta
    artifacts: tuple[FakeArtifactOutput, ...]
    failure_message: str | None

    def __post_init__(self) -> None:
        """Protect process and non-process fixture shapes."""
        if not isinstance(self.stdout, bytes) or not isinstance(self.stderr, bytes):
            raise TypeError("fake command streams must be bytes")
        if self.duration < timedelta(0):
            raise ValueError("fake command duration must not be negative")

        artifact_paths = tuple(artifact.normalized_path for artifact in self.artifacts)
        if len(artifact_paths) != len(set(artifact_paths)):
            raise ValueError("fake artifact paths must be unique")

        if self.failure_message is not None and (
            not self.failure_message
            or self.failure_message != " ".join(self.failure_message.split())
        ):
            raise ValueError("fake command failure message must be normalized")

        if self.kind is FakeCommandOutcomeKind.PROCESS_EXIT:
            if (
                self.exit_code is None
                or isinstance(self.exit_code, bool)
                or not 0 <= self.exit_code <= 255
                or self.failure_message is not None
            ):
                raise ValueError("fake process exit requires only a portable exit code")
        elif self.exit_code is not None or self.failure_message is None:
            raise ValueError("fake non-process outcome requires only a failure message")


class InMemorySandboxEvidenceStore(SandboxEvidenceStore):
    """Content-addressed byte store used by the deterministic runtime adapter."""

    def __init__(self) -> None:
        """Create an empty evidence namespace."""
        self._content: dict[str, bytes] = {}

    def store_log(
        self,
        *,
        run_id: UUID,
        command_id: str,
        stream: SandboxLogStream,
        content: bytes,
    ) -> SandboxLogReference:
        """Retain one raw stream under an immutable run-scoped key."""
        digest = hashlib.sha256(content).hexdigest()
        storage_key = (
            f"sandbox-runs/{run_id}/commands/{command_id}/{stream.value.casefold()}-{digest}.log"
        )
        self._store_immutable(storage_key, content)
        return SandboxLogReference(
            stream=stream,
            sha256_digest=digest,
            size_bytes=len(content),
            storage_key=storage_key,
        )

    def store_artifact(
        self,
        *,
        run_id: UUID,
        command_id: str,
        normalized_path: str,
        content: bytes,
        media_type: str,
    ) -> SandboxArtifactReference:
        """Retain one fake artifact and preserve its workspace-relative path."""
        _validate_relative_path(normalized_path)
        digest = hashlib.sha256(content).hexdigest()
        storage_key = (
            f"sandbox-runs/{run_id}/commands/{command_id}/artifacts/{digest}/{normalized_path}"
        )
        self._store_immutable(storage_key, content)
        return SandboxArtifactReference(
            normalized_path=normalized_path,
            sha256_digest=digest,
            size_bytes=len(content),
            storage_key=storage_key,
            media_type=media_type,
        )

    def read(self, storage_key: str) -> bytes | None:
        """Resolve retained content for contract assertions."""
        return self._content.get(storage_key)

    @property
    def content(self) -> Mapping[str, bytes]:
        """Expose a read-only view for deterministic test inspection."""
        return MappingProxyType(self._content)

    def _store_immutable(self, storage_key: str, content: bytes) -> None:
        """Reject collisions rather than overwriting prior evidence."""
        existing = self._content.get(storage_key)
        if existing is not None and existing != content:
            raise ValueError("sandbox evidence storage key collision")
        self._content[storage_key] = content


class FakeContainerRuntimeAdapter(ContainerRuntimePort):
    """Execute configured outcomes sequentially without Docker, network, or subprocesses."""

    def __init__(
        self,
        outcomes: Mapping[str, FakeCommandOutcome],
        *,
        started_at: datetime,
        evidence_store: InMemorySandboxEvidenceStore | None = None,
    ) -> None:
        """Bind immutable outcomes and a deterministic run start time."""
        if started_at.tzinfo is None or started_at.utcoffset() != UTC.utcoffset(started_at):
            raise ValueError("fake container start time must be UTC-aware")
        self._outcomes = MappingProxyType(dict(outcomes))
        self._started_at = started_at
        self._evidence_store = evidence_store or InMemorySandboxEvidenceStore()
        self._executed_command_ids: list[str] = []

    @property
    def evidence_store(self) -> InMemorySandboxEvidenceStore:
        """Return the in-memory raw evidence store for contract assertions."""
        return self._evidence_store

    @property
    def executed_command_ids(self) -> tuple[str, ...]:
        """Return the exact sequential commands attempted by the fake runtime."""
        return tuple(self._executed_command_ids)

    async def execute(
        self,
        request: ContainerExecutionRequest,
    ) -> SandboxRunEvidence:
        """Materialize deterministic terminal evidence and stop on first failure."""
        current_time = self._started_at
        command_evidence: list[SandboxCommandEvidence] = []
        self._executed_command_ids.clear()

        for command in request.plan.commands:
            self._executed_command_ids.append(command.command_id)
            outcome = self._outcomes.get(command.command_id)
            if outcome is None:
                outcome = FakeCommandOutcome(
                    kind=FakeCommandOutcomeKind.RUNTIME_ERROR,
                    exit_code=None,
                    stdout=b"",
                    stderr=b"",
                    duration=timedelta(0),
                    artifacts=(),
                    failure_message="Fake runtime has no configured command outcome.",
                )

            evidence = self._materialize_command_evidence(
                request,
                command=command,
                outcome=outcome,
                started_at=current_time,
            )
            command_evidence.append(evidence)
            current_time = evidence.finished_at

            if evidence.status is not SandboxCommandStatus.SUCCEEDED:
                break

        return create_sandbox_run_evidence(
            run_id=request.run_id,
            plan=request.plan,
            image_reference=request.image.value,
            runtime_reference="fake.container.v1",
            started_at=self._started_at,
            finished_at=current_time,
            command_evidence=tuple(command_evidence),
        )

    def _materialize_command_evidence(
        self,
        request: ContainerExecutionRequest,
        *,
        command: StructuredCommand,
        outcome: FakeCommandOutcome,
        started_at: datetime,
    ) -> SandboxCommandEvidence:
        """Store raw configured outputs and normalize one command status."""
        finished_at = started_at + outcome.duration
        stdout_log = self._evidence_store.store_log(
            run_id=request.run_id,
            command_id=command.command_id,
            stream=SandboxLogStream.STDOUT,
            content=outcome.stdout,
        )
        stderr_log = self._evidence_store.store_log(
            run_id=request.run_id,
            command_id=command.command_id,
            stream=SandboxLogStream.STDERR,
            content=outcome.stderr,
        )

        invalid_artifact = next(
            (
                artifact
                for artifact in outcome.artifacts
                if not _matches_artifact_patterns(
                    artifact.normalized_path,
                    patterns=command.artifact_patterns,
                )
            ),
            None,
        )
        if invalid_artifact is not None:
            return SandboxCommandEvidence(
                command_id=command.command_id,
                status=SandboxCommandStatus.RUNTIME_ERROR,
                started_at=started_at,
                finished_at=finished_at,
                exit_code=None,
                stdout_log=stdout_log,
                stderr_log=stderr_log,
                artifacts=(),
                output_parser_id=command.output_parser_id,
                failure_message="Fake artifact falls outside approved collection patterns.",
            )

        artifacts = tuple(
            self._evidence_store.store_artifact(
                run_id=request.run_id,
                command_id=command.command_id,
                normalized_path=artifact.normalized_path,
                content=artifact.content,
                media_type=artifact.media_type,
            )
            for artifact in outcome.artifacts
        )

        status, exit_code, failure_message = _normalize_outcome(
            outcome,
            command=command,
        )
        return SandboxCommandEvidence(
            command_id=command.command_id,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            exit_code=exit_code,
            stdout_log=stdout_log,
            stderr_log=stderr_log,
            artifacts=artifacts,
            output_parser_id=command.output_parser_id,
            failure_message=failure_message,
        )


def _normalize_outcome(
    outcome: FakeCommandOutcome,
    *,
    command: StructuredCommand,
) -> tuple[SandboxCommandStatus, int | None, str | None]:
    """Map configured fake boundary outcomes to shared terminal evidence."""
    if outcome.kind is FakeCommandOutcomeKind.PROCESS_EXIT:
        if outcome.exit_code in command.expected_exit_codes:
            return SandboxCommandStatus.SUCCEEDED, outcome.exit_code, None
        expected = ", ".join(str(code) for code in sorted(command.expected_exit_codes))
        return (
            SandboxCommandStatus.FAILED,
            outcome.exit_code,
            f"Command returned exit code {outcome.exit_code}; expected {expected}.",
        )

    status = {
        FakeCommandOutcomeKind.TIMED_OUT: SandboxCommandStatus.TIMED_OUT,
        FakeCommandOutcomeKind.RESOURCE_LIMIT_EXCEEDED: (
            SandboxCommandStatus.RESOURCE_LIMIT_EXCEEDED
        ),
        FakeCommandOutcomeKind.CANCELLED: SandboxCommandStatus.CANCELLED,
        FakeCommandOutcomeKind.RUNTIME_ERROR: SandboxCommandStatus.RUNTIME_ERROR,
    }[outcome.kind]
    return status, None, outcome.failure_message


def _matches_artifact_patterns(
    normalized_path: str,
    *,
    patterns: frozenset[str],
) -> bool:
    """Use portable case-sensitive glob matching for deterministic fake artifacts."""
    return any(fnmatch.fnmatchcase(normalized_path, pattern) for pattern in patterns)


def _validate_relative_path(value: str) -> None:
    """Require one canonical workspace-relative POSIX path."""
    if (
        not value
        or value != value.strip()
        or value.startswith("/")
        or "\\" in value
        or ":" in value
    ):
        raise ValueError("fake artifact path must be relative and normalized")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("fake artifact path must stay inside the workspace")
    if PurePosixPath(value).as_posix() != value:
        raise ValueError("fake artifact path must be canonical")
