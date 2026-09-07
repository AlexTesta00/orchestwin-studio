"""Generic workspace harvester turning actual run files into finalization-ready observations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from orchestwin.evaluation.case_artifact_capture import CaseStudyEvidenceMapEntry
from orchestwin.evaluation.case_capture_preflight import (
    CaseCapturePreflightSummary,
    evaluate_case_capture_preflight,
)
from orchestwin.evaluation.case_metric_bindings import CaseMetricBindingSet
from orchestwin.evaluation.case_observation_harvest import (
    CaseObservationHarvestRecord,
    harvest_case_study_observations,
    write_case_observation_harvest_record,
)
from orchestwin.evaluation.case_observations import (
    CaseStudyObservationSet,
    write_case_study_observation_set,
)
from orchestwin.evaluation.case_source_manifest import (
    ObservedEvidenceManifest,
    capture_observed_evidence_manifest,
    write_observed_evidence_manifest,
)
from orchestwin.evaluation.case_studies import CaseStudyDefinition
from orchestwin.evaluation.case_workspace import CaseStudyRunRequest, CaseStudyRunWorkspace


@dataclass(frozen=True, slots=True)
class HarvestedCaseWorkspace:
    """Finalization-ready raw files produced from actual evidence without executing the case."""

    manifest: ObservedEvidenceManifest
    observations: CaseStudyObservationSet
    harvest_record: CaseObservationHarvestRecord
    preflight: CaseCapturePreflightSummary
    manifest_path: Path
    observations_path: Path
    harvest_record_path: Path
    evidence_map_path: Path

    def to_snapshot(self) -> dict[str, object]:
        return {
            "case_id": self.observations.case_id,
            "workflow_run_id": str(self.observations.workflow_run_id),
            "manifest_hash": self.manifest.content_hash,
            "observation_hash": self.observations.content_hash,
            "harvest_record_hash": self.harvest_record.content_hash,
            "preflight_hash": self.preflight.content_hash,
            "manifest_path": str(self.manifest_path),
            "observations_path": str(self.observations_path),
            "harvest_record_path": str(self.harvest_record_path),
            "evidence_map_path": str(self.evidence_map_path),
        }


def _write_evidence_map(path: Path, entries: tuple[CaseStudyEvidenceMapEntry, ...]) -> None:
    payload = {
        "schema_version": 1,
        "entries": [
            entry.to_snapshot() for entry in sorted(entries, key=lambda item: item.sort_key)
        ],
    }
    path.write_text(
        f"{json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )


def harvest_case_study_workspace_evidence(
    *,
    workspace: CaseStudyRunWorkspace,
    request: CaseStudyRunRequest,
    definition: CaseStudyDefinition,
    binding_set: CaseMetricBindingSet,
    evidence_map: tuple[CaseStudyEvidenceMapEntry, ...],
    captured_at: datetime,
) -> HarvestedCaseWorkspace:
    """Harvest a prepared workspace without running, repairing, or mutating OrchesTwin itself."""
    target_paths = {
        "manifest": workspace.raw_dir / "evidence-manifest.json",
        "observations": workspace.raw_dir / "observations.json",
        "harvest": workspace.raw_dir / "observation-harvest.json",
        "evidence_map": workspace.raw_dir / "evidence-map.json",
    }
    existing = [str(path) for path in target_paths.values() if path.exists()]
    if existing:
        raise FileExistsError("formal case harvest output already exists: " + ", ".join(existing))

    source_paths = tuple(
        sorted(
            {
                *(binding.source_path for binding in binding_set.bindings),
                *(entry.relative_path for entry in evidence_map),
            }
        )
    )
    manifest = capture_observed_evidence_manifest(
        evidence_root=workspace.evidence_dir,
        case_id=request.case_id,
        workflow_run_id=request.workflow_run_id,
        relative_paths=source_paths,
        captured_at=captured_at,
    )
    preflight = evaluate_case_capture_preflight(
        definition=definition,
        request=request,
        binding_set=binding_set,
        manifest=manifest,
        evidence_map=evidence_map,
    )
    observations, harvest_record = harvest_case_study_observations(
        definition=definition,
        workflow_run_id=request.workflow_run_id,
        evidence_root=workspace.evidence_dir,
        binding_set=binding_set,
        manifest=manifest,
        captured_at=captured_at,
    )

    write_observed_evidence_manifest(target_paths["manifest"], manifest)
    write_case_study_observation_set(target_paths["observations"], observations)
    write_case_observation_harvest_record(target_paths["harvest"], harvest_record)
    _write_evidence_map(target_paths["evidence_map"], evidence_map)
    return HarvestedCaseWorkspace(
        manifest=manifest,
        observations=observations,
        harvest_record=harvest_record,
        preflight=preflight,
        manifest_path=target_paths["manifest"],
        observations_path=target_paths["observations"],
        harvest_record_path=target_paths["harvest"],
        evidence_map_path=target_paths["evidence_map"],
    )
