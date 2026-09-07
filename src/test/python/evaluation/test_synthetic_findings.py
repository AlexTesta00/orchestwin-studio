"""Tests for structured synthetic findings and epistemic labels."""

from __future__ import annotations

from uuid import UUID

import pytest

from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
    create_synthetic_finding,
)

TWIN_ID = UUID("00000000-0000-4000-8000-000000016001")
ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000016002")


def _finding(**overrides: object):
    values: dict[str, object] = {
        "finding_id": "UTF-001",
        "twin_id": TWIN_ID,
        "twin_version": 3,
        "artifact_id": ARTIFACT_ID,
        "artifact_version": 5,
        "location": "screen:booking-form/field:arrival-date",
        "summary": "The validation message does not explain how to recover.",
        "rationale": "The approved profile requires concise guidance during time-sensitive tasks.",
        "criterion": SyntheticFindingCriterion.ACTIONABILITY,
        "severity": SyntheticFindingSeverity.MAJOR,
        "epistemic_status": SyntheticFindingEpistemicStatus.MODEL_INFERRED,
        "evidence_refs": ("REQ-NFR-012", "ut-profile-v3.operational_constraints[0]"),
        "confidence": 0.72,
        "recommended_action": "Explain the accepted date range and retain keyboard focus.",
        "requires_human_validation": True,
        "model_config_ref": "model-policy-v2",
        "prompt_version_ref": "ut-eval-v4",
    }
    values.update(overrides)
    return create_synthetic_finding(**values)  # type: ignore[arg-type]


def test_finding_preserves_required_schema_and_simulated_status() -> None:
    finding = _finding()

    snapshot = finding.to_snapshot()

    assert snapshot["finding_id"] == "UTF-001"
    assert snapshot["epistemic_status"] == "MODEL_INFERRED"
    assert snapshot["criterion"] == "actionability"
    assert snapshot["is_simulated_feedback"] is True
    assert snapshot["confidence_semantics"] == "MODEL_SELF_ASSESSMENT_UNLESS_CALIBRATED"
    assert snapshot["evidence_refs"] == [
        "REQ-NFR-012",
        "ut-profile-v3.operational_constraints[0]",
    ]
    assert finding.is_simulated_feedback is True


def test_semantically_equal_findings_have_stable_content_hashes() -> None:
    first = _finding()
    second = _finding(evidence_refs=tuple(reversed(first.evidence_refs)))

    assert first.content_hash == second.content_hash


def test_finding_rejects_invalid_confidence_and_uncontrolled_inference() -> None:
    with pytest.raises(ValueError, match="between zero and one"):
        _finding(confidence=1.01)

    with pytest.raises(ValueError, match="require human validation"):
        _finding(requires_human_validation=False)

    with pytest.raises(ValueError, match="UTF-NNN"):
        _finding(finding_id="finding-one")
