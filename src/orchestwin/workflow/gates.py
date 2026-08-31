from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final
from uuid import UUID, uuid4

DEFAULT_GATE_ITERATION_LIMIT: Final = 3
MAX_GATE_REASON_LENGTH: Final = 2000


class HumanGateType(StrEnum):
    """Human gates supported by the governed workflow."""

    PROJECT_BRIEF = "PROJECT_BRIEF"
    AGENT_TEAM = "AGENT_TEAM"
    USER_MODELING = "USER_MODELING"
    REQUIREMENTS = "REQUIREMENTS"
    DESIGN = "DESIGN"
    ARCHITECTURE = "ARCHITECTURE"
    HIGH_IMPACT_OPERATION = "HIGH_IMPACT_OPERATION"
    FINAL_OUTPUT = "FINAL_OUTPUT"


class HumanGateStatus(StrEnum):
    """Lifecycle states of one artifact-bound gate iteration."""

    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    STALE = "STALE"
    PAUSED_NEEDS_HUMAN = "PAUSED_NEEDS_HUMAN"


class HumanGateAction(StrEnum):
    """Actions available to the project owner."""

    SUBMIT = "SUBMIT"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_REVISION = "REQUEST_REVISION"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    CANCEL = "CANCEL"


class HumanGateEventKind(StrEnum):
    """Auditable owner and system events emitted by transitions."""

    SUBMIT = "SUBMIT"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_REVISION = "REQUEST_REVISION"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    CANCEL = "CANCEL"
    ARTIFACT_SUPERSEDED = "ARTIFACT_SUPERSEDED"


class HumanGateTransitionStatus(StrEnum):
    """Stable outcomes of a gate transition attempt."""

    APPLIED = "APPLIED"
    NO_CHANGE = "NO_CHANGE"
    REJECTED = "REJECTED"


class HumanGateIssueCode(StrEnum):
    """Expected reasons a transition may be rejected."""

    INVALID_TRANSITION = "INVALID_TRANSITION"
    REASON_REQUIRED = "REASON_REQUIRED"
    REASON_TOO_LONG = "REASON_TOO_LONG"
    ACTOR_NOT_OWNER = "ACTOR_NOT_OWNER"
    TIMESTAMP_NOT_AWARE = "TIMESTAMP_NOT_AWARE"
    TIMESTAMP_OUT_OF_ORDER = "TIMESTAMP_OUT_OF_ORDER"
    ARTIFACT_SCOPE_MISMATCH = "ARTIFACT_SCOPE_MISMATCH"


@dataclass(frozen=True, slots=True)
class GateArtifactReference:
    """Exact immutable artifact snapshot governed by a gate."""

    project_id: UUID
    gate_type: HumanGateType
    artifact_id: UUID
    version: int
    content_hash: str

    def __post_init__(self) -> None:
        """Protect artifact identity and hash invariants."""
        if self.version < 1:
            raise ValueError("gate artifact version must be positive")

        if len(self.content_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.content_hash
        ):
            raise ValueError("gate artifact hash must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class HumanGate:
    """Current state of one human-gate iteration."""

    id: UUID
    project_id: UUID
    owner_user_id: UUID
    gate_type: HumanGateType
    artifact: GateArtifactReference
    iteration: int
    max_iterations: int
    status: HumanGateStatus
    created_at: datetime
    updated_at: datetime
    event_sequence: int = 0
    resume_status: HumanGateStatus | None = None

    def __post_init__(self) -> None:
        """Protect scope, iteration, time, and pause invariants."""
        if self.artifact.project_id != self.project_id:
            raise ValueError("gate artifact must belong to the gate project")

        if self.artifact.gate_type is not self.gate_type:
            raise ValueError("gate artifact type must match the gate type")

        if self.max_iterations < 1:
            raise ValueError("gate iteration limit must be positive")

        if not 1 <= self.iteration <= self.max_iterations:
            raise ValueError("gate iteration must be within its configured limit")

        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("gate timestamps must be timezone-aware")

        if self.updated_at < self.created_at:
            raise ValueError("gate updated_at must not precede created_at")

        if self.event_sequence < 0:
            raise ValueError("gate event sequence must not be negative")

        if self.status is not HumanGateStatus.DRAFT and self.event_sequence < 1:
            raise ValueError("a transitioned gate must have an event sequence")

        if self.status is HumanGateStatus.PAUSED and self.resume_status not in {
            HumanGateStatus.DRAFT,
            HumanGateStatus.PENDING_APPROVAL,
        }:
            raise ValueError("a paused gate must remember a resumable status")

        if self.status is not HumanGateStatus.PAUSED and self.resume_status is not None:
            raise ValueError("only a paused gate may contain a resume status")

        if (
            self.status is HumanGateStatus.PAUSED_NEEDS_HUMAN
            and self.iteration != self.max_iterations
        ):
            raise ValueError("iteration-limit pause requires the final iteration")


@dataclass(frozen=True, slots=True)
class HumanGateEvent:
    """Append-only event emitted by one successful transition."""

    id: UUID
    gate_id: UUID
    sequence_number: int
    kind: HumanGateEventKind
    previous_status: HumanGateStatus
    resulting_status: HumanGateStatus
    artifact: GateArtifactReference
    occurred_at: datetime
    actor_user_id: UUID | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        """Protect event ordering, actor, and reason invariants."""
        if self.sequence_number < 1:
            raise ValueError("gate event sequence must be positive")

        if self.previous_status is self.resulting_status:
            raise ValueError("gate event must change the gate status")

        if self.occurred_at.tzinfo is None:
            raise ValueError("gate event timestamp must be timezone-aware")

        if self.reason is not None:
            normalized = " ".join(self.reason.split())

            if not normalized or normalized != self.reason:
                raise ValueError("gate event reason must be normalized")

            if len(self.reason) > MAX_GATE_REASON_LENGTH:
                raise ValueError("gate event reason exceeds maximum length")

        system_event = self.kind is HumanGateEventKind.ARTIFACT_SUPERSEDED

        if system_event != (self.actor_user_id is None):
            raise ValueError("only system events may omit an actor")

        if (
            self.kind
            in {
                HumanGateEventKind.REJECT,
                HumanGateEventKind.REQUEST_REVISION,
            }
            and self.reason is None
        ):
            raise ValueError("reject and revision events require a reason")


@dataclass(frozen=True, slots=True)
class HumanGateTransitionResult:
    """Typed result of a gate transition."""

    status: HumanGateTransitionStatus
    gate: HumanGate
    event: HumanGateEvent | None = None
    issue: HumanGateIssueCode | None = None

    def __post_init__(self) -> None:
        """Protect result-shape invariants."""
        if self.status is HumanGateTransitionStatus.APPLIED:
            if self.event is None or self.issue is not None:
                raise ValueError("an applied transition requires only an event")

            return

        if self.status is HumanGateTransitionStatus.NO_CHANGE:
            if self.event is not None or self.issue is not None:
                raise ValueError("a no-change result must not contain event or issue")

            return

        if self.event is not None or self.issue is None:
            raise ValueError("a rejected transition requires only an issue")


def create_human_gate(
    *,
    project_id: UUID,
    owner_user_id: UUID,
    gate_type: HumanGateType,
    artifact: GateArtifactReference,
    iteration: int = 1,
    max_iterations: int = DEFAULT_GATE_ITERATION_LIMIT,
    gate_id: UUID | None = None,
    created_at: datetime | None = None,
) -> HumanGate:
    """Create one draft gate bound to an exact artifact snapshot."""
    timestamp = created_at or datetime.now(UTC)

    return HumanGate(
        id=gate_id or uuid4(),
        project_id=project_id,
        owner_user_id=owner_user_id,
        gate_type=gate_type,
        artifact=artifact,
        iteration=iteration,
        max_iterations=max_iterations,
        status=HumanGateStatus.DRAFT,
        created_at=timestamp,
        updated_at=timestamp,
    )


def transition_human_gate(
    gate: HumanGate,
    *,
    action: HumanGateAction,
    actor_user_id: UUID,
    occurred_at: datetime | None = None,
    reason: str | None = None,
    event_id: UUID | None = None,
) -> HumanGateTransitionResult:
    """Apply one owner action through the explicit state machine."""
    timestamp = occurred_at or datetime.now(UTC)

    issue = _operation_issue(
        gate,
        actor_user_id=actor_user_id,
        occurred_at=timestamp,
    )

    if issue is not None:
        return _rejected(
            gate,
            issue,
        )

    (
        normalized_reason,
        reason_issue,
    ) = _normalize_reason(reason)

    if reason_issue is not None:
        return _rejected(
            gate,
            reason_issue,
        )

    if (
        action
        in {
            HumanGateAction.REJECT,
            HumanGateAction.REQUEST_REVISION,
        }
        and normalized_reason is None
    ):
        return _rejected(
            gate,
            HumanGateIssueCode.REASON_REQUIRED,
        )

    target = _target_status(
        gate,
        action,
    )

    if target is None:
        return _rejected(
            gate,
            HumanGateIssueCode.INVALID_TRANSITION,
        )

    (
        target_status,
        resume_status,
    ) = target

    sequence_number = gate.event_sequence + 1

    updated_gate = replace(
        gate,
        status=target_status,
        updated_at=timestamp,
        event_sequence=sequence_number,
        resume_status=resume_status,
    )

    event = HumanGateEvent(
        id=event_id or uuid4(),
        gate_id=gate.id,
        sequence_number=sequence_number,
        kind=HumanGateEventKind(action.value),
        previous_status=gate.status,
        resulting_status=target_status,
        artifact=gate.artifact,
        occurred_at=timestamp,
        actor_user_id=actor_user_id,
        reason=normalized_reason,
    )

    return HumanGateTransitionResult(
        status=HumanGateTransitionStatus.APPLIED,
        gate=updated_gate,
        event=event,
    )


def mark_human_gate_stale(
    gate: HumanGate,
    *,
    current_artifact: GateArtifactReference,
    occurred_at: datetime | None = None,
    event_id: UUID | None = None,
) -> HumanGateTransitionResult:
    """Invalidate a gate when a different artifact becomes current."""
    timestamp = occurred_at or datetime.now(UTC)

    if timestamp.tzinfo is None:
        return _rejected(
            gate,
            HumanGateIssueCode.TIMESTAMP_NOT_AWARE,
        )

    if timestamp < gate.updated_at:
        return _rejected(
            gate,
            HumanGateIssueCode.TIMESTAMP_OUT_OF_ORDER,
        )

    if (
        current_artifact.project_id != gate.project_id
        or current_artifact.gate_type is not gate.gate_type
    ):
        return _rejected(
            gate,
            HumanGateIssueCode.ARTIFACT_SCOPE_MISMATCH,
        )

    if current_artifact == gate.artifact or gate.status is HumanGateStatus.STALE:
        return HumanGateTransitionResult(
            status=HumanGateTransitionStatus.NO_CHANGE,
            gate=gate,
        )

    if gate.status is HumanGateStatus.CANCELLED:
        return _rejected(
            gate,
            HumanGateIssueCode.INVALID_TRANSITION,
        )

    sequence_number = gate.event_sequence + 1

    updated_gate = replace(
        gate,
        status=HumanGateStatus.STALE,
        updated_at=timestamp,
        event_sequence=sequence_number,
        resume_status=None,
    )

    event = HumanGateEvent(
        id=event_id or uuid4(),
        gate_id=gate.id,
        sequence_number=sequence_number,
        kind=HumanGateEventKind.ARTIFACT_SUPERSEDED,
        previous_status=gate.status,
        resulting_status=HumanGateStatus.STALE,
        artifact=current_artifact,
        occurred_at=timestamp,
    )

    return HumanGateTransitionResult(
        status=HumanGateTransitionStatus.APPLIED,
        gate=updated_gate,
        event=event,
    )


def _target_status(
    gate: HumanGate,
    action: HumanGateAction,
) -> tuple[HumanGateStatus, HumanGateStatus | None] | None:
    """Return the target and optional resume state."""
    if gate.status is HumanGateStatus.DRAFT:
        targets = {
            HumanGateAction.SUBMIT: HumanGateStatus.PENDING_APPROVAL,
            HumanGateAction.PAUSE: HumanGateStatus.PAUSED,
            HumanGateAction.CANCEL: HumanGateStatus.CANCELLED,
        }

        target = targets.get(action)

        if target is None:
            return None

        resume_status = HumanGateStatus.DRAFT if action is HumanGateAction.PAUSE else None

        return (
            target,
            resume_status,
        )

    if gate.status is HumanGateStatus.PENDING_APPROVAL:
        if action is HumanGateAction.REQUEST_REVISION:
            target = (
                HumanGateStatus.PAUSED_NEEDS_HUMAN
                if gate.iteration >= gate.max_iterations
                else HumanGateStatus.REVISION_REQUESTED
            )

            return (
                target,
                None,
            )

        targets = {
            HumanGateAction.APPROVE: HumanGateStatus.APPROVED,
            HumanGateAction.REJECT: HumanGateStatus.REJECTED,
            HumanGateAction.PAUSE: HumanGateStatus.PAUSED,
            HumanGateAction.CANCEL: HumanGateStatus.CANCELLED,
        }

        target = targets.get(action)

        if target is None:
            return None

        resume_status = (
            HumanGateStatus.PENDING_APPROVAL if action is HumanGateAction.PAUSE else None
        )

        return (
            target,
            resume_status,
        )

    if gate.status is HumanGateStatus.PAUSED:
        if action is HumanGateAction.RESUME and gate.resume_status is not None:
            return (
                gate.resume_status,
                None,
            )

        if action is HumanGateAction.CANCEL:
            return (
                HumanGateStatus.CANCELLED,
                None,
            )

    if (
        gate.status
        in {
            HumanGateStatus.REVISION_REQUESTED,
            HumanGateStatus.PAUSED_NEEDS_HUMAN,
        }
        and action is HumanGateAction.CANCEL
    ):
        return (
            HumanGateStatus.CANCELLED,
            None,
        )

    return None


def _operation_issue(
    gate: HumanGate,
    *,
    actor_user_id: UUID,
    occurred_at: datetime,
) -> HumanGateIssueCode | None:
    """Validate owner authority and monotonic event time."""
    if actor_user_id != gate.owner_user_id:
        return HumanGateIssueCode.ACTOR_NOT_OWNER

    if occurred_at.tzinfo is None:
        return HumanGateIssueCode.TIMESTAMP_NOT_AWARE

    if occurred_at < gate.updated_at:
        return HumanGateIssueCode.TIMESTAMP_OUT_OF_ORDER

    return None


def _normalize_reason(
    reason: str | None,
) -> tuple[str | None, HumanGateIssueCode | None]:
    """Normalize an optional owner rationale."""
    if reason is None:
        return (
            None,
            None,
        )

    normalized = " ".join(reason.split())

    if not normalized:
        return (
            None,
            None,
        )

    if len(normalized) > MAX_GATE_REASON_LENGTH:
        return (
            None,
            HumanGateIssueCode.REASON_TOO_LONG,
        )

    return (
        normalized,
        None,
    )


def _rejected(
    gate: HumanGate,
    issue: HumanGateIssueCode,
) -> HumanGateTransitionResult:
    """Return a typed rejection without mutating the gate."""
    return HumanGateTransitionResult(
        status=HumanGateTransitionStatus.REJECTED,
        gate=gate,
        issue=issue,
    )
