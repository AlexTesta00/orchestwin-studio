"""Immutable Web execution attempts bound to source, profile, plan, and evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from orchestwin.artifacts.web_sources import WebSourceRevisionReference
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.reports import (
    WebExecutionReport,
    WebPhaseResultStatus,
)


class WebExecutionAttemptTrigger(StrEnum):
    """Inspectable reason one Web execution attempt was created."""

    INITIAL = "INITIAL"
    PROFILE_VALIDATION = "PROFILE_VALIDATION"
    REPAIR_RERUN = "REPAIR_RERUN"
    MANUAL_RERUN = "MANUAL_RERUN"


@dataclass(frozen=True, slots=True)
class WebExecutionAttempt:
    """Append-only execution attempt with exact lineage and terminal evidence."""

    id: UUID
    project_id: UUID
    created_by_user_id: UUID
    attempt_number: int
    previous_attempt_id: UUID | None
    source_revision: WebSourceRevisionReference
    profile_validation_content_hash: str
    execution_plan_content_hash: str
    trigger: WebExecutionAttemptTrigger
    executed_phases: tuple[WebExecutionPhase, ...]
    report: WebExecutionReport
    started_at: datetime
    completed_at: datetime

    def __post_init__(self) -> None:
        if self.project_id != self.source_revision.project_id:
            raise ValueError("Web execution attempt and source revision projects differ")
        if isinstance(self.attempt_number, bool) or self.attempt_number < 1:
            raise ValueError("Web execution attempt number must be positive")
        if self.attempt_number == 1:
            if self.previous_attempt_id is not None:
                raise ValueError("first Web execution attempt cannot have a predecessor")
        elif self.previous_attempt_id is None:
            raise ValueError("later Web execution attempt requires a predecessor")
        if self.trigger is WebExecutionAttemptTrigger.INITIAL and self.attempt_number != 1:
            raise ValueError("INITIAL Web execution trigger is valid only for attempt one")
        for value, label in (
            (
                self.profile_validation_content_hash,
                "Web execution profile validation hash",
            ),
            (self.execution_plan_content_hash, "Web execution plan hash"),
        ):
            _validate_sha256(value, label=label)
        expected_order = {phase: index for index, phase in enumerate(WebExecutionPhase)}
        if not self.executed_phases:
            raise ValueError("Web execution attempt requires at least one executed phase")
        if self.executed_phases != tuple(
            sorted(self.executed_phases, key=expected_order.__getitem__)
        ) or len(self.executed_phases) != len(set(self.executed_phases)):
            raise ValueError("Web executed phases must be canonical and unique")
        report_phases = tuple(result.phase for result in self.report.phase_results)
        if report_phases != tuple(WebExecutionPhase):
            raise ValueError("persisted Web execution attempt requires a complete phase report")
        results_by_phase = {result.phase: result for result in self.report.phase_results}
        if any(
            results_by_phase[phase].status is WebPhaseResultStatus.NOT_RUN
            for phase in self.executed_phases
        ):
            raise ValueError("executed Web phase cannot be represented as NOT_RUN")
        if self.report.source_revision_content_hash != self.source_revision.content_hash:
            raise ValueError("Web report targets another source revision")
        if self.report.source_tree_hash != self.source_revision.source_tree_hash:
            raise ValueError("Web report targets another source tree")
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            raise ValueError("Web execution start timestamp must be timezone-aware")
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None:
            raise ValueError("Web execution completion timestamp must be timezone-aware")
        if self.completed_at < self.started_at:
            raise ValueError("Web execution completion precedes its start")

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
            "profile_validation_content_hash": self.profile_validation_content_hash,
            "execution_plan_content_hash": self.execution_plan_content_hash,
            "trigger": self.trigger.value,
            "executed_phases": [phase.value for phase in self.executed_phases],
            "report": self.report.to_snapshot(),
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
        }


def _validate_sha256(value: str, *, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} must be lowercase SHA-256")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
