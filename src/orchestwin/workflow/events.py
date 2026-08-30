"""Typed, reasoning-free workflow events for durable replay and SSE delivery."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from orchestwin.projects.requirements_primitives import (
    normalize_required_text,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.workflow.runs import WorkflowRun, WorkflowRunStatus, WorkflowStage

_MAX_ISSUE_CODE_LENGTH = 100


class WorkflowEventType(StrEnum):
    """Stable public event names shared by persistence, API, and SSE."""

    RUN_STARTED = "workflow.run.started"
    STAGE_CHANGED = "workflow.stage.changed"
    WAITING_FOR_HUMAN = "workflow.waiting_for_human"
    PAUSED = "workflow.paused"
    RESUMED = "workflow.resumed"
    CANCELLED = "workflow.cancelled"
    FAILED = "workflow.failed"
    COMPLETED = "workflow.completed"
    APPROVED = "workflow.approved"
    CHECKPOINT_CREATED = "workflow.checkpoint.created"
    BUDGET_WARNING = "budget.warning"
    BUDGET_EXHAUSTED = "budget.exhausted"


@dataclass(frozen=True, slots=True)
class WorkflowEventPayload:
    """Minimal typed payload that excludes documents, secrets, and model reasoning."""

    current_stage: WorkflowStage
    current_status: WorkflowRunStatus
    state_version: int
    checkpoint_sequence: int
    previous_stage: WorkflowStage | None = None
    previous_status: WorkflowRunStatus | None = None
    pending_gate_id: UUID | None = None
    decision_id: UUID | None = None
    issue_code: str | None = None

    def __post_init__(self) -> None:
        validate_positive_integer(self.state_version, label="workflow event state version")
        if isinstance(self.checkpoint_sequence, bool) or self.checkpoint_sequence < 0:
            raise ValueError("workflow event checkpoint sequence must not be negative")
        if self.issue_code is not None:
            normalized = normalize_required_text(
                self.issue_code,
                label="workflow event issue code",
                maximum_length=_MAX_ISSUE_CODE_LENGTH,
            )
            if normalized != self.issue_code:
                raise ValueError("workflow event issue code must be normalized")

    def to_snapshot(self) -> dict[str, object]:
        """Return the stable JSON-compatible event payload shape."""
        return {
            "current_stage": self.current_stage.value,
            "current_status": self.current_status.value,
            "state_version": self.state_version,
            "checkpoint_sequence": self.checkpoint_sequence,
            "previous_stage": (
                self.previous_stage.value if self.previous_stage is not None else None
            ),
            "previous_status": (
                self.previous_status.value if self.previous_status is not None else None
            ),
            "pending_gate_id": (
                str(self.pending_gate_id) if self.pending_gate_id is not None else None
            ),
            "decision_id": str(self.decision_id) if self.decision_id is not None else None,
            "issue_code": self.issue_code,
        }


@dataclass(frozen=True, slots=True)
class WorkflowEvent:
    """Append-only workflow event with stable identity and monotonic run sequence."""

    id: UUID
    run_id: UUID
    project_id: UUID
    owner_user_id: UUID
    sequence_number: int
    event_type: WorkflowEventType
    occurred_at: datetime
    payload: WorkflowEventPayload
    payload_hash: str

    def __post_init__(self) -> None:
        validate_positive_integer(
            self.sequence_number,
            label="workflow event sequence number",
        )
        if self.occurred_at.tzinfo is None:
            raise ValueError("workflow event timestamp must be timezone-aware")
        validate_sha256(self.payload_hash, label="workflow event payload hash")
        if self.payload_hash != workflow_event_payload_hash(self.payload):
            raise ValueError("workflow event payload hash does not match payload")


def create_workflow_event(
    run: WorkflowRun,
    *,
    event_type: WorkflowEventType,
    sequence_number: int,
    occurred_at: datetime,
    previous_run: WorkflowRun | None = None,
    event_id: UUID | None = None,
    decision_id: UUID | None = None,
    issue_code: str | None = None,
) -> WorkflowEvent:
    """Create one event only when its type matches the observable run transition."""
    if occurred_at.tzinfo is None:
        raise ValueError("workflow event timestamp must be timezone-aware")
    if occurred_at < run.updated_at:
        raise ValueError("workflow event cannot precede the current workflow state")
    if previous_run is not None and (
        previous_run.id != run.id
        or previous_run.project_id != run.project_id
        or previous_run.owner_user_id != run.owner_user_id
    ):
        raise ValueError("previous workflow run must match event scope")

    payload = WorkflowEventPayload(
        current_stage=run.current_stage,
        current_status=run.status,
        state_version=run.state_version,
        checkpoint_sequence=run.checkpoint_sequence,
        previous_stage=previous_run.current_stage if previous_run is not None else None,
        previous_status=previous_run.status if previous_run is not None else None,
        pending_gate_id=run.pending_gate_id,
        decision_id=decision_id,
        issue_code=issue_code,
    )
    _validate_event_semantics(event_type, payload)
    return WorkflowEvent(
        id=event_id or uuid4(),
        run_id=run.id,
        project_id=run.project_id,
        owner_user_id=run.owner_user_id,
        sequence_number=sequence_number,
        event_type=event_type,
        occurred_at=occurred_at,
        payload=payload,
        payload_hash=workflow_event_payload_hash(payload),
    )


def serialize_workflow_event_payload(payload: WorkflowEventPayload) -> str:
    """Serialize an event payload canonically for hashing and replay."""
    return json.dumps(
        payload.to_snapshot(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def deserialize_workflow_event_payload(payload_json: str) -> WorkflowEventPayload:
    """Restore only the exact stable payload schema from canonical JSON."""
    raw = json.loads(payload_json)
    if not isinstance(raw, dict):
        raise ValueError("workflow event payload must be a JSON object")
    expected = {
        "current_stage",
        "current_status",
        "state_version",
        "checkpoint_sequence",
        "previous_stage",
        "previous_status",
        "pending_gate_id",
        "decision_id",
        "issue_code",
    }
    if set(raw) != expected:
        raise ValueError("workflow event payload fields are incompatible")
    if serialize_raw_workflow_event_payload(raw) != payload_json:
        raise ValueError("workflow event payload is not canonical")
    return WorkflowEventPayload(
        current_stage=WorkflowStage(_required_string(raw["current_stage"])),
        current_status=WorkflowRunStatus(_required_string(raw["current_status"])),
        state_version=_required_integer(raw["state_version"]),
        checkpoint_sequence=_required_integer(raw["checkpoint_sequence"]),
        previous_stage=(
            None
            if raw["previous_stage"] is None
            else WorkflowStage(_required_string(raw["previous_stage"]))
        ),
        previous_status=(
            None
            if raw["previous_status"] is None
            else WorkflowRunStatus(_required_string(raw["previous_status"]))
        ),
        pending_gate_id=_optional_uuid(raw["pending_gate_id"]),
        decision_id=_optional_uuid(raw["decision_id"]),
        issue_code=(None if raw["issue_code"] is None else _required_string(raw["issue_code"])),
    )


def workflow_event_payload_hash(payload: WorkflowEventPayload) -> str:
    """Return the SHA-256 digest of the canonical event payload."""
    return hashlib.sha256(serialize_workflow_event_payload(payload).encode("utf-8")).hexdigest()


def serialize_raw_workflow_event_payload(payload: dict[str, object]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _validate_event_semantics(
    event_type: WorkflowEventType,
    payload: WorkflowEventPayload,
) -> None:
    previous_status = payload.previous_status
    current_status = payload.current_status

    if event_type is WorkflowEventType.RUN_STARTED:
        if (
            previous_status is not WorkflowRunStatus.DRAFT
            or current_status is not WorkflowRunStatus.RUNNING
        ):
            raise ValueError("run-started event requires a DRAFT to RUNNING transition")
    elif event_type is WorkflowEventType.STAGE_CHANGED:
        if payload.previous_stage is None or payload.previous_stage is payload.current_stage:
            raise ValueError("stage-changed event requires distinct workflow stages")
    elif event_type is WorkflowEventType.WAITING_FOR_HUMAN:
        if current_status is not WorkflowRunStatus.WAITING_FOR_HUMAN:
            raise ValueError("waiting event requires WAITING_FOR_HUMAN status")
        if payload.pending_gate_id is None:
            raise ValueError("waiting event requires a pending gate")
    elif event_type is WorkflowEventType.PAUSED:
        if current_status not in {
            WorkflowRunStatus.PAUSED,
            WorkflowRunStatus.PAUSED_NEEDS_HUMAN,
        }:
            raise ValueError("paused event requires a paused workflow status")
    elif event_type is WorkflowEventType.RESUMED:
        if current_status is not WorkflowRunStatus.RUNNING or previous_status not in {
            WorkflowRunStatus.PAUSED,
            WorkflowRunStatus.PAUSED_NEEDS_HUMAN,
            WorkflowRunStatus.WAITING_FOR_HUMAN,
        }:
            raise ValueError("resumed event requires a paused or waiting run to become RUNNING")
    elif event_type is WorkflowEventType.CANCELLED:
        _require_status(current_status, WorkflowRunStatus.CANCELLED, label="cancelled")
    elif event_type is WorkflowEventType.FAILED:
        _require_status(current_status, WorkflowRunStatus.FAILED, label="failed")
    elif event_type is WorkflowEventType.COMPLETED:
        _require_status(
            current_status,
            WorkflowRunStatus.COMPLETED_PENDING_FINAL_APPROVAL,
            label="completed",
        )
    elif event_type is WorkflowEventType.APPROVED:
        _require_status(current_status, WorkflowRunStatus.APPROVED, label="approved")
    elif event_type is WorkflowEventType.CHECKPOINT_CREATED:
        if payload.checkpoint_sequence < 1:
            raise ValueError("checkpoint-created event requires a persisted checkpoint")
    elif event_type is WorkflowEventType.BUDGET_WARNING:
        if payload.issue_code is None:
            raise ValueError("budget-warning event requires an issue code")
    elif event_type is WorkflowEventType.BUDGET_EXHAUSTED:
        if current_status is not WorkflowRunStatus.PAUSED_NEEDS_HUMAN or payload.issue_code is None:
            raise ValueError("budget-exhausted event requires an explicit human pause")
    else:
        raise ValueError("unsupported workflow event type")


def _require_status(
    actual: WorkflowRunStatus,
    expected: WorkflowRunStatus,
    *,
    label: str,
) -> None:
    if actual is not expected:
        raise ValueError(f"{label} event does not match workflow status")


def _required_string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("workflow event payload value must be a non-empty string")
    return value


def _required_integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("workflow event payload value must be an integer")
    return value


def _optional_uuid(value: object) -> UUID | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("workflow event UUID must be a string")
    return UUID(value)
