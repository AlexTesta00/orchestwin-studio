"""Derive CaseStudyMeasurement values only from bound observed JSON evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from orchestwin.evaluation.case_metric_bindings import (
    CaseMetricBindingSet,
    resolve_case_metric_values,
)
from orchestwin.evaluation.case_metrics import CaseStudyMeasurement
from orchestwin.evaluation.case_runs import case_study_measurement_snapshot
from orchestwin.evaluation.case_studies import CaseStudyDefinition


def _hash(payload: object) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class HarvestedCaseStudyMeasurement:
    """Observed measurement plus exact binding identity and source paths."""

    measurement: CaseStudyMeasurement
    source_evidence_paths: tuple[str, ...]
    binding_set_hash: str
    content_hash: str

    def to_snapshot(self, *, include_hash: bool = True) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "measurement": case_study_measurement_snapshot(self.measurement),
            "source_evidence_paths": list(self.source_evidence_paths),
            "binding_set_hash": self.binding_set_hash,
        }
        if include_hash:
            snapshot["content_hash"] = self.content_hash
        return snapshot


def harvest_case_study_measurement(
    *,
    definition: CaseStudyDefinition,
    workflow_run_id: UUID,
    evidence_root: Path,
    binding_set: CaseMetricBindingSet,
) -> HarvestedCaseStudyMeasurement:
    """Build raw measurements from actual JSON values without copying caller-supplied counts."""
    if binding_set.case_id != definition.case_id:
        raise ValueError("metric binding set belongs to a different formal case")
    if binding_set.workflow_run_id != workflow_run_id:
        raise ValueError("metric binding set belongs to a different workflow run")
    values = resolve_case_metric_values(evidence_root, binding_set)
    measurement = CaseStudyMeasurement(case_id=definition.case_id, **values)
    source_paths = tuple(sorted({binding.source_path for binding in binding_set.bindings}))
    snapshot: dict[str, object] = {
        "measurement": case_study_measurement_snapshot(measurement),
        "source_evidence_paths": list(source_paths),
        "binding_set_hash": binding_set.content_hash,
    }
    return HarvestedCaseStudyMeasurement(
        measurement=measurement,
        source_evidence_paths=source_paths,
        binding_set_hash=binding_set.content_hash,
        content_hash=_hash(snapshot),
    )
