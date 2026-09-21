"""Durably bind one persisted synthetic evaluation to its workflow run."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from orchestwin.evaluation.application import (
    ApprovedUserTwinEvaluationTarget,
    SyntheticEvaluationRun,
    SyntheticEvaluationRunStatus,
)
from orchestwin.evaluation.artifacts import (
    EvaluationArtifactBundle,
)
from orchestwin.workflow.checkpoints import (
    create_workflow_checkpoint,
)
from orchestwin.workflow.routing import (
    WorkflowTransitionStatus,
    advance_workflow_run,
)
from orchestwin.workflow.run_persistence import (
    WorkflowRunRepository,
    WorkflowRunStoreStatus,
)
from orchestwin.workflow.runs import (
    WorkflowArtifactReference,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowStage,
)

_EVALUATION_ARTIFACT_TYPE = "SYNTHETIC_EVALUATION"


class SyntheticEvaluationStageIssueCode(StrEnum):
    """Stable failures at the synthetic-evaluation workflow boundary."""

    RUN_NOT_FOUND = "RUN_NOT_FOUND"
    RUN_NOT_ACTIVE = "RUN_NOT_ACTIVE"
    WRONG_STAGE = "WRONG_STAGE"
    STATE_VERSION_CONFLICT = "STATE_VERSION_CONFLICT"
    EVALUATION_SCOPE_MISMATCH = "EVALUATION_SCOPE_MISMATCH"
    EVALUATION_NOT_COMPLETED = "EVALUATION_NOT_COMPLETED"
    EVALUATION_TIMESTAMP_OUT_OF_ORDER = "EVALUATION_TIMESTAMP_OUT_OF_ORDER"
    WORKFLOW_TRANSITION_REJECTED = "WORKFLOW_TRANSITION_REJECTED"


class SyntheticEvaluationStageError(RuntimeError):
    """Typed workflow-stage failure with no evaluator content exposure."""

    def __init__(
        self,
        code: SyntheticEvaluationStageIssueCode,
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code


class PersistedAuthorizedEvaluationPort(Protocol):
    """Persisted owner-authorized evaluation boundary."""

    async def evaluate(
        self,
        *,
        owner_user_id: UUID,
        artifact_bundle: EvaluationArtifactBundle,
        targets: Iterable[ApprovedUserTwinEvaluationTarget],
        selected: tuple[tuple[UUID, int], ...],
    ) -> SyntheticEvaluationRun:
        """Return one completed, durably persisted evaluation run."""


@dataclass(frozen=True, slots=True)
class SyntheticEvaluationStageResult:
    """Persisted evaluation plus its checkpointed workflow state."""

    run: WorkflowRun
    evaluation_run: SyntheticEvaluationRun


class SyntheticEvaluationStageService:
    """Execute and checkpoint the SYNTHETIC_EVALUATION workflow stage."""

    def __init__(
        self,
        *,
        workflow_repository: WorkflowRunRepository,
        evaluation_service: PersistedAuthorizedEvaluationPort,
    ) -> None:
        self._workflow_repository = workflow_repository
        self._evaluation_service = evaluation_service

    async def execute(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        run_id: UUID,
        expected_state_version: int,
        artifact_bundle: EvaluationArtifactBundle,
        targets: Iterable[ApprovedUserTwinEvaluationTarget],
        selected: tuple[tuple[UUID, int], ...],
    ) -> SyntheticEvaluationStageResult:
        """Evaluate only from the exact active workflow state."""
        current = await self._workflow_repository.get_owned(run_id=run_id)

        if (
            current is None
            or current.owner_user_id != owner_user_id
            or current.project_id != project_id
        ):
            raise SyntheticEvaluationStageError(
                SyntheticEvaluationStageIssueCode.RUN_NOT_FOUND,
                "workflow run is not available in this owner scope",
            )

        if current.state_version != expected_state_version:
            raise SyntheticEvaluationStageError(
                SyntheticEvaluationStageIssueCode.STATE_VERSION_CONFLICT,
                "workflow state version changed before evaluation",
            )

        if current.status is not WorkflowRunStatus.RUNNING:
            raise SyntheticEvaluationStageError(
                SyntheticEvaluationStageIssueCode.RUN_NOT_ACTIVE,
                "synthetic evaluation requires an active workflow run",
            )

        if current.current_stage is not WorkflowStage.SYNTHETIC_EVALUATION:
            raise SyntheticEvaluationStageError(
                SyntheticEvaluationStageIssueCode.WRONG_STAGE,
                ("workflow run is not at the synthetic-evaluation stage"),
            )

        if (
            artifact_bundle.project_id != current.project_id
            or artifact_bundle.workflow_run_id != current.id
        ):
            raise SyntheticEvaluationStageError(
                SyntheticEvaluationStageIssueCode.EVALUATION_SCOPE_MISMATCH,
                ("evaluation artifact bundle does not match the active workflow scope"),
            )

        evaluation_run = await self._evaluation_service.evaluate(
            owner_user_id=owner_user_id,
            artifact_bundle=artifact_bundle,
            targets=targets,
            selected=selected,
        )

        if (
            evaluation_run.owner_user_id != current.owner_user_id
            or evaluation_run.project_id != current.project_id
            or evaluation_run.workflow_run_id != current.id
            or evaluation_run.artifact_bundle_id != artifact_bundle.id
            or evaluation_run.artifact_bundle_hash != artifact_bundle.content_hash
        ):
            raise SyntheticEvaluationStageError(
                SyntheticEvaluationStageIssueCode.EVALUATION_SCOPE_MISMATCH,
                (
                    "persisted evaluation result does not match "
                    "the active workflow and artifact bundle"
                ),
            )

        if evaluation_run.status is not SyntheticEvaluationRunStatus.COMPLETED:
            raise SyntheticEvaluationStageError(
                SyntheticEvaluationStageIssueCode.EVALUATION_NOT_COMPLETED,
                "workflow cannot bind an incomplete evaluation",
            )

        if evaluation_run.completed_at < current.updated_at:
            raise SyntheticEvaluationStageError(
                SyntheticEvaluationStageIssueCode.EVALUATION_TIMESTAMP_OUT_OF_ORDER,
                ("evaluation completion timestamp precedes the current workflow state"),
            )

        evaluation_reference = WorkflowArtifactReference(
            artifact_type=_EVALUATION_ARTIFACT_TYPE,
            artifact_id=evaluation_run.id,
            version_number=1,
            content_hash=evaluation_run.content_hash,
        )

        existing = tuple(
            reference
            for reference in current.artifact_references
            if (
                reference.artifact_type == evaluation_reference.artifact_type
                and reference.artifact_id == evaluation_reference.artifact_id
                and reference.version_number == evaluation_reference.version_number
            )
        )

        if existing:
            if len(existing) != 1 or existing[0] != evaluation_reference:
                raise SyntheticEvaluationStageError(
                    SyntheticEvaluationStageIssueCode.EVALUATION_SCOPE_MISMATCH,
                    ("workflow already contains conflicting evaluation artifact metadata"),
                )

            artifact_references = current.artifact_references
        else:
            artifact_references = tuple(
                sorted(
                    (
                        *current.artifact_references,
                        evaluation_reference,
                    ),
                    key=lambda reference: reference.sort_key,
                )
            )

        # Bind the completed evaluation without incrementing the version
        # here. The legal workflow transition owns the single state-version
        # increment for this stage completion.
        bound = replace(
            current,
            artifact_references=artifact_references,
            latest_evaluation_run_id=evaluation_run.id,
        )

        transition = advance_workflow_run(
            bound,
            next_stage=WorkflowStage.REVISION_DECISION,
            occurred_at=evaluation_run.completed_at,
        )

        if transition.status is not WorkflowTransitionStatus.APPLIED:
            raise SyntheticEvaluationStageError(
                SyntheticEvaluationStageIssueCode.WORKFLOW_TRANSITION_REJECTED,
                ("workflow rejected the transition from synthetic evaluation to revision decision"),
            )

        history = await self._workflow_repository.list_checkpoints(run_id=current.id)

        previous_checkpoint = None if not history else history[-1]

        creation = create_workflow_checkpoint(
            transition.run,
            created_at=evaluation_run.completed_at,
            previous_checkpoint=previous_checkpoint,
        )

        stored = await self._workflow_repository.save_checkpoint(
            previous_run=current,
            creation=creation,
        )

        if stored.status is not WorkflowRunStoreStatus.UPDATED or stored.run is None:
            raise SyntheticEvaluationStageError(
                SyntheticEvaluationStageIssueCode.STATE_VERSION_CONFLICT,
                ("workflow state changed before the evaluation checkpoint could be stored"),
            )

        return SyntheticEvaluationStageResult(
            run=stored.run,
            evaluation_run=evaluation_run,
        )


__all__ = [
    "PersistedAuthorizedEvaluationPort",
    "SyntheticEvaluationStageError",
    "SyntheticEvaluationStageIssueCode",
    "SyntheticEvaluationStageResult",
    "SyntheticEvaluationStageService",
]
