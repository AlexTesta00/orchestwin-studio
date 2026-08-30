"""Structured synthetic findings with explicit epistemic and provenance metadata."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

from orchestwin.projects.requirements_primitives import (
    normalize_required_text,
    normalize_text_items,
    snapshot_content_hash,
    validate_display_code,
    validate_positive_integer,
    validate_sha256,
)

_MAX_LOCATION_LENGTH: Final = 500
_MAX_SUMMARY_LENGTH: Final = 1_000
_MAX_RATIONALE_LENGTH: Final = 4_000
_MAX_RECOMMENDATION_LENGTH: Final = 2_000
_MAX_REFERENCE_LENGTH: Final = 512


class SyntheticFindingCriterion(StrEnum):
    """Stable UCD criteria shared across project evaluations."""

    USEFULNESS = "usefulness"
    COMPREHENSIBILITY = "comprehensibility"
    ACTIONABILITY = "actionability"
    COGNITIVE_LOAD = "cognitive_load"
    TRUST = "trust"
    ACCESSIBILITY = "accessibility"
    TASK_ALIGNMENT = "task_alignment"


class SyntheticFindingSeverity(StrEnum):
    """Role-oriented impact level of one synthetic finding."""

    CRITICAL = "critical"
    MAJOR = "major"
    MODERATE = "moderate"
    MINOR = "minor"
    OBSERVATION = "observation"


class SyntheticFindingEpistemicStatus(StrEnum):
    """Primary epistemic status used at the weakest defensible level."""

    USER_PROVIDED = "USER_PROVIDED"
    EMPIRICALLY_SUPPORTED = "EMPIRICALLY_SUPPORTED"
    HUMAN_VALIDATED = "HUMAN_VALIDATED"
    MODEL_INFERRED = "MODEL_INFERRED"
    UNSUPPORTED_ASSUMPTION = "UNSUPPORTED_ASSUMPTION"


@dataclass(frozen=True, slots=True)
class SyntheticFinding:
    """Immutable simulated feedback tied to exact twin and artifact versions."""

    finding_id: str
    twin_id: UUID
    twin_version: int
    artifact_id: UUID
    artifact_version: int
    location: str
    summary: str
    rationale: str
    criterion: SyntheticFindingCriterion
    severity: SyntheticFindingSeverity
    epistemic_status: SyntheticFindingEpistemicStatus
    evidence_refs: tuple[str, ...]
    confidence: float
    recommended_action: str
    requires_human_validation: bool
    model_config_ref: str
    prompt_version_ref: str
    content_hash: str

    def __post_init__(self) -> None:
        validate_display_code(
            self.finding_id,
            prefix="UTF",
            label="synthetic finding ID",
        )
        validate_positive_integer(
            self.twin_version,
            label="synthetic finding twin version",
        )
        validate_positive_integer(
            self.artifact_version,
            label="synthetic finding artifact version",
        )
        normalized_text = (
            (
                self.location,
                "synthetic finding location",
                _MAX_LOCATION_LENGTH,
            ),
            (
                self.summary,
                "synthetic finding summary",
                _MAX_SUMMARY_LENGTH,
            ),
            (
                self.rationale,
                "synthetic finding rationale",
                _MAX_RATIONALE_LENGTH,
            ),
            (
                self.recommended_action,
                "synthetic finding recommended action",
                _MAX_RECOMMENDATION_LENGTH,
            ),
            (
                self.model_config_ref,
                "synthetic finding model configuration reference",
                _MAX_REFERENCE_LENGTH,
            ),
            (
                self.prompt_version_ref,
                "synthetic finding prompt version reference",
                _MAX_REFERENCE_LENGTH,
            ),
        )
        for value, label, maximum_length in normalized_text:
            normalized = normalize_required_text(
                value,
                label=label,
                maximum_length=maximum_length,
            )
            if normalized != value:
                raise ValueError(f"{label} must be normalized")

        references = normalize_text_items(
            self.evidence_refs,
            label="synthetic finding evidence reference",
            maximum_item_length=_MAX_REFERENCE_LENGTH,
            require_items=False,
        )
        canonical_references = tuple(sorted(references))
        if references != self.evidence_refs or references != canonical_references:
            raise ValueError(
                "synthetic finding evidence references must be normalized and canonical"
            )
        if isinstance(self.confidence, bool) or not isinstance(
            self.confidence,
            int | float,
        ):
            raise ValueError("synthetic finding confidence must be numeric")
        if not 0 <= float(self.confidence) <= 1:
            raise ValueError("synthetic finding confidence must be between zero and one")
        if (
            self.epistemic_status
            in {
                SyntheticFindingEpistemicStatus.MODEL_INFERRED,
                SyntheticFindingEpistemicStatus.UNSUPPORTED_ASSUMPTION,
            }
            and not self.requires_human_validation
        ):
            raise ValueError("model-inferred and unsupported findings require human validation")
        validate_sha256(
            self.content_hash,
            label="synthetic finding content hash",
        )
        expected_hash = synthetic_finding_hash(
            finding_id=self.finding_id,
            twin_id=self.twin_id,
            twin_version=self.twin_version,
            artifact_id=self.artifact_id,
            artifact_version=self.artifact_version,
            location=self.location,
            summary=self.summary,
            rationale=self.rationale,
            criterion=self.criterion,
            severity=self.severity,
            epistemic_status=self.epistemic_status,
            evidence_refs=self.evidence_refs,
            confidence=float(self.confidence),
            recommended_action=self.recommended_action,
            requires_human_validation=self.requires_human_validation,
            model_config_ref=self.model_config_ref,
            prompt_version_ref=self.prompt_version_ref,
        )
        if self.content_hash != expected_hash:
            raise ValueError("synthetic finding content hash is inconsistent")

    @property
    def is_simulated_feedback(self) -> bool:
        """Keep the methodological status explicit at every public boundary."""
        return True

    def to_snapshot(self) -> dict[str, object]:
        """Return the stable schema-compatible finding snapshot."""
        return {
            "finding_id": self.finding_id,
            "twin_id": str(self.twin_id),
            "twin_version": self.twin_version,
            "artifact_id": str(self.artifact_id),
            "artifact_version": self.artifact_version,
            "location": self.location,
            "summary": self.summary,
            "rationale": self.rationale,
            "criterion": self.criterion.value,
            "severity": self.severity.value,
            "epistemic_status": self.epistemic_status.value,
            "evidence_refs": list(self.evidence_refs),
            "confidence": float(self.confidence),
            "confidence_semantics": "MODEL_SELF_ASSESSMENT_UNLESS_CALIBRATED",
            "recommended_action": self.recommended_action,
            "requires_human_validation": self.requires_human_validation,
            "model_config_ref": self.model_config_ref,
            "prompt_version_ref": self.prompt_version_ref,
            "is_simulated_feedback": True,
            "content_hash": self.content_hash,
        }


def create_synthetic_finding(
    *,
    finding_id: str,
    twin_id: UUID,
    twin_version: int,
    artifact_id: UUID,
    artifact_version: int,
    location: str,
    summary: str,
    rationale: str,
    criterion: SyntheticFindingCriterion,
    severity: SyntheticFindingSeverity,
    epistemic_status: SyntheticFindingEpistemicStatus,
    evidence_refs: tuple[str, ...],
    confidence: float,
    recommended_action: str,
    requires_human_validation: bool,
    model_config_ref: str,
    prompt_version_ref: str,
) -> SyntheticFinding:
    """Create one canonical immutable finding from validated structured output."""
    canonical_references = tuple(sorted(evidence_refs))
    return SyntheticFinding(
        finding_id=finding_id,
        twin_id=twin_id,
        twin_version=twin_version,
        artifact_id=artifact_id,
        artifact_version=artifact_version,
        location=location,
        summary=summary,
        rationale=rationale,
        criterion=criterion,
        severity=severity,
        epistemic_status=epistemic_status,
        evidence_refs=canonical_references,
        confidence=confidence,
        recommended_action=recommended_action,
        requires_human_validation=requires_human_validation,
        model_config_ref=model_config_ref,
        prompt_version_ref=prompt_version_ref,
        content_hash=synthetic_finding_hash(
            finding_id=finding_id,
            twin_id=twin_id,
            twin_version=twin_version,
            artifact_id=artifact_id,
            artifact_version=artifact_version,
            location=location,
            summary=summary,
            rationale=rationale,
            criterion=criterion,
            severity=severity,
            epistemic_status=epistemic_status,
            evidence_refs=canonical_references,
            confidence=confidence,
            recommended_action=recommended_action,
            requires_human_validation=requires_human_validation,
            model_config_ref=model_config_ref,
            prompt_version_ref=prompt_version_ref,
        ),
    )


def synthetic_finding_hash(
    *,
    finding_id: str,
    twin_id: UUID,
    twin_version: int,
    artifact_id: UUID,
    artifact_version: int,
    location: str,
    summary: str,
    rationale: str,
    criterion: SyntheticFindingCriterion,
    severity: SyntheticFindingSeverity,
    epistemic_status: SyntheticFindingEpistemicStatus,
    evidence_refs: tuple[str, ...],
    confidence: float,
    recommended_action: str,
    requires_human_validation: bool,
    model_config_ref: str,
    prompt_version_ref: str,
) -> str:
    """Hash semantic finding content independently from database identity."""
    return snapshot_content_hash(
        {
            "finding_id": finding_id,
            "twin_id": str(twin_id),
            "twin_version": twin_version,
            "artifact_id": str(artifact_id),
            "artifact_version": artifact_version,
            "location": location,
            "summary": summary,
            "rationale": rationale,
            "criterion": criterion.value,
            "severity": severity.value,
            "epistemic_status": epistemic_status.value,
            "evidence_refs": list(evidence_refs),
            "confidence": float(confidence),
            "recommended_action": recommended_action,
            "requires_human_validation": requires_human_validation,
            "model_config_ref": model_config_ref,
            "prompt_version_ref": prompt_version_ref,
        }
    )
