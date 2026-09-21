"""Tests for evidence-derived Definition of Done coverage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.evaluation.case_evidence import evaluate_case_study_evidence_coverage
from orchestwin.evaluation.case_metrics import CaseStudyMeasurement
from orchestwin.evaluation.case_runs import (
    CaseStudyEvidenceReference,
    CaseStudyRunStatus,
    create_case_study_run_record,
)
from orchestwin.evaluation.case_studies import (
    CaseStudyDefinition,
    CaseStudyEvidenceKind,
    DefinitionOfDoneItem,
    EvaluationFamily,
    case_study_content_hash,
)

NOW = datetime(2026, 9, 7, 14, 30, tzinfo=UTC)


def _definition() -> CaseStudyDefinition:
    items = (
        DefinitionOfDoneItem(
            criterion_id="DOD-001",
            description="The project builds and exports.",
            evidence=(CaseStudyEvidenceKind.BUILD_REPORT, CaseStudyEvidenceKind.FINAL_EXPORT),
        ),
        DefinitionOfDoneItem(
            criterion_id="DOD-002",
            description="Deterministic tests pass.",
            evidence=(CaseStudyEvidenceKind.TEST_REPORT,),
        ),
    )
    snapshot = {
        "schema_version": 1,
        "case_id": "coverage-case",
        "version": 1,
        "title": "Coverage case",
        "family": "WEB",
        "execution_profile": "WEB_STATIC",
        "technologies": ["HTML", "CSS", "JavaScript"],
        "project_brief": "Create a small deterministic web application.",
        "user_twin_roles": ["Operator"],
        "constraints": ["No external services."],
        "definition_of_done": [item.to_snapshot() for item in items],
    }
    return CaseStudyDefinition(
        schema_version=1,
        case_id="coverage-case",
        version=1,
        title="Coverage case",
        family=EvaluationFamily.WEB,
        execution_profile="WEB_STATIC",
        technologies=("HTML", "CSS", "JavaScript"),
        project_brief="Create a small deterministic web application.",
        user_twin_roles=("Operator",),
        constraints=("No external services.",),
        definition_of_done=items,
        content_hash=case_study_content_hash(snapshot),
    )


def _measurement(*, satisfied: int) -> CaseStudyMeasurement:
    return CaseStudyMeasurement(
        case_id="coverage-case",
        gates_completed=1,
        gates_total=1,
        artifacts_completed=1,
        artifacts_total=1,
        requirements_satisfied=1,
        requirements_total=1,
        criteria_satisfied=satisfied,
        criteria_total=2,
        traceability_links_present=1,
        traceability_links_required=1,
        tests_passed=1,
        tests_total=1,
        repair_successes=0,
        repair_attempts=0,
        build_succeeded=True,
        final_runtime_succeeded=True,
        elapsed_seconds=1.0,
        model_calls=0,
        input_tokens=0,
        output_tokens=0,
        estimated_cost_usd=0.0,
    )


def _evidence(kind, path, digest, criterion_ids):
    return CaseStudyEvidenceReference(
        kind=kind,
        relative_path=path,
        sha256_digest=digest * 64,
        size_bytes=100,
        criterion_ids=criterion_ids,
    )


def _run(definition: CaseStudyDefinition, *, satisfied: int, include_export: bool):
    evidence = [
        _evidence(CaseStudyEvidenceKind.BUILD_REPORT, "build.json", "a", ("DOD-001",)),
        _evidence(CaseStudyEvidenceKind.TEST_REPORT, "tests.json", "b", ("DOD-002",)),
    ]
    if include_export:
        evidence.append(
            _evidence(CaseStudyEvidenceKind.FINAL_EXPORT, "project.zip", "c", ("DOD-001",))
        )
    return create_case_study_run_record(
        run_id=UUID("00000000-0000-4000-8000-000000012101"),
        case_id=definition.case_id,
        case_version=definition.version,
        case_content_hash=definition.content_hash,
        workflow_run_id=UUID("00000000-0000-4000-8000-000000012102"),
        platform_commit="d" * 40,
        execution_profile=definition.execution_profile,
        environment_identity_hash="e" * 64,
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
        status=CaseStudyRunStatus.COMPLETED,
        evidence=tuple(evidence),
        measurement=_measurement(satisfied=satisfied),
    )


def test_coverage_is_derived_from_criterion_specific_evidence() -> None:
    definition = _definition()
    run = _run(definition, satisfied=2, include_export=True)

    summary = evaluate_case_study_evidence_coverage(definition, run)

    assert summary.criteria_total == 2
    assert summary.criteria_satisfied == 2
    assert summary.completion_ratio == 1.0
    assert summary.is_complete is True
    assert summary.coverage[0].missing_evidence == ()


def test_coverage_rejects_measurements_that_overstate_recorded_evidence() -> None:
    definition = _definition()
    run = _run(definition, satisfied=2, include_export=False)

    with pytest.raises(ValueError, match="evidence-derived coverage"):
        evaluate_case_study_evidence_coverage(definition, run)


def test_coverage_rejects_unknown_criterion_links() -> None:
    definition = _definition()
    base = _run(definition, satisfied=2, include_export=True)
    unknown = _evidence(
        CaseStudyEvidenceKind.SCREENSHOT,
        "unknown.png",
        "f",
        ("DOD-999",),
    )
    altered = create_case_study_run_record(
        run_id=base.run_id,
        case_id=base.case_id,
        case_version=base.case_version,
        case_content_hash=base.case_content_hash,
        workflow_run_id=base.workflow_run_id,
        platform_commit=base.platform_commit,
        execution_profile=base.execution_profile,
        environment_identity_hash=base.environment_identity_hash,
        started_at=base.started_at,
        completed_at=base.completed_at,
        status=base.status,
        evidence=(*base.evidence, unknown),
        measurement=base.measurement,
    )

    with pytest.raises(ValueError, match="unknown DoD criteria"):
        evaluate_case_study_evidence_coverage(definition, altered)
