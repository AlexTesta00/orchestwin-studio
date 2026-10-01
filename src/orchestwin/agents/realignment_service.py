from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError

from orchestwin.agents.proposals import (
    TeamProposalRevisionKind,
    TeamProposalVersion,
    TeamSelectionContextRepository,
)
from orchestwin.agents.realignment import PREPARE_AGAIN, reanchored_team, team_selection_can_realign
from orchestwin.workflow.gates import HumanGateStatus, HumanGateType
from orchestwin.workflow.repository import HumanGateRepository


class TeamRealignmentFailure(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class TeamAlignment:
    aligned: bool
    issue: str | None
    team_version_number: int | None
    brief_version_number: int | None


class TeamRealignmentProposals(Protocol):
    async def current(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> TeamProposalVersion | None: ...

    async def append(self, version: TeamProposalVersion) -> bool: ...


class TeamRealignmentUnitOfWork(Protocol):
    contexts: TeamSelectionContextRepository
    proposals: TeamRealignmentProposals
    gates: HumanGateRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


class TeamRealignmentUnitOfWorkFactory(Protocol):
    def __call__(self, *, owner_user_id: UUID) -> TeamRealignmentUnitOfWork: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


class TeamRealignmentService:
    def __init__(
        self,
        *,
        uow_factory: TeamRealignmentUnitOfWorkFactory,
        clock: Callable[[], datetime] = _utc_now,
        uuid_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._uuid_factory = uuid_factory

    async def _basis(
        self,
        unit: TeamRealignmentUnitOfWork,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        locked: bool,
    ):
        read = (
            unit.contexts.get_current_owned_for_update
            if locked
            else unit.contexts.get_current_owned
        )
        context = await read(owner_user_id=owner_user_id, project_id=project_id)
        current = await unit.proposals.current(owner_user_id=owner_user_id, project_id=project_id)
        if context is None or current is None:
            return context, current, "TEAM_NOT_FOUND"
        if not context.brief_is_approved or context.brief_version is None:
            return context, current, "BRIEF_APPROVAL_REQUIRED"
        gate = await unit.gates.get_latest_owned_for_update(
            owner_user_id=owner_user_id, project_id=project_id, gate_type=HumanGateType.AGENT_TEAM
        )
        if (
            gate is None
            or gate.status is not HumanGateStatus.APPROVED
            or (
                gate.artifact.artifact_id != current.id
                or gate.artifact.version != current.version_number
                or gate.artifact.content_hash != current.content_hash
            )
        ):
            return context, current, "TEAM_APPROVAL_REQUIRED"
        brief = context.brief_version
        proposal = current.proposal
        if (
            proposal.brief_version_id,
            proposal.brief_version_number,
            proposal.brief_content_hash,
        ) == (brief.id, brief.version_number, brief.content_hash):
            return context, current, "ALREADY_ALIGNED"
        if not team_selection_can_realign(
            proposal, brief=brief.brief, project_mode=context.project_mode
        ):
            return context, current, PREPARE_AGAIN
        return context, current, None

    async def status(self, *, owner_user_id: UUID, project_id: UUID) -> TeamAlignment:
        async with self._uow_factory(owner_user_id=owner_user_id) as unit:
            context, current, issue = await self._basis(
                unit, owner_user_id=owner_user_id, project_id=project_id, locked=False
            )
        brief = None if context is None else context.brief_version
        return TeamAlignment(
            aligned=issue == "ALREADY_ALIGNED",
            issue=issue,
            team_version_number=None if current is None else current.version_number,
            brief_version_number=None if brief is None else brief.version_number,
        )

    async def realign(self, *, owner_user_id: UUID, project_id: UUID) -> TeamProposalVersion:
        try:
            async with self._uow_factory(owner_user_id=owner_user_id) as unit:
                context, current, issue = await self._basis(
                    unit, owner_user_id=owner_user_id, project_id=project_id, locked=True
                )
                if issue is not None or current is None or context is None:
                    raise TeamRealignmentFailure(issue or "TEAM_NOT_FOUND")
                proposal = reanchored_team(
                    current.proposal, brief=context.brief_version, project_mode=context.project_mode
                )
                version = TeamProposalVersion(
                    id=self._uuid_factory(),
                    project_id=project_id,
                    version_number=current.version_number + 1,
                    proposal=proposal,
                    revision_kind=TeamProposalRevisionKind.OWNER_EDITED,
                    based_on_version_number=current.version_number,
                    created_by_user_id=owner_user_id,
                    created_at=self._clock(),
                )
                if not await unit.proposals.append(version):
                    raise TeamRealignmentFailure("PERSISTENCE_REJECTED")
                await unit.commit()
                return version
        except SQLAlchemyError:
            raise TeamRealignmentFailure("PERSISTENCE_REJECTED") from None


__all__ = [
    "TeamAlignment",
    "TeamRealignmentFailure",
    "TeamRealignmentProposals",
    "TeamRealignmentService",
    "TeamRealignmentUnitOfWork",
    "TeamRealignmentUnitOfWorkFactory",
]
