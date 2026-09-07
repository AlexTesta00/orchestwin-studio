"""Immutable durable workflow-run state shared by orchestration adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final
from uuid import UUID, uuid4

from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.requirements_primitives import (
    normalize_required_text,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionProfileReference,
)

_MAX_ARTIFACT_TYPE_LENGTH: Final = 100
_MAX_ISSUE_CODE_LENGTH: Final = 100
_MAX_ISSUE_SUMMARY_LENGTH: Final = 1000
_MAX_ERROR_CODE_LENGTH: Final = 100
_MAX_ERROR_SUMMARY_LENGTH: Final = 2000


class WorkflowRunStatus(StrEnum):
    """Durable lifecycle states of one governed project workflow run."""

    DRAFT = "DRAFT"
    RUNNING = "RUNNING"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    PAUSED = "PAUSED"
    PAUSED_NEEDS_HUMAN = "PAUSED_NEEDS_HUMAN"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    COMPLETED_PENDING_FINAL_APPROVAL = "COMPLETED_PENDING_FINAL_APPROVAL"
    APPROVED = "APPROVED"


class WorkflowStage(StrEnum):
    """Common and brownfield-specific stages of the explicit project workflow."""

    INTAKE = "INTAKE"
    SOURCE_INGESTION = "SOURCE_INGESTION"
    STACK_DETECTION = "STACK_DETECTION"
    ARCHITECTURE_RECOVERY = "ARCHITECTURE_RECOVERY"
    REQUIREMENTS_INFERENCE = "REQUIREMENTS_INFERENCE"
    BASELINE_EXECUTION = "BASELINE_EXECUTION"
    BRIEF_APPROVAL = "BRIEF_APPROVAL"
    TEAM_SELECTION = "TEAM_SELECTION"
    TEAM_APPROVAL = "TEAM_APPROVAL"
    USER_MODELING = "USER_MODELING"
    USER_TWIN_APPROVAL = "USER_TWIN_APPROVAL"
    REQUIREMENTS = "REQUIREMENTS"
    REQUIREMENTS_APPROVAL = "REQUIREMENTS_APPROVAL"
    DESIGN_EXPLORATION = "DESIGN_EXPLORATION"
    PATCH_PLANNING = "PATCH_PLANNING"
    DESIGN_APPROVAL = "DESIGN_APPROVAL"
    ARCHITECTURE_AND_TEST_PLAN = "ARCHITECTURE_AND_TEST_PLAN"
    ARCHITECTURE_APPROVAL = "ARCHITECTURE_APPROVAL"
    IMPLEMENTATION = "IMPLEMENTATION"
    EXECUTION = "EXECUTION"
    SYNTHETIC_EVALUATION = "SYNTHETIC_EVALUATION"
    REVISION_DECISION = "REVISION_DECISION"
    FINAL_REVIEW = "FINAL_REVIEW"
    FINAL_APPROVAL = "FINAL_APPROVAL"
    EXPORT = "EXPORT"


class WorkflowBlockingIssueSource(StrEnum):
    """Inspectable origin of one workflow-blocking issue."""

    POLICY = "POLICY"
    OPERATIONAL_LIMIT = "OPERATIONAL_LIMIT"
    HUMAN_DECISION = "HUMAN_DECISION"
    EXECUTION = "EXECUTION"
    SYSTEM = "SYSTEM"


@dataclass(frozen=True, slots=True)
class WorkflowArtifactReference:
    """Exact immutable artifact version referenced by graph state."""

    artifact_type: str
    artifact_id: UUID
    version_number: int
    content_hash: str

    def __post_init__(self) -> None:
        normalized_type = normalize_required_text(
            self.artifact_type,
            label="workflow artifact type",
            maximum_length=_MAX_ARTIFACT_TYPE_LENGTH,
        )
        if normalized_type != self.artifact_type:
            raise ValueError("workflow artifact type must be normalized")
        validate_positive_integer(
            self.version_number,
            label="workflow artifact version",
        )
        validate_sha256(
            self.content_hash,
            label="workflow artifact content hash",
        )

    @property
    def sort_key(self) -> tuple[str, str, int, str]:
        """Return the canonical artifact-reference ordering key."""
        return (
            self.artifact_type,
            self.artifact_id.hex,
            self.version_number,
            self.content_hash,
        )

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible reference snapshot."""
        return {
            "artifact_type": self.artifact_type,
            "artifact_id": str(self.artifact_id),
            "version_number": self.version_number,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class WorkflowCapabilityState:
    """Exact capability decision visible to routing, API, UI, and exports."""

    selected_profile: ExecutionProfileReference | None = None
    capability_status: ExecutionCapabilityStatus | None = None
    unsupported_requirements: tuple[str, ...] = ()
    owner_decision_required: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.unsupported_requirements, list):
            object.__setattr__(
                self,
                "unsupported_requirements",
                tuple(self.unsupported_requirements),
            )
        elif not isinstance(self.unsupported_requirements, tuple):
            raise ValueError("unsupported capability requirements must be an immutable sequence")

        if (self.selected_profile is None) != (self.capability_status is None):
            raise ValueError("workflow capability profile and status must be supplied together")

        normalized = tuple(
            normalize_required_text(
                item,
                label="unsupported capability requirement",
                maximum_length=_MAX_ISSUE_SUMMARY_LENGTH,
            )
            for item in self.unsupported_requirements
        )
        if normalized != self.unsupported_requirements:
            raise ValueError("unsupported capability requirements must be normalized")
        if normalized != tuple(sorted(set(normalized))):
            raise ValueError("unsupported capability requirements must be canonical and unique")

        if self.owner_decision_required and not self.unsupported_requirements:
            raise ValueError(
                "capability owner decision requires an explicit unsupported requirement"
            )

    def to_snapshot(self) -> dict[str, object]:
        """Return deterministic capability metadata."""
        return {
            "selected_profile": (
                self.selected_profile.to_snapshot() if self.selected_profile is not None else None
            ),
            "capability_status": (
                self.capability_status.value if self.capability_status is not None else None
            ),
            "unsupported_requirements": list(self.unsupported_requirements),
            "owner_decision_required": self.owner_decision_required,
        }


@dataclass(frozen=True, slots=True)
class WorkflowFailureCounter:
    """Bounded repair count associated with one stable failure signature."""

    failure_signature: str
    repair_count: int
    identical_failure_count: int

    def __post_init__(self) -> None:
        normalized = normalize_required_text(
            self.failure_signature,
            label="workflow failure signature",
            maximum_length=256,
        )
        if normalized != self.failure_signature:
            raise ValueError("workflow failure signature must be normalized")
        if self.repair_count < 0 or self.identical_failure_count < 0:
            raise ValueError("workflow failure counters must not be negative")
        if self.identical_failure_count > self.repair_count:
            raise ValueError("identical failure count cannot exceed repair count")

    @property
    def sort_key(self) -> str:
        return self.failure_signature

    def to_snapshot(self) -> dict[str, object]:
        return {
            "failure_signature": self.failure_signature,
            "repair_count": self.repair_count,
            "identical_failure_count": self.identical_failure_count,
        }


@dataclass(frozen=True, slots=True)
class WorkflowIterationCounters:
    """Explicit high-level loop counters and repair counters."""

    clarification_count: int = 0
    requirements_revision_count: int = 0
    design_cycle_count: int = 0
    architecture_revision_count: int = 0
    failure_counters: tuple[WorkflowFailureCounter, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.failure_counters, list):
            object.__setattr__(self, "failure_counters", tuple(self.failure_counters))
        elif not isinstance(self.failure_counters, tuple):
            raise ValueError("workflow failure counters must be an immutable sequence")

        values = (
            self.clarification_count,
            self.requirements_revision_count,
            self.design_cycle_count,
            self.architecture_revision_count,
        )
        if any(isinstance(value, bool) or value < 0 for value in values):
            raise ValueError("workflow iteration counters must be non-negative integers")

        ordered = tuple(sorted(self.failure_counters, key=lambda item: item.sort_key))
        if self.failure_counters != ordered:
            raise ValueError("workflow failure counters must use canonical order")
        if len({item.failure_signature for item in ordered}) != len(ordered):
            raise ValueError("workflow failure counters must use unique signatures")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "clarification_count": self.clarification_count,
            "requirements_revision_count": self.requirements_revision_count,
            "design_cycle_count": self.design_cycle_count,
            "architecture_revision_count": self.architecture_revision_count,
            "failure_counters": [item.to_snapshot() for item in self.failure_counters],
        }


@dataclass(frozen=True, slots=True)
class WorkflowBudgetState:
    """Observed model, cost, sandbox, and elapsed-time usage."""

    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_micros: int = 0
    sandbox_elapsed_seconds: int = 0
    project_elapsed_seconds: int = 0

    def __post_init__(self) -> None:
        values = (
            self.model_calls,
            self.input_tokens,
            self.output_tokens,
            self.estimated_cost_micros,
            self.sandbox_elapsed_seconds,
            self.project_elapsed_seconds,
        )
        if any(isinstance(value, bool) or value < 0 for value in values):
            raise ValueError("workflow budget values must be non-negative integers")

    def to_snapshot(self) -> dict[str, int]:
        return {
            "model_calls": self.model_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost_micros": self.estimated_cost_micros,
            "sandbox_elapsed_seconds": self.sandbox_elapsed_seconds,
            "project_elapsed_seconds": self.project_elapsed_seconds,
        }


@dataclass(frozen=True, slots=True)
class WorkflowBlockingIssue:
    """One typed issue preventing autonomous workflow progress."""

    code: str
    source: WorkflowBlockingIssueSource
    summary: str
    recoverable: bool

    def __post_init__(self) -> None:
        normalized_code = normalize_required_text(
            self.code,
            label="workflow blocking issue code",
            maximum_length=_MAX_ISSUE_CODE_LENGTH,
        )
        if normalized_code != self.code or not self.code.replace("_", "").isalnum():
            raise ValueError("workflow blocking issue code must be a normalized identifier")

        normalized_summary = normalize_required_text(
            self.summary,
            label="workflow blocking issue summary",
            maximum_length=_MAX_ISSUE_SUMMARY_LENGTH,
        )
        if normalized_summary != self.summary:
            raise ValueError("workflow blocking issue summary must be normalized")

    @property
    def sort_key(self) -> tuple[str, str, str]:
        return (self.source.value, self.code, self.summary)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "code": self.code,
            "source": self.source.value,
            "summary": self.summary,
            "recoverable": self.recoverable,
        }


@dataclass(frozen=True, slots=True)
class WorkflowErrorSummary:
    """Public concise error state without private reasoning or raw logs."""

    code: str
    summary: str
    retryable: bool

    def __post_init__(self) -> None:
        normalized_code = normalize_required_text(
            self.code,
            label="workflow error code",
            maximum_length=_MAX_ERROR_CODE_LENGTH,
        )
        if normalized_code != self.code or not self.code.replace("_", "").isalnum():
            raise ValueError("workflow error code must be a normalized identifier")

        normalized_summary = normalize_required_text(
            self.summary,
            label="workflow error summary",
            maximum_length=_MAX_ERROR_SUMMARY_LENGTH,
        )
        if normalized_summary != self.summary:
            raise ValueError("workflow error summary must be normalized")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "code": self.code,
            "summary": self.summary,
            "retryable": self.retryable,
        }


@dataclass(frozen=True, slots=True)
class WorkflowRun:
    """Authoritative immutable state of one owner-scoped workflow execution."""

    id: UUID
    project_id: UUID
    owner_user_id: UUID
    project_mode: ProjectMode
    current_stage: WorkflowStage
    status: WorkflowRunStatus
    artifact_references: tuple[WorkflowArtifactReference, ...]
    pending_gate_id: UUID | None
    latest_source_revision_id: UUID | None
    latest_execution_attempt_id: UUID | None
    latest_evaluation_run_id: UUID | None
    iteration_counters: WorkflowIterationCounters
    budget_state: WorkflowBudgetState
    capability_state: WorkflowCapabilityState
    blocking_issues: tuple[WorkflowBlockingIssue, ...]
    last_error: WorkflowErrorSummary | None
    state_version: int
    checkpoint_sequence: int
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    resume_status: WorkflowRunStatus | None = None

    def __post_init__(self) -> None:
        if isinstance(self.artifact_references, list):
            object.__setattr__(
                self,
                "artifact_references",
                tuple(self.artifact_references),
            )
        elif not isinstance(self.artifact_references, tuple):
            raise ValueError("workflow artifact references must be an immutable sequence")

        if isinstance(self.blocking_issues, list):
            object.__setattr__(self, "blocking_issues", tuple(self.blocking_issues))
        elif not isinstance(self.blocking_issues, tuple):
            raise ValueError("workflow blocking issues must be an immutable sequence")

        validate_positive_integer(self.state_version, label="workflow run state version")
        if self.checkpoint_sequence < 0:
            raise ValueError("workflow checkpoint sequence must not be negative")

        timestamps = (
            self.created_at,
            self.updated_at,
            self.started_at,
            self.completed_at,
        )
        if any(value is not None and value.tzinfo is None for value in timestamps):
            raise ValueError("workflow run timestamps must be timezone-aware")
        if self.updated_at < self.created_at:
            raise ValueError("workflow run updated_at must not precede created_at")
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("workflow run started_at must not precede created_at")
        if self.completed_at is not None and self.completed_at < self.created_at:
            raise ValueError("workflow run completed_at must not precede created_at")

        ordered_artifacts = tuple(sorted(self.artifact_references, key=lambda item: item.sort_key))
        if self.artifact_references != ordered_artifacts:
            raise ValueError("workflow artifact references must use canonical order")
        artifact_keys = {
            (item.artifact_type, item.artifact_id, item.version_number)
            for item in self.artifact_references
        }
        if len(artifact_keys) != len(self.artifact_references):
            raise ValueError("workflow artifact references must be unique")

        ordered_issues = tuple(sorted(self.blocking_issues, key=lambda item: item.sort_key))
        if self.blocking_issues != ordered_issues:
            raise ValueError("workflow blocking issues must use canonical order")
        if len({(item.source, item.code) for item in ordered_issues}) != len(ordered_issues):
            raise ValueError("workflow blocking issue identities must be unique")

        paused = self.status in {
            WorkflowRunStatus.PAUSED,
            WorkflowRunStatus.PAUSED_NEEDS_HUMAN,
        }
        if paused:
            if self.resume_status not in {
                WorkflowRunStatus.RUNNING,
                WorkflowRunStatus.WAITING_FOR_HUMAN,
            }:
                raise ValueError("paused workflow runs must preserve a resumable status")
        elif self.resume_status is not None:
            raise ValueError("only paused workflow runs may preserve a resume status")

        waiting_for_gate = self.status is WorkflowRunStatus.WAITING_FOR_HUMAN or (
            paused and self.resume_status is WorkflowRunStatus.WAITING_FOR_HUMAN
        )
        if waiting_for_gate != (self.pending_gate_id is not None):
            raise ValueError("workflow pending gate must match waiting-for-human state")

        if self.status is WorkflowRunStatus.DRAFT:
            if self.started_at is not None:
                raise ValueError("draft workflow runs must not have a start timestamp")
        elif self.started_at is None:
            raise ValueError("non-draft workflow runs require a start timestamp")

        terminal = self.status in {
            WorkflowRunStatus.FAILED,
            WorkflowRunStatus.CANCELLED,
            WorkflowRunStatus.APPROVED,
        }
        if terminal != (self.completed_at is not None):
            raise ValueError("terminal workflow run status must match completed_at")

    def to_snapshot(self) -> dict[str, object]:
        """Return the complete canonical JSON-compatible run snapshot."""
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "owner_user_id": str(self.owner_user_id),
            "project_mode": self.project_mode.value,
            "current_stage": self.current_stage.value,
            "status": self.status.value,
            "artifact_references": [item.to_snapshot() for item in self.artifact_references],
            "pending_gate_id": str(self.pending_gate_id) if self.pending_gate_id else None,
            "latest_source_revision_id": (
                str(self.latest_source_revision_id) if self.latest_source_revision_id else None
            ),
            "latest_execution_attempt_id": (
                str(self.latest_execution_attempt_id) if self.latest_execution_attempt_id else None
            ),
            "latest_evaluation_run_id": (
                str(self.latest_evaluation_run_id) if self.latest_evaluation_run_id else None
            ),
            "iteration_counters": self.iteration_counters.to_snapshot(),
            "budget_state": self.budget_state.to_snapshot(),
            "capability_state": self.capability_state.to_snapshot(),
            "blocking_issues": [item.to_snapshot() for item in self.blocking_issues],
            "last_error": self.last_error.to_snapshot() if self.last_error else None,
            "state_version": self.state_version,
            "checkpoint_sequence": self.checkpoint_sequence,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "resume_status": self.resume_status.value if self.resume_status else None,
        }


def create_workflow_run(
    *,
    project_id: UUID,
    owner_user_id: UUID,
    project_mode: ProjectMode,
    run_id: UUID | None = None,
    created_at: datetime | None = None,
) -> WorkflowRun:
    """Create one draft run containing only stable identifiers and typed summaries."""
    timestamp = created_at or datetime.now(UTC)
    return WorkflowRun(
        id=run_id or uuid4(),
        project_id=project_id,
        owner_user_id=owner_user_id,
        project_mode=project_mode,
        current_stage=WorkflowStage.INTAKE,
        status=WorkflowRunStatus.DRAFT,
        artifact_references=(),
        pending_gate_id=None,
        latest_source_revision_id=None,
        latest_execution_attempt_id=None,
        latest_evaluation_run_id=None,
        iteration_counters=WorkflowIterationCounters(),
        budget_state=WorkflowBudgetState(),
        capability_state=WorkflowCapabilityState(),
        blocking_issues=(),
        last_error=None,
        state_version=1,
        checkpoint_sequence=0,
        created_at=timestamp,
        updated_at=timestamp,
    )
