"""Persisted workflow lifecycle adapter for the normal authenticated API.

A newly created run stays DRAFT: this adapter does not start a graph, execute
models or containers, approve gates, or assert a formal case result.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import cast
from uuid import UUID

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import JsonValue
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.api.workflow_runs import (
    WorkflowRunApiCommandResult,
    WorkflowRunApiStatus,
    WorkflowRunCreateCommand,
    WorkflowRunLifecycleCommand,
)
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.projects.persistence.repositories import SqlAlchemyProjectRepository
from orchestwin.workflow.checkpoints import (
    WorkflowCheckpointRestoreStatus,
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
from orchestwin.workflow.run_persistence import (
    SqlAlchemyWorkflowRunRepository,
    WorkflowRunRecord,
    WorkflowRunStoreStatus,
    workflow_run_record_to_domain,
)
from orchestwin.workflow.runs import WorkflowRun, WorkflowRunStatus, create_workflow_run

_COMMAND_STATUSES = {
    WorkflowLifecycleCommandStatus.APPLIED: WorkflowRunApiStatus.COMMAND_APPLIED,
    WorkflowLifecycleCommandStatus.ALREADY_APPLIED: WorkflowRunApiStatus.COMMAND_ALREADY_APPLIED,
    WorkflowLifecycleCommandStatus.RUN_NOT_FOUND: WorkflowRunApiStatus.NOT_FOUND,
    WorkflowLifecycleCommandStatus.STATE_CONFLICT: WorkflowRunApiStatus.STATE_CONFLICT,
    WorkflowLifecycleCommandStatus.ILLEGAL_STATE: WorkflowRunApiStatus.ILLEGAL_STATE,
    WorkflowLifecycleCommandStatus.AUTHORIZATION_REQUIRED: WorkflowRunApiStatus.AUTHORIZATION_REQUIRED,
}


class WorkflowRunPersistenceConflict(RuntimeError):
    """Abort the surrounding transaction if its event append cannot be persisted."""


def _response(status: WorkflowRunApiStatus, run: WorkflowRun | None) -> WorkflowRunApiCommandResult:
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
    # Resuming a paused human gate does NOT approve it or make the run RUNNING.
    if run.status is WorkflowRunStatus.WAITING_FOR_HUMAN:
        return WorkflowEventType.WAITING_FOR_HUMAN
    return WorkflowEventType.RESUMED


class SqlAlchemyWorkflowRunApiService:
    """Use existing domain transitions, scoped repositories and one transaction per command."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_run(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        command: WorkflowRunCreateCommand,
    ) -> WorkflowRunApiCommandResult:
        _require_aware(command.created_at)
        async with self._session_factory() as session, session.begin():
            # Serialize creation against project archival and concurrent creation.
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
            status = (
                WorkflowRunApiStatus.RUN_CREATED
                if stored.status is WorkflowRunStoreStatus.CREATED
                else WorkflowRunApiStatus.COMMAND_ALREADY_APPLIED
            )
            # DRAFT creation is not a RUN_STARTED event and generates no fake checkpoint.
            return _response(status, stored.run)

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

    async def apply_lifecycle_command(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
        command: WorkflowRunLifecycleCommand,
    ) -> WorkflowRunApiCommandResult:
        _require_aware(command.occurred_at)
        if (
            isinstance(command.expected_state_version, bool)
            or not isinstance(command.expected_state_version, int)
        ) or command.expected_state_version < 1:
            raise _invalid_command()
        if (
            isinstance(command.expected_checkpoint_sequence, bool)
            or not isinstance(command.expected_checkpoint_sequence, int)
        ) or command.expected_checkpoint_sequence < 0:
            raise _invalid_command()
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
                # Locks both matching run and project until state/checkpoint/events commit.
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
                # An arbitrary UUID is not an authorization. No authority resolver is
                # connected here yet, so operational-limit resumes remain fail-closed.
                if command.kind is WorkflowLifecycleCommandKind.RESUME and (
                    previous.status is WorkflowRunStatus.PAUSED_NEEDS_HUMAN
                    or command.authorization_reference is not None
                ):
                    return _response(WorkflowRunApiStatus.AUTHORIZATION_REQUIRED, previous)
                result = await WorkflowLifecycleCommandService(runs).execute(lifecycle)
                if result.status is WorkflowLifecycleCommandStatus.APPLIED:
                    if result.run is None:
                        raise WorkflowRunPersistenceConflict("WORKFLOW_TRANSITION_INCONSISTENT")
                    await self._append_transition_events(session, previous, result.run, lifecycle)
                return _response(_COMMAND_STATUSES[result.status], result.run)
        except WorkflowRunPersistenceConflict:
            # The transaction context has already rolled back the state and checkpoint.
            raise HTTPException(409, detail={"code": "WORKFLOW_EVENT_WRITE_CONFLICT"}) from None

    async def _append_transition_events(
        self,
        session: AsyncSession,
        previous: WorkflowRun,
        run: WorkflowRun,
        command: WorkflowLifecycleCommand,
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
        for event_type in (
            _transition_event_type(command.kind, run),
            WorkflowEventType.CHECKPOINT_CREATED,
        ):
            event = create_workflow_event(
                run,
                event_type=event_type,
                sequence_number=sequence + 1,
                occurred_at=command.occurred_at,
                previous_run=previous,
                decision_id=command.command_id,
            )
            appended = await repository.append(event, expected_previous_sequence=sequence)
            if appended.status is not WorkflowEventAppendStatus.APPENDED:
                raise WorkflowRunPersistenceConflict("WORKFLOW_EVENT_APPEND_REJECTED")
            sequence += 1
