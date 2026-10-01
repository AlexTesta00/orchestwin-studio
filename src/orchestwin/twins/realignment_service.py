from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Final, Protocol, Self
from uuid import UUID, uuid4

from orchestwin.agents.team_gate import ProjectWorkflowReadiness
from orchestwin.twins.application import (
    GovernedUserModelingContext,
    UserModelingApplicationIssueCode,
    UserModelingGovernancePort,
    _governance_issue,
)
from orchestwin.twins.persistence.repositories import VersionAppendStatus
from orchestwin.twins.realignment import (
    UserModelingRealignment,
    realigned_user_modeling,
    user_modeling_is_aligned,
)
from orchestwin.twins.revisions import UserTwinProfileDiff
from orchestwin.twins.user_twins import UserModelingSnapshotVersion, UserTwinProfileVersion

USER_TWINS_NOT_FOUND: Final = "USER_TWINS_NOT_FOUND"
BRIEF_APPROVAL_REQUIRED: Final = "BRIEF_APPROVAL_REQUIRED"
TEAM_APPROVAL_REQUIRED: Final = "TEAM_APPROVAL_REQUIRED"
ALREADY_ALIGNED: Final = "ALREADY_ALIGNED"
USER_TWIN_REVISION_PENDING: Final = "USER_TWIN_REVISION_PENDING"
PERSISTENCE_REJECTED: Final = "PERSISTENCE_REJECTED"


class UserModelingRealignmentFailure(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class UserModelingAlignment:
    aligned: bool
    issue: str | None
    snapshot_version_number: int | None
    brief_version_number: int | None
    team_version_number: int | None


class UserModelingRealignmentSnapshotRepository(Protocol):
    async def current(self, *, project_id: UUID) -> UserModelingSnapshotVersion | None: ...

    async def append(self, version: UserModelingSnapshotVersion) -> VersionAppendStatus: ...


class UserModelingRealignmentTwinRepository(Protocol):
    async def append(self, version: UserTwinProfileVersion) -> VersionAppendStatus: ...


class UserModelingRealignmentDiffRepository(Protocol):
    async def current_proposed(
        self, *, project_id: UUID, base_snapshot_version_id: UUID, twin_id: UUID
    ) -> UserTwinProfileDiff | None: ...


class UserModelingRealignmentUnitOfWork(Protocol):
    snapshots: UserModelingRealignmentSnapshotRepository
    twins: UserModelingRealignmentTwinRepository
    diffs: UserModelingRealignmentDiffRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


class UserModelingRealignmentUnitOfWorkFactory(Protocol):
    def __call__(self, *, owner_user_id: UUID) -> UserModelingRealignmentUnitOfWork: ...


class UserModelingRealignmentTeamQueries(Protocol):
    async def readiness(
        self, *, project_id: UUID, owner_user_id: UUID
    ) -> ProjectWorkflowReadiness: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _context_issue(
    context: GovernedUserModelingContext | None,
    readiness: ProjectWorkflowReadiness,
) -> str | None:
    issue = _governance_issue(context)
    if (
        issue is UserModelingApplicationIssueCode.PROJECT_NOT_FOUND
        or readiness is ProjectWorkflowReadiness.PROJECT_NOT_FOUND
    ):
        return USER_TWINS_NOT_FOUND
    if (
        issue is UserModelingApplicationIssueCode.BRIEF_APPROVAL_REQUIRED
        or readiness is ProjectWorkflowReadiness.BRIEF_APPROVAL_REQUIRED
    ):
        return BRIEF_APPROVAL_REQUIRED
    if issue is not None or readiness is not ProjectWorkflowReadiness.READY_FOR_MAIN_WORKFLOW:
        return TEAM_APPROVAL_REQUIRED
    return None


def _blocking_issue(
    snapshot: UserModelingSnapshotVersion | None,
    context: GovernedUserModelingContext | None,
    readiness: ProjectWorkflowReadiness,
) -> str | None:
    if snapshot is None:
        return USER_TWINS_NOT_FOUND
    issue = _context_issue(context, readiness)
    if issue is None and context is not None and user_modeling_is_aligned(snapshot, context):
        return ALREADY_ALIGNED
    return issue


async def _revision_pending(
    uow: UserModelingRealignmentUnitOfWork,
    *,
    project_id: UUID,
    snapshot: UserModelingSnapshotVersion,
) -> bool:
    for version in snapshot.snapshot.twin_versions:
        proposed = await uow.diffs.current_proposed(
            project_id=project_id,
            base_snapshot_version_id=snapshot.id,
            twin_id=version.twin_id,
        )
        if proposed is not None:
            return True
    return False


async def _issue(
    uow: UserModelingRealignmentUnitOfWork,
    *,
    project_id: UUID,
    snapshot: UserModelingSnapshotVersion | None,
    context: GovernedUserModelingContext | None,
    readiness: ProjectWorkflowReadiness,
) -> str | None:
    issue = _blocking_issue(snapshot, context, readiness)
    if (
        issue is None
        and snapshot is not None
        and await _revision_pending(uow, project_id=project_id, snapshot=snapshot)
    ):
        return USER_TWIN_REVISION_PENDING
    return issue


class UserModelingRealignmentService:
    def __init__(
        self,
        *,
        governance: UserModelingGovernancePort,
        team_queries: UserModelingRealignmentTeamQueries,
        uow_factory: UserModelingRealignmentUnitOfWorkFactory,
        clock: Callable[[], datetime] = _utc_now,
        uuid_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._governance = governance
        self._team_queries = team_queries
        self._uow_factory = uow_factory
        self._clock = clock
        self._uuid_factory = uuid_factory

    async def status(self, *, owner_user_id: UUID, project_id: UUID) -> UserModelingAlignment:
        context, readiness = await self._context(owner_user_id=owner_user_id, project_id=project_id)
        async with self._uow_factory(owner_user_id=owner_user_id) as uow:
            snapshot = await uow.snapshots.current(project_id=project_id)
            issue = await _issue(
                uow,
                project_id=project_id,
                snapshot=snapshot,
                context=context,
                readiness=readiness,
            )
        brief = None if context is None else context.brief_version
        team = None if context is None else context.team_reference
        return UserModelingAlignment(
            aligned=issue == ALREADY_ALIGNED,
            issue=issue,
            snapshot_version_number=None if snapshot is None else snapshot.version_number,
            brief_version_number=None if brief is None else brief.version_number,
            team_version_number=None if team is None else team.version_number,
        )

    async def realign(self, *, owner_user_id: UUID, project_id: UUID) -> UserModelingRealignment:
        context, readiness = await self._context(owner_user_id=owner_user_id, project_id=project_id)
        async with self._uow_factory(owner_user_id=owner_user_id) as uow:
            snapshot = await uow.snapshots.current(project_id=project_id)
            issue = await _issue(
                uow,
                project_id=project_id,
                snapshot=snapshot,
                context=context,
                readiness=readiness,
            )
            if issue is not None or snapshot is None or context is None:
                raise UserModelingRealignmentFailure(issue or USER_TWINS_NOT_FOUND)
            realignment = realigned_user_modeling(
                snapshot,
                brief_reference=context.brief_reference,
                team_reference=context.team_reference,
                catalog_version=context.catalog_version,
                catalog_content_hash=context.catalog_content_hash,
                twin_version_ids={
                    version.twin_id: self._uuid_factory()
                    for version in snapshot.snapshot.twin_versions
                },
                snapshot_version_id=self._uuid_factory(),
                created_by_user_id=owner_user_id,
                created_at=self._clock(),
            )
            for version in realignment.twin_versions:
                if await uow.twins.append(version) is not VersionAppendStatus.APPENDED:
                    raise UserModelingRealignmentFailure(PERSISTENCE_REJECTED)
            status = await uow.snapshots.append(realignment.snapshot_version)
            if status is not VersionAppendStatus.APPENDED:
                raise UserModelingRealignmentFailure(PERSISTENCE_REJECTED)
            await uow.commit()
        return realignment

    async def snapshot_context_is_current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        snapshot: UserModelingSnapshotVersion | None,
    ) -> bool:
        if snapshot is None:
            return False
        context, readiness = await self._context(owner_user_id=owner_user_id, project_id=project_id)
        return (
            context is not None
            and _context_issue(context, readiness) is None
            and user_modeling_is_aligned(snapshot, context)
        )

    async def _context(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> tuple[GovernedUserModelingContext | None, ProjectWorkflowReadiness]:
        context = await self._governance.load_current(
            owner_user_id=owner_user_id, project_id=project_id
        )
        readiness = await self._team_queries.readiness(
            project_id=project_id, owner_user_id=owner_user_id
        )
        return context, readiness


__all__ = [
    "ALREADY_ALIGNED",
    "BRIEF_APPROVAL_REQUIRED",
    "PERSISTENCE_REJECTED",
    "TEAM_APPROVAL_REQUIRED",
    "USER_TWINS_NOT_FOUND",
    "USER_TWIN_REVISION_PENDING",
    "UserModelingAlignment",
    "UserModelingRealignmentDiffRepository",
    "UserModelingRealignmentFailure",
    "UserModelingRealignmentService",
    "UserModelingRealignmentSnapshotRepository",
    "UserModelingRealignmentTeamQueries",
    "UserModelingRealignmentTwinRepository",
    "UserModelingRealignmentUnitOfWork",
    "UserModelingRealignmentUnitOfWorkFactory",
]
