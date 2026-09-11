"""Persisted workflow lifecycle and governed progression API adapter.

Draft creation remains side-effect free. Explicit start, advance, and gate-resume
commands execute through the durable LangGraph orchestration shell, then persist
the authoritative application checkpoint and ordered workflow events.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import JsonValue
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.api.workflow_runs import (
    WorkflowRunAdvanceCommand,
    WorkflowRunApiCommandResult,
    WorkflowRunApiStatus,
    WorkflowRunCreateCommand,
    WorkflowRunGateResumeCommand,
    WorkflowRunLifecycleCommand,
    WorkflowRunStartCommand,
)
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.projects.persistence.repositories import SqlAlchemyProjectRepository
from orchestwin.workflow.checkpoints import (
    WorkflowCheckpointRestoreStatus,
    create_workflow_checkpoint,
    restore_workflow_checkpoint,
)
from orchestwin.workflow.commands import (
    WorkflowLifecycleCommand,
    WorkflowLifecycleCommandKind,
    WorkflowLifecycleCommandService,
    WorkflowLifecycleCommandStatus,
)
from orchestwin.workflow.event_persistence import (
    SqlAlchemyWorkflowEventRepository,
    WorkflowEventAppendStatus,
    WorkflowEventRecord,
)
from orchestwin.workflow.events import WorkflowEvent, WorkflowEventType, create_workflow_event
from orchestwin.workflow.gates import HumanGateStatus, HumanGateType
from orchestwin.workflow.langgraph_checkpointer import SqlAlchemyLangGraphCheckpointStore
from orchestwin.workflow.persistence.models import HumanGateEventRecord, HumanGateRecord
from orchestwin.workflow.progression_graph import (
    DurableWorkflowGraphProgression,
    WorkflowGraphExecutionConflict,
    WorkflowGraphProgressionResult,
    WorkflowGraphStateConflict,
)
from orchestwin.workflow.routing import (
    WorkflowTransitionIssueCode,
    WorkflowTransitionResult,
    WorkflowTransitionStatus,
    advance_workflow_run,
    resume_after_human_gate,
    start_workflow_run,
)
from orchestwin.workflow.run_persistence import (
    SqlAlchemyWorkflowRunRepository,
    WorkflowRunRecord,
    WorkflowRunStoreStatus,
    workflow_run_record_to_domain,
)
from orchestwin.workflow.runs import (
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowStage,
    create_workflow_run,
)

_COMMAND_STATUSES = {
    WorkflowLifecycleCommandStatus.APPLIED: WorkflowRunApiStatus.COMMAND_APPLIED,
    WorkflowLifecycleCommandStatus.ALREADY_APPLIED: WorkflowRunApiStatus.COMMAND_ALREADY_APPLIED,
    WorkflowLifecycleCommandStatus.RUN_NOT_FOUND: WorkflowRunApiStatus.NOT_FOUND,
    WorkflowLifecycleCommandStatus.STATE_CONFLICT: WorkflowRunApiStatus.STATE_CONFLICT,
    WorkflowLifecycleCommandStatus.ILLEGAL_STATE: WorkflowRunApiStatus.ILLEGAL_STATE,
    WorkflowLifecycleCommandStatus.AUTHORIZATION_REQUIRED: (
        WorkflowRunApiStatus.AUTHORIZATION_REQUIRED
    ),
}

_GATE_TYPE_BY_STAGE = {
    WorkflowStage.BRIEF_APPROVAL: HumanGateType.PROJECT_BRIEF,
    WorkflowStage.TEAM_APPROVAL: HumanGateType.AGENT_TEAM,
    WorkflowStage.USER_TWIN_APPROVAL: HumanGateType.USER_MODELING,
    WorkflowStage.REQUIREMENTS_APPROVAL: HumanGateType.REQUIREMENTS,
    WorkflowStage.DESIGN_APPROVAL: HumanGateType.DESIGN,
    WorkflowStage.ARCHITECTURE_APPROVAL: HumanGateType.ARCHITECTURE,
    WorkflowStage.FINAL_APPROVAL: HumanGateType.FINAL_OUTPUT,
}

Clock = Callable[[], datetime]


class WorkflowRunPersistenceConflict(RuntimeError):
    """Abort an application transaction if checkpoint/event persistence diverges."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _response(
    status: WorkflowRunApiStatus,
    run: WorkflowRun | None,
) -> WorkflowRunApiCommandResult:
    return WorkflowRunApiCommandResult(
        status=status,
        snapshot=None if run is None else cast(dict[str, JsonValue], run.to_snapshot()),
        message=status.value,
    )


def _invalid_command() -> HTTPException:
    return HTTPException(status_code=422, detail={"code": "WORKFLOW_COMMAND_INVALID"})


def _require_aware(timestamp: datetime) -> None:
    if not isinstance(timestamp, datetime) or timestamp.utcoffset() is None:
        raise _invalid_command()


def _validate_expected_state(*, state_version: int, checkpoint_sequence: int) -> None:
    if isinstance(state_version, bool) or not isinstance(state_version, int) or state_version < 1:
        raise _invalid_command()
    if (
        isinstance(checkpoint_sequence, bool)
        or not isinstance(checkpoint_sequence, int)
        or checkpoint_sequence < 0
    ):
        raise _invalid_command()


def _state_matches(
    run: WorkflowRun,
    *,
    expected_state_version: int,
    expected_checkpoint_sequence: int,
) -> bool:
    return (
        run.state_version == expected_state_version
        and run.checkpoint_sequence == expected_checkpoint_sequence
    )


def _owned_runs(owner_user_id: UUID):
    """Do not expose runs of another owner or an archived project."""
    return (
        select(WorkflowRunRecord)
        .join(ProjectRecord, ProjectRecord.id == WorkflowRunRecord.project_id)
        .where(
            WorkflowRunRecord.owner_user_id == owner_user_id,
            ProjectRecord.owner_user_id == owner_user_id,
            ProjectRecord.archived_at.is_(None),
        )
    )


def _event_snapshot(event: WorkflowEvent) -> dict[str, JsonValue]:
    return cast(
        dict[str, JsonValue],
        {
            "id": str(event.id),
            "run_id": str(event.run_id),
            "project_id": str(event.project_id),
            "owner_user_id": str(event.owner_user_id),
            "sequence_number": event.sequence_number,
            "event_type": event.event_type.value,
            "occurred_at": event.occurred_at.isoformat(),
            "payload": event.payload.to_snapshot(),
            "payload_hash": event.payload_hash,
        },
    )


def _transition_event_type(
    kind: WorkflowLifecycleCommandKind,
    run: WorkflowRun,
) -> WorkflowEventType:
    if kind is WorkflowLifecycleCommandKind.PAUSE:
        return WorkflowEventType.PAUSED
    if kind is WorkflowLifecycleCommandKind.CANCEL:
        return WorkflowEventType.CANCELLED
    if run.status is WorkflowRunStatus.WAITING_FOR_HUMAN:
        return WorkflowEventType.WAITING_FOR_HUMAN
    return WorkflowEventType.RESUMED


def _progression_status(result: WorkflowTransitionResult) -> WorkflowRunApiStatus:
    if result.status is WorkflowTransitionStatus.APPLIED:
        return WorkflowRunApiStatus.COMMAND_APPLIED
    if result.status is WorkflowTransitionStatus.NO_CHANGE:
        return WorkflowRunApiStatus.COMMAND_ALREADY_APPLIED
    if result.issue in {
        WorkflowTransitionIssueCode.TIMESTAMP_NOT_AWARE,
        WorkflowTransitionIssueCode.TIMESTAMP_OUT_OF_ORDER,
    }:
        return WorkflowRunApiStatus.STATE_CONFLICT
    return WorkflowRunApiStatus.ILLEGAL_STATE


def _advance_event_types(run: WorkflowRun) -> tuple[WorkflowEventType, ...]:
    events = [WorkflowEventType.STAGE_CHANGED]
    if run.status is WorkflowRunStatus.WAITING_FOR_HUMAN:
        events.append(WorkflowEventType.WAITING_FOR_HUMAN)
    events.append(WorkflowEventType.CHECKPOINT_CREATED)
    return tuple(events)


async def _latest_gate_for_stage(
    session: AsyncSession,
    *,
    project_id: UUID,
    owner_user_id: UUID,
    stage: WorkflowStage,
) -> HumanGateRecord | None:
    gate_type = _GATE_TYPE_BY_STAGE.get(stage)
    if gate_type is None:
        return None
    return await session.scalar(
        select(HumanGateRecord)
        .where(
            HumanGateRecord.project_id == project_id,
            HumanGateRecord.owner_user_id == owner_user_id,
            HumanGateRecord.gate_type == gate_type.value,
        )
        .order_by(
            HumanGateRecord.iteration.desc(),
            HumanGateRecord.created_at.desc(),
            HumanGateRecord.id.desc(),
        )
        .limit(1)
        .with_for_update()
    )


async def _gate_is_enterable(
    session: AsyncSession,
    *,
    project_id: UUID,
    owner_user_id: UUID,
    stage: WorkflowStage,
    gate_id: UUID,
) -> bool:
    """Require the latest exact owner gate to be pending or already approved."""
    gate = await _latest_gate_for_stage(
        session,
        project_id=project_id,
        owner_user_id=owner_user_id,
        stage=stage,
    )
    return (
        gate is not None
        and gate.id == gate_id
        and gate.status
        in {
            HumanGateStatus.PENDING_APPROVAL.value,
            HumanGateStatus.APPROVED.value,
        }
    )


async def _approved_gate_decision_exists(
    session: AsyncSession,
    *,
    project_id: UUID,
    owner_user_id: UUID,
    stage: WorkflowStage,
    gate_id: UUID,
    decision_id: UUID,
) -> bool:
    """Verify the latest exact gate and its latest append-only APPROVE event."""
    gate_type = _GATE_TYPE_BY_STAGE.get(stage)
    if gate_type is None:
        return False
    gate = await _latest_gate_for_stage(
        session,
        project_id=project_id,
        owner_user_id=owner_user_id,
        stage=stage,
    )
    if (
        gate is None
        or gate.id != gate_id
        or gate.status != HumanGateStatus.APPROVED.value
        or gate.event_sequence < 1
    ):
        return False
    approved = await session.scalar(
        select(HumanGateEventRecord.id).where(
            HumanGateEventRecord.id == decision_id,
            HumanGateEventRecord.gate_id == gate.id,
            HumanGateEventRecord.project_id == project_id,
            HumanGateEventRecord.gate_type == gate_type.value,
            HumanGateEventRecord.sequence_number == gate.event_sequence,
            HumanGateEventRecord.kind == "APPROVE",
            HumanGateEventRecord.resulting_status == HumanGateStatus.APPROVED.value,
            HumanGateEventRecord.actor_user_id == owner_user_id,
            HumanGateEventRecord.artifact_id == gate.artifact_id,
            HumanGateEventRecord.artifact_version == gate.artifact_version,
            HumanGateEventRecord.artifact_hash == gate.artifact_hash,
        )
    )
    return approved is not None


class SqlAlchemyWorkflowRunApiService:
    """Persist owner-scoped lifecycle and LangGraph progression commands."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        clock: Clock = _utc_now,
        graph_runtime: DurableWorkflowGraphProgression | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._graph_runtime = graph_runtime or DurableWorkflowGraphProgression(
            SqlAlchemyLangGraphCheckpointStore(session_factory)
        )

    def _timestamp(self) -> datetime:
        timestamp = self._clock()
        _require_aware(timestamp)
        return timestamp

    async def create_run(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        command: WorkflowRunCreateCommand,
    ) -> WorkflowRunApiCommandResult:
        _require_aware(command.created_at)
        async with self._session_factory() as session, session.begin():
            locked = await session.scalar(
                select(ProjectRecord.id)
                .where(
                    ProjectRecord.id == project_id,
                    ProjectRecord.owner_user_id == owner_user_id,
                    ProjectRecord.archived_at.is_(None),
                )
                .with_for_update()
            )
            if locked is None:
                return _response(WorkflowRunApiStatus.NOT_FOUND, None)
            project = await SqlAlchemyProjectRepository(session).get_owned(
                owner_user_id=owner_user_id,
                project_id=project_id,
            )
            if project is None:
                return _response(WorkflowRunApiStatus.NOT_FOUND, None)
            if project.mode != command.project_mode:
                raise HTTPException(409, detail={"code": "WORKFLOW_PROJECT_MODE_MISMATCH"})
            if command.created_at < project.created_at:
                raise _invalid_command()
            run = create_workflow_run(
                project_id=project_id,
                owner_user_id=owner_user_id,
                project_mode=project.mode,
                run_id=command.run_id,
                created_at=command.created_at,
            )
            stored = await SqlAlchemyWorkflowRunRepository(
                session,
                owner_user_id=owner_user_id,
            ).create(run)
            if stored.status is WorkflowRunStoreStatus.PROJECT_NOT_FOUND:
                return _response(WorkflowRunApiStatus.NOT_FOUND, None)
            if stored.status is WorkflowRunStoreStatus.STATE_CONFLICT:
                raise HTTPException(409, detail={"code": "WORKFLOW_RUN_ID_CONFLICT"})
            if stored.run is None or stored.status not in {
                WorkflowRunStoreStatus.CREATED,
                WorkflowRunStoreStatus.ALREADY_PRESENT,
            }:
                raise WorkflowRunPersistenceConflict("WORKFLOW_RUN_CREATE_INCONSISTENT")
            result_status = (
                WorkflowRunApiStatus.RUN_CREATED
                if stored.status is WorkflowRunStoreStatus.CREATED
                else WorkflowRunApiStatus.COMMAND_ALREADY_APPLIED
            )
            return _response(result_status, stored.run)

    async def list_runs(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                _owned_runs(owner_user_id)
                .where(WorkflowRunRecord.project_id == project_id)
                .order_by(WorkflowRunRecord.created_at, WorkflowRunRecord.id)
            )
            return tuple(
                cast(dict[str, JsonValue], workflow_run_record_to_domain(row).to_snapshot())
                for row in rows.all()
            )

    async def run(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
    ) -> dict[str, JsonValue] | None:
        async with self._session_factory() as session:
            run = await SqlAlchemyWorkflowRunRepository(
                session,
                owner_user_id=owner_user_id,
            ).get_owned(run_id=run_id)
            return None if run is None else cast(dict[str, JsonValue], run.to_snapshot())

    async def checkpoints(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]:
        async with self._session_factory() as session:
            repository = SqlAlchemyWorkflowRunRepository(session, owner_user_id=owner_user_id)
            run = await repository.get_owned(run_id=run_id)
            if run is None:
                return ()
            history = await repository.list_checkpoints(run_id=run_id)
            for checkpoint in history:
                restored = restore_workflow_checkpoint(
                    checkpoint,
                    expected_run_id=run.id,
                    expected_project_id=run.project_id,
                    expected_owner_user_id=owner_user_id,
                )
                if restored.status is not WorkflowCheckpointRestoreStatus.RESTORED:
                    raise WorkflowRunPersistenceConflict("WORKFLOW_CHECKPOINT_INTEGRITY_FAILED")
            return tuple(cast(dict[str, JsonValue], jsonable_encoder(asdict(cp))) for cp in history)

    async def events(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
        after_sequence: int,
        limit: int,
    ) -> tuple[dict[str, JsonValue], ...]:
        if (
            isinstance(after_sequence, bool) or not isinstance(after_sequence, int)
        ) or after_sequence < 0:
            raise _invalid_command()
        if (isinstance(limit, bool) or not isinstance(limit, int)) or not 1 <= limit <= 500:
            raise _invalid_command()
        async with self._session_factory() as session:
            run = await SqlAlchemyWorkflowRunRepository(
                session,
                owner_user_id=owner_user_id,
            ).get_owned(run_id=run_id)
            if run is None:
                return ()
            events = await SqlAlchemyWorkflowEventRepository(
                session,
                owner_user_id=owner_user_id,
            ).list_after(run_id=run_id, after_sequence=after_sequence, limit=limit)
            return tuple(_event_snapshot(event) for event in events)

    async def start_run(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
        command: WorkflowRunStartCommand,
    ) -> WorkflowRunApiCommandResult:
        _validate_expected_state(
            state_version=command.expected_state_version,
            checkpoint_sequence=command.expected_checkpoint_sequence,
        )
        timestamp = self._timestamp()
        try:
            async with self._session_factory() as session, session.begin():
                runs, previous = await self._locked_progression_run(
                    session,
                    owner_user_id=owner_user_id,
                    run_id=run_id,
                    project_id=command.project_id,
                )
                if previous is None or runs is None:
                    return _response(WorkflowRunApiStatus.NOT_FOUND, None)
                if not _state_matches(
                    previous,
                    expected_state_version=command.expected_state_version,
                    expected_checkpoint_sequence=command.expected_checkpoint_sequence,
                ):
                    return _response(WorkflowRunApiStatus.STATE_CONFLICT, previous)

                planned = start_workflow_run(previous, occurred_at=timestamp)
                if planned.status is not WorkflowTransitionStatus.APPLIED:
                    return _response(_progression_status(planned), planned.run)
                try:
                    observed = await self._graph_runtime.start(
                        run=previous,
                        occurred_at=timestamp,
                    )
                except WorkflowGraphStateConflict:
                    return _response(WorkflowRunApiStatus.STATE_CONFLICT, previous)
                self._require_graph_match(planned, observed)
                return await self._persist_progression(
                    session,
                    runs=runs,
                    previous=previous,
                    observed=observed,
                    occurred_at=timestamp,
                    event_types=(
                        WorkflowEventType.RUN_STARTED,
                        WorkflowEventType.CHECKPOINT_CREATED,
                    ),
                    decision_id=command.command_id,
                )
        except WorkflowRunPersistenceConflict:
            raise HTTPException(409, detail={"code": "WORKFLOW_EVENT_WRITE_CONFLICT"}) from None
        except WorkflowGraphExecutionConflict:
            raise HTTPException(409, detail={"code": "WORKFLOW_GRAPH_EXECUTION_CONFLICT"}) from None

    async def advance_run(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
        command: WorkflowRunAdvanceCommand,
    ) -> WorkflowRunApiCommandResult:
        _validate_expected_state(
            state_version=command.expected_state_version,
            checkpoint_sequence=command.expected_checkpoint_sequence,
        )
        timestamp = self._timestamp()
        try:
            async with self._session_factory() as session, session.begin():
                runs, previous = await self._locked_progression_run(
                    session,
                    owner_user_id=owner_user_id,
                    run_id=run_id,
                    project_id=command.project_id,
                )
                if previous is None or runs is None:
                    return _response(WorkflowRunApiStatus.NOT_FOUND, None)
                if not _state_matches(
                    previous,
                    expected_state_version=command.expected_state_version,
                    expected_checkpoint_sequence=command.expected_checkpoint_sequence,
                ):
                    return _response(WorkflowRunApiStatus.STATE_CONFLICT, previous)

                planned = advance_workflow_run(
                    previous,
                    next_stage=command.next_stage,
                    occurred_at=timestamp,
                    pending_gate_id=command.pending_gate_id,
                )
                if planned.status is not WorkflowTransitionStatus.APPLIED:
                    return _response(_progression_status(planned), planned.run)
                if planned.run.status is WorkflowRunStatus.WAITING_FOR_HUMAN and (
                    command.pending_gate_id is None
                    or not await _gate_is_enterable(
                        session,
                        project_id=command.project_id,
                        owner_user_id=owner_user_id,
                        stage=command.next_stage,
                        gate_id=command.pending_gate_id,
                    )
                ):
                    return _response(WorkflowRunApiStatus.AUTHORIZATION_REQUIRED, previous)

                try:
                    observed = await self._graph_runtime.advance(
                        run=previous,
                        next_stage=command.next_stage,
                        pending_gate_id=command.pending_gate_id,
                        occurred_at=timestamp,
                    )
                except WorkflowGraphStateConflict:
                    return _response(WorkflowRunApiStatus.STATE_CONFLICT, previous)
                self._require_graph_match(planned, observed)
                return await self._persist_progression(
                    session,
                    runs=runs,
                    previous=previous,
                    observed=observed,
                    occurred_at=timestamp,
                    event_types=_advance_event_types(observed.run),
                    decision_id=command.command_id,
                )
        except WorkflowRunPersistenceConflict:
            raise HTTPException(409, detail={"code": "WORKFLOW_EVENT_WRITE_CONFLICT"}) from None
        except WorkflowGraphExecutionConflict:
            raise HTTPException(409, detail={"code": "WORKFLOW_GRAPH_EXECUTION_CONFLICT"}) from None

    async def resume_after_gate(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
        command: WorkflowRunGateResumeCommand,
    ) -> WorkflowRunApiCommandResult:
        _validate_expected_state(
            state_version=command.expected_state_version,
            checkpoint_sequence=command.expected_checkpoint_sequence,
        )
        timestamp = self._timestamp()
        try:
            async with self._session_factory() as session, session.begin():
                runs, previous = await self._locked_progression_run(
                    session,
                    owner_user_id=owner_user_id,
                    run_id=run_id,
                    project_id=command.project_id,
                )
                if previous is None or runs is None:
                    return _response(WorkflowRunApiStatus.NOT_FOUND, None)
                if not _state_matches(
                    previous,
                    expected_state_version=command.expected_state_version,
                    expected_checkpoint_sequence=command.expected_checkpoint_sequence,
                ):
                    return _response(WorkflowRunApiStatus.STATE_CONFLICT, previous)
                if (
                    previous.status is not WorkflowRunStatus.WAITING_FOR_HUMAN
                    or previous.pending_gate_id != command.gate_id
                    or previous.current_stage not in _GATE_TYPE_BY_STAGE
                ):
                    return _response(WorkflowRunApiStatus.ILLEGAL_STATE, previous)

                planned = resume_after_human_gate(previous, occurred_at=timestamp)
                if planned.status is not WorkflowTransitionStatus.APPLIED:
                    return _response(_progression_status(planned), planned.run)
                if not await _approved_gate_decision_exists(
                    session,
                    project_id=command.project_id,
                    owner_user_id=owner_user_id,
                    stage=previous.current_stage,
                    gate_id=command.gate_id,
                    decision_id=command.decision_id,
                ):
                    return _response(WorkflowRunApiStatus.AUTHORIZATION_REQUIRED, previous)

                try:
                    observed = await self._graph_runtime.resume_gate(
                        run=previous,
                        gate_id=command.gate_id,
                        decision_id=command.decision_id,
                        occurred_at=timestamp,
                    )
                except WorkflowGraphStateConflict:
                    return _response(WorkflowRunApiStatus.STATE_CONFLICT, previous)
                self._require_graph_match(planned, observed)
                if observed.applied_decision_id != command.decision_id:
                    raise WorkflowGraphExecutionConflict(
                        "workflow graph did not apply the authorized gate decision"
                    )
                return await self._persist_progression(
                    session,
                    runs=runs,
                    previous=previous,
                    observed=observed,
                    occurred_at=timestamp,
                    event_types=(
                        WorkflowEventType.RESUMED,
                        WorkflowEventType.CHECKPOINT_CREATED,
                    ),
                    decision_id=command.decision_id,
                )
        except WorkflowRunPersistenceConflict:
            raise HTTPException(409, detail={"code": "WORKFLOW_EVENT_WRITE_CONFLICT"}) from None
        except WorkflowGraphExecutionConflict:
            raise HTTPException(409, detail={"code": "WORKFLOW_GRAPH_EXECUTION_CONFLICT"}) from None

    async def apply_lifecycle_command(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
        command: WorkflowRunLifecycleCommand,
    ) -> WorkflowRunApiCommandResult:
        _require_aware(command.occurred_at)
        _validate_expected_state(
            state_version=command.expected_state_version,
            checkpoint_sequence=command.expected_checkpoint_sequence,
        )
        try:
            lifecycle = WorkflowLifecycleCommand(
                command_id=command.command_id,
                run_id=run_id,
                project_id=command.project_id,
                owner_user_id=owner_user_id,
                kind=command.kind,
                expected_state_version=command.expected_state_version,
                expected_checkpoint_sequence=command.expected_checkpoint_sequence,
                occurred_at=command.occurred_at,
                reason=command.reason,
                authorization_reference=command.authorization_reference,
            )
        except ValueError:
            raise _invalid_command() from None
        try:
            async with self._session_factory() as session, session.begin():
                locked = await session.scalar(
                    _owned_runs(owner_user_id)
                    .where(
                        WorkflowRunRecord.id == run_id,
                        WorkflowRunRecord.project_id == command.project_id,
                    )
                    .with_for_update()
                )
                if locked is None:
                    return _response(WorkflowRunApiStatus.NOT_FOUND, None)
                runs = SqlAlchemyWorkflowRunRepository(session, owner_user_id=owner_user_id)
                previous = await runs.get_owned(run_id=run_id)
                if previous is None or previous.project_id != command.project_id:
                    return _response(WorkflowRunApiStatus.NOT_FOUND, None)
                if command.kind is WorkflowLifecycleCommandKind.RESUME and (
                    previous.status is WorkflowRunStatus.PAUSED_NEEDS_HUMAN
                    or command.authorization_reference is not None
                ):
                    return _response(WorkflowRunApiStatus.AUTHORIZATION_REQUIRED, previous)
                result = await WorkflowLifecycleCommandService(runs).execute(lifecycle)
                if result.status is WorkflowLifecycleCommandStatus.APPLIED:
                    if result.run is None:
                        raise WorkflowRunPersistenceConflict("WORKFLOW_TRANSITION_INCONSISTENT")
                    await self._append_events(
                        session,
                        previous=previous,
                        run=result.run,
                        event_types=(
                            _transition_event_type(command.kind, result.run),
                            WorkflowEventType.CHECKPOINT_CREATED,
                        ),
                        occurred_at=command.occurred_at,
                        decision_id=command.command_id,
                    )
                return _response(_COMMAND_STATUSES[result.status], result.run)
        except WorkflowRunPersistenceConflict:
            raise HTTPException(409, detail={"code": "WORKFLOW_EVENT_WRITE_CONFLICT"}) from None

    async def _locked_progression_run(
        self,
        session: AsyncSession,
        *,
        owner_user_id: UUID,
        run_id: UUID,
        project_id: UUID,
    ) -> tuple[SqlAlchemyWorkflowRunRepository | None, WorkflowRun | None]:
        # PostgreSQL renders key_share=True as FOR NO KEY UPDATE. That serializes
        # run mutations while remaining compatible with the KEY SHARE lock taken
        # when the independent LangGraph checkpoint transaction checks its FK.
        locked = await session.scalar(
            _owned_runs(owner_user_id)
            .where(
                WorkflowRunRecord.id == run_id,
                WorkflowRunRecord.project_id == project_id,
            )
            .with_for_update(key_share=True)
        )
        if locked is None:
            return None, None
        runs = SqlAlchemyWorkflowRunRepository(session, owner_user_id=owner_user_id)
        previous = await runs.get_owned(run_id=run_id)
        if previous is None or previous.project_id != project_id:
            return None, None
        return runs, previous

    @staticmethod
    def _require_graph_match(
        planned: WorkflowTransitionResult,
        observed: WorkflowGraphProgressionResult,
    ) -> None:
        if (
            observed.transition_status != WorkflowTransitionStatus.APPLIED.value
            or observed.transition_issue is not None
            or observed.run != planned.run
        ):
            raise WorkflowGraphExecutionConflict(
                "LangGraph result differs from deterministic workflow routing"
            )

    async def _persist_progression(
        self,
        session: AsyncSession,
        *,
        runs: SqlAlchemyWorkflowRunRepository,
        previous: WorkflowRun,
        observed: WorkflowGraphProgressionResult,
        occurred_at: datetime,
        event_types: tuple[WorkflowEventType, ...],
        decision_id: UUID | None,
    ) -> WorkflowRunApiCommandResult:
        history = await runs.list_checkpoints(run_id=previous.id)
        previous_checkpoint = None if not history else history[-1]
        creation = create_workflow_checkpoint(
            observed.run,
            created_at=occurred_at,
            previous_checkpoint=previous_checkpoint,
        )
        stored = await runs.save_checkpoint(
            previous_run=previous,
            creation=creation,
        )
        if stored.status is not WorkflowRunStoreStatus.UPDATED or stored.run is None:
            raise WorkflowRunPersistenceConflict("WORKFLOW_CHECKPOINT_STATE_CONFLICT")

        await self._append_events(
            session,
            previous=previous,
            run=stored.run,
            event_types=event_types,
            occurred_at=occurred_at,
            decision_id=decision_id,
        )
        return _response(WorkflowRunApiStatus.COMMAND_APPLIED, stored.run)

    async def _append_events(
        self,
        session: AsyncSession,
        *,
        previous: WorkflowRun,
        run: WorkflowRun,
        event_types: tuple[WorkflowEventType, ...],
        occurred_at: datetime,
        decision_id: UUID | None,
    ) -> None:
        sequence = (
            await session.scalar(
                select(func.max(WorkflowEventRecord.sequence_number)).where(
                    WorkflowEventRecord.run_id == run.id,
                    WorkflowEventRecord.project_id == run.project_id,
                    WorkflowEventRecord.owner_user_id == run.owner_user_id,
                )
            )
            or 0
        )
        repository = SqlAlchemyWorkflowEventRepository(session, owner_user_id=run.owner_user_id)
        for event_type in event_types:
            event = create_workflow_event(
                run,
                event_type=event_type,
                sequence_number=sequence + 1,
                occurred_at=occurred_at,
                previous_run=previous,
                decision_id=decision_id,
            )
            appended = await repository.append(event, expected_previous_sequence=sequence)
            if appended.status is not WorkflowEventAppendStatus.APPENDED:
                raise WorkflowRunPersistenceConflict("WORKFLOW_EVENT_APPEND_REJECTED")
            sequence += 1
