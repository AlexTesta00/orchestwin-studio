"""Application service for exact Gate 7 high-impact operation approval."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from orchestwin.workflow.gates import (
    DEFAULT_GATE_ITERATION_LIMIT,
    GateArtifactReference,
    HumanGate,
    HumanGateAction,
    HumanGateEvent,
    HumanGateIssueCode,
    HumanGateStatus,
    HumanGateTransitionStatus,
    HumanGateType,
    create_human_gate,
    mark_human_gate_stale,
    transition_human_gate,
)
from orchestwin.workflow.high_impact import (
    DEFAULT_HIGH_IMPACT_OPERATION_POLICY,
    HighImpactClassification,
    HighImpactExecutionRequest,
    HighImpactOperationPolicy,
    HighImpactOperationReference,
    HighImpactOperationRequestVersion,
    classify_high_impact_operation,
)
from orchestwin.workflow.high_impact_persistence import (
    HighImpactAppendStatus,
    HighImpactApprovalUnitOfWorkFactory,
    PersistedHighImpactOperation,
)


class HighImpactRequestCreateStatus(StrEnum):
    CREATED = "CREATED"
    ALREADY_PRESENT = "ALREADY_PRESENT"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    VERSION_CONFLICT = "VERSION_CONFLICT"


class HighImpactGateSubmissionStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    ALREADY_PENDING = "ALREADY_PENDING"
    ALREADY_APPROVED = "ALREADY_APPROVED"
    APPROVAL_NOT_REQUIRED = "APPROVAL_NOT_REQUIRED"
    FORBIDDEN_BY_POLICY = "FORBIDDEN_BY_POLICY"
    REQUEST_NOT_FOUND = "REQUEST_NOT_FOUND"
    STALE_REQUEST = "STALE_REQUEST"
    ITERATION_LIMIT_REACHED = "ITERATION_LIMIT_REACHED"
    INVALID_TRANSITION = "INVALID_TRANSITION"


class HighImpactGateDecisionStatus(StrEnum):
    APPLIED = "APPLIED"
    NO_CHANGE = "NO_CHANGE"
    APPROVAL_NOT_REQUIRED = "APPROVAL_NOT_REQUIRED"
    FORBIDDEN_BY_POLICY = "FORBIDDEN_BY_POLICY"
    REQUEST_NOT_FOUND = "REQUEST_NOT_FOUND"
    GATE_NOT_FOUND = "GATE_NOT_FOUND"
    STALE_REQUEST = "STALE_REQUEST"
    REJECTED = "REJECTED"


class HighImpactApprovalReadiness(StrEnum):
    REQUEST_NOT_FOUND = "REQUEST_NOT_FOUND"
    FORBIDDEN_BY_POLICY = "FORBIDDEN_BY_POLICY"
    APPROVAL_NOT_REQUIRED = "APPROVAL_NOT_REQUIRED"
    OWNER_APPROVAL_REQUIRED = "OWNER_APPROVAL_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    STALE = "STALE"


@dataclass(frozen=True, slots=True)
class HighImpactRequestCreateResult:
    status: HighImpactRequestCreateStatus
    operation: PersistedHighImpactOperation | None

    def __post_init__(self) -> None:
        successful = self.status in {
            HighImpactRequestCreateStatus.CREATED,
            HighImpactRequestCreateStatus.ALREADY_PRESENT,
        }
        if successful != (self.operation is not None):
            raise ValueError("high-impact request create result shape is inconsistent")


@dataclass(frozen=True, slots=True)
class HighImpactGateSubmissionResult:
    status: HighImpactGateSubmissionStatus
    operation: PersistedHighImpactOperation | None
    gate: HumanGate | None
    event: HumanGateEvent | None
    issue: HumanGateIssueCode | None = None


@dataclass(frozen=True, slots=True)
class HighImpactGateDecisionResult:
    status: HighImpactGateDecisionStatus
    operation: PersistedHighImpactOperation | None
    gate: HumanGate | None
    event: HumanGateEvent | None
    issue: HumanGateIssueCode | None = None


@dataclass(frozen=True, slots=True)
class HighImpactReadinessResult:
    status: HighImpactApprovalReadiness
    operation: PersistedHighImpactOperation | None
    gate: HumanGate | None


class LocalHighImpactApprovalService:
    """Coordinate append-only requests, classification, and exact Gate 7 decisions."""

    def __init__(
        self,
        *,
        unit_of_work_factory: HighImpactApprovalUnitOfWorkFactory,
        policy: HighImpactOperationPolicy = DEFAULT_HIGH_IMPACT_OPERATION_POLICY,
        uuid_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] | None = None,
        max_iterations: int = DEFAULT_GATE_ITERATION_LIMIT,
    ) -> None:
        if max_iterations < 1:
            raise ValueError("Gate 7 iteration limit must be positive")
        self._unit_of_work_factory = unit_of_work_factory
        self._policy = policy
        self._uuid_factory = uuid_factory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._max_iterations = max_iterations

    async def create_request(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        request: HighImpactExecutionRequest,
    ) -> HighImpactRequestCreateResult:
        if request.project_id != project_id:
            raise ValueError("high-impact request belongs to another project")
        async with self._unit_of_work_factory(owner_user_id=owner_user_id) as unit_of_work:
            current = await unit_of_work.operations.current(project_id=project_id)
            version = HighImpactOperationRequestVersion(
                id=self._uuid_factory(),
                project_id=project_id,
                version_number=1 if current is None else current.version_number + 1,
                based_on_version_number=(None if current is None else current.version_number),
                request=request,
                content_hash=request.content_hash,
                created_by_user_id=owner_user_id,
                created_at=self._clock(),
            )
            classification = classify_high_impact_operation(version, policy=self._policy)
            appended = await unit_of_work.operations.append(version, classification)
            status_map = {
                HighImpactAppendStatus.APPENDED: HighImpactRequestCreateStatus.CREATED,
                HighImpactAppendStatus.ALREADY_PRESENT: (
                    HighImpactRequestCreateStatus.ALREADY_PRESENT
                ),
                HighImpactAppendStatus.PROJECT_NOT_FOUND: (
                    HighImpactRequestCreateStatus.PROJECT_NOT_FOUND
                ),
                HighImpactAppendStatus.VERSION_CONFLICT: (
                    HighImpactRequestCreateStatus.VERSION_CONFLICT
                ),
            }
            if appended.status is not HighImpactAppendStatus.APPENDED:
                if appended.status is HighImpactAppendStatus.ALREADY_PRESENT:
                    await unit_of_work.commit()
                return HighImpactRequestCreateResult(
                    status_map[appended.status],
                    appended.operation,
                )

            operation = appended.operation
            if operation is None:
                raise RuntimeError("appended high-impact operation is missing")
            latest_gate = await unit_of_work.gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.HIGH_IMPACT_OPERATION,
            )
            if latest_gate is not None and latest_gate.artifact != _gate_artifact(operation):
                stale = mark_human_gate_stale(
                    latest_gate,
                    current_artifact=_gate_artifact(operation),
                    occurred_at=self._clock(),
                    event_id=self._uuid_factory(),
                )
                if stale.status is HumanGateTransitionStatus.APPLIED:
                    if stale.event is None:
                        raise RuntimeError("stale Gate 7 transition is missing its event")
                    await unit_of_work.gates.save_transition(
                        previous_gate=latest_gate,
                        updated_gate=stale.gate,
                        event=stale.event,
                    )
            await unit_of_work.commit()
            return HighImpactRequestCreateResult(
                HighImpactRequestCreateStatus.CREATED,
                operation,
            )

    async def submit_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        expected_reference: HighImpactOperationReference,
    ) -> HighImpactGateSubmissionResult:
        async with self._unit_of_work_factory(owner_user_id=owner_user_id) as unit_of_work:
            operation = await unit_of_work.operations.current(project_id=project_id)
            mismatch = _reference_mismatch(operation, expected_reference)
            if mismatch is not None:
                return HighImpactGateSubmissionResult(mismatch, operation, None, None)
            if operation is None:
                raise RuntimeError("matched high-impact operation is missing")
            classification = operation.classification.classification
            if classification is HighImpactClassification.FORBIDDEN_BY_POLICY:
                return HighImpactGateSubmissionResult(
                    HighImpactGateSubmissionStatus.FORBIDDEN_BY_POLICY,
                    operation,
                    None,
                    None,
                )
            if classification is HighImpactClassification.ALLOWED_WITHOUT_APPROVAL:
                return HighImpactGateSubmissionResult(
                    HighImpactGateSubmissionStatus.APPROVAL_NOT_REQUIRED,
                    operation,
                    None,
                    None,
                )

            latest = await unit_of_work.gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.HIGH_IMPACT_OPERATION,
            )
            artifact = _gate_artifact(operation)
            if latest is not None and latest.artifact == artifact:
                status_value = (
                    HighImpactGateSubmissionStatus.ALREADY_APPROVED
                    if latest.status is HumanGateStatus.APPROVED
                    else HighImpactGateSubmissionStatus.ALREADY_PENDING
                )
                return HighImpactGateSubmissionResult(
                    status_value,
                    operation,
                    latest,
                    None,
                )
            iteration = 1 if latest is None else latest.iteration + 1
            if iteration > self._max_iterations:
                return HighImpactGateSubmissionResult(
                    HighImpactGateSubmissionStatus.ITERATION_LIMIT_REACHED,
                    operation,
                    latest,
                    None,
                )
            gate = create_human_gate(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.HIGH_IMPACT_OPERATION,
                artifact=artifact,
                iteration=iteration,
                max_iterations=self._max_iterations,
                gate_id=self._uuid_factory(),
                created_at=self._clock(),
            )
            transition = transition_human_gate(
                gate,
                action=HumanGateAction.SUBMIT,
                actor_user_id=owner_user_id,
                occurred_at=self._clock(),
                event_id=self._uuid_factory(),
            )
            if transition.status is not HumanGateTransitionStatus.APPLIED:
                return HighImpactGateSubmissionResult(
                    HighImpactGateSubmissionStatus.INVALID_TRANSITION,
                    operation,
                    gate,
                    None,
                    transition.issue,
                )
            if transition.event is None:
                raise RuntimeError("Gate 7 submission transition is missing its event")
            persisted_gate = await unit_of_work.gates.add_with_event(
                gate=transition.gate,
                event=transition.event,
            )
            await unit_of_work.commit()
            return HighImpactGateSubmissionResult(
                HighImpactGateSubmissionStatus.SUBMITTED,
                operation,
                persisted_gate,
                transition.event,
            )

    async def decide_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        expected_reference: HighImpactOperationReference,
        action: HumanGateAction,
        reason: str | None = None,
    ) -> HighImpactGateDecisionResult:
        async with self._unit_of_work_factory(owner_user_id=owner_user_id) as unit_of_work:
            operation = await unit_of_work.operations.current(project_id=project_id)
            mismatch = _decision_reference_mismatch(operation, expected_reference)
            if mismatch is not None:
                return HighImpactGateDecisionResult(mismatch, operation, None, None)
            if operation is None:
                raise RuntimeError("matched high-impact operation is missing")
            classification = operation.classification.classification
            if classification is HighImpactClassification.FORBIDDEN_BY_POLICY:
                return HighImpactGateDecisionResult(
                    HighImpactGateDecisionStatus.FORBIDDEN_BY_POLICY,
                    operation,
                    None,
                    None,
                )
            if classification is HighImpactClassification.ALLOWED_WITHOUT_APPROVAL:
                return HighImpactGateDecisionResult(
                    HighImpactGateDecisionStatus.APPROVAL_NOT_REQUIRED,
                    operation,
                    None,
                    None,
                )
            gate = await unit_of_work.gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.HIGH_IMPACT_OPERATION,
            )
            if gate is None:
                return HighImpactGateDecisionResult(
                    HighImpactGateDecisionStatus.GATE_NOT_FOUND,
                    operation,
                    None,
                    None,
                )
            if gate.artifact != _gate_artifact(operation):
                return HighImpactGateDecisionResult(
                    HighImpactGateDecisionStatus.STALE_REQUEST,
                    operation,
                    gate,
                    None,
                )
            transition = transition_human_gate(
                gate,
                action=action,
                actor_user_id=owner_user_id,
                occurred_at=self._clock(),
                reason=reason,
                event_id=self._uuid_factory(),
            )
            if transition.status is HumanGateTransitionStatus.NO_CHANGE:
                return HighImpactGateDecisionResult(
                    HighImpactGateDecisionStatus.NO_CHANGE,
                    operation,
                    gate,
                    None,
                )
            if transition.status is HumanGateTransitionStatus.REJECTED:
                return HighImpactGateDecisionResult(
                    HighImpactGateDecisionStatus.REJECTED,
                    operation,
                    gate,
                    None,
                    transition.issue,
                )
            if transition.event is None:
                raise RuntimeError("Gate 7 decision transition is missing its event")
            persisted = await unit_of_work.gates.save_transition(
                previous_gate=gate,
                updated_gate=transition.gate,
                event=transition.event,
            )
            await unit_of_work.commit()
            return HighImpactGateDecisionResult(
                HighImpactGateDecisionStatus.APPLIED,
                operation,
                persisted,
                transition.event,
            )

    async def current_operation(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> PersistedHighImpactOperation | None:
        async with self._unit_of_work_factory(owner_user_id=owner_user_id) as unit_of_work:
            return await unit_of_work.operations.current(project_id=project_id)

    async def history(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[PersistedHighImpactOperation, ...]:
        async with self._unit_of_work_factory(owner_user_id=owner_user_id) as unit_of_work:
            return await unit_of_work.operations.history(project_id=project_id)

    async def current_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> HumanGate | None:
        async with self._unit_of_work_factory(owner_user_id=owner_user_id) as unit_of_work:
            return await unit_of_work.gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.HIGH_IMPACT_OPERATION,
            )

    async def gate_events(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ) -> tuple[HumanGateEvent, ...]:
        async with self._unit_of_work_factory(owner_user_id=owner_user_id) as unit_of_work:
            return await unit_of_work.gates.list_events_owned(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_id=gate_id,
            )

    async def readiness(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> HighImpactReadinessResult:
        operation = await self.current_operation(
            project_id=project_id,
            owner_user_id=owner_user_id,
        )
        if operation is None:
            return HighImpactReadinessResult(
                HighImpactApprovalReadiness.REQUEST_NOT_FOUND,
                None,
                None,
            )
        classification = operation.classification.classification
        if classification is HighImpactClassification.FORBIDDEN_BY_POLICY:
            return HighImpactReadinessResult(
                HighImpactApprovalReadiness.FORBIDDEN_BY_POLICY,
                operation,
                None,
            )
        if classification is HighImpactClassification.ALLOWED_WITHOUT_APPROVAL:
            return HighImpactReadinessResult(
                HighImpactApprovalReadiness.APPROVAL_NOT_REQUIRED,
                operation,
                None,
            )
        gate = await self.current_gate(project_id=project_id, owner_user_id=owner_user_id)
        if gate is None or gate.artifact != _gate_artifact(operation):
            return HighImpactReadinessResult(
                HighImpactApprovalReadiness.OWNER_APPROVAL_REQUIRED,
                operation,
                gate,
            )
        mapping = {
            HumanGateStatus.APPROVED: HighImpactApprovalReadiness.APPROVED,
            HumanGateStatus.REJECTED: HighImpactApprovalReadiness.REJECTED,
            HumanGateStatus.REVISION_REQUESTED: (HighImpactApprovalReadiness.REVISION_REQUESTED),
            HumanGateStatus.PAUSED: HighImpactApprovalReadiness.PAUSED,
            HumanGateStatus.PAUSED_NEEDS_HUMAN: HighImpactApprovalReadiness.PAUSED,
            HumanGateStatus.CANCELLED: HighImpactApprovalReadiness.CANCELLED,
            HumanGateStatus.STALE: HighImpactApprovalReadiness.STALE,
        }
        return HighImpactReadinessResult(
            mapping.get(gate.status, HighImpactApprovalReadiness.OWNER_APPROVAL_REQUIRED),
            operation,
            gate,
        )


def _gate_artifact(operation: PersistedHighImpactOperation) -> GateArtifactReference:
    version = operation.version
    return GateArtifactReference(
        project_id=version.project_id,
        gate_type=HumanGateType.HIGH_IMPACT_OPERATION,
        artifact_id=version.id,
        version=version.version_number,
        content_hash=version.content_hash,
    )


def _reference_mismatch(
    operation: PersistedHighImpactOperation | None,
    expected: HighImpactOperationReference,
) -> HighImpactGateSubmissionStatus | None:
    if operation is None:
        return HighImpactGateSubmissionStatus.REQUEST_NOT_FOUND
    if operation.version.reference != expected:
        return HighImpactGateSubmissionStatus.STALE_REQUEST
    return None


def _decision_reference_mismatch(
    operation: PersistedHighImpactOperation | None,
    expected: HighImpactOperationReference,
) -> HighImpactGateDecisionStatus | None:
    if operation is None:
        return HighImpactGateDecisionStatus.REQUEST_NOT_FOUND
    if operation.version.reference != expected:
        return HighImpactGateDecisionStatus.STALE_REQUEST
    return None
