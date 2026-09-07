"""Immutable versioned final-review assessments for exact workflow artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID, uuid4

from orchestwin.projects.requirements_primitives import (
    normalize_required_text,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.sandbox.execution_profiles import ExecutionCapabilityStatus
from orchestwin.workflow.runs import WorkflowArtifactReference, WorkflowRun

_MAX_CODE_LENGTH: Final = 128
_MAX_TEXT_LENGTH: Final = 2_000
_MAX_REFERENCE_LENGTH: Final = 500


class FinalReviewCheckKind(StrEnum):
    """Stable dimensions that must be inspected before Gate 8."""

    DEFINITION_OF_DONE = "DEFINITION_OF_DONE"
    REQUIREMENTS = "REQUIREMENTS"
    TRACEABILITY = "TRACEABILITY"
    EXECUTION_EVIDENCE = "EXECUTION_EVIDENCE"
    DETERMINISTIC_FINDINGS = "DETERMINISTIC_FINDINGS"
    SYNTHETIC_EVALUATION = "SYNTHETIC_EVALUATION"
    CAPABILITY = "CAPABILITY"
    HUMAN_VALIDATION = "HUMAN_VALIDATION"
    LIMITATIONS = "LIMITATIONS"
    EXPORT_READINESS = "EXPORT_READINESS"


class FinalReviewCheckStatus(StrEnum):
    """Inspectable outcome of one final-review dimension."""

    SATISFIED = "SATISFIED"
    NOT_SATISFIED = "NOT_SATISFIED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ACCEPTED_LIMITATION = "ACCEPTED_LIMITATION"


class FinalReviewIssueSeverity(StrEnum):
    """Severity of one unresolved final-review issue."""

    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MODERATE = "MODERATE"
    MINOR = "MINOR"


class HumanValidationStatus(StrEnum):
    """Empirical human-validation state kept separate from owner approval."""

    NOT_RECORDED = "NOT_RECORDED"
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"


_REQUIRED_CHECK_KINDS: Final = frozenset(FinalReviewCheckKind)
_BLOCKING_ISSUE_SEVERITIES: Final = frozenset(
    {FinalReviewIssueSeverity.CRITICAL, FinalReviewIssueSeverity.MAJOR}
)


@dataclass(frozen=True, slots=True)
class FinalReviewCheck:
    """One traceable check contributing to the final approval recommendation."""

    check_id: str
    kind: FinalReviewCheckKind
    status: FinalReviewCheckStatus
    summary: str
    evidence_refs: tuple[str, ...]
    blocking: bool

    def __post_init__(self) -> None:
        for value, label, maximum_length in (
            (self.check_id, "final review check ID", _MAX_CODE_LENGTH),
            (self.summary, "final review check summary", _MAX_TEXT_LENGTH),
        ):
            normalized = normalize_required_text(
                value,
                label=label,
                maximum_length=maximum_length,
            )
            if normalized != value:
                raise ValueError(f"{label} must be normalized")
        normalized_refs = tuple(
            normalize_required_text(
                item,
                label="final review evidence reference",
                maximum_length=_MAX_REFERENCE_LENGTH,
            )
            for item in self.evidence_refs
        )
        if normalized_refs != self.evidence_refs:
            raise ValueError("final review evidence references must be normalized")
        if normalized_refs != tuple(sorted(set(normalized_refs))):
            raise ValueError("final review evidence references must be canonical and unique")
        if self.blocking and self.status in {
            FinalReviewCheckStatus.NOT_APPLICABLE,
            FinalReviewCheckStatus.ACCEPTED_LIMITATION,
        }:
            raise ValueError("blocking final review checks cannot be waived implicitly")

    @property
    def sort_key(self) -> tuple[str, str]:
        return (self.kind.value, self.check_id)

    @property
    def blocks_gate8(self) -> bool:
        return self.blocking and self.status is not FinalReviewCheckStatus.SATISFIED

    def to_snapshot(self) -> dict[str, object]:
        return {
            "check_id": self.check_id,
            "kind": self.kind.value,
            "status": self.status.value,
            "summary": self.summary,
            "evidence_refs": list(self.evidence_refs),
            "blocking": self.blocking,
            "blocks_gate8": self.blocks_gate8,
        }


@dataclass(frozen=True, slots=True)
class FinalReviewIssue:
    """One unresolved issue retained without silently manufacturing completion."""

    issue_id: str
    severity: FinalReviewIssueSeverity
    summary: str
    source_ref: str

    def __post_init__(self) -> None:
        for value, label, maximum_length in (
            (self.issue_id, "final review issue ID", _MAX_CODE_LENGTH),
            (self.summary, "final review issue summary", _MAX_TEXT_LENGTH),
            (self.source_ref, "final review issue source reference", _MAX_REFERENCE_LENGTH),
        ):
            normalized = normalize_required_text(
                value,
                label=label,
                maximum_length=maximum_length,
            )
            if normalized != value:
                raise ValueError(f"{label} must be normalized")

    @property
    def sort_key(self) -> tuple[int, str]:
        order = {
            FinalReviewIssueSeverity.CRITICAL: 0,
            FinalReviewIssueSeverity.MAJOR: 1,
            FinalReviewIssueSeverity.MODERATE: 2,
            FinalReviewIssueSeverity.MINOR: 3,
        }
        return (order[self.severity], self.issue_id)

    @property
    def blocks_gate8(self) -> bool:
        return self.severity in _BLOCKING_ISSUE_SEVERITIES

    def to_snapshot(self) -> dict[str, object]:
        return {
            "issue_id": self.issue_id,
            "severity": self.severity.value,
            "summary": self.summary,
            "source_ref": self.source_ref,
            "blocks_gate8": self.blocks_gate8,
        }


@dataclass(frozen=True, slots=True)
class AcceptedFinalLimitation:
    """One explicit owner-visible limitation carried into the final export."""

    limitation_id: str
    summary: str
    rationale: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.limitation_id, "final limitation ID"),
            (self.summary, "final limitation summary"),
            (self.rationale, "final limitation rationale"),
        ):
            normalized = normalize_required_text(
                value,
                label=label,
                maximum_length=(_MAX_CODE_LENGTH if label.endswith("ID") else _MAX_TEXT_LENGTH),
            )
            if normalized != value:
                raise ValueError(f"{label} must be normalized")

    @property
    def sort_key(self) -> str:
        return self.limitation_id

    def to_snapshot(self) -> dict[str, object]:
        return {
            "limitation_id": self.limitation_id,
            "summary": self.summary,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class FinalReviewAssessment:
    """Exact versioned assessment submitted to the final owner gate."""

    id: UUID
    project_id: UUID
    workflow_run_id: UUID
    owner_user_id: UUID
    version_number: int
    parent_review_id: UUID | None
    parent_content_hash: str | None
    workflow_state_version: int
    artifact_references: tuple[WorkflowArtifactReference, ...]
    checks: tuple[FinalReviewCheck, ...]
    unresolved_issues: tuple[FinalReviewIssue, ...]
    accepted_limitations: tuple[AcceptedFinalLimitation, ...]
    latest_execution_attempt_id: UUID | None
    latest_evaluation_run_id: UUID | None
    evaluation_aggregation_hash: str | None
    capability_status: ExecutionCapabilityStatus | None
    human_validation_status: HumanValidationStatus
    created_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        validate_positive_integer(self.version_number, label="final review version")
        validate_positive_integer(
            self.workflow_state_version,
            label="final review workflow state version",
        )
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("final review timestamp must be timezone-aware")
        if self.version_number == 1:
            if self.parent_review_id is not None or self.parent_content_hash is not None:
                raise ValueError("the first final review cannot have a parent")
        elif self.parent_review_id is None or self.parent_content_hash is None:
            raise ValueError("later final review versions require an exact parent")
        if self.parent_content_hash is not None:
            validate_sha256(self.parent_content_hash, label="parent final review hash")
        if self.evaluation_aggregation_hash is not None:
            validate_sha256(
                self.evaluation_aggregation_hash,
                label="final review evaluation aggregation hash",
            )
        if (self.latest_evaluation_run_id is None) != (self.evaluation_aggregation_hash is None):
            raise ValueError("final review evaluation identity and hash must be supplied together")

        ordered_artifacts = tuple(sorted(self.artifact_references, key=lambda item: item.sort_key))
        if ordered_artifacts != self.artifact_references:
            raise ValueError("final review artifacts must use canonical order")
        if len({item.sort_key for item in ordered_artifacts}) != len(ordered_artifacts):
            raise ValueError("final review artifacts must be unique")
        if tuple(sorted(self.checks, key=lambda item: item.sort_key)) != self.checks:
            raise ValueError("final review checks must use canonical order")
        if {item.kind for item in self.checks} != _REQUIRED_CHECK_KINDS:
            raise ValueError("final review must contain exactly one check for every required kind")
        if len({item.kind for item in self.checks}) != len(self.checks):
            raise ValueError("final review check kinds must be unique")
        if (
            tuple(sorted(self.unresolved_issues, key=lambda item: item.sort_key))
            != self.unresolved_issues
        ):
            raise ValueError("final review issues must use canonical order")
        if len({item.issue_id for item in self.unresolved_issues}) != len(self.unresolved_issues):
            raise ValueError("final review issue IDs must be unique")
        if (
            tuple(sorted(self.accepted_limitations, key=lambda item: item.sort_key))
            != self.accepted_limitations
        ):
            raise ValueError("accepted final limitations must use canonical order")
        if len({item.limitation_id for item in self.accepted_limitations}) != len(
            self.accepted_limitations
        ):
            raise ValueError("accepted final limitation IDs must be unique")

        validate_sha256(self.content_hash, label="final review content hash")
        if self.content_hash != final_review_content_hash(
            review_id=self.id,
            project_id=self.project_id,
            workflow_run_id=self.workflow_run_id,
            owner_user_id=self.owner_user_id,
            version_number=self.version_number,
            parent_review_id=self.parent_review_id,
            parent_content_hash=self.parent_content_hash,
            workflow_state_version=self.workflow_state_version,
            artifact_references=self.artifact_references,
            checks=self.checks,
            unresolved_issues=self.unresolved_issues,
            accepted_limitations=self.accepted_limitations,
            latest_execution_attempt_id=self.latest_execution_attempt_id,
            latest_evaluation_run_id=self.latest_evaluation_run_id,
            evaluation_aggregation_hash=self.evaluation_aggregation_hash,
            capability_status=self.capability_status,
            human_validation_status=self.human_validation_status,
        ):
            raise ValueError("final review content hash is inconsistent")

    @property
    def blocking_check_ids(self) -> tuple[str, ...]:
        return tuple(item.check_id for item in self.checks if item.blocks_gate8)

    @property
    def blocking_issue_ids(self) -> tuple[str, ...]:
        return tuple(item.issue_id for item in self.unresolved_issues if item.blocks_gate8)

    @property
    def ready_for_gate8(self) -> bool:
        return not self.blocking_check_ids and not self.blocking_issue_ids

    @property
    def owner_approval_is_empirical_validation(self) -> bool:
        return False

    def semantic_snapshot(self) -> dict[str, object]:
        return _final_review_semantic_snapshot(
            review_id=self.id,
            project_id=self.project_id,
            workflow_run_id=self.workflow_run_id,
            owner_user_id=self.owner_user_id,
            version_number=self.version_number,
            parent_review_id=self.parent_review_id,
            parent_content_hash=self.parent_content_hash,
            workflow_state_version=self.workflow_state_version,
            artifact_references=self.artifact_references,
            checks=self.checks,
            unresolved_issues=self.unresolved_issues,
            accepted_limitations=self.accepted_limitations,
            latest_execution_attempt_id=self.latest_execution_attempt_id,
            latest_evaluation_run_id=self.latest_evaluation_run_id,
            evaluation_aggregation_hash=self.evaluation_aggregation_hash,
            capability_status=self.capability_status,
            human_validation_status=self.human_validation_status,
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            **self.semantic_snapshot(),
            "created_at": self.created_at.isoformat(),
            "content_hash": self.content_hash,
            "ready_for_gate8": self.ready_for_gate8,
            "blocking_check_ids": list(self.blocking_check_ids),
            "blocking_issue_ids": list(self.blocking_issue_ids),
            "owner_approval_is_empirical_validation": False,
        }


def create_final_review_assessment(
    run: WorkflowRun,
    *,
    checks: tuple[FinalReviewCheck, ...],
    unresolved_issues: tuple[FinalReviewIssue, ...] = (),
    accepted_limitations: tuple[AcceptedFinalLimitation, ...] = (),
    evaluation_aggregation_hash: str | None = None,
    human_validation_status: HumanValidationStatus = HumanValidationStatus.NOT_RECORDED,
    previous_review: FinalReviewAssessment | None = None,
    review_id: UUID | None = None,
    created_at: datetime,
) -> FinalReviewAssessment:
    """Create the next exact review version from an authoritative workflow snapshot."""
    if previous_review is not None:
        if (
            previous_review.project_id != run.project_id
            or previous_review.workflow_run_id != run.id
            or previous_review.owner_user_id != run.owner_user_id
        ):
            raise ValueError("previous final review must share project, run, and owner scope")
        version_number = previous_review.version_number + 1
        parent_review_id = previous_review.id
        parent_content_hash = previous_review.content_hash
    else:
        version_number = 1
        parent_review_id = None
        parent_content_hash = None

    ordered_checks = tuple(sorted(checks, key=lambda item: item.sort_key))
    ordered_issues = tuple(sorted(unresolved_issues, key=lambda item: item.sort_key))
    ordered_limitations = tuple(sorted(accepted_limitations, key=lambda item: item.sort_key))
    identifier = review_id or uuid4()
    content_hash = final_review_content_hash(
        review_id=identifier,
        project_id=run.project_id,
        workflow_run_id=run.id,
        owner_user_id=run.owner_user_id,
        version_number=version_number,
        parent_review_id=parent_review_id,
        parent_content_hash=parent_content_hash,
        workflow_state_version=run.state_version,
        artifact_references=run.artifact_references,
        checks=ordered_checks,
        unresolved_issues=ordered_issues,
        accepted_limitations=ordered_limitations,
        latest_execution_attempt_id=run.latest_execution_attempt_id,
        latest_evaluation_run_id=run.latest_evaluation_run_id,
        evaluation_aggregation_hash=evaluation_aggregation_hash,
        capability_status=run.capability_state.capability_status,
        human_validation_status=human_validation_status,
    )
    return FinalReviewAssessment(
        id=identifier,
        project_id=run.project_id,
        workflow_run_id=run.id,
        owner_user_id=run.owner_user_id,
        version_number=version_number,
        parent_review_id=parent_review_id,
        parent_content_hash=parent_content_hash,
        workflow_state_version=run.state_version,
        artifact_references=run.artifact_references,
        checks=ordered_checks,
        unresolved_issues=ordered_issues,
        accepted_limitations=ordered_limitations,
        latest_execution_attempt_id=run.latest_execution_attempt_id,
        latest_evaluation_run_id=run.latest_evaluation_run_id,
        evaluation_aggregation_hash=evaluation_aggregation_hash,
        capability_status=run.capability_state.capability_status,
        human_validation_status=human_validation_status,
        created_at=created_at,
        content_hash=content_hash,
    )


def final_review_content_hash(
    *,
    review_id: UUID,
    project_id: UUID,
    workflow_run_id: UUID,
    owner_user_id: UUID,
    version_number: int,
    parent_review_id: UUID | None,
    parent_content_hash: str | None,
    workflow_state_version: int,
    artifact_references: tuple[WorkflowArtifactReference, ...],
    checks: tuple[FinalReviewCheck, ...],
    unresolved_issues: tuple[FinalReviewIssue, ...],
    accepted_limitations: tuple[AcceptedFinalLimitation, ...],
    latest_execution_attempt_id: UUID | None,
    latest_evaluation_run_id: UUID | None,
    evaluation_aggregation_hash: str | None,
    capability_status: ExecutionCapabilityStatus | None,
    human_validation_status: HumanValidationStatus,
) -> str:
    return snapshot_content_hash(
        _final_review_semantic_snapshot(
            review_id=review_id,
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            owner_user_id=owner_user_id,
            version_number=version_number,
            parent_review_id=parent_review_id,
            parent_content_hash=parent_content_hash,
            workflow_state_version=workflow_state_version,
            artifact_references=artifact_references,
            checks=checks,
            unresolved_issues=unresolved_issues,
            accepted_limitations=accepted_limitations,
            latest_execution_attempt_id=latest_execution_attempt_id,
            latest_evaluation_run_id=latest_evaluation_run_id,
            evaluation_aggregation_hash=evaluation_aggregation_hash,
            capability_status=capability_status,
            human_validation_status=human_validation_status,
        )
    )


def _final_review_semantic_snapshot(
    *,
    review_id: UUID,
    project_id: UUID,
    workflow_run_id: UUID,
    owner_user_id: UUID,
    version_number: int,
    parent_review_id: UUID | None,
    parent_content_hash: str | None,
    workflow_state_version: int,
    artifact_references: tuple[WorkflowArtifactReference, ...],
    checks: tuple[FinalReviewCheck, ...],
    unresolved_issues: tuple[FinalReviewIssue, ...],
    accepted_limitations: tuple[AcceptedFinalLimitation, ...],
    latest_execution_attempt_id: UUID | None,
    latest_evaluation_run_id: UUID | None,
    evaluation_aggregation_hash: str | None,
    capability_status: ExecutionCapabilityStatus | None,
    human_validation_status: HumanValidationStatus,
) -> dict[str, object]:
    return {
        "review_id": str(review_id),
        "project_id": str(project_id),
        "workflow_run_id": str(workflow_run_id),
        "owner_user_id": str(owner_user_id),
        "version_number": version_number,
        "parent_review_id": str(parent_review_id) if parent_review_id else None,
        "parent_content_hash": parent_content_hash,
        "workflow_state_version": workflow_state_version,
        "artifact_references": [item.to_snapshot() for item in artifact_references],
        "checks": [item.to_snapshot() for item in checks],
        "unresolved_issues": [item.to_snapshot() for item in unresolved_issues],
        "accepted_limitations": [item.to_snapshot() for item in accepted_limitations],
        "latest_execution_attempt_id": (
            str(latest_execution_attempt_id) if latest_execution_attempt_id else None
        ),
        "latest_evaluation_run_id": (
            str(latest_evaluation_run_id) if latest_evaluation_run_id else None
        ),
        "evaluation_aggregation_hash": evaluation_aggregation_hash,
        "capability_status": capability_status.value if capability_status else None,
        "human_validation_status": human_validation_status.value,
    }
