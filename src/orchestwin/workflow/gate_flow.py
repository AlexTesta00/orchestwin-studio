from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

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
    next_human_gate_iteration,
    transition_human_gate,
)
from orchestwin.workflow.repository import HumanGateRepository

Clock = Callable[[], datetime]
UuidFactory = Callable[[], UUID]


@dataclass(frozen=True, slots=True)
class GateOutcomes:
    submission: Callable[..., Any]
    submission_status: type[StrEnum]
    new_artifact_required: StrEnum
    decision: Callable[..., Any]
    decision_status: type[StrEnum]


def current_time(clock: Clock, message: str, *, by_offset: bool = False) -> datetime:
    timestamp = clock()

    if (timestamp.utcoffset() if by_offset else timestamp.tzinfo) is None:
        raise ValueError(message)

    return timestamp


def gate_is_currently_approved[Version](
    gate: HumanGate | None,
    version: Version | None,
    reference: Callable[[Version], GateArtifactReference],
) -> bool:
    if gate is None or version is None:
        return False

    return gate.status is HumanGateStatus.APPROVED and gate.artifact == reference(version)


async def latest_gate(
    unit_of_work: AbstractAsyncContextManager[Any],
    gate_type: HumanGateType,
    *,
    project_id: UUID,
    owner_user_id: UUID,
) -> HumanGate | None:
    async with unit_of_work as unit:
        return await unit.gates.get_latest_owned_for_update(
            project_id=project_id, owner_user_id=owner_user_id, gate_type=gate_type
        )


async def gate_history(
    unit_of_work: AbstractAsyncContextManager[Any],
    *,
    project_id: UUID,
    owner_user_id: UUID,
    gate_id: UUID,
) -> tuple[HumanGateEvent, ...]:
    async with unit_of_work as unit:
        return await unit.gates.list_events_owned(
            project_id=project_id, owner_user_id=owner_user_id, gate_id=gate_id
        )


async def resubmit_existing(
    gates: HumanGateRepository,
    gate: HumanGate,
    *,
    owner_user_id: UUID,
    occurred_at: datetime,
    event_id_factory: UuidFactory,
    outcomes: GateOutcomes,
) -> Any:
    result, statuses = outcomes.submission, outcomes.submission_status

    if gate.status is HumanGateStatus.PENDING_APPROVAL:
        return result(status=statuses.ALREADY_PENDING, gate=gate)

    if gate.status is HumanGateStatus.APPROVED:
        return result(status=statuses.ALREADY_APPROVED, gate=gate)

    if gate.status is HumanGateStatus.DRAFT:
        submitted = transition_human_gate(
            gate,
            action=HumanGateAction.SUBMIT,
            actor_user_id=owner_user_id,
            occurred_at=occurred_at,
            event_id=event_id_factory(),
        )

        if submitted.status is not HumanGateTransitionStatus.APPLIED or submitted.event is None:
            return result(status=statuses.TRANSITION_REJECTED, gate=gate, issue=submitted.issue)

        persisted = await gates.save_transition(
            previous_gate=gate, updated_gate=submitted.gate, event=submitted.event
        )
        return result(status=statuses.SUBMITTED, gate=persisted, events=(submitted.event,))

    if gate.status in {
        HumanGateStatus.PAUSED,
        HumanGateStatus.CANCELLED,
        HumanGateStatus.PAUSED_NEEDS_HUMAN,
    }:
        return result(status=statuses.GATE_BLOCKED, gate=gate)

    return result(status=outcomes.new_artifact_required, gate=gate)


async def submit_artifact(
    gates: HumanGateRepository,
    artifact: GateArtifactReference,
    *,
    project_id: UUID,
    owner_user_id: UUID,
    occurred_at: datetime,
    gate_id_factory: UuidFactory,
    event_id_factory: UuidFactory,
    outcomes: GateOutcomes,
) -> Any:
    result, statuses = outcomes.submission, outcomes.submission_status
    latest = await gates.get_latest_owned_for_update(
        project_id=project_id, owner_user_id=owner_user_id, gate_type=artifact.gate_type
    )

    if latest is not None and latest.artifact == artifact:
        return await resubmit_existing(
            gates,
            latest,
            owner_user_id=owner_user_id,
            occurred_at=occurred_at,
            event_id_factory=event_id_factory,
            outcomes=outcomes,
        )

    stale_events: tuple[HumanGateEvent, ...] = ()
    iteration, max_iterations = 1, DEFAULT_GATE_ITERATION_LIMIT

    if latest is not None:
        if latest.status in {HumanGateStatus.CANCELLED, HumanGateStatus.PAUSED_NEEDS_HUMAN}:
            return result(status=statuses.GATE_BLOCKED, gate=latest)

        if latest.status is not HumanGateStatus.STALE:
            stale = mark_human_gate_stale(
                latest,
                current_artifact=artifact,
                occurred_at=occurred_at,
                event_id=event_id_factory(),
            )

            if stale.status is HumanGateTransitionStatus.REJECTED:
                return result(status=statuses.TRANSITION_REJECTED, gate=latest, issue=stale.issue)

            if stale.status is HumanGateTransitionStatus.APPLIED and stale.event is not None:
                await gates.save_transition(
                    previous_gate=latest, updated_gate=stale.gate, event=stale.event
                )
                stale_events = (stale.event,)
                latest = stale.gate

        budget = next_human_gate_iteration(
            latest,
            await gates.list_events_owned(
                project_id=project_id, owner_user_id=owner_user_id, gate_id=latest.id
            ),
        )

        if budget is None:
            return result(status=statuses.ITERATION_LIMIT_REACHED, gate=latest, events=stale_events)

        iteration, max_iterations = budget

    draft = create_human_gate(
        gate_id=gate_id_factory(),
        project_id=project_id,
        owner_user_id=owner_user_id,
        gate_type=artifact.gate_type,
        artifact=artifact,
        iteration=iteration,
        max_iterations=max_iterations,
        created_at=occurred_at,
    )
    submitted = transition_human_gate(
        draft,
        action=HumanGateAction.SUBMIT,
        actor_user_id=owner_user_id,
        occurred_at=occurred_at,
        event_id=event_id_factory(),
    )

    if submitted.status is not HumanGateTransitionStatus.APPLIED or submitted.event is None:
        return result(
            status=statuses.TRANSITION_REJECTED,
            gate=draft,
            events=stale_events,
            issue=submitted.issue,
        )

    persisted = await gates.add_with_event(gate=submitted.gate, event=submitted.event)
    return result(
        status=statuses.SUBMITTED, gate=persisted, events=(*stale_events, submitted.event)
    )


async def decide_current(
    gates: HumanGateRepository,
    artifact: GateArtifactReference,
    *,
    project_id: UUID,
    owner_user_id: UUID,
    action: HumanGateAction,
    reason: str | None,
    occurred_at: datetime,
    event_id_factory: UuidFactory,
    outcomes: GateOutcomes,
) -> Any:
    result, statuses = outcomes.decision, outcomes.decision_status
    gate = await gates.get_latest_owned_for_update(
        project_id=project_id, owner_user_id=owner_user_id, gate_type=artifact.gate_type
    )

    if gate is None:
        return result(status=statuses.GATE_NOT_FOUND)

    if action is HumanGateAction.SUBMIT:
        return result(
            status=statuses.REJECTED, gate=gate, issue=HumanGateIssueCode.INVALID_TRANSITION
        )

    if gate.artifact != artifact:
        stale = mark_human_gate_stale(
            gate, current_artifact=artifact, occurred_at=occurred_at, event_id=event_id_factory()
        )

        if stale.status is HumanGateTransitionStatus.APPLIED and stale.event is not None:
            await gates.save_transition(
                previous_gate=gate, updated_gate=stale.gate, event=stale.event
            )
            return result(status=statuses.ARTIFACT_STALE, gate=stale.gate, event=stale.event)

        if stale.status is HumanGateTransitionStatus.NO_CHANGE:
            return result(status=statuses.ARTIFACT_STALE, gate=gate)

        return result(status=statuses.REJECTED, gate=gate, issue=stale.issue)

    transition = transition_human_gate(
        gate,
        action=action,
        actor_user_id=owner_user_id,
        occurred_at=occurred_at,
        reason=reason,
        event_id=event_id_factory(),
    )

    if transition.status is not HumanGateTransitionStatus.APPLIED or transition.event is None:
        return result(status=statuses.REJECTED, gate=gate, issue=transition.issue)

    persisted = await gates.save_transition(
        previous_gate=gate, updated_gate=transition.gate, event=transition.event
    )
    return result(status=statuses.APPLIED, gate=persisted, event=transition.event)
