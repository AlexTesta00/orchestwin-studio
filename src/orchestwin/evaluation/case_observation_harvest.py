"""Materialize observation sets with immutable binding and source-manifest provenance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

from orchestwin.evaluation.case_measurement_harvest import harvest_case_study_measurement
from orchestwin.evaluation.case_metric_bindings import CaseMetricBindingSet
from orchestwin.evaluation.case_metric_provenance import verify_metric_binding_provenance
from orchestwin.evaluation.case_observations import (
    CaseStudyObservationSet,
    create_case_study_observation_set,
)
from orchestwin.evaluation.case_source_manifest import ObservedEvidenceManifest
from orchestwin.evaluation.case_studies import CaseStudyDefinition


def _hash(payload: object) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CaseObservationHarvestRecord:
    """Audit record linking final observations to exact metric bindings and source identities."""

    schema_version: int
    case_id: str
    workflow_run_id: UUID
    binding_set_hash: str
    evidence_manifest_hash: str
    observation_content_hash: str
    metric_source_paths: tuple[str, ...]
    captured_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported case observation harvest record version")
        if self.captured_at.tzinfo is None:
            raise ValueError("observation harvest timestamp must be timezone-aware")
        if self.content_hash != _hash(self.to_snapshot(include_hash=False)):
            raise ValueError("observation harvest content hash is inconsistent")

    def to_snapshot(self, *, include_hash: bool = True) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "workflow_run_id": str(self.workflow_run_id),
            "binding_set_hash": self.binding_set_hash,
            "evidence_manifest_hash": self.evidence_manifest_hash,
            "observation_content_hash": self.observation_content_hash,
            "metric_source_paths": list(self.metric_source_paths),
            "captured_at": self.captured_at.isoformat(),
        }
        if include_hash:
            snapshot["content_hash"] = self.content_hash
        return snapshot


def harvest_case_study_observations(
    *,
    definition: CaseStudyDefinition,
    workflow_run_id: UUID,
    evidence_root: Path,
    binding_set: CaseMetricBindingSet,
    manifest: ObservedEvidenceManifest,
    captured_at: datetime,
) -> tuple[CaseStudyObservationSet, CaseObservationHarvestRecord]:
    """Create observations only after source files and metric pointers pass provenance checks."""
    provenance = verify_metric_binding_provenance(
        evidence_root=evidence_root,
        binding_set=binding_set,
        manifest=manifest,
    )
    harvested = harvest_case_study_measurement(
        definition=definition,
        workflow_run_id=workflow_run_id,
        evidence_root=evidence_root,
        binding_set=binding_set,
    )
    if harvested.source_evidence_paths != provenance.metric_source_paths:
        raise ValueError("harvested metric sources disagree with verified provenance")
    observations = create_case_study_observation_set(
        workflow_run_id=workflow_run_id,
        measurement=harvested.measurement,
        source_evidence_paths=harvested.source_evidence_paths,
        captured_at=captured_at,
    )
    snapshot: dict[str, object] = {
        "schema_version": 1,
        "case_id": definition.case_id,
        "workflow_run_id": str(workflow_run_id),
        "binding_set_hash": binding_set.content_hash,
        "evidence_manifest_hash": manifest.content_hash,
        "observation_content_hash": observations.content_hash,
        "metric_source_paths": list(harvested.source_evidence_paths),
        "captured_at": captured_at.isoformat(),
    }
    return (
        observations,
        CaseObservationHarvestRecord(
            schema_version=1,
            case_id=definition.case_id,
            workflow_run_id=workflow_run_id,
            binding_set_hash=binding_set.content_hash,
            evidence_manifest_hash=manifest.content_hash,
            observation_content_hash=observations.content_hash,
            metric_source_paths=harvested.source_evidence_paths,
            captured_at=captured_at,
            content_hash=_hash(snapshot),
        ),
    )


def write_case_observation_harvest_record(
    path: Path,
    record: CaseObservationHarvestRecord,
) -> None:
    """Persist the provenance record without overwriting previous observed evidence."""
    if path.exists():
        raise FileExistsError(f"observation harvest record already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"{json.dumps(record.to_snapshot(), ensure_ascii=False, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )


def load_case_observation_harvest_record(path: Path) -> CaseObservationHarvestRecord:
    """Load and revalidate an observation harvest provenance record."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return CaseObservationHarvestRecord(
        schema_version=payload["schema_version"],
        case_id=payload["case_id"],
        workflow_run_id=UUID(payload["workflow_run_id"]),
        binding_set_hash=payload["binding_set_hash"],
        evidence_manifest_hash=payload["evidence_manifest_hash"],
        observation_content_hash=payload["observation_content_hash"],
        metric_source_paths=tuple(payload["metric_source_paths"]),
        captured_at=datetime.fromisoformat(payload["captured_at"]),
        content_hash=payload["content_hash"],
    )
