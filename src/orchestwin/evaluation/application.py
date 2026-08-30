"""Application service for independent approved User Twin evaluations."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from orchestwin.evaluation.artifacts import EvaluationArtifactBundle
from orchestwin.evaluation.evaluator import (
    EvaluationUserTwinProfile,
    UserTwinEvaluationRequest,
    UserTwinEvaluationResponse,
    UserTwinEvaluatorConfiguration,
    UserTwinEvaluatorPort,
)
from orchestwin.evaluation.findings import SyntheticFinding
from orchestwin.evaluation.validation import (
    EvaluationEvidenceReference,
    SyntheticFindingValidationContext,
    validate_synthetic_finding,
)
from orchestwin.projects.requirements_primitives import (
    snapshot_content_hash,
    validate_sha256,
)
from orchestwin.twins.user_twins import UserTwinLifecycleStatus

_MIN_TWINS = 1
_MAX_TWINS = 4

_APPROVED_LIFECYCLE_STATUSES = frozenset(
    {
        UserTwinLifecycleStatus.OWNER_APPROVED_UT,
        UserTwinLifecycleStatus.EMPIRICALLY_GROUNDED_UT,
        UserTwinLifecycleStatus.EMPIRICALLY_VALIDATED_UT,
    }
)

SYNTHETIC_RUN_DISCLAIMER = (
    "Each User Twin was evaluated independently. The outputs are simulated design "
    "hypotheses, not independent human samples or empirical validation."
)


class SyntheticEvaluationRunStatus(StrEnum):
    """Stable lifecycle of one completed application-level evaluation run."""

    COMPLETED = "COMPLETED"


class SyntheticEvaluationIssueCode(StrEnum):
    """Stable precondition or output-validation failure codes."""

    INVALID_TWIN_COUNT = "INVALID_TWIN_COUNT"
    DUPLICATE_TWIN = "DUPLICATE_TWIN"
    UNAPPROVED_TWIN = "UNAPPROVED_TWIN"
    INVALID_FINDING = "INVALID_FINDING"
    RESPONSE_SCOPE_MISMATCH = "RESPONSE_SCOPE_MISMATCH"


class SyntheticEvaluationError(ValueError):
    """Typed application error safe to map at API or workflow boundaries."""

    def __init__(self, code: SyntheticEvaluationIssueCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ApprovedUserTwinEvaluationTarget:
    """One exact approved profile and its authorized evidence boundary."""

    twin: EvaluationUserTwinProfile
    evidence: tuple[EvaluationEvidenceReference, ...]

    def __post_init__(self) -> None:
        if self.twin.lifecycle_status not in _APPROVED_LIFECYCLE_STATUSES:
            raise SyntheticEvaluationError(
                SyntheticEvaluationIssueCode.UNAPPROVED_TWIN,
                "synthetic evaluation requires an owner-approved or empirical User Twin",
            )
        ordered = tuple(sorted(self.evidence, key=lambda item: item.sort_key))
        if ordered != self.evidence:
            raise ValueError("evaluation target evidence must use canonical order")
        identifiers = tuple(reference.reference_id for reference in self.evidence)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("evaluation target evidence references must be unique")

    @property
    def sort_key(self) -> tuple[str, int]:
        return (self.twin.twin_id.hex, self.twin.version_number)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "twin": self.twin.to_snapshot(),
            "evidence": [reference.to_snapshot() for reference in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class SyntheticEvaluationRun:
    """Immutable run retaining each User Twin response without forced consensus."""

    id: UUID
    project_id: UUID
    workflow_run_id: UUID
    owner_user_id: UUID
    artifact_bundle_id: UUID
    artifact_bundle_hash: str
    evaluator: UserTwinEvaluatorConfiguration
    status: SyntheticEvaluationRunStatus
    twin_evaluations: tuple[UserTwinEvaluationResponse, ...]
    started_at: datetime
    completed_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        validate_sha256(
            self.artifact_bundle_hash,
            label="synthetic evaluation artifact bundle hash",
        )
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            raise ValueError("synthetic evaluation start timestamp must be timezone-aware")
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None:
            raise ValueError("synthetic evaluation completion timestamp must be timezone-aware")
        if self.completed_at < self.started_at:
            raise ValueError("synthetic evaluation cannot complete before it starts")
        if not _MIN_TWINS <= len(self.twin_evaluations) <= _MAX_TWINS:
            raise ValueError("synthetic evaluation requires between one and four User Twins")
        ordered = tuple(
            sorted(
                self.twin_evaluations,
                key=lambda response: (response.twin_id.hex, response.twin_version),
            )
        )
        if ordered != self.twin_evaluations:
            raise ValueError("synthetic evaluation responses must use canonical twin order")
        identities = tuple(
            (response.twin_id, response.twin_version) for response in self.twin_evaluations
        )
        if len(identities) != len(set(identities)):
            raise ValueError("synthetic evaluation responses must contain unique twin versions")
        if any(
            response.evaluation_run_id != self.id
            or response.artifact_bundle_id != self.artifact_bundle_id
            or response.artifact_bundle_hash != self.artifact_bundle_hash
            or response.evaluator != self.evaluator
            for response in self.twin_evaluations
        ):
            raise ValueError("synthetic evaluation response scope is inconsistent")
        validate_sha256(
            self.content_hash,
            label="synthetic evaluation run content hash",
        )
        if self.content_hash != synthetic_evaluation_run_hash(
            run_id=self.id,
            project_id=self.project_id,
            workflow_run_id=self.workflow_run_id,
            owner_user_id=self.owner_user_id,
            artifact_bundle_id=self.artifact_bundle_id,
            artifact_bundle_hash=self.artifact_bundle_hash,
            evaluator=self.evaluator,
            status=self.status,
            twin_evaluations=self.twin_evaluations,
        ):
            raise ValueError("synthetic evaluation run content hash is inconsistent")

    @property
    def findings(self) -> tuple[SyntheticFinding, ...]:
        """Flatten findings while retaining originating twin metadata on every item."""
        return tuple(finding for response in self.twin_evaluations for finding in response.findings)

    @property
    def disclaimer(self) -> str:
        return SYNTHETIC_RUN_DISCLAIMER

    def semantic_snapshot(self) -> dict[str, object]:
        return _run_semantic_snapshot(
            run_id=self.id,
            project_id=self.project_id,
            workflow_run_id=self.workflow_run_id,
            owner_user_id=self.owner_user_id,
            artifact_bundle_id=self.artifact_bundle_id,
            artifact_bundle_hash=self.artifact_bundle_hash,
            evaluator=self.evaluator,
            status=self.status,
            twin_evaluations=self.twin_evaluations,
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            **self.semantic_snapshot(),
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "content_hash": self.content_hash,
            "disclaimer": self.disclaimer,
        }


class IndependentUserTwinEvaluationService:
    """Evaluate exact approved twins one at a time with isolated request context."""

    def __init__(
        self,
        evaluator: UserTwinEvaluatorPort,
        *,
        identifier_provider: Callable[[], UUID],
        clock: Callable[[], datetime],
    ) -> None:
        self._evaluator = evaluator
        self._identifier_provider = identifier_provider
        self._clock = clock

    async def evaluate(
        self,
        *,
        owner_user_id: UUID,
        artifact_bundle: EvaluationArtifactBundle,
        targets: Iterable[ApprovedUserTwinEvaluationTarget],
    ) -> SyntheticEvaluationRun:
        ordered_targets = tuple(sorted(targets, key=lambda target: target.sort_key))
        if not _MIN_TWINS <= len(ordered_targets) <= _MAX_TWINS:
            raise SyntheticEvaluationError(
                SyntheticEvaluationIssueCode.INVALID_TWIN_COUNT,
                "synthetic evaluation requires between one and four approved User Twins",
            )
        identities = tuple(target.sort_key for target in ordered_targets)
        if len(identities) != len(set(identities)):
            raise SyntheticEvaluationError(
                SyntheticEvaluationIssueCode.DUPLICATE_TWIN,
                "synthetic evaluation targets must contain unique User Twin versions",
            )

        evaluation_run_id = self._identifier_provider()
        started_at = self._clock()
        responses: list[UserTwinEvaluationResponse] = []
        for target in ordered_targets:
            request = UserTwinEvaluationRequest(
                evaluation_run_id=evaluation_run_id,
                project_id=artifact_bundle.project_id,
                workflow_run_id=artifact_bundle.workflow_run_id,
                artifact_bundle=artifact_bundle,
                twin=target.twin,
                evidence=target.evidence,
                requested_at=started_at,
            )
            response = await self._evaluator.evaluate(request)
            self._validate_response(response, request=request, target=target)
            responses.append(response)

        completed_at = self._clock()
        ordered_responses = tuple(
            sorted(responses, key=lambda response: (response.twin_id.hex, response.twin_version))
        )
        return SyntheticEvaluationRun(
            id=evaluation_run_id,
            project_id=artifact_bundle.project_id,
            workflow_run_id=artifact_bundle.workflow_run_id,
            owner_user_id=owner_user_id,
            artifact_bundle_id=artifact_bundle.id,
            artifact_bundle_hash=artifact_bundle.content_hash,
            evaluator=self._evaluator.configuration,
            status=SyntheticEvaluationRunStatus.COMPLETED,
            twin_evaluations=ordered_responses,
            started_at=started_at,
            completed_at=completed_at,
            content_hash=synthetic_evaluation_run_hash(
                run_id=evaluation_run_id,
                project_id=artifact_bundle.project_id,
                workflow_run_id=artifact_bundle.workflow_run_id,
                owner_user_id=owner_user_id,
                artifact_bundle_id=artifact_bundle.id,
                artifact_bundle_hash=artifact_bundle.content_hash,
                evaluator=self._evaluator.configuration,
                status=SyntheticEvaluationRunStatus.COMPLETED,
                twin_evaluations=ordered_responses,
            ),
        )

    @staticmethod
    def _validate_response(
        response: UserTwinEvaluationResponse,
        *,
        request: UserTwinEvaluationRequest,
        target: ApprovedUserTwinEvaluationTarget,
    ) -> None:
        if (
            response.evaluation_run_id != request.evaluation_run_id
            or response.artifact_bundle_id != request.artifact_bundle.id
            or response.artifact_bundle_hash != request.artifact_bundle.content_hash
            or response.twin_id != target.twin.twin_id
            or response.twin_version != target.twin.version_number
        ):
            raise SyntheticEvaluationError(
                SyntheticEvaluationIssueCode.RESPONSE_SCOPE_MISMATCH,
                "User Twin evaluator returned a response for another evaluation scope",
            )
        artifacts = {
            (artifact.artifact_id, artifact.version_number)
            for artifact in request.artifact_bundle.artifacts
        }
        for finding in response.findings:
            if (finding.artifact_id, finding.artifact_version) not in artifacts:
                raise SyntheticEvaluationError(
                    SyntheticEvaluationIssueCode.RESPONSE_SCOPE_MISMATCH,
                    "User Twin evaluator cited an artifact outside the supplied bundle",
                )
            report = validate_synthetic_finding(
                finding,
                SyntheticFindingValidationContext(
                    twin_id=target.twin.twin_id,
                    twin_version=target.twin.version_number,
                    artifact_id=finding.artifact_id,
                    artifact_version=finding.artifact_version,
                    evidence=target.evidence,
                ),
            )
            if not report.is_valid:
                issue_codes = ", ".join(issue.code.value for issue in report.issues)
                raise SyntheticEvaluationError(
                    SyntheticEvaluationIssueCode.INVALID_FINDING,
                    f"User Twin evaluator returned an invalid finding: {issue_codes}",
                )


def synthetic_evaluation_run_hash(
    *,
    run_id: UUID,
    project_id: UUID,
    workflow_run_id: UUID,
    owner_user_id: UUID,
    artifact_bundle_id: UUID,
    artifact_bundle_hash: str,
    evaluator: UserTwinEvaluatorConfiguration,
    status: SyntheticEvaluationRunStatus,
    twin_evaluations: tuple[UserTwinEvaluationResponse, ...],
) -> str:
    """Hash semantic run content independently from timestamps."""
    return snapshot_content_hash(
        _run_semantic_snapshot(
            run_id=run_id,
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            owner_user_id=owner_user_id,
            artifact_bundle_id=artifact_bundle_id,
            artifact_bundle_hash=artifact_bundle_hash,
            evaluator=evaluator,
            status=status,
            twin_evaluations=twin_evaluations,
        )
    )


def _run_semantic_snapshot(
    *,
    run_id: UUID,
    project_id: UUID,
    workflow_run_id: UUID,
    owner_user_id: UUID,
    artifact_bundle_id: UUID,
    artifact_bundle_hash: str,
    evaluator: UserTwinEvaluatorConfiguration,
    status: SyntheticEvaluationRunStatus,
    twin_evaluations: tuple[UserTwinEvaluationResponse, ...],
) -> dict[str, object]:
    return {
        "id": str(run_id),
        "project_id": str(project_id),
        "workflow_run_id": str(workflow_run_id),
        "owner_user_id": str(owner_user_id),
        "artifact_bundle_id": str(artifact_bundle_id),
        "artifact_bundle_hash": artifact_bundle_hash,
        "evaluator": evaluator.to_snapshot(),
        "status": status.value,
        "twin_evaluations": [response.to_snapshot() for response in twin_evaluations],
        "is_simulated_feedback": True,
        "aggregation": "NONE_INDEPENDENT_RESPONSES_PRESERVED",
    }
