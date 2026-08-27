"""Normalized Web execution reports with stable failure signatures and raw evidence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from orchestwin.sandbox.evidence import (
    SandboxArtifactReference,
    SandboxCommandEvidence,
    SandboxCommandStatus,
    SandboxLogReference,
    SandboxRunEvidence,
    SandboxRunStatus,
)
from orchestwin.web_execution.plans import (
    WebExecutionPhase,
    WebPhaseExecutionKind,
    WebPhasePlan,
)

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
_HEX_ADDRESS_PATTERN: Final = re.compile(r"\b0x[0-9a-fA-F]+\b")
_WINDOWS_PATH_PATTERN: Final = re.compile(
    r"(?i)\b[A-Z]:\\(?:[^\s:*?\"<>|\r\n]+\\)*[^\s:*?\"<>|\r\n]*"
)
_WORKSPACE_PATH_PATTERN: Final = re.compile(
    r"(?i)(?:/[^\s:'\"/]+)*/(?:workspaces?|workspace|tmp)/[^\s:'\"]+"
)
_LINE_WORD_PATTERN: Final = re.compile(r"(?i)\bline\s+\d+(?::\d+)?")
_LINE_COLUMN_PATTERN: Final = re.compile(r"(?<=:)\d+(?::\d+)?")
_WHITESPACE_PATTERN: Final = re.compile(r"\s+")
_MAX_NORMALIZED_MESSAGE_LENGTH: Final = 1_024


class WebPhaseResultStatus(StrEnum):
    """Normalized terminal state for one explicit Web phase."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    TIMED_OUT = "TIMED_OUT"
    RESOURCE_LIMIT_EXCEEDED = "RESOURCE_LIMIT_EXCEEDED"
    CANCELLED = "CANCELLED"
    RUNTIME_ERROR = "RUNTIME_ERROR"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    NOT_RUN = "NOT_RUN"


class WebFailureCategory(StrEnum):
    """Cross-tool failure categories used by repair routing."""

    VALIDATION = "VALIDATION"
    DEPENDENCY_INSTALL = "DEPENDENCY_INSTALL"
    STATIC_CHECK = "STATIC_CHECK"
    BUILD = "BUILD"
    TEST = "TEST"
    RUNTIME = "RUNTIME"
    HEALTH_CHECK = "HEALTH_CHECK"
    BROWSER = "BROWSER"
    ARTIFACT_COLLECTION = "ARTIFACT_COLLECTION"
    TIMEOUT = "TIMEOUT"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    CANCELLED = "CANCELLED"
    POLICY = "POLICY"


class WebExecutionReportStatus(StrEnum):
    """Aggregate status without converting a partial run into success."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True, slots=True, order=True)
class WebEvidenceReference:
    """Content-addressed raw log or artifact metadata."""

    storage_key: str
    sha256_digest: str
    size_bytes: int
    media_type: str

    def __post_init__(self) -> None:
        if not self.storage_key or self.storage_key != self.storage_key.strip():
            raise ValueError("Web evidence storage key must be normalized")
        _validate_sha256(self.sha256_digest, label="Web evidence digest")
        if isinstance(self.size_bytes, bool) or self.size_bytes < 0:
            raise ValueError("Web evidence size must be non-negative")
        if (
            not self.media_type
            or self.media_type != self.media_type.strip()
            or "/" not in self.media_type
        ):
            raise ValueError("Web evidence media type must be normalized")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "storage_key": self.storage_key,
            "sha256_digest": self.sha256_digest,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
        }


@dataclass(frozen=True, slots=True, order=True)
class WebNormalizedFinding:
    """Tool-neutral issue while retaining the source tool and location."""

    code: str
    message: str
    source_tool: str
    location: str | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.code, "Web finding code"),
            (self.message, "Web finding message"),
            (self.source_tool, "Web finding source tool"),
        ):
            if not value or value != " ".join(value.split()):
                raise ValueError(f"{label} must be normalized")
        if self.location is not None and (
            not self.location or self.location != " ".join(self.location.split())
        ):
            raise ValueError("Web finding location must be normalized")

    def to_snapshot(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "message": self.message,
            "source_tool": self.source_tool,
            "location": self.location,
        }


@dataclass(frozen=True, slots=True)
class WebPhaseResult:
    """One normalized phase outcome with original evidence references preserved."""

    phase: WebExecutionPhase
    status: WebPhaseResultStatus
    command_plan_hashes: tuple[str, ...]
    started_at: datetime | None
    completed_at: datetime | None
    exit_codes: tuple[int, ...]
    stdout_refs: tuple[WebEvidenceReference, ...]
    stderr_refs: tuple[WebEvidenceReference, ...]
    artifact_refs: tuple[WebEvidenceReference, ...]
    findings: tuple[WebNormalizedFinding, ...]
    failure_category: WebFailureCategory | None
    failure_code: str | None
    normalized_summary: str

    def __post_init__(self) -> None:
        _validate_canonical_hashes(self.command_plan_hashes)
        _validate_timestamps(self.started_at, self.completed_at)
        if any(isinstance(code, bool) or not 0 <= code <= 255 for code in self.exit_codes):
            raise ValueError("Web phase exit codes must be integers from zero to 255")
        _validate_canonical_evidence(self.stdout_refs, label="stdout references")
        _validate_canonical_evidence(self.stderr_refs, label="stderr references")
        _validate_canonical_evidence(self.artifact_refs, label="artifact references")
        ordered_findings = tuple(
            sorted(
                self.findings,
                key=lambda finding: (
                    finding.code,
                    finding.source_tool,
                    finding.location or "",
                    finding.message,
                ),
            )
        )
        if self.findings != ordered_findings or len(self.findings) != len(set(self.findings)):
            raise ValueError("Web normalized findings must be canonical and unique")
        if not self.normalized_summary or self.normalized_summary != " ".join(
            self.normalized_summary.split()
        ):
            raise ValueError("Web phase summary must be normalized")

        failed = self.status in {
            WebPhaseResultStatus.FAILED,
            WebPhaseResultStatus.TIMED_OUT,
            WebPhaseResultStatus.RESOURCE_LIMIT_EXCEEDED,
            WebPhaseResultStatus.CANCELLED,
            WebPhaseResultStatus.RUNTIME_ERROR,
            WebPhaseResultStatus.POLICY_BLOCKED,
        }
        if failed:
            if self.failure_category is None or not self.failure_code:
                raise ValueError("failed Web phase requires a category and stable code")
            if self.status is not WebPhaseResultStatus.POLICY_BLOCKED and (
                not self.stdout_refs and not self.stderr_refs
            ):
                raise ValueError("executed failed Web phase must retain raw log evidence")
        elif self.failure_category is not None or self.failure_code is not None:
            raise ValueError("non-failed Web phase must not expose failure metadata")

        executed = self.status in {
            WebPhaseResultStatus.PASSED,
            WebPhaseResultStatus.FAILED,
            WebPhaseResultStatus.TIMED_OUT,
            WebPhaseResultStatus.RESOURCE_LIMIT_EXCEEDED,
            WebPhaseResultStatus.CANCELLED,
            WebPhaseResultStatus.RUNTIME_ERROR,
        }
        if executed and (self.started_at is None or self.completed_at is None):
            raise ValueError("executed Web phase requires start and completion timestamps")
        if self.status in {
            WebPhaseResultStatus.SKIPPED,
            WebPhaseResultStatus.NOT_RUN,
            WebPhaseResultStatus.POLICY_BLOCKED,
        } and (self.exit_codes or self.stdout_refs or self.stderr_refs):
            raise ValueError("unexecuted Web phase must not fabricate process evidence")

    @property
    def is_failure(self) -> bool:
        return self.failure_category is not None

    def to_snapshot(self) -> dict[str, object]:
        return {
            "phase": self.phase.value,
            "status": self.status.value,
            "command_plan_hashes": list(self.command_plan_hashes),
            "started_at": None if self.started_at is None else self.started_at.isoformat(),
            "completed_at": (None if self.completed_at is None else self.completed_at.isoformat()),
            "exit_codes": list(self.exit_codes),
            "stdout_refs": [reference.to_snapshot() for reference in self.stdout_refs],
            "stderr_refs": [reference.to_snapshot() for reference in self.stderr_refs],
            "artifact_refs": [reference.to_snapshot() for reference in self.artifact_refs],
            "findings": [finding.to_snapshot() for finding in self.findings],
            "failure_category": (
                None if self.failure_category is None else self.failure_category.value
            ),
            "failure_code": self.failure_code,
            "normalized_summary": self.normalized_summary,
        }


@dataclass(frozen=True, slots=True)
class WebFailureSignature:
    """Stable identity for bounded repair accounting across reruns."""

    category: WebFailureCategory
    phase: WebExecutionPhase
    profile_id: str
    profile_version: str
    failure_code: str
    normalized_message: str
    subject_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for value, label in (
            (self.profile_id, "Web failure profile ID"),
            (self.profile_version, "Web failure profile version"),
            (self.failure_code, "Web failure code"),
            (self.normalized_message, "Web failure normalized message"),
        ):
            if not value or value != value.strip():
                raise ValueError(f"{label} must be normalized")
        if self.normalized_message != normalize_failure_message(self.normalized_message):
            raise ValueError("Web failure message must use stable normalization")
        _validate_canonical_text(self.subject_refs, label="Web failure subject references")

    @property
    def digest(self) -> str:
        payload = {
            "category": self.category.value,
            "phase": self.phase.value,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "failure_code": self.failure_code,
            "normalized_message": self.normalized_message,
            "subject_refs": list(self.subject_refs),
        }
        return hashlib.sha256(_canonical_json(payload)).hexdigest()

    def to_snapshot(self) -> dict[str, object]:
        return {
            "category": self.category.value,
            "phase": self.phase.value,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "failure_code": self.failure_code,
            "normalized_message": self.normalized_message,
            "subject_refs": list(self.subject_refs),
            "digest": self.digest,
        }


@dataclass(frozen=True, slots=True)
class WebExecutionReport:
    """Ordered phase evidence bound to exact source, profile, runner, and policy hashes."""

    source_revision_content_hash: str
    source_tree_hash: str
    profile_id: str
    profile_version: str
    runner_image_digest: str
    policy_content_hash: str
    phase_results: tuple[WebPhaseResult, ...]

    def __post_init__(self) -> None:
        for value, label in (
            (self.source_revision_content_hash, "Web report source revision hash"),
            (self.source_tree_hash, "Web report source tree hash"),
            (self.runner_image_digest, "Web report runner image digest"),
            (self.policy_content_hash, "Web report policy hash"),
        ):
            _validate_sha256(value, label=label)
        for value, label in (
            (self.profile_id, "Web report profile ID"),
            (self.profile_version, "Web report profile version"),
        ):
            if not value or value != value.strip():
                raise ValueError(f"{label} must be normalized")
        phases = tuple(result.phase for result in self.phase_results)
        if len(phases) != len(set(phases)):
            raise ValueError("Web execution report phase results must be unique")
        expected_order = {phase: index for index, phase in enumerate(WebExecutionPhase)}
        if self.phase_results != tuple(
            sorted(self.phase_results, key=lambda result: expected_order[result.phase])
        ):
            raise ValueError("Web execution report phases must use canonical order")

    @property
    def status(self) -> WebExecutionReportStatus:
        if any(result.is_failure for result in self.phase_results):
            return WebExecutionReportStatus.FAILED
        if len(self.phase_results) != len(tuple(WebExecutionPhase)) or any(
            result.status is WebPhaseResultStatus.NOT_RUN for result in self.phase_results
        ):
            return WebExecutionReportStatus.INCOMPLETE
        return WebExecutionReportStatus.PASSED

    def failure_signatures(self) -> tuple[WebFailureSignature, ...]:
        signatures = [
            create_web_failure_signature(
                result,
                profile_id=self.profile_id,
                profile_version=self.profile_version,
            )
            for result in self.phase_results
            if result.is_failure
        ]
        return tuple(sorted(signatures, key=lambda signature: signature.digest))

    def to_snapshot(self) -> dict[str, object]:
        return {
            "source_revision_content_hash": self.source_revision_content_hash,
            "source_tree_hash": self.source_tree_hash,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "runner_image_digest": self.runner_image_digest,
            "policy_content_hash": self.policy_content_hash,
            "status": self.status.value,
            "phase_results": [result.to_snapshot() for result in self.phase_results],
            "failure_signatures": [
                signature.to_snapshot() for signature in self.failure_signatures()
            ],
        }


def normalize_web_command_phase(
    phase_plan: WebPhasePlan,
    *,
    runs: tuple[SandboxRunEvidence, ...],
    findings: tuple[WebNormalizedFinding, ...] = (),
) -> WebPhaseResult:
    """Normalize exact sandbox runs for one command-backed phase without losing raw logs."""
    if phase_plan.execution_kind is not WebPhaseExecutionKind.COMMAND_PLANS:
        raise ValueError("sandbox normalization requires a command-backed Web phase")
    if len(runs) != len(phase_plan.command_plans):
        raise ValueError("Web phase requires one sandbox run for each command plan")

    for plan, run in zip(phase_plan.command_plans, runs, strict=True):
        if run.plan_id != plan.plan_id or run.plan_content_hash != plan.content_hash:
            raise ValueError("sandbox evidence targets another Web command plan")
        if run.profile_id != plan.profile_id or run.profile_version != plan.profile_version:
            raise ValueError("sandbox evidence targets another Web execution profile")

    command_evidence = tuple(evidence for run in runs for evidence in run.command_evidence)
    status, category, failure_code = _normalized_run_status(
        phase_plan.phase,
        runs=runs,
        command_evidence=command_evidence,
    )
    failure_message = next(
        (
            message
            for message in (
                *(run.failure_message for run in reversed(runs)),
                *(evidence.failure_message for evidence in reversed(command_evidence)),
            )
            if message
        ),
        None,
    )
    normalized_summary = (
        _success_summary(phase_plan.phase)
        if category is None
        else normalize_failure_message(
            failure_message or _failure_summary(phase_plan.phase, status=status)
        )
    )
    return WebPhaseResult(
        phase=phase_plan.phase,
        status=status,
        command_plan_hashes=tuple(sorted(plan.content_hash for plan in phase_plan.command_plans)),
        started_at=min(run.started_at for run in runs),
        completed_at=max(run.finished_at for run in runs),
        exit_codes=tuple(
            evidence.exit_code for evidence in command_evidence if evidence.exit_code is not None
        ),
        stdout_refs=_canonical_evidence(
            tuple(_log_reference(evidence.stdout_log) for evidence in command_evidence)
        ),
        stderr_refs=_canonical_evidence(
            tuple(_log_reference(evidence.stderr_log) for evidence in command_evidence)
        ),
        artifact_refs=_canonical_evidence(
            tuple(
                _artifact_reference(artifact)
                for evidence in command_evidence
                for artifact in evidence.artifacts
            )
        ),
        findings=_canonical_findings(findings),
        failure_category=category,
        failure_code=failure_code,
        normalized_summary=normalized_summary,
    )


def create_web_no_op_phase_result(phase_plan: WebPhasePlan) -> WebPhaseResult:
    """Represent an explicitly inapplicable phase without fabricating execution evidence."""
    if phase_plan.execution_kind is not WebPhaseExecutionKind.NO_OP:
        raise ValueError("no-op result requires a no-op Web phase plan")
    assert phase_plan.no_op_reason is not None
    return WebPhaseResult(
        phase=phase_plan.phase,
        status=WebPhaseResultStatus.SKIPPED,
        command_plan_hashes=(),
        started_at=None,
        completed_at=None,
        exit_codes=(),
        stdout_refs=(),
        stderr_refs=(),
        artifact_refs=(),
        findings=(),
        failure_category=None,
        failure_code=None,
        normalized_summary=phase_plan.no_op_reason,
    )


def create_web_policy_blocked_phase_result(
    phase: WebExecutionPhase,
    *,
    command_plan_hashes: tuple[str, ...],
    policy_issue_code: str,
    message: str,
) -> WebPhaseResult:
    """Represent deterministic policy rejection without pretending a process was started."""
    normalized_message = normalize_failure_message(message)
    return WebPhaseResult(
        phase=phase,
        status=WebPhaseResultStatus.POLICY_BLOCKED,
        command_plan_hashes=tuple(sorted(command_plan_hashes)),
        started_at=None,
        completed_at=None,
        exit_codes=(),
        stdout_refs=(),
        stderr_refs=(),
        artifact_refs=(),
        findings=(),
        failure_category=WebFailureCategory.POLICY,
        failure_code=policy_issue_code,
        normalized_summary=normalized_message,
    )


def create_web_failure_signature(
    result: WebPhaseResult,
    *,
    profile_id: str,
    profile_version: str,
) -> WebFailureSignature:
    """Create one deterministic signature from normalized, non-volatile facts."""
    if result.failure_category is None or result.failure_code is None:
        raise ValueError("Web failure signature requires a failed phase result")
    subject_refs = tuple(sorted({finding.location or finding.code for finding in result.findings}))
    return WebFailureSignature(
        category=result.failure_category,
        phase=result.phase,
        profile_id=profile_id,
        profile_version=profile_version,
        failure_code=result.failure_code,
        normalized_message=normalize_failure_message(result.normalized_summary),
        subject_refs=subject_refs,
    )


def normalize_failure_message(message: str) -> str:
    """Remove volatile runtime values while retaining failure meaning for repair accounting."""
    if not message:
        raise ValueError("Web failure message must not be empty")
    value = message
    for pattern, replacement in (
        (_ISO_TIMESTAMP_PATTERN, "<timestamp>"),
        (_UUID_PATTERN, "<uuid>"),
        (_SHA_IN_TEXT_PATTERN, "<sha256>"),
        (_HEX_ADDRESS_PATTERN, "<address>"),
        (_WINDOWS_PATH_PATTERN, "<workspace-path>"),
        (_WORKSPACE_PATH_PATTERN, "<workspace-path>"),
        (_LINE_WORD_PATTERN, "line <line>"),
        (_LINE_COLUMN_PATTERN, "<line>"),
    ):
        value = pattern.sub(replacement, value)
    value = _WHITESPACE_PATTERN.sub(" ", value).strip()
    if not value:
        raise ValueError("Web failure message becomes empty after normalization")
    return value[:_MAX_NORMALIZED_MESSAGE_LENGTH]


def _normalized_run_status(
    phase: WebExecutionPhase,
    *,
    runs: tuple[SandboxRunEvidence, ...],
    command_evidence: tuple[SandboxCommandEvidence, ...],
) -> tuple[WebPhaseResultStatus, WebFailureCategory | None, str | None]:
    statuses = tuple(run.status for run in runs)
    if all(status is SandboxRunStatus.SUCCEEDED for status in statuses):
        return WebPhaseResultStatus.PASSED, None, None
    if SandboxRunStatus.TIMED_OUT in statuses:
        return (
            WebPhaseResultStatus.TIMED_OUT,
            WebFailureCategory.TIMEOUT,
            "SANDBOX_TIMEOUT",
        )
    if SandboxRunStatus.RESOURCE_LIMIT_EXCEEDED in statuses:
        return (
            WebPhaseResultStatus.RESOURCE_LIMIT_EXCEEDED,
            WebFailureCategory.RESOURCE_LIMIT,
            "SANDBOX_RESOURCE_LIMIT",
        )
    if SandboxRunStatus.CANCELLED in statuses:
        return (
            WebPhaseResultStatus.CANCELLED,
            WebFailureCategory.CANCELLED,
            "SANDBOX_CANCELLED",
        )
    if SandboxRunStatus.RUNTIME_ERROR in statuses:
        return (
            WebPhaseResultStatus.RUNTIME_ERROR,
            WebFailureCategory.RUNTIME,
            "SANDBOX_RUNTIME_ERROR",
        )
    failing_command = next(
        (
            evidence
            for evidence in reversed(command_evidence)
            if evidence.status is not SandboxCommandStatus.SUCCEEDED
        ),
        None,
    )
    parser_id = None if failing_command is None else failing_command.output_parser_id
    code = _phase_failure_code(phase, parser_id=parser_id)
    return WebPhaseResultStatus.FAILED, _phase_failure_category(phase), code


def _phase_failure_category(phase: WebExecutionPhase) -> WebFailureCategory:
    return {
        WebExecutionPhase.VALIDATE: WebFailureCategory.VALIDATION,
        WebExecutionPhase.SETUP: WebFailureCategory.DEPENDENCY_INSTALL,
        WebExecutionPhase.STATIC_CHECK: WebFailureCategory.STATIC_CHECK,
        WebExecutionPhase.BUILD: WebFailureCategory.BUILD,
        WebExecutionPhase.TEST: WebFailureCategory.TEST,
        WebExecutionPhase.RUN: WebFailureCategory.RUNTIME,
        WebExecutionPhase.HEALTH_CHECK: WebFailureCategory.HEALTH_CHECK,
        WebExecutionPhase.BROWSER_EVIDENCE: WebFailureCategory.BROWSER,
        WebExecutionPhase.COLLECT_ARTIFACTS: WebFailureCategory.ARTIFACT_COLLECTION,
    }[phase]


def _phase_failure_code(
    phase: WebExecutionPhase,
    *,
    parser_id: str | None,
) -> str:
    parser_token = "COMMAND" if parser_id is None else _stable_code_token(parser_id)
    return f"{phase.value}_{parser_token}_FAILED"


def _stable_code_token(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").upper()


def _success_summary(phase: WebExecutionPhase) -> str:
    return f"Web {phase.value.casefold().replace('_', ' ')} phase completed successfully."


def _failure_summary(
    phase: WebExecutionPhase,
    *,
    status: WebPhaseResultStatus,
) -> str:
    return (
        f"Web {phase.value.casefold().replace('_', ' ')} phase ended with "
        f"{status.value.casefold().replace('_', ' ')}."
    )


def _log_reference(reference: SandboxLogReference) -> WebEvidenceReference:
    return WebEvidenceReference(
        storage_key=reference.storage_key,
        sha256_digest=reference.sha256_digest,
        size_bytes=reference.size_bytes,
        media_type="text/plain",
    )


def _artifact_reference(reference: SandboxArtifactReference) -> WebEvidenceReference:
    return WebEvidenceReference(
        storage_key=reference.storage_key,
        sha256_digest=reference.sha256_digest,
        size_bytes=reference.size_bytes,
        media_type=reference.media_type,
    )


def _canonical_evidence(
    values: tuple[WebEvidenceReference, ...],
) -> tuple[WebEvidenceReference, ...]:
    by_key: dict[str, WebEvidenceReference] = {}
    for value in values:
        existing = by_key.get(value.storage_key)
        if existing is not None and existing != value:
            raise ValueError("Web evidence storage key refers to conflicting metadata")
        by_key[value.storage_key] = value
    return tuple(sorted(by_key.values(), key=lambda reference: reference.storage_key))


def _canonical_findings(
    findings: tuple[WebNormalizedFinding, ...],
) -> tuple[WebNormalizedFinding, ...]:
    return tuple(
        sorted(
            set(findings),
            key=lambda finding: (
                finding.code,
                finding.source_tool,
                finding.location or "",
                finding.message,
            ),
        )
    )


def _validate_timestamps(started_at: datetime | None, completed_at: datetime | None) -> None:
    for value in (started_at, completed_at):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Web phase timestamps must be timezone-aware")
    if started_at is not None and completed_at is not None and completed_at < started_at:
        raise ValueError("Web phase completion cannot precede its start")


def _validate_canonical_hashes(values: tuple[str, ...]) -> None:
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError("Web phase command-plan hashes must be canonical and unique")
    for value in values:
        _validate_sha256(value, label="Web phase command-plan hash")


def _validate_canonical_evidence(
    values: tuple[WebEvidenceReference, ...],
    *,
    label: str,
) -> None:
    ordered = tuple(sorted(values, key=lambda reference: reference.storage_key))
    if values != ordered or len(values) != len(set(values)):
        raise ValueError(f"Web phase {label} must be canonical and unique")


def _validate_canonical_text(values: tuple[str, ...], *, label: str) -> None:
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError(f"{label} must be canonical and unique")
    if any(not value or value != " ".join(value.split()) for value in values):
        raise ValueError(f"{label} must contain normalized values")


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
