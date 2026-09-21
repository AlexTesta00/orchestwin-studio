"""Independent User Twin runs through owner-authorized verified artifact content."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from uuid import UUID

from orchestwin.evaluation.application import (
    ApprovedUserTwinEvaluationTarget,
    SyntheticEvaluationError,
    SyntheticEvaluationIssueCode,
    SyntheticEvaluationRun,
    SyntheticEvaluationRunStatus,
    synthetic_evaluation_run_hash,
)
from orchestwin.evaluation.artifacts import (
    EvaluationArtifactBundle,
    EvaluationArtifactKind,
)
from orchestwin.evaluation.authorized_content_application import (
    AuthorizedArtifactContentEvaluationService,
)
from orchestwin.evaluation.evaluator import (
    UserTwinEvaluationRequest,
    UserTwinEvaluationResponse,
)
from orchestwin.evaluation.validation import (
    EvaluationEvidenceKind,
    EvaluationEvidenceReference,
    SyntheticFindingValidationContext,
    validate_synthetic_finding,
)

_MIN_TWINS = 1
_MAX_TWINS = 4


class AuthorizedIndependentUserTwinEvaluationService:
    """Evaluate approved User Twins independently through verified content."""

    def __init__(
        self,
        *,
        authorized_evaluation_service: AuthorizedArtifactContentEvaluationService,
        identifier_provider: Callable[[], UUID],
        clock: Callable[[], datetime],
    ) -> None:
        self._authorized_evaluation_service = authorized_evaluation_service
        self._identifier_provider = identifier_provider
        self._clock = clock

    async def evaluate(
        self,
        *,
        owner_user_id: UUID,
        artifact_bundle: EvaluationArtifactBundle,
        targets: Iterable[ApprovedUserTwinEvaluationTarget],
        selected: tuple[tuple[UUID, int], ...],
    ) -> SyntheticEvaluationRun:
        """Run each exact approved Twin through its own authorized context."""
        ordered_targets = tuple(
            sorted(
                targets,
                key=lambda target: target.sort_key,
            )
        )

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

            response = await self._authorized_evaluation_service.evaluate(
                owner_user_id=owner_user_id,
                request=request,
                selected=selected,
            )

            self._validate_response(
                response,
                request=request,
                target=target,
                selected=selected,
            )

            if responses and response.evaluator != responses[0].evaluator:
                raise SyntheticEvaluationError(
                    SyntheticEvaluationIssueCode.RESPONSE_SCOPE_MISMATCH,
                    "independent User Twin evaluations used inconsistent evaluator configurations",
                )

            responses.append(response)

        completed_at = self._clock()

        ordered_responses = tuple(
            sorted(
                responses,
                key=lambda response: (
                    response.twin_id.hex,
                    response.twin_version,
                ),
            )
        )

        evaluator = ordered_responses[0].evaluator

        return SyntheticEvaluationRun(
            id=evaluation_run_id,
            project_id=artifact_bundle.project_id,
            workflow_run_id=artifact_bundle.workflow_run_id,
            owner_user_id=owner_user_id,
            artifact_bundle_id=artifact_bundle.id,
            artifact_bundle_hash=artifact_bundle.content_hash,
            evaluator=evaluator,
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
                evaluator=evaluator,
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
        selected: tuple[tuple[UUID, int], ...],
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
            (artifact.artifact_id, artifact.version_number): artifact
            for artifact in request.artifact_bundle.artifacts
        }

        authorized_evidence = {reference.reference_id: reference for reference in target.evidence}

        for identity in selected:
            artifact = artifacts.get(identity)

            if artifact is None:
                raise SyntheticEvaluationError(
                    SyntheticEvaluationIssueCode.RESPONSE_SCOPE_MISMATCH,
                    "verified artifact selection is outside the supplied bundle",
                )

            if artifact.kind not in {
                EvaluationArtifactKind.DOM_SNAPSHOT,
                EvaluationArtifactKind.AXE_REPORT,
            }:
                raise SyntheticEvaluationError(
                    SyntheticEvaluationIssueCode.RESPONSE_SCOPE_MISMATCH,
                    "verified artifact selection contains unsupported content",
                )

            kind = (
                EvaluationEvidenceKind.DETERMINISTIC_TEST
                if artifact.kind is EvaluationArtifactKind.AXE_REPORT
                else EvaluationEvidenceKind.PROJECT_ARTIFACT
            )

            citation = EvaluationEvidenceReference(
                reference_id=(f"artifact:{artifact.artifact_id}:v{artifact.version_number}"),
                kind=kind,
                content_hash=artifact.sha256_digest,
                locator=artifact.location,
            )

            existing = authorized_evidence.get(citation.reference_id)

            if existing is not None and existing != citation:
                raise SyntheticEvaluationError(
                    SyntheticEvaluationIssueCode.INVALID_FINDING,
                    "verified artifact citation conflicts with target evidence",
                )

            authorized_evidence[citation.reference_id] = citation

        evidence = tuple(
            sorted(
                authorized_evidence.values(),
                key=lambda reference: reference.sort_key,
            )
        )

        selected_identities = set(selected)

        for finding in response.findings:
            identity = (
                finding.artifact_id,
                finding.artifact_version,
            )

            if identity not in selected_identities:
                raise SyntheticEvaluationError(
                    SyntheticEvaluationIssueCode.RESPONSE_SCOPE_MISMATCH,
                    "User Twin evaluator cited content outside the verified artifact selection",
                )

            report = validate_synthetic_finding(
                finding,
                SyntheticFindingValidationContext(
                    twin_id=target.twin.twin_id,
                    twin_version=target.twin.version_number,
                    artifact_id=finding.artifact_id,
                    artifact_version=finding.artifact_version,
                    evidence=evidence,
                ),
            )

            if not report.is_valid:
                issue_codes = ", ".join(issue.code.value for issue in report.issues)

                raise SyntheticEvaluationError(
                    SyntheticEvaluationIssueCode.INVALID_FINDING,
                    (f"User Twin evaluator returned an invalid finding: {issue_codes}"),
                )


__all__ = [
    "AuthorizedIndependentUserTwinEvaluationService",
]
