"""Bind JSON metric pointers to an immutable manifest of actual case-study evidence files."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from orchestwin.evaluation.case_metric_bindings import CaseMetricBindingSet
from orchestwin.evaluation.case_source_manifest import (
    ObservedEvidenceManifest,
    verify_observed_evidence_manifest,
)


def _hash(payload: object) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class MetricBindingProvenanceSummary:
    """Exact manifest/binding relationship verified before measurement extraction."""

    case_id: str
    workflow_run_id: UUID
    binding_set_hash: str
    evidence_manifest_hash: str
    metric_source_paths: tuple[str, ...]
    content_hash: str

    def to_snapshot(self, *, include_hash: bool = True) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "case_id": self.case_id,
            "workflow_run_id": str(self.workflow_run_id),
            "binding_set_hash": self.binding_set_hash,
            "evidence_manifest_hash": self.evidence_manifest_hash,
            "metric_source_paths": list(self.metric_source_paths),
        }
        if include_hash:
            snapshot["content_hash"] = self.content_hash
        return snapshot


def verify_metric_binding_provenance(
    *,
    evidence_root: Path,
    binding_set: CaseMetricBindingSet,
    manifest: ObservedEvidenceManifest,
) -> MetricBindingProvenanceSummary:
    """Require every metric source to be present and unchanged in the observed manifest."""
    if binding_set.case_id != manifest.case_id:
        raise ValueError("metric bindings and evidence manifest belong to different cases")
    if binding_set.workflow_run_id != manifest.workflow_run_id:
        raise ValueError("metric bindings and evidence manifest belong to different workflow runs")
    verify_observed_evidence_manifest(evidence_root, manifest)
    manifest_paths = {source.relative_path for source in manifest.sources}
    metric_paths = tuple(sorted({binding.source_path for binding in binding_set.bindings}))
    missing = sorted(set(metric_paths) - manifest_paths)
    if missing:
        raise ValueError(
            "metric sources are absent from observed evidence manifest: " + ", ".join(missing)
        )
    snapshot: dict[str, object] = {
        "case_id": binding_set.case_id,
        "workflow_run_id": str(binding_set.workflow_run_id),
        "binding_set_hash": binding_set.content_hash,
        "evidence_manifest_hash": manifest.content_hash,
        "metric_source_paths": list(metric_paths),
    }
    return MetricBindingProvenanceSummary(
        case_id=binding_set.case_id,
        workflow_run_id=binding_set.workflow_run_id,
        binding_set_hash=binding_set.content_hash,
        evidence_manifest_hash=manifest.content_hash,
        metric_source_paths=metric_paths,
        content_hash=_hash(snapshot),
    )
