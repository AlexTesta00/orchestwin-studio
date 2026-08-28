"""Immutable JVM execution attempts bound to source, profile, runner, and evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from orchestwin.artifacts.jvm_sources import JvmSourceRevisionReference
from orchestwin.jvm_execution.evidence import JvmExecutionReport, JvmPhaseResultStatus
from orchestwin.jvm_execution.plans import JvmExecutionPhase
from orchestwin.jvm_execution.targets import jvm_scope_for


class JvmExecutionAttemptTrigger(StrEnum):
    """Inspectable reason one JVM execution attempt was created."""

    INITIAL = "INITIAL"
    PROFILE_VALIDATION = "PROFILE_VALIDATION"
    REPAIR_RERUN = "REPAIR_RERUN"
    MANUAL_RERUN = "MANUAL_RERUN"


@dataclass(frozen=True, slots=True)
class JvmExecutionAttempt:
    """Append-only JVM attempt with exact lineage and terminal phase evidence."""

    id: UUID
    project_id: UUID
    created_by_user_id: UUID
    attempt_number: int
    previous_attempt_id: UUID | None
    source_revision: JvmSourceRevisionReference
    profile_id: str
    profile_version: str
    profile_validation_content_hash: str
    execution_plan_content_hash: str
    runner_id: str
    runner_version: str
    runner_image_digest: str
    policy_content_hash: str
    trigger: JvmExecutionAttemptTrigger
    executed_phases: tuple[JvmExecutionPhase, ...]
    report: JvmExecutionReport
    started_at: datetime
    completed_at: datetime

    def __post_init__(self) -> None:
        if self.project_id != self.source_revision.project_id:
            raise ValueError("JVM execution attempt and source revision projects differ")
        if isinstance(self.attempt_number, bool) or self.attempt_number < 1:
            raise ValueError("JVM execution attempt number must be positive")
        if self.attempt_number == 1:
            if self.previous_attempt_id is not None:
                raise ValueError("first JVM execution attempt cannot have a predecessor")
        elif self.previous_attempt_id is None:
            raise ValueError("later JVM execution attempt requires a predecessor")
        if self.trigger is JvmExecutionAttemptTrigger.INITIAL and self.attempt_number != 1:
            raise ValueError("INITIAL JVM trigger is valid only for attempt one")

        scope = jvm_scope_for(self.report.target_selection.target)
        if self.profile_id != scope.profile_id or self.profile_version != scope.profile_version:
            raise ValueError("JVM execution attempt profile differs from the report target")
        for value, label in (
            (self.profile_validation_content_hash, "JVM profile validation hash"),
            (self.execution_plan_content_hash, "JVM execution plan hash"),
            (self.runner_image_digest, "JVM runner image digest"),
            (self.policy_content_hash, "JVM execution policy hash"),
        ):
            _validate_sha256(value, label=label)
        for value, label in (
            (self.runner_id, "JVM runner ID"),
            (self.runner_version, "JVM runner version"),
        ):
            _validate_normalized_text(value, label=label)
        if self.report.execution_plan_content_hash != self.execution_plan_content_hash:
            raise ValueError("JVM report targets another execution plan")

        expected_order = {phase: index for index, phase in enumerate(JvmExecutionPhase)}
        if not self.executed_phases:
            raise ValueError("JVM execution attempt requires at least one executed phase")
        if self.executed_phases != tuple(
            sorted(self.executed_phases, key=expected_order.__getitem__)
        ) or len(self.executed_phases) != len(set(self.executed_phases)):
            raise ValueError("JVM executed phases must be canonical and unique")
        report_phases = tuple(result.phase for result in self.report.phase_results)
        if report_phases != tuple(JvmExecutionPhase):
            raise ValueError("persisted JVM attempt requires a complete phase report")
        results_by_phase = {result.phase: result for result in self.report.phase_results}
        if any(
            results_by_phase[phase].status is JvmPhaseResultStatus.NOT_RUN
            for phase in self.executed_phases
        ):
            raise ValueError("executed JVM phase cannot be represented as NOT_RUN")

        for value, label in (
            (self.started_at, "JVM execution start"),
            (self.completed_at, "JVM execution completion"),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{label} timestamp must be timezone-aware")
        if self.completed_at < self.started_at:
            raise ValueError("JVM execution completion precedes its start")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self._content_snapshot())).hexdigest()

    def to_snapshot(self) -> dict[str, object]:
        return {**self._content_snapshot(), "content_hash": self.content_hash}

    def _content_snapshot(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "created_by_user_id": str(self.created_by_user_id),
            "attempt_number": self.attempt_number,
            "previous_attempt_id": (
                None if self.previous_attempt_id is None else str(self.previous_attempt_id)
            ),
            "source_revision": self.source_revision.to_snapshot(),
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "profile_validation_content_hash": self.profile_validation_content_hash,
            "execution_plan_content_hash": self.execution_plan_content_hash,
            "runner_id": self.runner_id,
            "runner_version": self.runner_version,
            "runner_image_digest": self.runner_image_digest,
            "policy_content_hash": self.policy_content_hash,
            "trigger": self.trigger.value,
            "executed_phases": [phase.value for phase in self.executed_phases],
            "report": self.report.to_snapshot(),
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
        }


def _validate_sha256(value: str, *, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} must be lowercase SHA-256")


def _validate_normalized_text(value: str, *, label: str) -> None:
    if not value or value != " ".join(value.split()):
        raise ValueError(f"{label} must be normalized")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
