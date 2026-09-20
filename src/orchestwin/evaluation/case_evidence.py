"""Definition-of-Done evidence coverage for finalized formal case-study runs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from orchestwin.evaluation.case_runs import CaseStudyRunRecord
from orchestwin.evaluation.case_studies import (
    CaseStudyDefinition,
    CaseStudyEvidenceKind,
)


def _hash(payload: object) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DefinitionOfDoneEvidenceCoverage:
    """Evidence coverage for one frozen Definition of Done criterion."""

    criterion_id: str
    required_evidence: tuple[CaseStudyEvidenceKind, ...]
    observed_evidence: tuple[CaseStudyEvidenceKind, ...]
    missing_evidence: tuple[CaseStudyEvidenceKind, ...]

    @property
    def satisfied(self) -> bool:
        return not self.missing_evidence

    def to_snapshot(self) -> dict[str, object]:
        return {
            "criterion_id": self.criterion_id,
            "required_evidence": [item.value for item in self.required_evidence],
            "observed_evidence": [item.value for item in self.observed_evidence],
            "missing_evidence": [item.value for item in self.missing_evidence],
            "satisfied": self.satisfied,
        }


@dataclass(frozen=True, slots=True)
class CaseStudyEvidenceCoverageSummary:
    """Deterministic coverage result derived only from frozen DoD and recorded evidence."""

    case_id: str
    criteria_total: int
    criteria_satisfied: int
    coverage: tuple[DefinitionOfDoneEvidenceCoverage, ...]
    content_hash: str

    @property
    def completion_ratio(self) -> float:
        return self.criteria_satisfied / self.criteria_total

    @property
    def is_complete(self) -> bool:
        return self.criteria_satisfied == self.criteria_total

    def to_snapshot(self, *, include_hash: bool = True) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "case_id": self.case_id,
            "criteria_total": self.criteria_total,
            "criteria_satisfied": self.criteria_satisfied,
            "completion_ratio": self.completion_ratio,
            "is_complete": self.is_complete,
            "coverage": [item.to_snapshot() for item in self.coverage],
        }
        if include_hash:
            snapshot["content_hash"] = self.content_hash
        return snapshot


def evaluate_case_study_evidence_coverage(
    definition: CaseStudyDefinition,
    run: CaseStudyRunRecord,
) -> CaseStudyEvidenceCoverageSummary:
    """Validate exact case binding and calculate criterion-specific evidence coverage."""
    if run.case_id != definition.case_id:
        raise ValueError("case-study run is bound to a different case ID")
    if run.case_version != definition.version:
        raise ValueError("case-study run is bound to a different case version")
    if run.case_content_hash != definition.content_hash:
        raise ValueError("case-study run is bound to a different case definition hash")
    if run.execution_profile != definition.execution_profile:
        raise ValueError("case-study run is bound to a different execution profile")

    known_criteria = {item.criterion_id for item in definition.definition_of_done}
    referenced_criteria = {
        criterion_id for evidence in run.evidence for criterion_id in evidence.criterion_ids
    }
    unknown_criteria = referenced_criteria - known_criteria
    if unknown_criteria:
        joined = ", ".join(sorted(unknown_criteria))
        raise ValueError(f"case-study evidence references unknown DoD criteria: {joined}")

    coverage_items: list[DefinitionOfDoneEvidenceCoverage] = []
    for criterion in definition.definition_of_done:
        required = tuple(sorted(criterion.evidence, key=lambda item: item.value))
        observed = tuple(
            sorted(
                {
                    evidence.kind
                    for evidence in run.evidence
                    if criterion.criterion_id in evidence.criterion_ids
                },
                key=lambda item: item.value,
            )
        )
        missing = tuple(item for item in required if item not in observed)
        coverage_items.append(
            DefinitionOfDoneEvidenceCoverage(
                criterion_id=criterion.criterion_id,
                required_evidence=required,
                observed_evidence=observed,
                missing_evidence=missing,
            )
        )

    coverage = tuple(coverage_items)
    criteria_satisfied = sum(item.satisfied for item in coverage)
    criteria_total = len(coverage)
    if run.measurement is not None:
        if run.measurement.criteria_total != criteria_total:
            raise ValueError(
                "recorded criterion total disagrees with the frozen Definition of Done"
            )
        if run.measurement.criteria_satisfied != criteria_satisfied:
            raise ValueError("recorded criterion count disagrees with evidence-derived coverage")

    snapshot: dict[str, object] = {
        "case_id": definition.case_id,
        "criteria_total": criteria_total,
        "criteria_satisfied": criteria_satisfied,
        "completion_ratio": criteria_satisfied / criteria_total,
        "is_complete": criteria_satisfied == criteria_total,
        "coverage": [item.to_snapshot() for item in coverage],
    }
    return CaseStudyEvidenceCoverageSummary(
        case_id=definition.case_id,
        criteria_total=criteria_total,
        criteria_satisfied=criteria_satisfied,
        coverage=coverage,
        content_hash=_hash(snapshot),
    )
