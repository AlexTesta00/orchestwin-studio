"""Finalize formal case-study records only from observed files, metrics, and environment data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

from orchestwin.evaluation.case_artifact_capture import (
    CaseStudyEvidenceMapEntry,
    capture_case_study_evidence,
)
from orchestwin.evaluation.case_environment import (
    CaseStudyEnvironmentIdentity,
    verify_case_study_environment_binding,
)
from orchestwin.evaluation.case_evidence import (
    CaseStudyEvidenceCoverageSummary,
    evaluate_case_study_evidence_coverage,
)
from orchestwin.evaluation.case_observations import CaseStudyObservationSet
from orchestwin.evaluation.case_run_io import write_case_study_run_record
from orchestwin.evaluation.case_runs import (
    CaseStudyRunRecord,
    CaseStudyRunStatus,
    create_case_study_run_record,
)
from orchestwin.evaluation.case_studies import CaseStudyDefinition
from orchestwin.evaluation.case_workspace import (
    CaseStudyRunRequest,
    CaseStudyRunWorkspace,
)


@dataclass(frozen=True, slots=True)
class FinalizedFormalCaseRun:
    """Validated terminal record and evidence-derived Definition-of-Done coverage."""

    record: CaseStudyRunRecord
    coverage: CaseStudyEvidenceCoverageSummary
    record_path: Path


def _verify_request_binding(
    request: CaseStudyRunRequest,
    definition: CaseStudyDefinition,
    environment: CaseStudyEnvironmentIdentity,
) -> None:
    if request.case_id != definition.case_id:
        raise ValueError("formal run request and case definition use different case IDs")
    if request.case_version != definition.version:
        raise ValueError("formal run request and case definition use different versions")
    if request.case_content_hash != definition.content_hash:
        raise ValueError("formal run request and case definition use different hashes")
    if request.execution_profile != definition.execution_profile:
        raise ValueError("formal run request and case definition use different profiles")
    if request.platform_commit != environment.platform_commit:
        raise ValueError("formal run request and environment use different platform commits")
    if request.execution_profile != environment.execution_profile:
        raise ValueError("formal run request and environment use different execution profiles")


def finalize_case_study_run(
    *,
    workspace: CaseStudyRunWorkspace,
    request: CaseStudyRunRequest,
    definition: CaseStudyDefinition,
    environment: CaseStudyEnvironmentIdentity,
    evidence_map: tuple[CaseStudyEvidenceMapEntry, ...],
    observations: CaseStudyObservationSet | None,
    started_at: datetime,
    completed_at: datetime,
    status: CaseStudyRunStatus,
    notes: tuple[str, ...] = (),
    record_id: UUID | None = None,
) -> FinalizedFormalCaseRun:
    """Create a terminal case record without fabricating missing files or raw measurements."""
    _verify_request_binding(request, definition, environment)
    if status is CaseStudyRunStatus.COMPLETED and observations is None:
        raise ValueError("completed formal case runs require observed raw measurements")
    if observations is not None:
        if observations.case_id != request.case_id:
            raise ValueError("formal observations belong to a different case")
        if observations.workflow_run_id != request.workflow_run_id:
            raise ValueError("formal observations belong to a different workflow run")

    evidence = capture_case_study_evidence(workspace.evidence_dir, evidence_map)
    captured_paths = {item.relative_path for item in evidence}
    if observations is not None:
        missing_sources = [
            path for path in observations.source_evidence_paths if path not in captured_paths
        ]
        if missing_sources:
            raise ValueError(
                "observed metric source paths are not part of captured evidence: "
                + ", ".join(missing_sources)
            )

    record = create_case_study_run_record(
        case_id=request.case_id,
        case_version=request.case_version,
        case_content_hash=request.case_content_hash,
        workflow_run_id=request.workflow_run_id,
        platform_commit=request.platform_commit,
        execution_profile=request.execution_profile,
        environment_identity_hash=environment.content_hash,
        started_at=started_at,
        completed_at=completed_at,
        status=status,
        evidence=evidence,
        measurement=None if observations is None else observations.measurement,
        notes=notes,
        run_id=record_id,
    )
    verify_case_study_environment_binding(record, environment)
    coverage = evaluate_case_study_evidence_coverage(definition, record)
    if status is CaseStudyRunStatus.COMPLETED and not coverage.is_complete:
        raise ValueError("completed formal case runs require complete Definition-of-Done evidence")

    record_path = workspace.final_dir / "case-run.json"
    write_case_study_run_record(record_path, record)
    return FinalizedFormalCaseRun(record=record, coverage=coverage, record_path=record_path)
