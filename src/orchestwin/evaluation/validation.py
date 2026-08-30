"""Deterministic validation of synthetic-finding provenance and epistemic claims."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

from orchestwin.evaluation.findings import (
    SyntheticFinding,
    SyntheticFindingEpistemicStatus,
)
from orchestwin.projects.requirements_primitives import (
    normalize_required_text,
    validate_positive_integer,
    validate_sha256,
)

_MAX_REFERENCE_LENGTH: Final = 512
_MAX_LOCATOR_LENGTH: Final = 512


class EvaluationEvidenceKind(StrEnum):
    """Inspectable provenance classes available to finding validation."""

    OWNER_STATEMENT = "OWNER_STATEMENT"
    USER_TWIN_PROFILE = "USER_TWIN_PROFILE"
    PROJECT_ARTIFACT = "PROJECT_ARTIFACT"
    DETERMINISTIC_TEST = "DETERMINISTIC_TEST"
    EMPIRICAL_TARGET_USER_RESEARCH = "EMPIRICAL_TARGET_USER_RESEARCH"
    HUMAN_VALIDATION_RECORD = "HUMAN_VALIDATION_RECORD"


@dataclass(frozen=True, slots=True)
class EvaluationEvidenceReference:
    """Exact authorized source that a synthetic evaluator may cite."""

    reference_id: str
    kind: EvaluationEvidenceKind
    content_hash: str
    locator: str

    def __post_init__(self) -> None:
        for value, label, maximum_length in (
            (
                self.reference_id,
                "evaluation evidence reference ID",
                _MAX_REFERENCE_LENGTH,
            ),
            (
                self.locator,
                "evaluation evidence locator",
                _MAX_LOCATOR_LENGTH,
            ),
        ):
            normalized = normalize_required_text(
                value,
                label=label,
                maximum_length=maximum_length,
            )
            if normalized != value:
                raise ValueError(f"{label} must be normalized")
        validate_sha256(
            self.content_hash,
            label="evaluation evidence content hash",
        )

    @property
    def sort_key(self) -> tuple[str, str, str, str]:
        return (
            self.reference_id,
            self.kind.value,
            self.content_hash,
            self.locator,
        )

    def to_snapshot(self) -> dict[str, str]:
        return {
            "reference_id": self.reference_id,
            "kind": self.kind.value,
            "content_hash": self.content_hash,
            "locator": self.locator,
        }


@dataclass(frozen=True, slots=True)
class SyntheticFindingValidationContext:
    """Exact twin, artifact, and authorized evidence boundary for one finding."""

    twin_id: UUID
    twin_version: int
    artifact_id: UUID
    artifact_version: int
    evidence: tuple[EvaluationEvidenceReference, ...]

    def __post_init__(self) -> None:
        validate_positive_integer(
            self.twin_version,
            label="validation context twin version",
        )
        validate_positive_integer(
            self.artifact_version,
            label="validation context artifact version",
        )
        ordered = tuple(sorted(self.evidence, key=lambda item: item.sort_key))
        if ordered != self.evidence:
            raise ValueError("evaluation evidence references must use canonical order")
        identifiers = [item.reference_id for item in self.evidence]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("evaluation evidence reference IDs must be unique")


class SyntheticFindingValidationIssueCode(StrEnum):
    """Stable reasons why one structured finding cannot be accepted."""

    TWIN_VERSION_MISMATCH = "TWIN_VERSION_MISMATCH"
    ARTIFACT_VERSION_MISMATCH = "ARTIFACT_VERSION_MISMATCH"
    UNKNOWN_EVIDENCE_REFERENCE = "UNKNOWN_EVIDENCE_REFERENCE"
    OWNER_EVIDENCE_REQUIRED = "OWNER_EVIDENCE_REQUIRED"
    EMPIRICAL_EVIDENCE_REQUIRED = "EMPIRICAL_EVIDENCE_REQUIRED"
    HUMAN_VALIDATION_RECORD_REQUIRED = "HUMAN_VALIDATION_RECORD_REQUIRED"
    HUMAN_VALIDATION_FLAG_REQUIRED = "HUMAN_VALIDATION_FLAG_REQUIRED"


@dataclass(frozen=True, slots=True)
class SyntheticFindingValidationIssue:
    """One concise deterministic issue without hidden reasoning."""

    code: SyntheticFindingValidationIssueCode
    reference_id: str | None = None

    def to_snapshot(self) -> dict[str, str | None]:
        return {
            "code": self.code.value,
            "reference_id": self.reference_id,
        }


@dataclass(frozen=True, slots=True)
class SyntheticFindingValidationReport:
    """Deterministic acceptance result for a candidate synthetic finding."""

    finding_id: str
    issues: tuple[SyntheticFindingValidationIssue, ...]

    @property
    def is_valid(self) -> bool:
        return not self.issues

    def to_snapshot(self) -> dict[str, object]:
        return {
            "finding_id": self.finding_id,
            "is_valid": self.is_valid,
            "issues": [item.to_snapshot() for item in self.issues],
        }


def validate_synthetic_finding(
    finding: SyntheticFinding,
    context: SyntheticFindingValidationContext,
) -> SyntheticFindingValidationReport:
    """Validate exact identities, allowed citations, and epistemic authority."""
    issues: list[SyntheticFindingValidationIssue] = []

    if finding.twin_id != context.twin_id or finding.twin_version != context.twin_version:
        issues.append(
            SyntheticFindingValidationIssue(
                SyntheticFindingValidationIssueCode.TWIN_VERSION_MISMATCH
            )
        )
    if (
        finding.artifact_id != context.artifact_id
        or finding.artifact_version != context.artifact_version
    ):
        issues.append(
            SyntheticFindingValidationIssue(
                SyntheticFindingValidationIssueCode.ARTIFACT_VERSION_MISMATCH
            )
        )

    evidence_by_id = {item.reference_id: item for item in context.evidence}
    resolved: list[EvaluationEvidenceReference] = []
    for reference_id in finding.evidence_refs:
        evidence = evidence_by_id.get(reference_id)
        if evidence is None:
            issues.append(
                SyntheticFindingValidationIssue(
                    SyntheticFindingValidationIssueCode.UNKNOWN_EVIDENCE_REFERENCE,
                    reference_id=reference_id,
                )
            )
        else:
            resolved.append(evidence)

    resolved_kinds = {item.kind for item in resolved}
    required_kind = _REQUIRED_EVIDENCE_KIND.get(finding.epistemic_status)
    if required_kind is not None and required_kind not in resolved_kinds:
        issues.append(
            SyntheticFindingValidationIssue(_MISSING_EVIDENCE_ISSUE[finding.epistemic_status])
        )

    if (
        finding.epistemic_status
        in {
            SyntheticFindingEpistemicStatus.MODEL_INFERRED,
            SyntheticFindingEpistemicStatus.UNSUPPORTED_ASSUMPTION,
        }
        and not finding.requires_human_validation
    ):
        issues.append(
            SyntheticFindingValidationIssue(
                SyntheticFindingValidationIssueCode.HUMAN_VALIDATION_FLAG_REQUIRED
            )
        )

    return SyntheticFindingValidationReport(
        finding_id=finding.finding_id,
        issues=tuple(issues),
    )


_REQUIRED_EVIDENCE_KIND: Final = {
    SyntheticFindingEpistemicStatus.USER_PROVIDED: EvaluationEvidenceKind.OWNER_STATEMENT,
    SyntheticFindingEpistemicStatus.EMPIRICALLY_SUPPORTED: (
        EvaluationEvidenceKind.EMPIRICAL_TARGET_USER_RESEARCH
    ),
    SyntheticFindingEpistemicStatus.HUMAN_VALIDATED: (
        EvaluationEvidenceKind.HUMAN_VALIDATION_RECORD
    ),
}

_MISSING_EVIDENCE_ISSUE: Final = {
    SyntheticFindingEpistemicStatus.USER_PROVIDED: (
        SyntheticFindingValidationIssueCode.OWNER_EVIDENCE_REQUIRED
    ),
    SyntheticFindingEpistemicStatus.EMPIRICALLY_SUPPORTED: (
        SyntheticFindingValidationIssueCode.EMPIRICAL_EVIDENCE_REQUIRED
    ),
    SyntheticFindingEpistemicStatus.HUMAN_VALIDATED: (
        SyntheticFindingValidationIssueCode.HUMAN_VALIDATION_RECORD_REQUIRED
    ),
}
