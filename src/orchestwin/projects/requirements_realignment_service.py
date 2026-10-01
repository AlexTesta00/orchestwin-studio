from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID, uuid4

from orchestwin.projects.requirements_application import RequirementsVersionAppendStatus
from orchestwin.projects.requirements_realignment import (
    realigned_requirements_version,
    realignment_issue,
    requirements_are_aligned,
)
from orchestwin.projects.requirements_revisions import RequirementsSpecificationDiff
from orchestwin.projects.requirements_specifications import RequirementsSpecificationVersion
from orchestwin.twins.user_modeling_gate import user_modeling_gate_is_currently_approved
from orchestwin.twins.user_twins import UserModelingSnapshotVersion
from orchestwin.workflow.gates import HumanGate


class RequirementsRealignmentFailure(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class RequirementsAlignment:
    aligned: bool
    issue: str | None
    requirements_version_number: int | None
    snapshot_version_number: int | None
    twins_approved: bool


class RealignmentSpecificationRepository(Protocol):
    async def current(self, *, project_id: UUID) -> RequirementsSpecificationVersion | None: ...

    async def get_current_owned_for_update(
        self, *, project_id: UUID, owner_user_id: UUID
    ) -> RequirementsSpecificationVersion | None: ...

    async def append(
        self, version: RequirementsSpecificationVersion
    ) -> RequirementsVersionAppendStatus: ...


class RealignmentDiffRepository(Protocol):
    async def current_proposed(
        self, *, project_id: UUID, base_version_id: UUID
    ) -> RequirementsSpecificationDiff | None: ...


class RequirementsRealignmentUnitOfWork(Protocol):
    specifications: RealignmentSpecificationRepository
    diffs: RealignmentDiffRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


class RequirementsRealignmentUnitOfWorkFactory(Protocol):
    def __call__(self, *, owner_user_id: UUID) -> RequirementsRealignmentUnitOfWork: ...


class RealignmentSnapshotQueries(Protocol):
    async def current_snapshot(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> UserModelingSnapshotVersion | None: ...


class RealignmentGateQueries(Protocol):
    async def current_gate(self, *, project_id: UUID, owner_user_id: UUID) -> HumanGate | None: ...


class RealignmentContextQueries(Protocol):
    async def snapshot_context_is_current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        snapshot: UserModelingSnapshotVersion | None,
    ) -> bool: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _issue(
    current: RequirementsSpecificationVersion | None,
    snapshot: UserModelingSnapshotVersion | None,
    *,
    twins_approved: bool,
    revision_pending: bool,
) -> str | None:
    if current is None:
        return "REQUIREMENTS_NOT_FOUND"
    if snapshot is None:
        return "USER_TWINS_REQUIRED"
    if not twins_approved:
        return "USER_TWINS_APPROVAL_REQUIRED"
    issue = realignment_issue(current.specification, snapshot)
    if issue is not None:
        return issue.value
    if revision_pending:
        return "REQUIREMENTS_REVISION_PENDING"
    return None


async def _revision_pending(
    uow: RequirementsRealignmentUnitOfWork,
    *,
    project_id: UUID,
    current: RequirementsSpecificationVersion | None,
) -> bool:
    if current is None:
        return False
    proposed = await uow.diffs.current_proposed(project_id=project_id, base_version_id=current.id)
    return proposed is not None


class RequirementsRealignmentService:
    def __init__(
        self,
        *,
        uow_factory: RequirementsRealignmentUnitOfWorkFactory,
        user_modeling_queries: RealignmentSnapshotQueries,
        user_modeling_gates: RealignmentGateQueries,
        user_modeling_context: RealignmentContextQueries | None = None,
        clock: Callable[[], datetime] = _utc_now,
        uuid_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._uow_factory = uow_factory
        self._user_modeling_queries = user_modeling_queries
        self._user_modeling_gates = user_modeling_gates
        self._user_modeling_context = user_modeling_context
        self._clock = clock
        self._uuid_factory = uuid_factory

    async def status(self, *, owner_user_id: UUID, project_id: UUID) -> RequirementsAlignment:
        snapshot, twins_approved = await self._twins(
            owner_user_id=owner_user_id, project_id=project_id
        )
        async with self._uow_factory(owner_user_id=owner_user_id) as uow:
            current = await uow.specifications.current(project_id=project_id)
            revision_pending = await _revision_pending(uow, project_id=project_id, current=current)
        return RequirementsAlignment(
            aligned=(
                current is not None
                and snapshot is not None
                and requirements_are_aligned(current.specification, snapshot)
            ),
            issue=_issue(
                current,
                snapshot,
                twins_approved=twins_approved,
                revision_pending=revision_pending,
            ),
            requirements_version_number=None if current is None else current.version_number,
            snapshot_version_number=None if snapshot is None else snapshot.version_number,
            twins_approved=twins_approved,
        )

    async def realign(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> RequirementsSpecificationVersion:
        snapshot, twins_approved = await self._twins(
            owner_user_id=owner_user_id, project_id=project_id
        )
        async with self._uow_factory(owner_user_id=owner_user_id) as uow:
            current = await uow.specifications.get_current_owned_for_update(
                project_id=project_id, owner_user_id=owner_user_id
            )
            issue = _issue(
                current,
                snapshot,
                twins_approved=twins_approved,
                revision_pending=await _revision_pending(
                    uow, project_id=project_id, current=current
                ),
            )
            if issue is not None or current is None or snapshot is None:
                raise RequirementsRealignmentFailure(issue or "REQUIREMENTS_NOT_FOUND")
            version = realigned_requirements_version(
                current,
                snapshot,
                version_id=self._uuid_factory(),
                created_by_user_id=owner_user_id,
                created_at=self._clock(),
            )
            status = await uow.specifications.append(version)
            if status is not RequirementsVersionAppendStatus.APPENDED:
                raise RequirementsRealignmentFailure("PERSISTENCE_REJECTED")
            await uow.commit()
        return version

    async def _twins(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> tuple[UserModelingSnapshotVersion | None, bool]:
        snapshot = await self._user_modeling_queries.current_snapshot(
            owner_user_id=owner_user_id, project_id=project_id
        )
        if snapshot is None:
            return None, False
        gate = await self._user_modeling_gates.current_gate(
            project_id=project_id, owner_user_id=owner_user_id
        )
        if not user_modeling_gate_is_currently_approved(gate, snapshot):
            return snapshot, False
        if self._user_modeling_context is None:
            return snapshot, True
        return snapshot, await self._user_modeling_context.snapshot_context_is_current(
            owner_user_id=owner_user_id, project_id=project_id, snapshot=snapshot
        )


__all__ = [
    "RealignmentContextQueries",
    "RealignmentDiffRepository",
    "RealignmentGateQueries",
    "RealignmentSnapshotQueries",
    "RealignmentSpecificationRepository",
    "RequirementsAlignment",
    "RequirementsRealignmentFailure",
    "RequirementsRealignmentService",
    "RequirementsRealignmentUnitOfWork",
    "RequirementsRealignmentUnitOfWorkFactory",
]
