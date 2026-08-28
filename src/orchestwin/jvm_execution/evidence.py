"""Normalized JVM execution evidence with stable bounded-repair signatures."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from orchestwin.jvm_execution.plans import JvmExecutionPhase, JvmExecutionPlanBundle
from orchestwin.jvm_execution.targets import JvmTargetSelection, jvm_scope_for

_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_UUID_PATTERN: Final = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
_ISO_TIMESTAMP_PATTERN: Final = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b"
)
_SHA_IN_TEXT_PATTERN: Final = re.compile(r"\b(?:sha256:)?[0-9a-fA-F]{64}\b")
_WINDOWS_PATH_PATTERN: Final = re.compile(
    r"(?i)\b[A-Z]:\\(?:[^\s:*?\"<>|\r\n]+\\)*[^\s:*?\"<>|\r\n]*"
)
_WORKSPACE_PATH_PATTERN: Final = re.compile(
    r"(?i)(?:/[^\s:'\"/]+)*/(?:workspaces?|workspace|tmp)/[^\s:'\"]+"
)
_LINE_WORD_PATTERN: Final = re.compile(r"(?i)\bline\s+\d+(?::\d+)?")
_LINE_COLUMN_PATTERN: Final = re.compile(r"(?<=:)(?:\d+)(?::\d+)?")
_WHITESPACE_PATTERN: Final = re.compile(r"\s+")
_MAX_MESSAGE_LENGTH: Final = 1_024


class JvmPhaseResultStatus(StrEnum):
    """Normalized terminal state for one explicit JVM phase."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    TIMED_OUT = "TIMED_OUT"
    RESOURCE_LIMIT_EXCEEDED = "RESOURCE_LIMIT_EXCEEDED"
    CANCELLED = "CANCELLED"
    RUNTIME_ERROR = "RUNTIME_ERROR"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    NOT_RUN = "NOT_RUN"


class JvmFailureCategory(StrEnum):
    """Tool-neutral categories used by the later bounded repair workflow."""

    VALIDATION = "VALIDATION"
    DEPENDENCY_INSTALL = "DEPENDENCY_INSTALL"
    STATIC_CHECK = "STATIC_CHECK"
    BUILD = "BUILD"
    TEST = "TEST"
    RUNTIME = "RUNTIME"
    ARTIFACT_COLLECTION = "ARTIFACT_COLLECTION"
    TIMEOUT = "TIMEOUT"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    CANCELLED = "CANCELLED"
    POLICY = "POLICY"


class JvmExecutionReportStatus(StrEnum):
    """Aggregate status without converting a partial execution into success."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True, slots=True, order=True)
class JvmEvidenceReference:
    """Content-addressed raw log or artifact reference."""

    storage_key: str
    sha256_digest: str
    size_bytes: int
    media_type: str

    def __post_init__(self) -> None:
        if not self.storage_key or self.storage_key != self.storage_key.strip():
            raise ValueError("JVM evidence storage key must be normalized")
        _validate_sha256(self.sha256_digest, label="JVM evidence digest")
        if isinstance(self.size_bytes, bool) or self.size_bytes < 0:
            raise ValueError("JVM evidence size must be non-negative")
        if (
            not self.media_type
            or self.media_type != self.media_type.strip()
            or "/" not in self.media_type
        ):
            raise ValueError("JVM evidence media type must be normalized")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "storage_key": self.storage_key,
            "sha256_digest": self.sha256_digest,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
        }


@dataclass(frozen=True, slots=True, order=True)
class JvmNormalizedFinding:
    """One tool-neutral compiler, test, policy, or runtime finding."""

    code: str
    message: str
    source_tool: str
    location: str | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.code, "JVM finding code"),
            (self.message, "JVM finding message"),
            (self.source_tool, "JVM finding source tool"),
        ):
            _validate_normalized_text(value, label=label)
        if self.location is not None:
            _validate_normalized_text(self.location, label="JVM finding location")

    def to_snapshot(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "message": self.message,
            "source_tool": self.source_tool,
            "location": self.location,
        }


@dataclass(frozen=True, slots=True)
class JvmPhaseResult:
    """One normalized phase outcome retaining exact raw evidence references."""

    phase: JvmExecutionPhase
    status: JvmPhaseResultStatus
    command_plan_hash: str
    started_at: datetime | None
    completed_at: datetime | None
    exit_codes: tuple[int, ...]
    stdout_refs: tuple[JvmEvidenceReference, ...]
    stderr_refs: tuple[JvmEvidenceReference, ...]
    artifact_refs: tuple[JvmEvidenceReference, ...]
    findings: tuple[JvmNormalizedFinding, ...]
    failure_category: JvmFailureCategory | None
    failure_code: str | None
    normalized_summary: str

    def __post_init__(self) -> None:
        _validate_sha256(self.command_plan_hash, label="JVM command plan hash")
        _validate_timestamps(self.started_at, self.completed_at)
        if any(isinstance(code, bool) or not 0 <= code <= 255 for code in self.exit_codes):
            raise ValueError("JVM phase exit codes must be integers from zero to 255")
        _require_canonical(self.stdout_refs, label="JVM stdout references")
        _require_canonical(self.stderr_refs, label="JVM stderr references")
        _require_canonical(self.artifact_refs, label="JVM artifact references")
        ordered_findings = tuple(
            sorted(
                self.findings,
                key=lambda item: (item.code, item.source_tool, item.location or "", item.message),
            )
        )
        if self.findings != ordered_findings or len(self.findings) != len(set(self.findings)):
            raise ValueError("JVM normalized findings must be canonical and unique")
        _validate_normalized_text(self.normalized_summary, label="JVM phase summary")

        failed = self.status in {
            JvmPhaseResultStatus.FAILED,
            JvmPhaseResultStatus.TIMED_OUT,
            JvmPhaseResultStatus.RESOURCE_LIMIT_EXCEEDED,
            JvmPhaseResultStatus.CANCELLED,
            JvmPhaseResultStatus.RUNTIME_ERROR,
            JvmPhaseResultStatus.POLICY_BLOCKED,
        }
        if failed:
            if self.failure_category is None or not self.failure_code:
                raise ValueError("failed JVM phase requires a category and stable code")
            _validate_normalized_text(self.failure_code, label="JVM failure code")
            if self.status is not JvmPhaseResultStatus.POLICY_BLOCKED and not (
                self.stdout_refs or self.stderr_refs
            ):
                raise ValueError("executed failed JVM phase must retain raw log evidence")
        elif self.failure_category is not None or self.failure_code is not None:
            raise ValueError("non-failed JVM phase must not expose failure metadata")

        executed = self.status in {
            JvmPhaseResultStatus.PASSED,
            JvmPhaseResultStatus.FAILED,
            JvmPhaseResultStatus.TIMED_OUT,
            JvmPhaseResultStatus.RESOURCE_LIMIT_EXCEEDED,
            JvmPhaseResultStatus.CANCELLED,
            JvmPhaseResultStatus.RUNTIME_ERROR,
        }
        if executed and (self.started_at is None or self.completed_at is None):
            raise ValueError("executed JVM phase requires timestamps")
        if self.status in {
            JvmPhaseResultStatus.SKIPPED,
            JvmPhaseResultStatus.NOT_RUN,
            JvmPhaseResultStatus.POLICY_BLOCKED,
        } and (self.exit_codes or self.stdout_refs or self.stderr_refs):
            raise ValueError("unexecuted JVM phase must not fabricate process evidence")

    @property
    def is_failure(self) -> bool:
        return self.failure_category is not None

    def to_snapshot(self) -> dict[str, object]:
        return {
            "phase": self.phase.value,
            "status": self.status.value,
            "command_plan_hash": self.command_plan_hash,
            "started_at": None if self.started_at is None else self.started_at.isoformat(),
            "completed_at": None if self.completed_at is None else self.completed_at.isoformat(),
            "exit_codes": list(self.exit_codes),
            "stdout_refs": [item.to_snapshot() for item in self.stdout_refs],
            "stderr_refs": [item.to_snapshot() for item in self.stderr_refs],
            "artifact_refs": [item.to_snapshot() for item in self.artifact_refs],
            "findings": [item.to_snapshot() for item in self.findings],
            "failure_category": (
                None if self.failure_category is None else self.failure_category.value
            ),
            "failure_code": self.failure_code,
            "normalized_summary": self.normalized_summary,
        }


@dataclass(frozen=True, slots=True, order=True)
class JvmFailureSignature:
    """Stable failure identity used to count identical repair outcomes."""

    category: JvmFailureCategory
    phase: JvmExecutionPhase
    failure_code: str
    normalized_message: str
    signature: str

    def __post_init__(self) -> None:
        _validate_normalized_text(self.failure_code, label="JVM failure code")
        _validate_normalized_text(self.normalized_message, label="JVM normalized failure message")
        _validate_sha256(self.signature, label="JVM failure signature")
        expected = _failure_signature(
            category=self.category,
            phase=self.phase,
            failure_code=self.failure_code,
            normalized_message=self.normalized_message,
        )
        if self.signature != expected:
            raise ValueError("JVM failure signature does not match its canonical payload")

    def to_snapshot(self) -> dict[str, str]:
        return {
            "category": self.category.value,
            "phase": self.phase.value,
            "failure_code": self.failure_code,
            "normalized_message": self.normalized_message,
            "signature": self.signature,
        }


@dataclass(frozen=True, slots=True)
class JvmExecutionReport:
    """Aggregate normalized evidence for one source revision and phase-plan bundle."""

    target_selection: JvmTargetSelection
    execution_plan_content_hash: str
    status: JvmExecutionReportStatus
    phase_results: tuple[JvmPhaseResult, ...]
    failure_signatures: tuple[JvmFailureSignature, ...]

    def __post_init__(self) -> None:
        self.target_selection.validate_against(jvm_scope_for(self.target_selection.target))
        _validate_sha256(self.execution_plan_content_hash, label="JVM execution plan hash")
        ordered_results = tuple(
            sorted(self.phase_results, key=lambda item: tuple(JvmExecutionPhase).index(item.phase))
        )
        if self.phase_results != ordered_results:
            raise ValueError("JVM phase results must use canonical phase order")
        if len({item.phase for item in self.phase_results}) != len(self.phase_results):
            raise ValueError("JVM execution report must not duplicate phase results")
        ordered_signatures = tuple(sorted(self.failure_signatures, key=lambda item: item.signature))
        if self.failure_signatures != ordered_signatures or len(self.failure_signatures) != len(
            set(self.failure_signatures)
        ):
            raise ValueError("JVM failure signatures must be canonical and unique")
        derived = _report_status(self.phase_results)
        if self.status is not derived:
            raise ValueError("JVM execution report status is inconsistent with phase results")
        if {item.signature for item in self.failure_signatures} != {
            signature.signature
            for result in self.phase_results
            if (signature := failure_signature_for(result)) is not None
        }:
            raise ValueError("JVM execution report signatures do not match failed phases")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_snapshot())).hexdigest()

    def to_snapshot(self) -> dict[str, object]:
        return {
            "target_selection": self.target_selection.to_snapshot(),
            "execution_plan_content_hash": self.execution_plan_content_hash,
            "status": self.status.value,
            "phase_results": [item.to_snapshot() for item in self.phase_results],
            "failure_signatures": [item.to_snapshot() for item in self.failure_signatures],
        }


def create_jvm_execution_report(
    bundle: JvmExecutionPlanBundle,
    phase_results: tuple[JvmPhaseResult, ...],
) -> JvmExecutionReport:
    """Create an aggregate report and derive signatures from failed phases."""
    expected_hashes = {phase.phase: phase.command_plan.content_hash for phase in bundle.phases}
    for result in phase_results:
        if expected_hashes[result.phase] != result.command_plan_hash:
            raise ValueError("JVM phase result is bound to another command plan")
    signatures = tuple(
        sorted(
            {
                signature
                for result in phase_results
                if (signature := failure_signature_for(result)) is not None
            },
            key=lambda item: item.signature,
        )
    )
    return JvmExecutionReport(
        target_selection=bundle.target_selection,
        execution_plan_content_hash=bundle.content_hash,
        status=_report_status(phase_results),
        phase_results=phase_results,
        failure_signatures=signatures,
    )


def failure_signature_for(result: JvmPhaseResult) -> JvmFailureSignature | None:
    """Derive a stable signature while preserving raw logs separately."""
    if not result.is_failure:
        return None
    assert result.failure_category is not None
    assert result.failure_code is not None
    normalized = normalize_jvm_message(result.normalized_summary)
    return JvmFailureSignature(
        category=result.failure_category,
        phase=result.phase,
        failure_code=result.failure_code,
        normalized_message=normalized,
        signature=_failure_signature(
            category=result.failure_category,
            phase=result.phase,
            failure_code=result.failure_code,
            normalized_message=normalized,
        ),
    )


def normalize_jvm_message(message: str) -> str:
    """Remove volatile process identities without discarding diagnostic meaning."""
    value = _UUID_PATTERN.sub("<uuid>", message)
    value = _ISO_TIMESTAMP_PATTERN.sub("<timestamp>", value)
    value = _SHA_IN_TEXT_PATTERN.sub("<sha256>", value)
    value = _WINDOWS_PATH_PATTERN.sub("<workspace>", value)
    value = _WORKSPACE_PATH_PATTERN.sub("<workspace>", value)
    value = _LINE_WORD_PATTERN.sub("line <n>", value)
    value = _LINE_COLUMN_PATTERN.sub("<n>", value)
    value = _WHITESPACE_PATTERN.sub(" ", value).strip()
    if not value:
        value = "unspecified JVM failure"
    return value[:_MAX_MESSAGE_LENGTH]


def _report_status(results: tuple[JvmPhaseResult, ...]) -> JvmExecutionReportStatus:
    if any(result.is_failure for result in results):
        return JvmExecutionReportStatus.FAILED
    if len(results) != len(tuple(JvmExecutionPhase)) or any(
        result.status is not JvmPhaseResultStatus.PASSED for result in results
    ):
        return JvmExecutionReportStatus.INCOMPLETE
    return JvmExecutionReportStatus.PASSED


def _failure_signature(
    *,
    category: JvmFailureCategory,
    phase: JvmExecutionPhase,
    failure_code: str,
    normalized_message: str,
) -> str:
    return hashlib.sha256(
        _canonical_json(
            {
                "category": category.value,
                "phase": phase.value,
                "failure_code": failure_code,
                "normalized_message": normalized_message,
            }
        )
    ).hexdigest()


def _require_canonical(values: tuple[JvmEvidenceReference, ...], *, label: str) -> None:
    ordered = tuple(sorted(values))
    if values != ordered or len(values) != len(set(values)):
        raise ValueError(f"{label} must be canonical and unique")


def _validate_timestamps(started_at: datetime | None, completed_at: datetime | None) -> None:
    for value in (started_at, completed_at):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("JVM evidence timestamps must be timezone-aware")
    if started_at is not None and completed_at is not None and completed_at < started_at:
        raise ValueError("JVM evidence completion cannot precede its start")


def _validate_sha256(value: str, *, label: str) -> None:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase SHA-256")


def _validate_normalized_text(value: str, *, label: str) -> None:
    if not value or value != " ".join(value.split()):
        raise ValueError(f"{label} must be normalized")


def _canonical_json(value: dict[str, object]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
