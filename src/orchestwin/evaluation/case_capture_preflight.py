"""Preflight semantic mappings before a formal case workspace is harvested."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from orchestwin.evaluation.case_artifact_capture import CaseStudyEvidenceMapEntry
from orchestwin.evaluation.case_metric_bindings import CaseMetricBindingSet
from orchestwin.evaluation.case_source_manifest import ObservedEvidenceManifest
from orchestwin.evaluation.case_studies import CaseStudyDefinition
from orchestwin.evaluation.case_workspace import CaseStudyRunRequest


def _hash(payload: object) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CaseCapturePreflightSummary:
    """Inspectable proof that observed files cover the frozen DoD before harvesting."""

    case_id: str
    workflow_run_id: str
    manifest_source_count: int
    metric_source_count: int
    required_evidence_pairs: int
    covered_evidence_pairs: int
    complete: bool
    content_hash: str

    def to_snapshot(self, *, include_hash: bool = True) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "case_id": self.case_id,
            "workflow_run_id": self.workflow_run_id,
            "manifest_source_count": self.manifest_source_count,
            "metric_source_count": self.metric_source_count,
            "required_evidence_pairs": self.required_evidence_pairs,
            "covered_evidence_pairs": self.covered_evidence_pairs,
            "complete": self.complete,
        }
        if include_hash:
            snapshot["content_hash"] = self.content_hash
        return snapshot


def evaluate_case_capture_preflight(
    *,
    definition: CaseStudyDefinition,
    request: CaseStudyRunRequest,
    binding_set: CaseMetricBindingSet,
    manifest: ObservedEvidenceManifest,
    evidence_map: tuple[CaseStudyEvidenceMapEntry, ...],
) -> CaseCapturePreflightSummary:
    """Require exact case/run binding and complete explicit DoD-to-file mappings."""
    if request.case_id != definition.case_id or request.case_version != definition.version:
        raise ValueError("case run request does not match the frozen definition")
    if request.case_content_hash != definition.content_hash:
        raise ValueError("case run request uses a different frozen definition hash")
    if request.execution_profile != definition.execution_profile:
        raise ValueError("case run request uses a different execution profile")
    if binding_set.case_id != request.case_id or manifest.case_id != request.case_id:
        raise ValueError("capture inputs belong to different formal cases")
    if (
        binding_set.workflow_run_id != request.workflow_run_id
        or manifest.workflow_run_id != request.workflow_run_id
    ):
        raise ValueError("capture inputs belong to different workflow runs")

    manifest_paths = {source.relative_path for source in manifest.sources}
    metric_paths = {binding.source_path for binding in binding_set.bindings}
    missing_metric_paths = sorted(metric_paths - manifest_paths)
    if missing_metric_paths:
        raise ValueError(
            "metric sources are not present in observed manifest: "
            + ", ".join(missing_metric_paths)
        )

    map_paths = {entry.relative_path for entry in evidence_map}
    missing_map_paths = sorted(map_paths - manifest_paths)
    if missing_map_paths:
        raise ValueError(
            "evidence-map sources are not present in observed manifest: "
            + ", ".join(missing_map_paths)
        )

    known_criteria = {criterion.criterion_id for criterion in definition.definition_of_done}
    for entry in evidence_map:
        unknown = sorted(set(entry.criterion_ids) - known_criteria)
        if unknown:
            raise ValueError("evidence map references unknown DoD criteria: " + ", ".join(unknown))

    required_pairs = {
        (criterion.criterion_id, kind)
        for criterion in definition.definition_of_done
        for kind in criterion.evidence
    }
    covered_pairs = {
        (criterion_id, entry.kind) for entry in evidence_map for criterion_id in entry.criterion_ids
    }
    missing_pairs = sorted(
        required_pairs - covered_pairs,
        key=lambda item: (item[0], item[1].value),
    )
    if missing_pairs:
        formatted = ", ".join(
            f"{criterion_id}:{kind.value}" for criterion_id, kind in missing_pairs
        )
        raise ValueError("frozen Definition-of-Done evidence mapping is incomplete: " + formatted)

    snapshot: dict[str, object] = {
        "case_id": definition.case_id,
        "workflow_run_id": str(request.workflow_run_id),
        "manifest_source_count": len(manifest_paths),
        "metric_source_count": len(metric_paths),
        "required_evidence_pairs": len(required_pairs),
        "covered_evidence_pairs": len(required_pairs),
        "complete": True,
    }
    return CaseCapturePreflightSummary(
        case_id=definition.case_id,
        workflow_run_id=str(request.workflow_run_id),
        manifest_source_count=len(manifest_paths),
        metric_source_count=len(metric_paths),
        required_evidence_pairs=len(required_pairs),
        covered_evidence_pairs=len(required_pairs),
        complete=True,
        content_hash=_hash(snapshot),
    )
