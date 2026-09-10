"""Persist completed owner-authorized User Twin evaluations."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from uuid import UUID

from orchestwin.evaluation.application import (
    ApprovedUserTwinEvaluationTarget,
    SyntheticEvaluationRun,
)
from orchestwin.evaluation.artifacts import (
    EvaluationArtifactBundle,
)
from orchestwin.evaluation.authorized_run_application import (
    AuthorizedIndependentUserTwinEvaluationService,
)
from orchestwin.evaluation.persistence import (
    StoredSyntheticEvaluationRun,
    SyntheticEvaluationRepository,
    SyntheticEvaluationStoreStatus,
)


class PersistedAuthorizedEvaluationIssueCode(StrEnum):
    """Stable failures at the authorized persistence boundary."""

    WORKFLOW_RUN_NOT_FOUND = "WORKFLOW_RUN_NOT_FOUND"
    CONTENT_CONFLICT = "CONTENT_CONFLICT"
    STORAGE_INTEGRITY_MISMATCH = "STORAGE_INTEGRITY_MISMATCH"


class PersistedAuthorizedEvaluationError(RuntimeError):
    """Typed failure without exposing evaluator or artifact content."""

    def __init__(
        self,
        code: PersistedAuthorizedEvaluationIssueCode,
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code


class PersistedAuthorizedIndependentUserTwinEvaluationService:
    """Evaluate through authorization, then durably verify the result."""

    def __init__(
        self,
        *,
        evaluation_service: (AuthorizedIndependentUserTwinEvaluationService),
        repository: SyntheticEvaluationRepository,
    ) -> None:
        self._evaluation_service = evaluation_service
        self._repository = repository

    async def evaluate(
        self,
        *,
        owner_user_id: UUID,
        artifact_bundle: EvaluationArtifactBundle,
        targets: Iterable[ApprovedUserTwinEvaluationTarget],
        selected: tuple[tuple[UUID, int], ...],
    ) -> SyntheticEvaluationRun:
        """Persist only the completed run returned by authorization."""
        run = await self._evaluation_service.evaluate(
            owner_user_id=owner_user_id,
            artifact_bundle=artifact_bundle,
            targets=targets,
            selected=selected,
        )

        stored_result = await self._repository.append(run)

        if stored_result.status is SyntheticEvaluationStoreStatus.WORKFLOW_RUN_NOT_FOUND:
            raise PersistedAuthorizedEvaluationError(
                PersistedAuthorizedEvaluationIssueCode.WORKFLOW_RUN_NOT_FOUND,
                ("authorized evaluation cannot be persisted outside its owner workflow scope"),
            )

        if stored_result.status is SyntheticEvaluationStoreStatus.CONTENT_CONFLICT:
            raise PersistedAuthorizedEvaluationError(
                PersistedAuthorizedEvaluationIssueCode.CONTENT_CONFLICT,
                ("authorized evaluation identity conflicts with existing persisted content"),
            )

        if stored_result.status not in {
            SyntheticEvaluationStoreStatus.CREATED,
            SyntheticEvaluationStoreStatus.ALREADY_PRESENT,
        }:
            raise PersistedAuthorizedEvaluationError(
                PersistedAuthorizedEvaluationIssueCode.STORAGE_INTEGRITY_MISMATCH,
                "synthetic evaluation persistence returned an invalid status",
            )

        expected = StoredSyntheticEvaluationRun.from_domain(run)

        if stored_result.run != expected:
            raise PersistedAuthorizedEvaluationError(
                PersistedAuthorizedEvaluationIssueCode.STORAGE_INTEGRITY_MISMATCH,
                ("persisted evaluation projection does not match the authorized run"),
            )

        persisted_run = await self._repository.get_owned(run_id=run.id)

        if persisted_run != expected:
            raise PersistedAuthorizedEvaluationError(
                PersistedAuthorizedEvaluationIssueCode.STORAGE_INTEGRITY_MISMATCH,
                ("authorized evaluation readback does not match the completed run"),
            )

        persisted_findings = await self._repository.list_findings(run_id=run.id)

        if persisted_findings != run.findings:
            raise PersistedAuthorizedEvaluationError(
                PersistedAuthorizedEvaluationIssueCode.STORAGE_INTEGRITY_MISMATCH,
                ("persisted synthetic findings do not match the authorized evaluator output"),
            )

        return run


__all__ = [
    "PersistedAuthorizedEvaluationError",
    "PersistedAuthorizedEvaluationIssueCode",
    "PersistedAuthorizedIndependentUserTwinEvaluationService",
]
