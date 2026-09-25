"""Application services for Project Brief clarification and assumptions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID, uuid4

from orchestwin.projects.briefs import (
    LIST_FIELDS,
    BriefField,
    ProjectBrief,
    ProjectBriefVersion,
)
from orchestwin.projects.clarification_repository import (
    BriefAssumptionRepository,
)
from orchestwin.projects.clarification_state import (
    BriefAssumption,
    BriefAssumptionSource,
    BriefAssumptionStatus,
    create_brief_assumption,
)
from orchestwin.projects.repository import (
    BriefVersionCreationStatus,
    ProjectBriefRepository,
)


class CurrentProjectBriefRepository(Protocol):
    """Owner-scoped access to the current Project Brief."""

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ProjectBriefVersion | None:
        """Lock the project and return its current brief version."""


class ProjectClarificationUnitOfWork(Protocol):
    """Transactional boundary for clarification and assumption use cases."""

    @property
    def current_briefs(self) -> CurrentProjectBriefRepository:
        """Return the current-brief repository."""

    @property
    def briefs(self) -> ProjectBriefRepository:
        """Return the immutable brief-version repository."""

    @property
    def assumptions(self) -> BriefAssumptionRepository:
        """Return the brief-assumption repository."""

    async def __aenter__(self) -> Self:
        """Open the transaction."""

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Commit or roll back the transaction."""


ProjectClarificationUnitOfWorkFactory = Callable[
    [],
    ProjectClarificationUnitOfWork,
]
Clock = Callable[[], datetime]
UuidFactory = Callable[[], UUID]


class BriefAssumptionCreationStatus(StrEnum):
    """Stable outcomes of creating a Project Brief assumption."""

    CREATED = "CREATED"
    BRIEF_NOT_FOUND = "BRIEF_NOT_FOUND"
    FIELD_ALREADY_PROVIDED = "FIELD_ALREADY_PROVIDED"


class BriefAssumptionDecisionStatus(StrEnum):
    """Stable outcomes of accepting or rejecting an assumption."""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    ASSUMPTION_NOT_FOUND = "ASSUMPTION_NOT_FOUND"
    ASSUMPTION_NOT_PROPOSED = "ASSUMPTION_NOT_PROPOSED"
    ASSUMPTION_STALE = "ASSUMPTION_STALE"
    FIELD_ALREADY_PROVIDED = "FIELD_ALREADY_PROVIDED"
    VERSION_UNCHANGED = "VERSION_UNCHANGED"


@dataclass(frozen=True, slots=True)
class BriefAssumptionCreationResult:
    """Typed result of proposing a separate Project Brief assumption."""

    status: BriefAssumptionCreationStatus
    assumption: BriefAssumption | None = None


@dataclass(frozen=True, slots=True)
class BriefAssumptionDecisionResult:
    """Typed result of deciding one Project Brief assumption."""

    status: BriefAssumptionDecisionStatus
    assumption: BriefAssumption | None = None
    version: ProjectBriefVersion | None = None


class ProjectClarificationApplicationService(Protocol):
    """Use cases exposed to the clarification API adapter."""

    async def create_assumption(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        field: BriefField,
        statement: str,
    ) -> BriefAssumptionCreationResult:
        """Propose one owner-provided assumption."""

    async def assumptions(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[BriefAssumption, ...]:
        """Return owner-scoped assumptions."""

    async def accept_assumption(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        assumption_id: UUID,
        reason: str | None = None,
    ) -> BriefAssumptionDecisionResult:
        """Accept an assumption and create an explicit brief version."""

    async def reject_assumption(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        assumption_id: UUID,
        reason: str,
    ) -> BriefAssumptionDecisionResult:
        """Reject an assumption with a required reason."""


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class LocalProjectClarificationApplicationService:
    """Clarification use cases composed from explicit repository ports."""

    def __init__(
        self,
        *,
        unit_of_work_factory: ProjectClarificationUnitOfWorkFactory,
        clock: Clock = utc_now,
        assumption_id_factory: UuidFactory = uuid4,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._assumption_id_factory = assumption_id_factory

    async def create_assumption(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        field: BriefField,
        statement: str,
    ) -> BriefAssumptionCreationResult:
        """Create an owner-provided assumption for the current brief."""
        timestamp = self._current_time()

        async with self._unit_of_work_factory() as unit:
            current = await unit.current_briefs.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )

            if current is None:
                return BriefAssumptionCreationResult(
                    status=BriefAssumptionCreationStatus.BRIEF_NOT_FOUND
                )

            if field in current.brief.provided_fields:
                return BriefAssumptionCreationResult(
                    status=BriefAssumptionCreationStatus.FIELD_ALREADY_PROVIDED
                )

            assumption = create_brief_assumption(
                assumption_id=self._assumption_id_factory(),
                project_id=project_id,
                brief_version_number=current.version_number,
                field=field,
                statement=statement,
                source=BriefAssumptionSource.OWNER_PROVIDED,
                created_by_user_id=owner_user_id,
                created_at=timestamp,
            )
            persisted = await unit.assumptions.add(assumption)

            return BriefAssumptionCreationResult(
                status=BriefAssumptionCreationStatus.CREATED,
                assumption=persisted,
            )

    async def assumptions(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[BriefAssumption, ...]:
        """Return owner-scoped assumptions."""
        async with self._unit_of_work_factory() as unit:
            return await unit.assumptions.list_owned(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )

    async def accept_assumption(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        assumption_id: UUID,
        reason: str | None = None,
    ) -> BriefAssumptionDecisionResult:
        """Accept an assumption and materialize it in a new brief version."""
        timestamp = self._current_time()

        async with self._unit_of_work_factory() as unit:
            current = await unit.current_briefs.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )
            assumption = await unit.assumptions.get_owned(
                project_id=project_id,
                owner_user_id=owner_user_id,
                assumption_id=assumption_id,
            )

            if current is None or assumption is None:
                return BriefAssumptionDecisionResult(
                    status=BriefAssumptionDecisionStatus.ASSUMPTION_NOT_FOUND
                )

            if assumption.status is not BriefAssumptionStatus.PROPOSED:
                return BriefAssumptionDecisionResult(
                    status=(BriefAssumptionDecisionStatus.ASSUMPTION_NOT_PROPOSED),
                    assumption=assumption,
                )

            if assumption.brief_version_number != current.version_number:
                return BriefAssumptionDecisionResult(
                    status=BriefAssumptionDecisionStatus.ASSUMPTION_STALE,
                    assumption=assumption,
                )

            if assumption.field in current.brief.provided_fields:
                return BriefAssumptionDecisionResult(
                    status=(BriefAssumptionDecisionStatus.FIELD_ALREADY_PROVIDED),
                    assumption=assumption,
                )

            updated_brief = self._brief_with_assumption(
                current.brief,
                assumption,
            )

            accepted = await unit.assumptions.accept_owned(
                project_id=project_id,
                owner_user_id=owner_user_id,
                assumption_id=assumption_id,
                decided_at=timestamp,
                reason=reason,
            )

            if accepted is None:
                return BriefAssumptionDecisionResult(
                    status=BriefAssumptionDecisionStatus.ASSUMPTION_NOT_FOUND
                )

            creation = await unit.briefs.create_owned_version(
                project_id=project_id,
                owner_user_id=owner_user_id,
                created_by_user_id=owner_user_id,
                brief=updated_brief,
            )

            if (
                creation.status is not BriefVersionCreationStatus.CREATED
                or creation.version is None
            ):
                raise RuntimeError("accepted assumption did not create a new Project Brief version")

            return BriefAssumptionDecisionResult(
                status=BriefAssumptionDecisionStatus.ACCEPTED,
                assumption=accepted,
                version=creation.version,
            )

    async def reject_assumption(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        assumption_id: UUID,
        reason: str,
    ) -> BriefAssumptionDecisionResult:
        """Reject an owner-scoped proposed assumption."""
        timestamp = self._current_time()

        async with self._unit_of_work_factory() as unit:
            try:
                rejected = await unit.assumptions.reject_owned(
                    project_id=project_id,
                    owner_user_id=owner_user_id,
                    assumption_id=assumption_id,
                    decided_at=timestamp,
                    reason=reason,
                )
            except ValueError:
                existing = await unit.assumptions.get_owned(
                    project_id=project_id,
                    owner_user_id=owner_user_id,
                    assumption_id=assumption_id,
                )

                return BriefAssumptionDecisionResult(
                    status=(BriefAssumptionDecisionStatus.ASSUMPTION_NOT_PROPOSED),
                    assumption=existing,
                )

            if rejected is None:
                return BriefAssumptionDecisionResult(
                    status=BriefAssumptionDecisionStatus.ASSUMPTION_NOT_FOUND
                )

            return BriefAssumptionDecisionResult(
                status=BriefAssumptionDecisionStatus.REJECTED,
                assumption=rejected,
            )

    @staticmethod
    def _brief_with_assumption(
        brief: ProjectBrief,
        assumption: BriefAssumption,
    ) -> ProjectBrief:
        """Materialize one accepted assumption as an explicit brief value."""
        unknown_fields = set(brief.unknown_fields)
        unknown_fields.discard(assumption.field)
        value: object = assumption.statement

        if assumption.field in LIST_FIELDS:
            value = (assumption.statement,)

        return replace(
            brief,
            **{
                assumption.field.value: value,
                "unknown_fields": frozenset(unknown_fields),
            },
        )

    def _current_time(self) -> datetime:
        """Return and validate the injected application clock."""
        timestamp = self._clock()

        if timestamp.tzinfo is None:
            raise ValueError("clarification application clock must be timezone-aware")

        return timestamp
