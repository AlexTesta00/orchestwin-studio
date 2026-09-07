"""Immutable finalized run records for formal Sprint 12 case studies."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final
from uuid import UUID, uuid4

from orchestwin.evaluation.case_metrics import CaseStudyMeasurement
from orchestwin.evaluation.case_studies import CaseStudyEvidenceKind

_SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}")
_GIT_SHA1_PATTERN: Final = re.compile(r"[0-9a-f]{40}")
_MAX_TEXT_LENGTH: Final = 4_000


class CaseStudyRunStatus(StrEnum):
    """Terminal states preserved by a finalized formal case-study record."""

    ABORTED = "ABORTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def _normalize_required_text(value: str, *, label: str, maximum: int = _MAX_TEXT_LENGTH) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"{label} exceeds maximum length")
    if normalized != value:
        raise ValueError(f"{label} must be normalized")
    return normalized


def _validate_sha256(value: str, *, label: str) -> None:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


def _validate_git_commit(value: str) -> None:
    if _GIT_SHA1_PATTERN.fullmatch(value) is None:
        raise ValueError("platform commit must be a lowercase 40-character Git commit SHA")


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _validate_relative_path(value: str) -> None:
    _normalize_required_text(value, label="evidence relative path", maximum=1_000)
    if "\\" in value:
        raise ValueError("evidence relative path must use POSIX separators")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("evidence relative path must remain inside the case evidence root")


def case_study_measurement_snapshot(measurement: CaseStudyMeasurement) -> dict[str, object]:
    """Preserve raw measurement inputs together with their deterministic derived metrics."""
    return {
        "case_id": measurement.case_id,
        "gates_completed": measurement.gates_completed,
        "gates_total": measurement.gates_total,
        "artifacts_completed": measurement.artifacts_completed,
        "artifacts_total": measurement.artifacts_total,
        "requirements_satisfied": measurement.requirements_satisfied,
        "requirements_total": measurement.requirements_total,
        "criteria_satisfied": measurement.criteria_satisfied,
        "criteria_total": measurement.criteria_total,
        "traceability_links_present": measurement.traceability_links_present,
        "traceability_links_required": measurement.traceability_links_required,
        "tests_passed": measurement.tests_passed,
        "tests_total": measurement.tests_total,
        "repair_successes": measurement.repair_successes,
        "repair_attempts": measurement.repair_attempts,
        "build_succeeded": measurement.build_succeeded,
        "final_runtime_succeeded": measurement.final_runtime_succeeded,
        "elapsed_seconds": measurement.elapsed_seconds,
        "model_calls": measurement.model_calls,
        "input_tokens": measurement.input_tokens,
        "output_tokens": measurement.output_tokens,
        "estimated_cost_usd": measurement.estimated_cost_usd,
        "derived_metrics": measurement.metric_snapshot(),
    }


@dataclass(frozen=True, slots=True)
class CaseStudyEvidenceReference:
    """One content-addressed file mapped to the DoD criteria it supports."""

    kind: CaseStudyEvidenceKind
    relative_path: str
    sha256_digest: str
    size_bytes: int
    criterion_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_relative_path(self.relative_path)
        _validate_sha256(self.sha256_digest, label="evidence digest")
        if isinstance(self.size_bytes, bool) or self.size_bytes < 1:
            raise ValueError("evidence size must be a positive integer")
        if not self.criterion_ids:
            raise ValueError("evidence must reference at least one Definition of Done criterion")
        if len(self.criterion_ids) != len(set(self.criterion_ids)):
            raise ValueError("evidence criterion IDs must be unique")
        for criterion_id in self.criterion_ids:
            _normalize_required_text(
                criterion_id,
                label="evidence criterion ID",
                maximum=200,
            )
        if self.criterion_ids != tuple(sorted(self.criterion_ids)):
            raise ValueError("evidence criterion IDs must use canonical order")

    @property
    def sort_key(self) -> tuple[str, str, str, tuple[str, ...]]:
        return (
            self.kind.value,
            self.relative_path,
            self.sha256_digest,
            self.criterion_ids,
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "relative_path": self.relative_path,
            "sha256_digest": self.sha256_digest,
            "size_bytes": self.size_bytes,
            "criterion_ids": list(self.criterion_ids),
        }


@dataclass(frozen=True, slots=True)
class CaseStudyRunRecord:
    """Immutable terminal record binding one case to exact code, environment, and evidence."""

    schema_version: int
    run_id: UUID
    case_id: str
    case_version: int
    case_content_hash: str
    workflow_run_id: UUID
    platform_commit: str
    execution_profile: str
    environment_identity_hash: str
    started_at: datetime
    completed_at: datetime
    status: CaseStudyRunStatus
    evidence: tuple[CaseStudyEvidenceReference, ...]
    measurement: CaseStudyMeasurement | None
    notes: tuple[str, ...]
    real_user_behavior_validated: bool
    empirical_user_evidence_created: bool
    content_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported case-study run schema version")
        if self.case_version < 1:
            raise ValueError("case-study run case version must be positive")
        _normalize_required_text(self.case_id, label="case-study run case ID", maximum=200)
        _validate_sha256(self.case_content_hash, label="case-study definition hash")
        _validate_git_commit(self.platform_commit)
        _normalize_required_text(
            self.execution_profile,
            label="case-study execution profile",
            maximum=200,
        )
        _validate_sha256(self.environment_identity_hash, label="environment identity hash")
        if self.started_at.tzinfo is None or self.completed_at.tzinfo is None:
            raise ValueError("case-study run timestamps must be timezone-aware")
        if self.completed_at < self.started_at:
            raise ValueError("case-study run completion must not precede start")
        if not self.evidence:
            raise ValueError("case-study run must preserve at least one evidence reference")
        if self.evidence != tuple(sorted(self.evidence, key=lambda item: item.sort_key)):
            raise ValueError("case-study evidence references must use canonical order")
        paths = tuple(item.relative_path for item in self.evidence)
        if len(paths) != len(set(paths)):
            raise ValueError("case-study evidence paths must be unique")
        if self.status is CaseStudyRunStatus.COMPLETED and self.measurement is None:
            raise ValueError("completed case-study runs require raw measurements")
        if self.measurement is not None and self.measurement.case_id != self.case_id:
            raise ValueError("case-study measurement must belong to the same case")
        if len(self.notes) != len(set(self.notes)):
            raise ValueError("case-study run notes must be unique")
        for note in self.notes:
            _normalize_required_text(note, label="case-study run note")
        if self.notes != tuple(sorted(self.notes)):
            raise ValueError("case-study run notes must use canonical order")
        if self.real_user_behavior_validated:
            raise ValueError("formal case-study runs must not claim real-user behavior validation")
        if self.empirical_user_evidence_created:
            raise ValueError("formal case-study runs must not claim empirical user evidence")
        _validate_sha256(self.content_hash, label="case-study run content hash")
        if self.content_hash != case_study_run_content_hash(self.to_snapshot(include_hash=False)):
            raise ValueError("case-study run content hash is inconsistent")

    def to_snapshot(self, *, include_hash: bool = True) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "schema_version": self.schema_version,
            "run_id": str(self.run_id),
            "case_id": self.case_id,
            "case_version": self.case_version,
            "case_content_hash": self.case_content_hash,
            "workflow_run_id": str(self.workflow_run_id),
            "platform_commit": self.platform_commit,
            "execution_profile": self.execution_profile,
            "environment_identity_hash": self.environment_identity_hash,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "status": self.status.value,
            "evidence": [item.to_snapshot() for item in self.evidence],
            "measurement": (
                None
                if self.measurement is None
                else case_study_measurement_snapshot(self.measurement)
            ),
            "notes": list(self.notes),
            "real_user_behavior_validated": self.real_user_behavior_validated,
            "empirical_user_evidence_created": self.empirical_user_evidence_created,
        }
        if include_hash:
            snapshot["content_hash"] = self.content_hash
        return snapshot


def case_study_run_content_hash(payload: object) -> str:
    """Return the deterministic semantic identity of a finalized case-study run."""
    return _hash(payload)


def create_case_study_run_record(
    *,
    case_id: str,
    case_version: int,
    case_content_hash: str,
    workflow_run_id: UUID,
    platform_commit: str,
    execution_profile: str,
    environment_identity_hash: str,
    started_at: datetime,
    completed_at: datetime,
    status: CaseStudyRunStatus,
    evidence: tuple[CaseStudyEvidenceReference, ...],
    measurement: CaseStudyMeasurement | None,
    notes: tuple[str, ...] = (),
    run_id: UUID | None = None,
) -> CaseStudyRunRecord:
    """Create one canonically ordered finalized record with conservative claim flags."""
    ordered_evidence = tuple(sorted(evidence, key=lambda item: item.sort_key))
    ordered_notes = tuple(sorted(notes))
    record_id = run_id or uuid4()
    snapshot: dict[str, object] = {
        "schema_version": 1,
        "run_id": str(record_id),
        "case_id": case_id,
        "case_version": case_version,
        "case_content_hash": case_content_hash,
        "workflow_run_id": str(workflow_run_id),
        "platform_commit": platform_commit,
        "execution_profile": execution_profile,
        "environment_identity_hash": environment_identity_hash,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "status": status.value,
        "evidence": [item.to_snapshot() for item in ordered_evidence],
        "measurement": (
            None if measurement is None else case_study_measurement_snapshot(measurement)
        ),
        "notes": list(ordered_notes),
        "real_user_behavior_validated": False,
        "empirical_user_evidence_created": False,
    }
    return CaseStudyRunRecord(
        schema_version=1,
        run_id=record_id,
        case_id=case_id,
        case_version=case_version,
        case_content_hash=case_content_hash,
        workflow_run_id=workflow_run_id,
        platform_commit=platform_commit,
        execution_profile=execution_profile,
        environment_identity_hash=environment_identity_hash,
        started_at=started_at,
        completed_at=completed_at,
        status=status,
        evidence=ordered_evidence,
        measurement=measurement,
        notes=ordered_notes,
        real_user_behavior_validated=False,
        empirical_user_evidence_created=False,
        content_hash=case_study_run_content_hash(snapshot),
    )
