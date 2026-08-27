"""Loopback health, runtime lifecycle, and bounded Web artifact evidence."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import stat
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final

from orchestwin.web_execution.reports import WebEvidenceReference

_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_LOOPBACK_HOSTS: Final = frozenset({"127.0.0.1", "::1", "localhost"})
_PROTECTED_COMPONENTS: Final = frozenset({".git", ".orchestwin", ".ssh"})
_HASH_CHUNK_SIZE: Final = 1024 * 1024


class WebHealthCheckStatus(StrEnum):
    """Terminal outcome of a bounded loopback health probe."""

    HEALTHY = "HEALTHY"
    UNHEALTHY = "UNHEALTHY"
    TIMED_OUT = "TIMED_OUT"


@dataclass(frozen=True, slots=True)
class WebHealthCheckSpec:
    """Bounded local HTTP health probe without external navigation."""

    check_id: str
    host: str
    port: int
    path: str
    expected_status_codes: tuple[int, ...]
    request_timeout_seconds: int
    maximum_attempts: int
    interval_milliseconds: int

    def __post_init__(self) -> None:
        if not self.check_id or self.check_id != self.check_id.strip():
            raise ValueError("Web health check ID must be normalized")
        if self.host.casefold() not in _LOOPBACK_HOSTS:
            raise ValueError("Web health checks are restricted to loopback hosts")
        if isinstance(self.port, bool) or not 1 <= self.port <= 65_535:
            raise ValueError("Web health check port must be from one to 65535")
        if (
            not self.path.startswith("/")
            or "\\" in self.path
            or any(character in self.path for character in ("\x00", "\r", "\n"))
        ):
            raise ValueError("Web health check path must be an absolute HTTP path")
        if self.expected_status_codes != tuple(sorted(self.expected_status_codes)) or len(
            self.expected_status_codes
        ) != len(set(self.expected_status_codes)):
            raise ValueError("Web health status codes must be canonical and unique")
        if not self.expected_status_codes or any(
            isinstance(code, bool) or not 100 <= code <= 599 for code in self.expected_status_codes
        ):
            raise ValueError("Web health check requires valid HTTP status codes")
        for value, label, maximum in (
            (self.request_timeout_seconds, "request timeout", 30),
            (self.maximum_attempts, "maximum attempts", 30),
            (self.interval_milliseconds, "interval", 60_000),
        ):
            if isinstance(value, bool) or not 1 <= value <= maximum:
                raise ValueError(f"Web health check {label} is outside the supported boundary")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_snapshot())).hexdigest()

    def to_snapshot(self) -> dict[str, object]:
        return {
            "check_id": self.check_id,
            "host": self.host,
            "port": self.port,
            "path": self.path,
            "expected_status_codes": list(self.expected_status_codes),
            "request_timeout_seconds": self.request_timeout_seconds,
            "maximum_attempts": self.maximum_attempts,
            "interval_milliseconds": self.interval_milliseconds,
        }


@dataclass(frozen=True, slots=True, order=True)
class WebHealthCheckAttempt:
    """One observable probe attempt without response-body retention."""

    attempt_number: int
    observed_at: datetime
    latency_milliseconds: int
    status_code: int | None
    error_code: str | None

    def __post_init__(self) -> None:
        if isinstance(self.attempt_number, bool) or self.attempt_number < 1:
            raise ValueError("Web health attempt number must be positive")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("Web health attempt timestamp must be timezone-aware")
        if isinstance(self.latency_milliseconds, bool) or self.latency_milliseconds < 0:
            raise ValueError("Web health attempt latency must be non-negative")
        if (self.status_code is None) == (self.error_code is None):
            raise ValueError("Web health attempt requires exactly one status or error")
        if self.status_code is not None and not 100 <= self.status_code <= 599:
            raise ValueError("Web health attempt status code is invalid")
        if self.error_code is not None and (
            not self.error_code or self.error_code != self.error_code.strip()
        ):
            raise ValueError("Web health attempt error code must be normalized")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "attempt_number": self.attempt_number,
            "observed_at": self.observed_at.isoformat(),
            "latency_milliseconds": self.latency_milliseconds,
            "status_code": self.status_code,
            "error_code": self.error_code,
        }


@dataclass(frozen=True, slots=True)
class WebHealthCheckResult:
    """Terminal health evidence bound to the exact probe specification."""

    spec: WebHealthCheckSpec
    status: WebHealthCheckStatus
    attempts: tuple[WebHealthCheckAttempt, ...]

    def __post_init__(self) -> None:
        expected_numbers = tuple(range(1, len(self.attempts) + 1))
        if tuple(attempt.attempt_number for attempt in self.attempts) != expected_numbers:
            raise ValueError("Web health attempts must be contiguous and ordered")
        if not self.attempts or len(self.attempts) > self.spec.maximum_attempts:
            raise ValueError("Web health result has an invalid attempt count")
        last = self.attempts[-1]
        last_is_healthy = last.status_code in self.spec.expected_status_codes
        if self.status is WebHealthCheckStatus.HEALTHY and not last_is_healthy:
            raise ValueError("healthy Web result requires an expected final status")
        if self.status is not WebHealthCheckStatus.HEALTHY and last_is_healthy:
            raise ValueError("unhealthy Web result cannot end with a successful status")
        if self.status is WebHealthCheckStatus.TIMED_OUT and last.error_code != "TIMEOUT":
            raise ValueError("timed-out Web result requires a timeout error")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "spec": self.spec.to_snapshot(),
            "spec_content_hash": self.spec.content_hash,
            "status": self.status.value,
            "attempts": [attempt.to_snapshot() for attempt in self.attempts],
        }


class WebArtifactCollectionStatus(StrEnum):
    """Outcome of bounded artifact inspection."""

    COLLECTED = "COLLECTED"
    REJECTED = "REJECTED"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"


class WebArtifactCollectionIssueCode(StrEnum):
    """Stable artifact-collection rejection reasons."""

    WORKSPACE_INVALID = "WORKSPACE_INVALID"
    PATTERN_INVALID = "PATTERN_INVALID"
    SYMLINK_FORBIDDEN = "SYMLINK_FORBIDDEN"
    SPECIAL_FILE_FORBIDDEN = "SPECIAL_FILE_FORBIDDEN"
    PROTECTED_PATH = "PROTECTED_PATH"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    TOO_MANY_FILES = "TOO_MANY_FILES"
    TOTAL_SIZE_EXCEEDED = "TOTAL_SIZE_EXCEEDED"
    FILE_READ_FAILED = "FILE_READ_FAILED"


@dataclass(frozen=True, slots=True)
class WebArtifactCollectionPolicy:
    """Resource limits applied while collecting generated-project artifacts."""

    maximum_files: int
    maximum_file_size_bytes: int
    maximum_total_size_bytes: int

    def __post_init__(self) -> None:
        values = (
            self.maximum_files,
            self.maximum_file_size_bytes,
            self.maximum_total_size_bytes,
        )
        if any(isinstance(value, bool) or value < 1 for value in values):
            raise ValueError("Web artifact collection limits must be positive")
        if self.maximum_file_size_bytes > self.maximum_total_size_bytes:
            raise ValueError("Web artifact file limit must not exceed the total limit")


DEFAULT_WEB_ARTIFACT_COLLECTION_POLICY: Final = WebArtifactCollectionPolicy(
    maximum_files=1_000,
    maximum_file_size_bytes=25 * 1024 * 1024,
    maximum_total_size_bytes=250 * 1024 * 1024,
)


@dataclass(frozen=True, slots=True, order=True)
class WebCollectedArtifact:
    """Content-addressed metadata for one regular workspace artifact."""

    normalized_path: str
    sha256_digest: str
    size_bytes: int
    media_type: str

    def __post_init__(self) -> None:
        _validate_relative_path(self.normalized_path)
        _validate_sha256(self.sha256_digest, label="Web collected artifact digest")
        if isinstance(self.size_bytes, bool) or self.size_bytes < 0:
            raise ValueError("Web collected artifact size must be non-negative")
        if not self.media_type or "/" not in self.media_type:
            raise ValueError("Web collected artifact media type must be normalized")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "normalized_path": self.normalized_path,
            "sha256_digest": self.sha256_digest,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
        }


@dataclass(frozen=True, slots=True, order=True)
class WebArtifactCollectionIssue:
    """One safe artifact-collection issue without exposing host paths."""

    code: WebArtifactCollectionIssueCode
    message: str
    normalized_path: str | None

    def __post_init__(self) -> None:
        if not self.message or self.message != " ".join(self.message.split()):
            raise ValueError("Web artifact issue message must be normalized")

    def to_snapshot(self) -> dict[str, str | None]:
        return {
            "code": self.code.value,
            "message": self.message,
            "normalized_path": self.normalized_path,
        }


@dataclass(frozen=True, slots=True)
class WebArtifactCollectionResult:
    """Canonical artifact evidence and any bounded inspection failures."""

    status: WebArtifactCollectionStatus
    artifacts: tuple[WebCollectedArtifact, ...]
    issues: tuple[WebArtifactCollectionIssue, ...]
    total_size_bytes: int

    def __post_init__(self) -> None:
        if self.artifacts != tuple(sorted(self.artifacts)) or len(self.artifacts) != len(
            set(self.artifacts)
        ):
            raise ValueError("Web collected artifacts must be canonical and unique")
        if self.issues != tuple(sorted(self.issues)):
            raise ValueError("Web artifact issues must use canonical order")
        if isinstance(self.total_size_bytes, bool) or self.total_size_bytes < 0:
            raise ValueError("Web artifact total size must be non-negative")
        if self.total_size_bytes != sum(artifact.size_bytes for artifact in self.artifacts):
            raise ValueError("Web artifact total size is inconsistent")
        if self.status is WebArtifactCollectionStatus.COLLECTED and self.issues:
            raise ValueError("successful Web artifact collection must not contain issues")
        if self.status is not WebArtifactCollectionStatus.COLLECTED and not self.issues:
            raise ValueError("failed Web artifact collection requires issues")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "artifacts": [artifact.to_snapshot() for artifact in self.artifacts],
            "issues": [issue.to_snapshot() for issue in self.issues],
            "total_size_bytes": self.total_size_bytes,
        }


@dataclass(frozen=True, slots=True, order=True)
class WebRuntimeProcessEvidence:
    """Terminal evidence for one controller-managed runtime process."""

    process_id: str
    command_plan_hash: str
    started_at: datetime
    completed_at: datetime
    exit_code: int
    terminated_by_controller: bool
    stdout_ref: WebEvidenceReference
    stderr_ref: WebEvidenceReference

    def __post_init__(self) -> None:
        if not self.process_id or self.process_id != self.process_id.strip():
            raise ValueError("Web runtime process ID must be normalized")
        _validate_sha256(self.command_plan_hash, label="Web runtime command-plan hash")
        for timestamp in (self.started_at, self.completed_at):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("Web runtime timestamps must be timezone-aware")
        if self.completed_at < self.started_at:
            raise ValueError("Web runtime process completion cannot precede start")
        if isinstance(self.exit_code, bool) or not 0 <= self.exit_code <= 255:
            raise ValueError("Web runtime process exit code must be from zero to 255")
        if not isinstance(self.terminated_by_controller, bool):
            raise TypeError("Web runtime termination marker must be a boolean")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "process_id": self.process_id,
            "command_plan_hash": self.command_plan_hash,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "exit_code": self.exit_code,
            "terminated_by_controller": self.terminated_by_controller,
            "stdout_ref": self.stdout_ref.to_snapshot(),
            "stderr_ref": self.stderr_ref.to_snapshot(),
        }


@dataclass(frozen=True, slots=True)
class WebRuntimeEvidence:
    """Runtime, health, and artifact evidence bound to exact immutable inputs."""

    source_revision_content_hash: str
    source_tree_hash: str
    runner_image_digest: str
    processes: tuple[WebRuntimeProcessEvidence, ...]
    health_results: tuple[WebHealthCheckResult, ...]
    artifact_collection: WebArtifactCollectionResult

    def __post_init__(self) -> None:
        for value, label in (
            (self.source_revision_content_hash, "Web runtime source revision hash"),
            (self.source_tree_hash, "Web runtime source tree hash"),
            (self.runner_image_digest, "Web runtime runner image digest"),
        ):
            _validate_sha256(value, label=label)
        if self.processes != tuple(sorted(self.processes)) or len(self.processes) != len(
            set(self.processes)
        ):
            raise ValueError("Web runtime process evidence must be canonical and unique")
        health_ids = tuple(result.spec.check_id for result in self.health_results)
        if health_ids != tuple(sorted(health_ids)) or len(health_ids) != len(set(health_ids)):
            raise ValueError("Web runtime health evidence must be canonical and unique")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_snapshot())).hexdigest()

    def to_snapshot(self) -> dict[str, object]:
        return {
            "source_revision_content_hash": self.source_revision_content_hash,
            "source_tree_hash": self.source_tree_hash,
            "runner_image_digest": self.runner_image_digest,
            "processes": [process.to_snapshot() for process in self.processes],
            "health_results": [result.to_snapshot() for result in self.health_results],
            "artifact_collection": self.artifact_collection.to_snapshot(),
        }


def collect_web_artifacts(
    workspace_path: Path,
    *,
    patterns: tuple[str, ...],
    policy: WebArtifactCollectionPolicy = DEFAULT_WEB_ARTIFACT_COLLECTION_POLICY,
) -> WebArtifactCollectionResult:
    """Collect matching regular files without following symlinks or escaping workspace."""
    workspace = Path(workspace_path)
    if not workspace.is_absolute() or workspace.is_symlink() or not workspace.is_dir():
        return _collection_failure(
            WebArtifactCollectionStatus.REJECTED,
            WebArtifactCollectionIssueCode.WORKSPACE_INVALID,
            "Artifact workspace must be an absolute regular directory.",
        )
    if patterns != tuple(sorted(patterns)) or len(patterns) != len(set(patterns)):
        return _collection_failure(
            WebArtifactCollectionStatus.REJECTED,
            WebArtifactCollectionIssueCode.PATTERN_INVALID,
            "Artifact patterns must be canonical and unique.",
        )
    if any(not _is_safe_pattern(pattern) for pattern in patterns):
        return _collection_failure(
            WebArtifactCollectionStatus.REJECTED,
            WebArtifactCollectionIssueCode.PATTERN_INVALID,
            "Artifact patterns must stay inside the workspace.",
        )

    workspace_resolved = workspace.resolve()
    candidates: dict[str, Path] = {}
    for pattern in patterns:
        try:
            matches = tuple(workspace.glob(pattern))
        except (OSError, ValueError):
            return _collection_failure(
                WebArtifactCollectionStatus.REJECTED,
                WebArtifactCollectionIssueCode.PATTERN_INVALID,
                "Artifact pattern could not be evaluated safely.",
            )
        for candidate in matches:
            try:
                relative = candidate.relative_to(workspace).as_posix()
            except ValueError:
                return _collection_failure(
                    WebArtifactCollectionStatus.REJECTED,
                    WebArtifactCollectionIssueCode.PROTECTED_PATH,
                    "Artifact candidate escaped the workspace.",
                )
            candidates.setdefault(relative, candidate)

    artifacts: list[WebCollectedArtifact] = []
    issues: list[WebArtifactCollectionIssue] = []
    total_size = 0
    for relative, candidate in sorted(candidates.items()):
        if candidate.is_dir():
            continue
        if _path_contains_symlink(workspace, candidate):
            issues.append(
                _artifact_issue(
                    WebArtifactCollectionIssueCode.SYMLINK_FORBIDDEN,
                    "Artifact collection does not follow symlinks.",
                    relative,
                )
            )
            continue
        if any(part.casefold() in _PROTECTED_COMPONENTS for part in PurePosixPath(relative).parts):
            issues.append(
                _artifact_issue(
                    WebArtifactCollectionIssueCode.PROTECTED_PATH,
                    "Artifact path targets protected workspace metadata.",
                    relative,
                )
            )
            continue
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(workspace_resolved)
            mode = candidate.stat().st_mode
        except (OSError, ValueError):
            issues.append(
                _artifact_issue(
                    WebArtifactCollectionIssueCode.FILE_READ_FAILED,
                    "Artifact file could not be inspected safely.",
                    relative,
                )
            )
            continue
        if not stat.S_ISREG(mode):
            issues.append(
                _artifact_issue(
                    WebArtifactCollectionIssueCode.SPECIAL_FILE_FORBIDDEN,
                    "Artifact collection accepts regular files only.",
                    relative,
                )
            )
            continue
        size = candidate.stat().st_size
        if size > policy.maximum_file_size_bytes:
            issues.append(
                _artifact_issue(
                    WebArtifactCollectionIssueCode.FILE_TOO_LARGE,
                    "Artifact file exceeds the individual size limit.",
                    relative,
                )
            )
            continue
        if len(artifacts) + 1 > policy.maximum_files:
            issues.append(
                _artifact_issue(
                    WebArtifactCollectionIssueCode.TOO_MANY_FILES,
                    "Artifact collection exceeds the file-count limit.",
                    relative,
                )
            )
            break
        if total_size + size > policy.maximum_total_size_bytes:
            issues.append(
                _artifact_issue(
                    WebArtifactCollectionIssueCode.TOTAL_SIZE_EXCEEDED,
                    "Artifact collection exceeds the total size limit.",
                    relative,
                )
            )
            break
        try:
            digest = _hash_file(candidate)
        except OSError:
            issues.append(
                _artifact_issue(
                    WebArtifactCollectionIssueCode.FILE_READ_FAILED,
                    "Artifact file could not be read safely.",
                    relative,
                )
            )
            continue
        media_type = mimetypes.guess_type(relative)[0] or "application/octet-stream"
        artifacts.append(
            WebCollectedArtifact(
                normalized_path=relative,
                sha256_digest=digest,
                size_bytes=size,
                media_type=media_type,
            )
        )
        total_size += size

    limit_codes = {
        WebArtifactCollectionIssueCode.FILE_TOO_LARGE,
        WebArtifactCollectionIssueCode.TOO_MANY_FILES,
        WebArtifactCollectionIssueCode.TOTAL_SIZE_EXCEEDED,
    }
    status = (
        WebArtifactCollectionStatus.COLLECTED
        if not issues
        else (
            WebArtifactCollectionStatus.LIMIT_EXCEEDED
            if any(issue.code in limit_codes for issue in issues)
            else WebArtifactCollectionStatus.REJECTED
        )
    )
    return WebArtifactCollectionResult(
        status=status,
        artifacts=tuple(sorted(artifacts)),
        issues=tuple(sorted(issues)),
        total_size_bytes=total_size,
    )


def _collection_failure(
    status: WebArtifactCollectionStatus,
    code: WebArtifactCollectionIssueCode,
    message: str,
) -> WebArtifactCollectionResult:
    return WebArtifactCollectionResult(
        status=status,
        artifacts=(),
        issues=(WebArtifactCollectionIssue(code, message, None),),
        total_size_bytes=0,
    )


def _artifact_issue(
    code: WebArtifactCollectionIssueCode,
    message: str,
    path: str,
) -> WebArtifactCollectionIssue:
    return WebArtifactCollectionIssue(code=code, message=message, normalized_path=path)


def _is_safe_pattern(pattern: str) -> bool:
    if (
        not pattern
        or pattern != pattern.strip()
        or pattern.startswith(("/", "~"))
        or "\\" in pattern
        or ":" in pattern
    ):
        return False
    return all(part not in {"", ".", ".."} for part in pattern.split("/"))


def _path_contains_symlink(workspace: Path, candidate: Path) -> bool:
    current = candidate
    while current != workspace:
        if current.is_symlink():
            return True
        current = current.parent
    return workspace.is_symlink()


def _validate_relative_path(value: str) -> None:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or "\\" in value
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("Web artifact path must be normalized and relative")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(_HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_sha256(value: str, *, label: str) -> None:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase SHA-256")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
