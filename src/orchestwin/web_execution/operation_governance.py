"""Exact Gate 7 approvals and single-use lifecycle for Web operations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from orchestwin.web_execution.static_browser_jobs import canonical_bytes, content_hash
from orchestwin.web_execution.verified_browser_runner import read_json
from orchestwin.workflow.gates import (
    DEFAULT_GATE_ITERATION_LIMIT,
    GateArtifactReference,
    HumanGateAction,
    HumanGateStatus,
    HumanGateTransitionStatus,
    HumanGateType,
    create_human_gate,
    mark_human_gate_stale,
    transition_human_gate,
)

MAX_OPERATION_JSON_BYTES = 4 * 1024 * 1024


class WebOperationError(ValueError):
    """Stable boundary error without source text, database details, or host paths."""

    def __init__(self, code: str, status_code: int = 409):
        self.code, self.status_code = code, status_code
        super().__init__(code)


class WebOperationKind(StrEnum):
    EXECUTION = "EXECUTION"
    REPAIR = "REPAIR"


class WebOperationState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def operation_json(value: object) -> str:
    """Copy an exact bounded JSON object into immutable canonical storage."""
    try:
        if not isinstance(value, dict):
            raise ValueError
        data = canonical_bytes(value)
        if not 1 <= len(data) <= MAX_OPERATION_JSON_BYTES:
            raise ValueError
        # Round-trip also rejects unsupported dictionary keys and non-JSON values.
        restored = read_json(data)
        if restored != value:
            raise ValueError
        return data.decode("utf-8")
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise WebOperationError("WEB_OPERATION_JSON_INVALID", 422) from None


def _json_object(value: str) -> dict:
    if (
        not isinstance(value, str)
        or not 1 <= len(value.encode("utf-8")) <= MAX_OPERATION_JSON_BYTES
    ):
        raise WebOperationError("WEB_OPERATION_JSON_INVALID", 422)
    result = read_json(value.encode("utf-8"))
    if operation_json(result) != value:
        raise WebOperationError("WEB_OPERATION_JSON_NOT_CANONICAL", 422)
    return result


@dataclass(frozen=True, slots=True)
class WebGovernedOperation:
    """Immutable input bytes and terminal result bytes; payload access returns copies."""

    id: UUID
    project_id: UUID
    owner_user_id: UUID
    source_revision_id: UUID
    kind: WebOperationKind
    payload_json: str
    gate_id: UUID
    created_at: datetime
    state: WebOperationState = WebOperationState.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result_json: str | None = None

    def __post_init__(self):
        if (
            any(
                not isinstance(value, UUID)
                for value in (
                    self.id,
                    self.project_id,
                    self.owner_user_id,
                    self.source_revision_id,
                    self.gate_id,
                )
            )
            or not isinstance(self.kind, WebOperationKind)
            or not isinstance(self.state, WebOperationState)
        ):
            raise WebOperationError("WEB_OPERATION_IDENTITY_INVALID", 422)
        _json_object(self.payload_json)
        if self.result_json is not None:
            _json_object(self.result_json)
        for name in ("created_at", "started_at", "finished_at"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, datetime) or value.utcoffset() is None):
                raise WebOperationError("WEB_OPERATION_TIMESTAMP_INVALID", 422)
            if value is not None:
                object.__setattr__(self, name, value.astimezone(UTC))
        if self.created_at is None:
            raise WebOperationError("WEB_OPERATION_TIMESTAMP_INVALID", 422)
        terminal = self.state in {WebOperationState.COMPLETED, WebOperationState.FAILED}
        if terminal != (self.finished_at is not None and self.result_json is not None):
            raise WebOperationError("WEB_OPERATION_LIFECYCLE_INVALID", 422)
        if not terminal and (self.finished_at is not None or self.result_json is not None):
            raise WebOperationError("WEB_OPERATION_LIFECYCLE_INVALID", 422)
        if self.state is WebOperationState.PENDING and self.started_at is not None:
            raise WebOperationError("WEB_OPERATION_LIFECYCLE_INVALID", 422)
        if (
            self.state in {WebOperationState.RUNNING, WebOperationState.COMPLETED}
            and self.started_at is None
        ):
            raise WebOperationError("WEB_OPERATION_LIFECYCLE_INVALID", 422)
        if self.started_at is not None and self.started_at < self.created_at:
            raise WebOperationError("WEB_OPERATION_TIMESTAMP_INVALID", 422)
        if self.finished_at is not None and self.finished_at < (self.started_at or self.created_at):
            raise WebOperationError("WEB_OPERATION_TIMESTAMP_INVALID", 422)
        if (
            self.state is WebOperationState.FAILED
            and self.started_at is None
            and self.result
            != {
                "failure_code": "WEB_OPERATION_CANCELLED",
                "execution_started": False,
            }
        ):
            raise WebOperationError("WEB_OPERATION_UNSTARTED_FAILURE_INVALID", 422)

    @classmethod
    def create(
        cls,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        source_revision_id: UUID,
        kind: WebOperationKind | str,
        payload: dict,
        operation_id: UUID | None = None,
        created_at: datetime | None = None,
    ):
        return cls(
            operation_id or uuid4(),
            project_id,
            owner_user_id,
            source_revision_id,
            WebOperationKind(kind),
            operation_json(payload),
            uuid4(),
            created_at or datetime.now(UTC),
        )

    @property
    def payload(self) -> dict:
        return read_json(self.payload_json.encode("utf-8"))

    @property
    def result(self) -> dict | None:
        return None if self.result_json is None else read_json(self.result_json.encode("utf-8"))

    @property
    def payload_content_hash(self) -> str:
        return content_hash(self.payload)

    def _identity_snapshot(self) -> dict:
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "owner_user_id": str(self.owner_user_id),
            "source_revision_id": str(self.source_revision_id),
            "kind": self.kind.value,
            "payload": self.payload,
            "payload_content_hash": self.payload_content_hash,
            "gate_id": str(self.gate_id),
            "created_at": self.created_at.isoformat(),
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self._identity_snapshot())

    @property
    def artifact(self) -> GateArtifactReference:
        return GateArtifactReference(
            self.project_id, HumanGateType.HIGH_IMPACT_OPERATION, self.id, 1, self.content_hash
        )

    def to_snapshot(self) -> dict:
        return {
            **self._identity_snapshot(),
            "content_hash": self.content_hash,
            "state": self.state.value,
            "started_at": None if self.started_at is None else self.started_at.isoformat(),
            "finished_at": None if self.finished_at is None else self.finished_at.isoformat(),
            "result": self.result,
        }


class WebOperationScope:
    """Shared governance operations; implementations provide one locked transaction."""

    owner_user_id: UUID
    project_id: UUID

    async def get(self, operation_id: UUID):
        raise NotImplementedError

    async def history(self, kind=None):
        raise NotImplementedError

    async def source_owned(self, source_revision_id: UUID):
        raise NotImplementedError

    async def insert(self, operation):
        raise NotImplementedError

    async def update(self, previous, updated):
        raise NotImplementedError

    async def latest_gate(self):
        raise NotImplementedError

    async def load_gate(self, gate_id):
        raise NotImplementedError

    async def add_gate(self, gate, event):
        raise NotImplementedError

    async def save_gate(self, previous, updated, event):
        raise NotImplementedError

    async def _current(self, operation):
        if operation.project_id != self.project_id or operation.owner_user_id != self.owner_user_id:
            raise WebOperationError("WEB_OPERATION_NOT_FOUND", 404)
        current = await self.get(operation.id)
        if current is None:
            raise WebOperationError("WEB_OPERATION_NOT_FOUND", 404)
        if current != operation:
            raise WebOperationError("WEB_OPERATION_STATE_CONFLICT")
        return current

    async def gate(self, operation):
        await self._current(operation)
        gate = await self.load_gate(operation.gate_id)
        if (
            gate is None
            or gate.project_id != self.project_id
            or gate.owner_user_id != self.owner_user_id
            or gate.artifact != operation.artifact
        ):
            raise WebOperationError("WEB_OPERATION_GATE_INTEGRITY_FAILED")
        return gate

    async def _exact_gate(self, operation):
        gate = await self.gate(operation)
        latest = await self.latest_gate()
        if latest is None or latest.id != gate.id:
            raise WebOperationError("WEB_OPERATION_GATE_STALE")
        return gate

    async def snapshot(self, operation):
        gate = await self.gate(operation)
        latest = await self.latest_gate()
        current = latest is not None and latest.id == gate.id
        return {
            **operation.to_snapshot(),
            "gate_current": current,
            "gate": {
                "id": str(gate.id),
                "type": gate.gate_type.value,
                "status": gate.status.value,
                "event_sequence": gate.event_sequence,
                "iteration": gate.iteration,
                "max_iterations": gate.max_iterations,
                "is_current": current,
                "artifact_id": str(gate.artifact.artifact_id),
                "artifact_content_hash": gate.artifact.content_hash,
            },
        }

    async def propose(self, *, source_revision_id, kind, payload, operation_id=None):
        if not await self.source_owned(source_revision_id):
            raise WebOperationError("WEB_OPERATION_SOURCE_NOT_FOUND", 404)
        if operation_id is not None:
            existing = await self.get(operation_id)
            if existing is not None:
                if (
                    existing.kind != kind
                    or existing.source_revision_id != source_revision_id
                    or existing.payload_json != operation_json(payload)
                ):
                    raise WebOperationError("WEB_OPERATION_ID_CONFLICT")
                return existing
        if any(item.state is WebOperationState.RUNNING for item in await self.history()):
            raise WebOperationError("WEB_OPERATION_ALREADY_RUNNING")
        latest = await self.latest_gate()
        if latest is not None and latest.status in {
            HumanGateStatus.DRAFT,
            HumanGateStatus.PENDING_APPROVAL,
            HumanGateStatus.PAUSED,
            HumanGateStatus.PAUSED_NEEDS_HUMAN,
        }:
            raise WebOperationError("WEB_OPERATION_EXISTING_GATE_REQUIRES_DECISION")
        iteration = 1 if latest is None else latest.iteration + 1
        operation = WebGovernedOperation.create(
            project_id=self.project_id,
            owner_user_id=self.owner_user_id,
            source_revision_id=source_revision_id,
            kind=kind,
            payload=payload,
            operation_id=operation_id,
        )
        gate = create_human_gate(
            project_id=self.project_id,
            owner_user_id=self.owner_user_id,
            gate_type=HumanGateType.HIGH_IMPACT_OPERATION,
            artifact=operation.artifact,
            gate_id=operation.gate_id,
            iteration=iteration,
            # The persisted ordinal is project-wide and unique. Each new immutable
            # artifact starts its own review budget at that ordinal; completed
            # operations must not consume the next operation's review allowance.
            max_iterations=iteration + DEFAULT_GATE_ITERATION_LIMIT - 1,
            created_at=operation.created_at,
        )
        submitted = transition_human_gate(
            gate,
            action=HumanGateAction.SUBMIT,
            actor_user_id=self.owner_user_id,
            occurred_at=operation.created_at,
        )
        if submitted.status is not HumanGateTransitionStatus.APPLIED or submitted.event is None:
            raise WebOperationError("WEB_OPERATION_GATE_SUBMISSION_FAILED")
        if latest is not None and latest.status not in {
            HumanGateStatus.CANCELLED,
            HumanGateStatus.STALE,
        }:
            stale = mark_human_gate_stale(
                latest, current_artifact=operation.artifact, occurred_at=operation.created_at
            )
            if stale.status is not HumanGateTransitionStatus.APPLIED or stale.event is None:
                raise WebOperationError("WEB_OPERATION_GATE_STALE_FAILED")
            await self.save_gate(latest, stale.gate, stale.event)
        await self.add_gate(submitted.gate, submitted.event)
        await self.insert(operation)
        return operation

    @staticmethod
    def _expected(operation, expected_hash):
        if expected_hash != operation.content_hash:
            raise WebOperationError("WEB_OPERATION_INPUT_CHANGED")

    async def decide(
        self, operation, *, expected_hash, expected_event_sequence, action, reason=None
    ):
        await self._current(operation)
        self._expected(operation, expected_hash)
        if operation.state is not WebOperationState.PENDING:
            raise WebOperationError("WEB_OPERATION_ALREADY_CLAIMED")
        gate = await self._exact_gate(operation)
        if (
            type(expected_event_sequence) is not int
            or gate.event_sequence != expected_event_sequence
        ):
            raise WebOperationError("WEB_OPERATION_GATE_STATE_CONFLICT")
        if action is HumanGateAction.SUBMIT:
            raise WebOperationError("WEB_OPERATION_GATE_ACTION_INVALID", 422)
        transition = transition_human_gate(
            gate, action=action, actor_user_id=self.owner_user_id, reason=reason
        )
        if transition.status is HumanGateTransitionStatus.REJECTED:
            raise WebOperationError(
                "WEB_OPERATION_GATE_" + (transition.issue.value if transition.issue else "REJECTED")
            )
        if transition.status is HumanGateTransitionStatus.APPLIED:
            if transition.event is None:
                raise WebOperationError("WEB_OPERATION_GATE_EVENT_REQUIRED")
            await self.save_gate(gate, transition.gate, transition.event)
        if transition.gate.status is HumanGateStatus.CANCELLED:
            cancelled = replace(
                operation,
                state=WebOperationState.FAILED,
                finished_at=datetime.now(UTC),
                result_json=operation_json(
                    {"failure_code": "WEB_OPERATION_CANCELLED", "execution_started": False}
                ),
            )
            await self.update(operation, cancelled)
            return cancelled
        return operation

    async def claim(self, operation, *, expected_hash):
        await self._current(operation)
        self._expected(operation, expected_hash)
        if operation.state is not WebOperationState.PENDING:
            raise WebOperationError("WEB_OPERATION_ALREADY_CLAIMED")
        gate = await self._exact_gate(operation)
        if gate.status is not HumanGateStatus.APPROVED:
            raise WebOperationError("WEB_OPERATION_APPROVAL_REQUIRED", 403)
        if any(item.state is WebOperationState.RUNNING for item in await self.history()):
            raise WebOperationError("WEB_OPERATION_ALREADY_RUNNING")
        running = replace(operation, state=WebOperationState.RUNNING, started_at=datetime.now(UTC))
        await self.update(operation, running)
        return running

    async def finish(self, operation, *, result, succeeded):
        await self._current(operation)
        if operation.state is not WebOperationState.RUNNING or type(succeeded) is not bool:
            raise WebOperationError("WEB_OPERATION_STATE_CONFLICT")
        updated = replace(
            operation,
            state=WebOperationState.COMPLETED if succeeded else WebOperationState.FAILED,
            result_json=operation_json(result),
            finished_at=datetime.now(UTC),
        )
        await self.update(operation, updated)
        return updated
