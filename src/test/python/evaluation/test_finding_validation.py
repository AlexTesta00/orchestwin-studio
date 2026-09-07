"""Tests for finding provenance and epistemic-claim validation."""

from __future__ import annotations

from uuid import UUID

from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
    create_synthetic_finding,
)
from orchestwin.evaluation.validation import (
    EvaluationEvidenceKind,
    EvaluationEvidenceReference,
    SyntheticFindingValidationContext,
    SyntheticFindingValidationIssueCode,
    validate_synthetic_finding,
)

TWIN_ID = UUID("00000000-0000-4000-8000-000000017001")
ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000017002")


def _evidence(reference_id: str, kind: EvaluationEvidenceKind, character: str):
    return EvaluationEvidenceReference(
        reference_id=reference_id,
        kind=kind,
        content_hash=character * 64,
        locator=f"source:{reference_id}",
    )


def _context() -> SyntheticFindingValidationContext:
    evidence = (
        _evidence("EMP-001", EvaluationEvidenceKind.EMPIRICAL_TARGET_USER_RESEARCH, "a"),
        _evidence("HVR-001", EvaluationEvidenceKind.HUMAN_VALIDATION_RECORD, "b"),
        _evidence("OWNER-001", EvaluationEvidenceKind.OWNER_STATEMENT, "c"),
        _evidence("REQ-001", EvaluationEvidenceKind.PROJECT_ARTIFACT, "d"),
    )
    return SyntheticFindingValidationContext(
        twin_id=TWIN_ID,
        twin_version=2,
        artifact_id=ARTIFACT_ID,
        artifact_version=4,
        evidence=tuple(sorted(evidence, key=lambda item: item.sort_key)),
    )


def _finding(
    status: SyntheticFindingEpistemicStatus,
    evidence_refs: tuple[str, ...],
    **overrides: object,
):
    values: dict[str, object] = {
        "finding_id": "UTF-017",
        "twin_id": TWIN_ID,
        "twin_version": 2,
        "artifact_id": ARTIFACT_ID,
        "artifact_version": 4,
        "location": "screen:dashboard/alert:delay",
        "summary": "The disruption alert lacks an operational explanation.",
        "rationale": "The referenced evidence describes an explanation need.",
        "criterion": SyntheticFindingCriterion.TRUST,
        "severity": SyntheticFindingSeverity.MAJOR,
        "epistemic_status": status,
        "evidence_refs": evidence_refs,
        "confidence": 0.8,
        "recommended_action": "Add a concise operational explanation.",
        "requires_human_validation": status
        in {
            SyntheticFindingEpistemicStatus.MODEL_INFERRED,
            SyntheticFindingEpistemicStatus.UNSUPPORTED_ASSUMPTION,
        },
        "model_config_ref": "model-config-1",
        "prompt_version_ref": "ut-eval-v1",
    }
    values.update(overrides)
    return create_synthetic_finding(**values)  # type: ignore[arg-type]


def test_authorized_evidence_supports_only_matching_epistemic_authority() -> None:
    context = _context()

    empirical = validate_synthetic_finding(
        _finding(
            SyntheticFindingEpistemicStatus.EMPIRICALLY_SUPPORTED,
            ("EMP-001", "REQ-001"),
        ),
        context,
    )
    human_validated = validate_synthetic_finding(
        _finding(
            SyntheticFindingEpistemicStatus.HUMAN_VALIDATED,
            ("HVR-001",),
        ),
        context,
    )
    owner_provided = validate_synthetic_finding(
        _finding(
            SyntheticFindingEpistemicStatus.USER_PROVIDED,
            ("OWNER-001",),
        ),
        context,
    )

    assert empirical.is_valid is True
    assert human_validated.is_valid is True
    assert owner_provided.is_valid is True


def test_project_artifacts_cannot_be_upgraded_to_empirical_evidence() -> None:
    report = validate_synthetic_finding(
        _finding(
            SyntheticFindingEpistemicStatus.EMPIRICALLY_SUPPORTED,
            ("REQ-001",),
        ),
        _context(),
    )

    assert report.is_valid is False
    assert [issue.code for issue in report.issues] == [
        SyntheticFindingValidationIssueCode.EMPIRICAL_EVIDENCE_REQUIRED
    ]


def test_unknown_references_and_exact_version_mismatches_are_reported() -> None:
    report = validate_synthetic_finding(
        _finding(
            SyntheticFindingEpistemicStatus.MODEL_INFERRED,
            ("MISSING-001",),
            twin_version=3,
            artifact_version=5,
        ),
        _context(),
    )

    assert report.is_valid is False
    assert [issue.code for issue in report.issues] == [
        SyntheticFindingValidationIssueCode.TWIN_VERSION_MISMATCH,
        SyntheticFindingValidationIssueCode.ARTIFACT_VERSION_MISMATCH,
        SyntheticFindingValidationIssueCode.UNKNOWN_EVIDENCE_REFERENCE,
    ]
    assert report.issues[-1].reference_id == "MISSING-001"
