"""Deterministic JSON persistence for finalized formal case-study run records."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

from orchestwin.evaluation.case_metrics import CaseStudyMeasurement
from orchestwin.evaluation.case_runs import (
    CaseStudyEvidenceReference,
    CaseStudyRunRecord,
    CaseStudyRunStatus,
)
from orchestwin.evaluation.case_studies import CaseStudyEvidenceKind


def write_case_study_run_record(
    path: Path,
    record: CaseStudyRunRecord,
    *,
    overwrite: bool = False,
) -> None:
    """Persist a finalized record atomically without overwriting evidence by default."""
    if path.exists() and not overwrite:
        raise FileExistsError(f"case-study run record already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    payload = json.dumps(
        record.to_snapshot(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    temporary.write_text(f"{payload}\n", encoding="utf-8")
    temporary.replace(path)


def load_case_study_run_record(path: Path) -> CaseStudyRunRecord:
    """Load one finalized record and re-run every hash and invariant check."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    measurement_payload = payload["measurement"]
    measurement = None
    if measurement_payload is not None:
        measurement = CaseStudyMeasurement(
            case_id=measurement_payload["case_id"],
            gates_completed=measurement_payload["gates_completed"],
            gates_total=measurement_payload["gates_total"],
            artifacts_completed=measurement_payload["artifacts_completed"],
            artifacts_total=measurement_payload["artifacts_total"],
            requirements_satisfied=measurement_payload["requirements_satisfied"],
            requirements_total=measurement_payload["requirements_total"],
            criteria_satisfied=measurement_payload["criteria_satisfied"],
            criteria_total=measurement_payload["criteria_total"],
            traceability_links_present=measurement_payload["traceability_links_present"],
            traceability_links_required=measurement_payload["traceability_links_required"],
            tests_passed=measurement_payload["tests_passed"],
            tests_total=measurement_payload["tests_total"],
            repair_successes=measurement_payload["repair_successes"],
            repair_attempts=measurement_payload["repair_attempts"],
            build_succeeded=measurement_payload["build_succeeded"],
            final_runtime_succeeded=measurement_payload["final_runtime_succeeded"],
            elapsed_seconds=measurement_payload["elapsed_seconds"],
            model_calls=measurement_payload["model_calls"],
            input_tokens=measurement_payload["input_tokens"],
            output_tokens=measurement_payload["output_tokens"],
            estimated_cost_usd=measurement_payload["estimated_cost_usd"],
        )
        if measurement_payload["derived_metrics"] != measurement.metric_snapshot():
            raise ValueError("persisted derived case-study metrics are inconsistent")

    evidence = tuple(
        CaseStudyEvidenceReference(
            kind=CaseStudyEvidenceKind(item["kind"]),
            relative_path=item["relative_path"],
            sha256_digest=item["sha256_digest"],
            size_bytes=item["size_bytes"],
            criterion_ids=tuple(item["criterion_ids"]),
        )
        for item in payload["evidence"]
    )
    return CaseStudyRunRecord(
        schema_version=payload["schema_version"],
        run_id=UUID(payload["run_id"]),
        case_id=payload["case_id"],
        case_version=payload["case_version"],
        case_content_hash=payload["case_content_hash"],
        workflow_run_id=UUID(payload["workflow_run_id"]),
        platform_commit=payload["platform_commit"],
        execution_profile=payload["execution_profile"],
        environment_identity_hash=payload["environment_identity_hash"],
        started_at=datetime.fromisoformat(payload["started_at"]),
        completed_at=datetime.fromisoformat(payload["completed_at"]),
        status=CaseStudyRunStatus(payload["status"]),
        evidence=evidence,
        measurement=measurement,
        notes=tuple(payload["notes"]),
        real_user_behavior_validated=payload["real_user_behavior_validated"],
        empirical_user_evidence_created=payload["empirical_user_evidence_created"],
        content_hash=payload["content_hash"],
    )
