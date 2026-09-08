"""Bridge the existing User Modeling router to authenticated process-level services."""

from __future__ import annotations

from typing import Annotated, Never
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.user_modeling import (
    GateApiOutcome,
    GateApiResult,
    UserModelingApiDependencies,
    create_user_modeling_router,
)
from orchestwin.identity.domain import UserAccount
from orchestwin.twins.runtime import UserModelingServices
from orchestwin.twins.user_modeling_gate import (
    LocalUserModelingGateService,
    UserModelingGateDecisionStatus,
    UserModelingGateSubmissionStatus,
)
from orchestwin.workflow.gates import HumanGate, HumanGateAction, HumanGateEvent
from orchestwin.workflow.repository import HumanGateStateConflict


async def authenticated_modeling_owner(
    user: Annotated[UserAccount, Depends(current_user_dependency)],
) -> UUID:
    """Obtain owner scope only from the existing bearer authentication dependency."""
    return user.id


class UserModelingGateApiAdapter:
    """Translate domain outcomes without implementing or bypassing gate transitions."""

    def __init__(self, service: LocalUserModelingGateService) -> None:
        self._service = service

    async def submit(self, *, owner_user_id: UUID, project_id: UUID) -> GateApiResult:
        try:
            result = await self._service.submit(
                owner_user_id=owner_user_id,
                project_id=project_id,
            )
        except HumanGateStateConflict:
            return GateApiResult(outcome=GateApiOutcome.STALE, issue="GATE_STATE_CONFLICT")
        outcome = {
            UserModelingGateSubmissionStatus.SUBMITTED: GateApiOutcome.APPLIED,
            UserModelingGateSubmissionStatus.ALREADY_PENDING: GateApiOutcome.NO_CHANGE,
            UserModelingGateSubmissionStatus.ALREADY_APPROVED: GateApiOutcome.NO_CHANGE,
            UserModelingGateSubmissionStatus.SNAPSHOT_NOT_FOUND: GateApiOutcome.NOT_FOUND,
        }.get(result.status, GateApiOutcome.REJECTED)
        return GateApiResult(
            outcome=outcome,
            gate=result.gate,
            events=result.events,
            issue=(result.issue.value if result.issue else result.status.value)
            if outcome in {GateApiOutcome.NOT_FOUND, GateApiOutcome.REJECTED}
            else None,
        )

    async def decide(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        action: HumanGateAction,
        reason: str | None = None,
    ) -> GateApiResult:
        try:
            result = await self._service.decide(
                owner_user_id=owner_user_id,
                project_id=project_id,
                action=action,
                reason=reason,
            )
        except HumanGateStateConflict:
            return GateApiResult(outcome=GateApiOutcome.STALE, issue="GATE_STATE_CONFLICT")
        outcome = {
            UserModelingGateDecisionStatus.APPLIED: GateApiOutcome.APPLIED,
            UserModelingGateDecisionStatus.GATE_NOT_FOUND: GateApiOutcome.NOT_FOUND,
            UserModelingGateDecisionStatus.SNAPSHOT_NOT_FOUND: GateApiOutcome.NOT_FOUND,
            UserModelingGateDecisionStatus.ARTIFACT_STALE: GateApiOutcome.STALE,
            UserModelingGateDecisionStatus.REJECTED: GateApiOutcome.REJECTED,
        }[result.status]
        return GateApiResult(
            outcome=outcome,
            gate=result.gate,
            events=() if result.event is None else (result.event,),
            issue=(result.issue.value if result.issue else result.status.value)
            if outcome is not GateApiOutcome.APPLIED
            else None,
        )

    async def current_gate(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> HumanGate | None:
        return await self._service.current_gate(
            owner_user_id=owner_user_id,
            project_id=project_id,
        )

    async def gate_events(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[HumanGateEvent, ...]:
        gate = await self.current_gate(owner_user_id=owner_user_id, project_id=project_id)
        if gate is None:
            return ()
        return await self._service.gate_events(
            owner_user_id=owner_user_id,
            project_id=project_id,
            gate_id=gate.id,
        )


class _UnavailableUserModelingPort:
    """Keep routes registered when credentials are absent; never supply fabricated results."""

    async def unavailable(self, **_arguments: object) -> Never:
        raise HTTPException(
            status_code=503,
            detail={"code": "USER_MODELING_SERVICE_UNAVAILABLE"},
        )

    propose_personas = unavailable
    decide_persona = unavailable
    generate_grounded_snapshot = unavailable
    propose_revision = unavailable
    decide_revision = unavailable
    current_snapshot = unavailable
    snapshot_history = unavailable
    get_diff = unavailable
    submit = unavailable
    decide = unavailable
    current_gate = unavailable
    gate_events = unavailable


def create_runtime_user_modeling_router(services: UserModelingServices | None) -> APIRouter:
    """Mount the existing HTTP contract using concrete services and authenticated owner IDs."""
    if services is None:
        unavailable = _UnavailableUserModelingPort()
        dependencies = UserModelingApiDependencies(
            commands=unavailable,
            revisions=unavailable,
            gates=unavailable,
            queries=unavailable,
            owner_user_id_dependency=authenticated_modeling_owner,
        )
    else:
        dependencies = UserModelingApiDependencies(
            commands=services.commands,
            revisions=services.revisions,
            queries=services.queries,
            gates=UserModelingGateApiAdapter(services.gates),
            owner_user_id_dependency=authenticated_modeling_owner,
        )
    return create_user_modeling_router(dependencies)
