"""Versioned application checkpoints for durable governed workflow runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID, uuid4

from orchestwin.projects.domain import ProjectMode
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionProfileReference,
)
from orchestwin.workflow.runs import (
    WorkflowArtifactReference,
    WorkflowBlockingIssue,
    WorkflowBlockingIssueSource,
    WorkflowBudgetState,
    WorkflowCapabilityState,
    WorkflowErrorSummary,
    WorkflowFailureCounter,
    WorkflowIterationCounters,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowStage,
)

WORKFLOW_CHECKPOINT_SCHEMA_VERSION: Final = 1
_CHECKPOINT_PAYLOAD_KEYS: Final = frozenset({"schema_version", "run"})
_RUN_SNAPSHOT_KEYS: Final = frozenset(
    {
        "id",
        "project_id",
        "owner_user_id",
        "project_mode",
        "current_stage",
        "status",
        "artifact_references",
        "pending_gate_id",
        "latest_source_revision_id",
        "latest_execution_attempt_id",
        "latest_evaluation_run_id",
        "iteration_counters",
        "budget_state",
        "capability_state",
        "blocking_issues",
        "last_error",
        "state_version",
        "checkpoint_sequence",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "resume_status",
    }
)


class WorkflowCheckpointRestoreStatus(StrEnum):
    """Inspectable outcome of verifying and restoring one checkpoint."""

    RESTORED = "RESTORED"
    CORRUPTED = "CORRUPTED"
    UNSUPPORTED_SCHEMA = "UNSUPPORTED_SCHEMA"
    RUN_ID_MISMATCH = "RUN_ID_MISMATCH"
    PROJECT_ID_MISMATCH = "PROJECT_ID_MISMATCH"
    OWNER_MISMATCH = "OWNER_MISMATCH"
    STALE_STATE = "STALE_STATE"


@dataclass(frozen=True, slots=True)
class WorkflowCheckpoint:
    """Immutable checkpoint envelope stored separately from the graph framework."""

    id: UUID
    run_id: UUID
    project_id: UUID
    owner_user_id: UUID
    sequence_number: int
    schema_version: int
    parent_checkpoint_id: UUID | None
    state_version: int
    state_hash: str
    payload_json: str
    payload_hash: str
    created_at: datetime

    def __post_init__(self) -> None:
        if self.sequence_number < 1:
            raise ValueError("workflow checkpoint sequence must be positive")
        if self.schema_version < 1:
            raise ValueError("workflow checkpoint schema version must be positive")
        if self.state_version < 1:
            raise ValueError("workflow checkpoint state version must be positive")
        if self.created_at.tzinfo is None:
            raise ValueError("workflow checkpoint timestamp must be timezone-aware")
        _validate_sha256(self.state_hash, label="workflow checkpoint state hash")
        _validate_sha256(self.payload_hash, label="workflow checkpoint payload hash")
        if not self.payload_json:
            raise ValueError("workflow checkpoint payload is required")
        if self.sequence_number == 1 and self.parent_checkpoint_id is not None:
            raise ValueError("first workflow checkpoint cannot have a parent")
        if self.sequence_number > 1 and self.parent_checkpoint_id is None:
            raise ValueError("subsequent workflow checkpoint requires a parent")


@dataclass(frozen=True, slots=True)
class WorkflowCheckpointCreation:
    """Updated run and checkpoint that must be persisted atomically."""

    run: WorkflowRun
    checkpoint: WorkflowCheckpoint


@dataclass(frozen=True, slots=True)
class WorkflowCheckpointRestoreResult:
    """Typed restore result that never silently accepts incompatible state."""

    status: WorkflowCheckpointRestoreStatus
    run: WorkflowRun | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        restored = self.status is WorkflowCheckpointRestoreStatus.RESTORED
        if restored != (self.run is not None):
            raise ValueError("restored checkpoint result must include exactly one run")
        if restored and self.detail is not None:
            raise ValueError("successful checkpoint restore cannot include an error detail")
        if not restored and not self.detail:
            raise ValueError("failed checkpoint restore requires a concise detail")


def create_workflow_checkpoint(
    run: WorkflowRun,
    *,
    created_at: datetime,
    previous_checkpoint: WorkflowCheckpoint | None = None,
    checkpoint_id: UUID | None = None,
) -> WorkflowCheckpointCreation:
    """Create the next canonical checkpoint while preserving linear lineage."""
    if created_at.tzinfo is None:
        raise ValueError("workflow checkpoint timestamp must be timezone-aware")
    if created_at < run.updated_at:
        raise ValueError("workflow checkpoint timestamp must not precede run state")

    if previous_checkpoint is None:
        if run.checkpoint_sequence != 0:
            raise ValueError(
                "workflow run with checkpoint history requires its previous checkpoint"
            )
        sequence_number = 1
        parent_checkpoint_id = None
    else:
        _validate_previous_checkpoint(run, previous_checkpoint)
        sequence_number = previous_checkpoint.sequence_number + 1
        parent_checkpoint_id = previous_checkpoint.id

    checkpointed_run = replace(
        run,
        checkpoint_sequence=sequence_number,
        state_version=run.state_version + 1,
        updated_at=created_at,
    )
    run_payload = checkpointed_run.to_snapshot()
    state_json = _canonical_json(run_payload)
    payload_json = _canonical_json(
        {
            "schema_version": WORKFLOW_CHECKPOINT_SCHEMA_VERSION,
            "run": run_payload,
        }
    )
    checkpoint = WorkflowCheckpoint(
        id=checkpoint_id or uuid4(),
        run_id=checkpointed_run.id,
        project_id=checkpointed_run.project_id,
        owner_user_id=checkpointed_run.owner_user_id,
        sequence_number=sequence_number,
        schema_version=WORKFLOW_CHECKPOINT_SCHEMA_VERSION,
        parent_checkpoint_id=parent_checkpoint_id,
        state_version=checkpointed_run.state_version,
        state_hash=_sha256_text(state_json),
        payload_json=payload_json,
        payload_hash=_sha256_text(payload_json),
        created_at=created_at,
    )
    return WorkflowCheckpointCreation(run=checkpointed_run, checkpoint=checkpoint)


def restore_workflow_checkpoint(
    checkpoint: WorkflowCheckpoint,
    *,
    expected_run_id: UUID,
    expected_project_id: UUID,
    expected_owner_user_id: UUID,
    minimum_state_version: int = 1,
) -> WorkflowCheckpointRestoreResult:
    """Verify integrity, compatibility, ownership, and staleness before restore."""
    if minimum_state_version < 1:
        raise ValueError("minimum workflow state version must be positive")
    if checkpoint.schema_version != WORKFLOW_CHECKPOINT_SCHEMA_VERSION:
        return _restore_failure(
            WorkflowCheckpointRestoreStatus.UNSUPPORTED_SCHEMA,
            "workflow checkpoint schema version is not supported",
        )
    if checkpoint.run_id != expected_run_id:
        return _restore_failure(
            WorkflowCheckpointRestoreStatus.RUN_ID_MISMATCH,
            "workflow checkpoint belongs to a different run",
        )
    if checkpoint.project_id != expected_project_id:
        return _restore_failure(
            WorkflowCheckpointRestoreStatus.PROJECT_ID_MISMATCH,
            "workflow checkpoint belongs to a different project",
        )
    if checkpoint.owner_user_id != expected_owner_user_id:
        return _restore_failure(
            WorkflowCheckpointRestoreStatus.OWNER_MISMATCH,
            "workflow checkpoint belongs to a different owner",
        )
    if checkpoint.state_version < minimum_state_version:
        return _restore_failure(
            WorkflowCheckpointRestoreStatus.STALE_STATE,
            "workflow checkpoint state version is stale",
        )

    try:
        run = _decode_checkpoint_payload(checkpoint)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return _restore_failure(
            WorkflowCheckpointRestoreStatus.CORRUPTED,
            "workflow checkpoint integrity verification failed",
        )

    if (
        run.id != checkpoint.run_id
        or run.project_id != checkpoint.project_id
        or run.owner_user_id != checkpoint.owner_user_id
        or run.state_version != checkpoint.state_version
        or run.checkpoint_sequence != checkpoint.sequence_number
    ):
        return _restore_failure(
            WorkflowCheckpointRestoreStatus.CORRUPTED,
            "workflow checkpoint envelope does not match its payload",
        )
    return WorkflowCheckpointRestoreResult(
        status=WorkflowCheckpointRestoreStatus.RESTORED,
        run=run,
    )


def workflow_run_from_snapshot(snapshot: Mapping[str, object]) -> WorkflowRun:
    """Rebuild immutable domain state from one strict canonical snapshot."""
    if set(snapshot) != _RUN_SNAPSHOT_KEYS:
        raise ValueError("workflow run snapshot fields are incompatible")

    artifacts_raw = _sequence(snapshot["artifact_references"], "artifact references")
    failure_counters_raw = _sequence(
        _mapping(snapshot["iteration_counters"], "iteration counters")["failure_counters"],
        "failure counters",
    )
    unsupported_raw = _sequence(
        _mapping(snapshot["capability_state"], "capability state")["unsupported_requirements"],
        "unsupported requirements",
    )
    issues_raw = _sequence(snapshot["blocking_issues"], "blocking issues")

    capability = _mapping(snapshot["capability_state"], "capability state")
    selected_profile_raw = capability["selected_profile"]
    selected_profile = (
        None
        if selected_profile_raw is None
        else _profile_from_snapshot(_mapping(selected_profile_raw, "selected profile"))
    )
    capability_status_raw = capability["capability_status"]

    return WorkflowRun(
        id=_uuid(snapshot["id"], "run id"),
        project_id=_uuid(snapshot["project_id"], "project id"),
        owner_user_id=_uuid(snapshot["owner_user_id"], "owner user id"),
        project_mode=ProjectMode(_string(snapshot["project_mode"], "project mode")),
        current_stage=WorkflowStage(_string(snapshot["current_stage"], "workflow stage")),
        status=WorkflowRunStatus(_string(snapshot["status"], "workflow status")),
        artifact_references=tuple(
            _artifact_from_snapshot(_mapping(value, "artifact reference"))
            for value in artifacts_raw
        ),
        pending_gate_id=_optional_uuid(snapshot["pending_gate_id"], "pending gate id"),
        latest_source_revision_id=_optional_uuid(
            snapshot["latest_source_revision_id"],
            "latest source revision id",
        ),
        latest_execution_attempt_id=_optional_uuid(
            snapshot["latest_execution_attempt_id"],
            "latest execution attempt id",
        ),
        latest_evaluation_run_id=_optional_uuid(
            snapshot["latest_evaluation_run_id"],
            "latest evaluation run id",
        ),
        iteration_counters=_iteration_counters_from_snapshot(
            _mapping(snapshot["iteration_counters"], "iteration counters"),
            failure_counters_raw,
        ),
        budget_state=_budget_from_snapshot(_mapping(snapshot["budget_state"], "budget state")),
        capability_state=WorkflowCapabilityState(
            selected_profile=selected_profile,
            capability_status=(
                None
                if capability_status_raw is None
                else ExecutionCapabilityStatus(_string(capability_status_raw, "capability status"))
            ),
            unsupported_requirements=tuple(
                _string(value, "unsupported requirement") for value in unsupported_raw
            ),
            owner_decision_required=_boolean(
                capability["owner_decision_required"],
                "capability owner decision",
            ),
        ),
        blocking_issues=tuple(
            _blocking_issue_from_snapshot(_mapping(value, "blocking issue")) for value in issues_raw
        ),
        last_error=(
            None
            if snapshot["last_error"] is None
            else _error_from_snapshot(_mapping(snapshot["last_error"], "last error"))
        ),
        state_version=_integer(snapshot["state_version"], "state version"),
        checkpoint_sequence=_integer(
            snapshot["checkpoint_sequence"],
            "checkpoint sequence",
        ),
        created_at=_datetime(snapshot["created_at"], "created at"),
        updated_at=_datetime(snapshot["updated_at"], "updated at"),
        started_at=_optional_datetime(snapshot["started_at"], "started at"),
        completed_at=_optional_datetime(snapshot["completed_at"], "completed at"),
        resume_status=(
            None
            if snapshot["resume_status"] is None
            else WorkflowRunStatus(_string(snapshot["resume_status"], "resume status"))
        ),
    )


def _decode_checkpoint_payload(checkpoint: WorkflowCheckpoint) -> WorkflowRun:
    if _sha256_text(checkpoint.payload_json) != checkpoint.payload_hash:
        raise ValueError("workflow checkpoint payload hash does not match")
    payload = json.loads(checkpoint.payload_json)
    payload_mapping = _mapping(payload, "checkpoint payload")
    if set(payload_mapping) != _CHECKPOINT_PAYLOAD_KEYS:
        raise ValueError("workflow checkpoint payload fields are incompatible")
    if _canonical_json(payload_mapping) != checkpoint.payload_json:
        raise ValueError("workflow checkpoint payload is not canonical")
    if _integer(payload_mapping["schema_version"], "checkpoint schema version") != (
        checkpoint.schema_version
    ):
        raise ValueError("workflow checkpoint payload schema does not match envelope")

    run_snapshot = _mapping(payload_mapping["run"], "workflow run snapshot")
    if _sha256_text(_canonical_json(run_snapshot)) != checkpoint.state_hash:
        raise ValueError("workflow checkpoint state hash does not match")
    return workflow_run_from_snapshot(run_snapshot)


def _validate_previous_checkpoint(
    run: WorkflowRun,
    checkpoint: WorkflowCheckpoint,
) -> None:
    if (
        checkpoint.run_id != run.id
        or checkpoint.project_id != run.project_id
        or checkpoint.owner_user_id != run.owner_user_id
    ):
        raise ValueError("previous workflow checkpoint must match run scope")
    if checkpoint.sequence_number != run.checkpoint_sequence:
        raise ValueError("previous workflow checkpoint sequence does not match run")
    result = restore_workflow_checkpoint(
        checkpoint,
        expected_run_id=run.id,
        expected_project_id=run.project_id,
        expected_owner_user_id=run.owner_user_id,
    )
    if result.status is not WorkflowCheckpointRestoreStatus.RESTORED:
        raise ValueError("previous workflow checkpoint must pass integrity verification")


def _artifact_from_snapshot(value: Mapping[str, object]) -> WorkflowArtifactReference:
    _require_keys(
        value,
        {"artifact_type", "artifact_id", "version_number", "content_hash"},
        "workflow artifact reference",
    )
    return WorkflowArtifactReference(
        artifact_type=_string(value["artifact_type"], "artifact type"),
        artifact_id=_uuid(value["artifact_id"], "artifact id"),
        version_number=_integer(value["version_number"], "artifact version"),
        content_hash=_string(value["content_hash"], "artifact content hash"),
    )


def _profile_from_snapshot(value: Mapping[str, object]) -> ExecutionProfileReference:
    _require_keys(
        value,
        {"profile_id", "profile_version", "content_hash"},
        "execution profile reference",
    )
    return ExecutionProfileReference(
        profile_id=_string(value["profile_id"], "profile id"),
        profile_version=_string(value["profile_version"], "profile version"),
        content_hash=_string(value["content_hash"], "profile content hash"),
    )


def _iteration_counters_from_snapshot(
    value: Mapping[str, object],
    failure_values: Sequence[object],
) -> WorkflowIterationCounters:
    _require_keys(
        value,
        {
            "clarification_count",
            "requirements_revision_count",
            "design_cycle_count",
            "architecture_revision_count",
            "failure_counters",
        },
        "workflow iteration counters",
    )
    return WorkflowIterationCounters(
        clarification_count=_integer(value["clarification_count"], "clarification count"),
        requirements_revision_count=_integer(
            value["requirements_revision_count"],
            "requirements revision count",
        ),
        design_cycle_count=_integer(value["design_cycle_count"], "design cycle count"),
        architecture_revision_count=_integer(
            value["architecture_revision_count"],
            "architecture revision count",
        ),
        failure_counters=tuple(
            _failure_counter_from_snapshot(_mapping(item, "failure counter"))
            for item in failure_values
        ),
    )


def _failure_counter_from_snapshot(value: Mapping[str, object]) -> WorkflowFailureCounter:
    _require_keys(
        value,
        {"failure_signature", "repair_count", "identical_failure_count"},
        "workflow failure counter",
    )
    return WorkflowFailureCounter(
        failure_signature=_string(value["failure_signature"], "failure signature"),
        repair_count=_integer(value["repair_count"], "repair count"),
        identical_failure_count=_integer(
            value["identical_failure_count"],
            "identical failure count",
        ),
    )


def _budget_from_snapshot(value: Mapping[str, object]) -> WorkflowBudgetState:
    _require_keys(
        value,
        {
            "model_calls",
            "input_tokens",
            "output_tokens",
            "estimated_cost_micros",
            "sandbox_elapsed_seconds",
            "project_elapsed_seconds",
        },
        "workflow budget state",
    )
    return WorkflowBudgetState(
        model_calls=_integer(value["model_calls"], "model calls"),
        input_tokens=_integer(value["input_tokens"], "input tokens"),
        output_tokens=_integer(value["output_tokens"], "output tokens"),
        estimated_cost_micros=_integer(
            value["estimated_cost_micros"],
            "estimated cost",
        ),
        sandbox_elapsed_seconds=_integer(
            value["sandbox_elapsed_seconds"],
            "sandbox elapsed seconds",
        ),
        project_elapsed_seconds=_integer(
            value["project_elapsed_seconds"],
            "project elapsed seconds",
        ),
    )


def _blocking_issue_from_snapshot(value: Mapping[str, object]) -> WorkflowBlockingIssue:
    _require_keys(value, {"code", "source", "summary", "recoverable"}, "blocking issue")
    return WorkflowBlockingIssue(
        code=_string(value["code"], "blocking issue code"),
        source=WorkflowBlockingIssueSource(_string(value["source"], "blocking issue source")),
        summary=_string(value["summary"], "blocking issue summary"),
        recoverable=_boolean(value["recoverable"], "blocking issue recoverable"),
    )


def _error_from_snapshot(value: Mapping[str, object]) -> WorkflowErrorSummary:
    _require_keys(value, {"code", "summary", "retryable"}, "workflow error")
    return WorkflowErrorSummary(
        code=_string(value["code"], "workflow error code"),
        summary=_string(value["summary"], "workflow error summary"),
        retryable=_boolean(value["retryable"], "workflow error retryable"),
    )


def _restore_failure(
    status: WorkflowCheckpointRestoreStatus,
    detail: str,
) -> WorkflowCheckpointRestoreResult:
    return WorkflowCheckpointRestoreResult(status=status, detail=detail)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_sha256(value: str, *, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 value")


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise TypeError(f"{label} must be an object")
    return value


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise TypeError(f"{label} must be an array")
    return value


def _require_keys(value: Mapping[str, object], keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise ValueError(f"{label} fields are incompatible")


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    return value


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{label} must be boolean")
    return value


def _uuid(value: object, label: str) -> UUID:
    try:
        return UUID(_string(value, label))
    except ValueError as error:
        raise ValueError(f"{label} must be a UUID") from error


def _optional_uuid(value: object, label: str) -> UUID | None:
    return None if value is None else _uuid(value, label)


def _datetime(value: object, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_string(value, label))
    except ValueError as error:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware")
    return parsed


def _optional_datetime(value: object, label: str) -> datetime | None:
    return None if value is None else _datetime(value, label)
