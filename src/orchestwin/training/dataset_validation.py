"""Pure epistemic, provenance, and reference validation for dataset examples."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

from orchestwin.evaluation.findings import SyntheticFindingEpistemicStatus
from orchestwin.projects.requirements_primitives import snapshot_content_hash
from orchestwin.training.dataset_examples import (
    DatasetEvidenceKind,
    EvaluatorDatasetExample,
)
from orchestwin.twins.user_twins import UserTwinLifecycleStatus


class DatasetValidationCode(StrEnum):
    """Stable machine-readable quality failures for one dataset example."""

    UNKNOWN_EVIDENCE_REFERENCE = "UNKNOWN_EVIDENCE_REFERENCE"
    EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"
    FALSE_EMPIRICAL_FINDING = "FALSE_EMPIRICAL_FINDING"
    FALSE_HUMAN_VALIDATION = "FALSE_HUMAN_VALIDATION"
    USER_PROVIDED_SOURCE_REQUIRED = "USER_PROVIDED_SOURCE_REQUIRED"
    TWIN_REFERENCE_MISMATCH = "TWIN_REFERENCE_MISMATCH"
    ARTIFACT_REFERENCE_MISMATCH = "ARTIFACT_REFERENCE_MISMATCH"
    RUBRIC_CRITERION_MISMATCH = "RUBRIC_CRITERION_MISMATCH"
    PROFILE_STATUS_MISMATCH = "PROFILE_STATUS_MISMATCH"
    FALSE_EMPIRICAL_PROFILE_STATUS = "FALSE_EMPIRICAL_PROFILE_STATUS"
    DUPLICATE_FINDING_ID = "DUPLICATE_FINDING_ID"


@dataclass(frozen=True, slots=True)
class DatasetValidationIssue:
    """One deterministic validation failure with a stable path."""

    code: DatasetValidationCode
    path: str
    message: str

    @property
    def sort_key(self) -> tuple[str, str, str]:
        return (self.path, self.code.value, self.message)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "path": self.path,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class DatasetValidationReport:
    """Complete validation outcome without dropping individual failures."""

    example_id: str
    issues: tuple[DatasetValidationIssue, ...]
    content_hash: str

    @property
    def accepted(self) -> bool:
        return not self.issues

    def to_snapshot(self) -> dict[str, object]:
        return {
            "example_id": self.example_id,
            "accepted": self.accepted,
            "issues": [issue.to_snapshot() for issue in self.issues],
            "content_hash": self.content_hash,
        }


def validate_dataset_example(example: EvaluatorDatasetExample) -> DatasetValidationReport:
    """Validate one immutable example at the weakest defensible epistemic level."""
    issues: list[DatasetValidationIssue] = []
    evidence_by_id = {item.reference_id: item for item in example.evidence}
    empirical_evidence_ids = {
        item.reference_id for item in example.evidence if item.is_target_user_empirical_evidence
    }
    human_validation_ids = {
        item.reference_id for item in example.evidence if item.is_human_validation_activity
    }
    user_provided_ids = {
        item.reference_id
        for item in example.evidence
        if item.kind
        in {
            DatasetEvidenceKind.OWNER_INPUT,
            DatasetEvidenceKind.USER_TWIN_PROFILE,
            DatasetEvidenceKind.PROJECT_BRIEF,
        }
    }

    finding_ids: set[str] = set()
    for index, finding in enumerate(example.expected_output.findings):
        finding_path = f"expected_output.findings[{index}]"
        if finding.finding_id in finding_ids:
            issues.append(
                DatasetValidationIssue(
                    DatasetValidationCode.DUPLICATE_FINDING_ID,
                    f"{finding_path}.finding_id",
                    "Finding IDs must be unique within an example.",
                )
            )
        finding_ids.add(finding.finding_id)

        if (
            finding.twin_id != example.user_twin_reference.twin_id
            or finding.twin_version != example.user_twin_reference.version_number
        ):
            issues.append(
                DatasetValidationIssue(
                    DatasetValidationCode.TWIN_REFERENCE_MISMATCH,
                    finding_path,
                    "The finding must reference the exact User Twin version in the example.",
                )
            )

        artifact_reference = example.artifact.reference
        if (
            finding.artifact_id != artifact_reference.artifact_id
            or finding.artifact_version != artifact_reference.version_number
        ):
            issues.append(
                DatasetValidationIssue(
                    DatasetValidationCode.ARTIFACT_REFERENCE_MISMATCH,
                    finding_path,
                    "The finding must reference the exact artifact version in the example.",
                )
            )

        if finding.criterion not in example.rubric.criteria:
            issues.append(
                DatasetValidationIssue(
                    DatasetValidationCode.RUBRIC_CRITERION_MISMATCH,
                    f"{finding_path}.criterion",
                    "The finding criterion is not enabled by the attached rubric.",
                )
            )

        referenced_ids = set(finding.evidence_refs)
        unknown_ids = sorted(referenced_ids - set(evidence_by_id))
        for evidence_id in unknown_ids:
            issues.append(
                DatasetValidationIssue(
                    DatasetValidationCode.UNKNOWN_EVIDENCE_REFERENCE,
                    f"{finding_path}.evidence_refs",
                    f"Evidence reference {evidence_id!r} is not authorized by the example.",
                )
            )

        if (
            finding.epistemic_status is not SyntheticFindingEpistemicStatus.UNSUPPORTED_ASSUMPTION
            and not finding.evidence_refs
        ):
            issues.append(
                DatasetValidationIssue(
                    DatasetValidationCode.EVIDENCE_REQUIRED,
                    f"{finding_path}.evidence_refs",
                    "Supported findings require at least one inspectable evidence reference.",
                )
            )

        if (
            finding.epistemic_status is SyntheticFindingEpistemicStatus.EMPIRICALLY_SUPPORTED
            and not referenced_ids.intersection(empirical_evidence_ids)
        ):
            issues.append(
                DatasetValidationIssue(
                    DatasetValidationCode.FALSE_EMPIRICAL_FINDING,
                    f"{finding_path}.epistemic_status",
                    "Empirically supported findings require target-user empirical evidence.",
                )
            )

        if (
            finding.epistemic_status is SyntheticFindingEpistemicStatus.HUMAN_VALIDATED
            and not referenced_ids.intersection(human_validation_ids)
        ):
            issues.append(
                DatasetValidationIssue(
                    DatasetValidationCode.FALSE_HUMAN_VALIDATION,
                    f"{finding_path}.epistemic_status",
                    "Human-validated findings require a recorded human-validation activity.",
                )
            )

        if (
            finding.epistemic_status is SyntheticFindingEpistemicStatus.USER_PROVIDED
            and not referenced_ids.intersection(user_provided_ids)
        ):
            issues.append(
                DatasetValidationIssue(
                    DatasetValidationCode.USER_PROVIDED_SOURCE_REQUIRED,
                    f"{finding_path}.epistemic_status",
                    "User-provided findings require an owner, brief, or profile source.",
                )
            )

    profile_snapshot = json.loads(example.user_twin_profile_json)
    profile_status = profile_snapshot.get("validation_status")
    if profile_status != example.user_twin_reference.lifecycle_status.value:
        issues.append(
            DatasetValidationIssue(
                DatasetValidationCode.PROFILE_STATUS_MISMATCH,
                "user_twin_profile.validation_status",
                "The profile snapshot status must match the exact User Twin reference.",
            )
        )

    if (
        example.user_twin_reference.lifecycle_status
        in {
            UserTwinLifecycleStatus.EMPIRICALLY_GROUNDED_UT,
            UserTwinLifecycleStatus.EMPIRICALLY_VALIDATED_UT,
        }
        and not empirical_evidence_ids
    ):
        issues.append(
            DatasetValidationIssue(
                DatasetValidationCode.FALSE_EMPIRICAL_PROFILE_STATUS,
                "user_twin_reference.lifecycle_status",
                "An empirical User Twin status requires target-user empirical evidence.",
            )
        )

    canonical_issues = tuple(sorted(issues, key=lambda issue: issue.sort_key))
    report_hash = snapshot_content_hash(
        {
            "example_id": example.example_id,
            "example_content_hash": example.content_hash,
            "accepted": not canonical_issues,
            "issues": [issue.to_snapshot() for issue in canonical_issues],
        }
    )
    return DatasetValidationReport(
        example_id=example.example_id,
        issues=canonical_issues,
        content_hash=report_hash,
    )
