"""Observed raw metric inputs captured from real governed case-study workflow evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

from orchestwin.evaluation.case_metrics import CaseStudyMeasurement
from orchestwin.evaluation.case_runs import case_study_measurement_snapshot

_OBSERVATION_KIND = "ACTUAL_RUN_EVIDENCE"


def _hash(payload: object) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _validate_relative_path(value: str) -> None:
    normalized = " ".join(value.split())
    if not normalized or normalized != value or "\\" in value:
        raise ValueError("observation source path must be normalized POSIX relative text")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("observation source path must remain inside the evidence root")


@dataclass(frozen=True, slots=True)
class CaseStudyObservationSet:
    """Immutable raw measurements plus exact evidence paths from which they were observed."""

    schema_version: int
    observation_kind: str
    case_id: str
    workflow_run_id: UUID
    measurement: CaseStudyMeasurement
    source_evidence_paths: tuple[str, ...]
    captured_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported case observation schema version")
        if self.observation_kind != _OBSERVATION_KIND:
            raise ValueError("formal case observations must be marked as actual run evidence")
        if self.measurement.case_id != self.case_id:
            raise ValueError("observed measurement must belong to the same case")
        if not self.source_evidence_paths:
            raise ValueError("observed measurements require at least one source evidence path")
        if len(self.source_evidence_paths) != len(set(self.source_evidence_paths)):
            raise ValueError("observation source evidence paths must be unique")
        if self.source_evidence_paths != tuple(sorted(self.source_evidence_paths)):
            raise ValueError("observation source evidence paths must use canonical order")
        for path in self.source_evidence_paths:
            _validate_relative_path(path)
        if self.captured_at.tzinfo is None:
            raise ValueError("case observation capture time must be timezone-aware")
        if self.content_hash != _hash(self.to_snapshot(include_hash=False)):
            raise ValueError("case observation content hash is inconsistent")

    def to_snapshot(self, *, include_hash: bool = True) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "schema_version": self.schema_version,
            "observation_kind": self.observation_kind,
            "case_id": self.case_id,
            "workflow_run_id": str(self.workflow_run_id),
            "measurement": case_study_measurement_snapshot(self.measurement),
            "source_evidence_paths": list(self.source_evidence_paths),
            "captured_at": self.captured_at.isoformat(),
        }
        if include_hash:
            snapshot["content_hash"] = self.content_hash
        return snapshot


def create_case_study_observation_set(
    *,
    workflow_run_id: UUID,
    measurement: CaseStudyMeasurement,
    source_evidence_paths: tuple[str, ...],
    captured_at: datetime,
) -> CaseStudyObservationSet:
    """Create observations only from explicit caller-supplied raw values and evidence paths."""
    ordered_paths = tuple(sorted(source_evidence_paths))
    snapshot: dict[str, object] = {
        "schema_version": 1,
        "observation_kind": _OBSERVATION_KIND,
        "case_id": measurement.case_id,
        "workflow_run_id": str(workflow_run_id),
        "measurement": case_study_measurement_snapshot(measurement),
        "source_evidence_paths": list(ordered_paths),
        "captured_at": captured_at.isoformat(),
    }
    return CaseStudyObservationSet(
        schema_version=1,
        observation_kind=_OBSERVATION_KIND,
        case_id=measurement.case_id,
        workflow_run_id=workflow_run_id,
        measurement=measurement,
        source_evidence_paths=ordered_paths,
        captured_at=captured_at,
        content_hash=_hash(snapshot),
    )


def write_case_study_observation_set(
    path: Path,
    observations: CaseStudyObservationSet,
    *,
    overwrite: bool = False,
) -> None:
    """Persist raw observations atomically and refuse replacement by default."""
    if path.exists() and not overwrite:
        raise FileExistsError(f"case observation file already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        f"{json.dumps(observations.to_snapshot(), ensure_ascii=False, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _required_integer(payload: dict[str, object], key: str) -> int:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"observed measurement field {key} must be an integer")
    return value


def _required_number(payload: dict[str, object], key: str) -> float:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"observed measurement field {key} must be numeric")
    return float(value)


def _required_boolean(payload: dict[str, object], key: str) -> bool:
    value = payload[key]
    if not isinstance(value, bool):
        raise ValueError(f"observed measurement field {key} must be boolean")
    return value


def _measurement_from_snapshot(payload: dict[str, object]) -> CaseStudyMeasurement:
    case_id = payload["case_id"]
    if not isinstance(case_id, str):
        raise ValueError("observed measurement case_id must be text")
    measurement = CaseStudyMeasurement(
        case_id=case_id,
        gates_completed=_required_integer(payload, "gates_completed"),
        gates_total=_required_integer(payload, "gates_total"),
        artifacts_completed=_required_integer(payload, "artifacts_completed"),
        artifacts_total=_required_integer(payload, "artifacts_total"),
        requirements_satisfied=_required_integer(payload, "requirements_satisfied"),
        requirements_total=_required_integer(payload, "requirements_total"),
        criteria_satisfied=_required_integer(payload, "criteria_satisfied"),
        criteria_total=_required_integer(payload, "criteria_total"),
        traceability_links_present=_required_integer(payload, "traceability_links_present"),
        traceability_links_required=_required_integer(payload, "traceability_links_required"),
        tests_passed=_required_integer(payload, "tests_passed"),
        tests_total=_required_integer(payload, "tests_total"),
        repair_successes=_required_integer(payload, "repair_successes"),
        repair_attempts=_required_integer(payload, "repair_attempts"),
        build_succeeded=_required_boolean(payload, "build_succeeded"),
        final_runtime_succeeded=_required_boolean(payload, "final_runtime_succeeded"),
        elapsed_seconds=_required_number(payload, "elapsed_seconds"),
        model_calls=_required_integer(payload, "model_calls"),
        input_tokens=_required_integer(payload, "input_tokens"),
        output_tokens=_required_integer(payload, "output_tokens"),
        estimated_cost_usd=_required_number(payload, "estimated_cost_usd"),
    )
    if payload["derived_metrics"] != measurement.metric_snapshot():
        raise ValueError("observed derived metrics are inconsistent with raw measurements")
    return measurement


def load_case_study_observation_set(path: Path) -> CaseStudyObservationSet:
    """Load observations and revalidate raw counts, derived metrics, and content identity."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return CaseStudyObservationSet(
        schema_version=payload["schema_version"],
        observation_kind=payload["observation_kind"],
        case_id=payload["case_id"],
        workflow_run_id=UUID(payload["workflow_run_id"]),
        measurement=_measurement_from_snapshot(payload["measurement"]),
        source_evidence_paths=tuple(payload["source_evidence_paths"]),
        captured_at=datetime.fromisoformat(payload["captured_at"]),
        content_hash=payload["content_hash"],
    )
