"""Application services for Project Brief clarification and assumptions."""

from __future__ import annotations

from collections.abc import Callable, Iterable
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
from orchestwin.projects.clarification import (
    CLARIFICATION_CATALOG_VERSION,
    ClarificationAnswer,
    ClarificationAnswerIssue,
    ClarificationApplicationStatus,
    apply_clarification_answers,
    focused_clarification_questions,
)
from orchestwin.projects.clarification_repository import (
    BriefAssumptionRepository,
    ClarificationRoundRepository,
)
from orchestwin.projects.clarification_state import (
    MAX_CLARIFICATION_ROUNDS,
    BriefAssumption,
    BriefAssumptionSource,
    BriefAssumptionStatus,
    ClarificationRound,
    ClarificationRoundStatus,
    create_brief_assumption,
    create_clarification_round,
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
    def rounds(self) -> ClarificationRoundRepository:
        """Return the clarification-round repository."""

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


class ClarificationRoundStartStatus(StrEnum):
    """Stable outcomes of starting a clarification round."""

    STARTED = "STARTED"
    OPEN_ROUND_EXISTS = "OPEN_ROUND_EXISTS"
    BRIEF_NOT_FOUND = "BRIEF_NOT_FOUND"
    BRIEF_COMPLETE = "BRIEF_COMPLETE"
    LIMIT_REACHED = "LIMIT_REACHED"


class ClarificationNextStep(StrEnum):
    """Derived next step after applying clarification answers."""

    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    BRIEF_READY_FOR_APPROVAL = "BRIEF_READY_FOR_APPROVAL"
    PAUSED_NEEDS_HUMAN = "PAUSED_NEEDS_HUMAN"


class ClarificationRoundAnswerStatus(StrEnum):
    """Stable outcomes of answering one clarification round."""

    APPLIED = "APPLIED"
    ROUND_NOT_FOUND = "ROUND_NOT_FOUND"
    ROUND_NOT_OPEN = "ROUND_NOT_OPEN"
    ROUND_STALE = "ROUND_STALE"
    NO_ANSWERS = "NO_ANSWERS"
    INVALID_ANSWERS = "INVALID_ANSWERS"
    VERSION_UNCHANGED = "VERSION_UNCHANGED"


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
class ClarificationRoundStartResult:
    """Typed result of starting a clarification round."""

    status: ClarificationRoundStartStatus
    round_state: ClarificationRound | None = None


@dataclass(frozen=True, slots=True)
class ClarificationRoundAnswerResult:
    """Typed result of applying one round of owner answers."""

    status: ClarificationRoundAnswerStatus
    round_state: ClarificationRound | None = None
    version: ProjectBriefVersion | None = None
    next_step: ClarificationNextStep | None = None
    issues: tuple[ClarificationAnswerIssue, ...] = ()
    invalid_question_ids: tuple[str, ...] = ()


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

    async def start_round(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ClarificationRoundStartResult:
        """Start or return the current clarification round."""

    async def answer_round(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        round_id: UUID,
        answers: Iterable[ClarificationAnswer],
    ) -> ClarificationRoundAnswerResult:
        """Apply answers and create a new immutable brief version."""

    async def current_round(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ClarificationRound | None:
        """Return the current open clarification round."""

    async def round_history(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[ClarificationRound, ...]:
        """Return clarification-round history."""

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
        maximum_questions_per_round: int = 5,
        clock: Clock = utc_now,
        round_id_factory: UuidFactory = uuid4,
        assumption_id_factory: UuidFactory = uuid4,
    ) -> None:
        if maximum_questions_per_round < 1:
            raise ValueError("maximum questions per clarification round must be positive")

        self._unit_of_work_factory = unit_of_work_factory
        self._maximum_questions_per_round = maximum_questions_per_round
        self._clock = clock
        self._round_id_factory = round_id_factory
        self._assumption_id_factory = assumption_id_factory

    async def start_round(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ClarificationRoundStartResult:
        """Start the next focused clarification round."""
        timestamp = self._current_time()

        async with self._unit_of_work_factory() as unit:
            current = await unit.current_briefs.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )

            if current is None:
                return ClarificationRoundStartResult(
                    status=ClarificationRoundStartStatus.BRIEF_NOT_FOUND
                )

            open_round = await unit.rounds.get_current_open_owned(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )

            if open_round is not None:
                return ClarificationRoundStartResult(
                    status=ClarificationRoundStartStatus.OPEN_ROUND_EXISTS,
                    round_state=open_round,
                )

            if not current.brief.missing_fields:
                return ClarificationRoundStartResult(
                    status=ClarificationRoundStartStatus.BRIEF_COMPLETE
                )

            completed_rounds = await unit.rounds.count_owned(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )

            if completed_rounds >= MAX_CLARIFICATION_ROUNDS:
                return ClarificationRoundStartResult(
                    status=ClarificationRoundStartStatus.LIMIT_REACHED
                )

            questions = focused_clarification_questions(
                current.brief,
                maximum_questions=self._maximum_questions_per_round,
            )
            round_state = create_clarification_round(
                round_id=self._round_id_factory(),
                project_id=project_id,
                source_brief_version_number=current.version_number,
                round_number=completed_rounds + 1,
                catalog_version=CLARIFICATION_CATALOG_VERSION,
                questions=questions,
                created_by_user_id=owner_user_id,
                created_at=timestamp,
            )
            persisted = await unit.rounds.add(round_state)

            return ClarificationRoundStartResult(
                status=ClarificationRoundStartStatus.STARTED,
                round_state=persisted,
            )

    async def answer_round(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        round_id: UUID,
        answers: Iterable[ClarificationAnswer],
    ) -> ClarificationRoundAnswerResult:
        """Apply owner answers atomically and complete the round."""
        timestamp = self._current_time()
        answer_batch = tuple(answers)

        if not answer_batch:
            return ClarificationRoundAnswerResult(status=ClarificationRoundAnswerStatus.NO_ANSWERS)

        async with self._unit_of_work_factory() as unit:
            current = await unit.current_briefs.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )
            round_state = await unit.rounds.get_owned(
                project_id=project_id,
                owner_user_id=owner_user_id,
                round_id=round_id,
            )

            if current is None or round_state is None:
                return ClarificationRoundAnswerResult(
                    status=ClarificationRoundAnswerStatus.ROUND_NOT_FOUND
                )

            if round_state.status is not ClarificationRoundStatus.OPEN:
                return ClarificationRoundAnswerResult(
                    status=ClarificationRoundAnswerStatus.ROUND_NOT_OPEN,
                    round_state=round_state,
                )

            if round_state.source_brief_version_number != current.version_number:
                return ClarificationRoundAnswerResult(
                    status=ClarificationRoundAnswerStatus.ROUND_STALE,
                    round_state=round_state,
                )

            allowed_question_ids = {question.question_id for question in round_state.questions}
            invalid_question_ids = tuple(
                sorted(
                    {
                        answer.question_id
                        for answer in answer_batch
                        if answer.question_id not in allowed_question_ids
                    }
                )
            )

            if invalid_question_ids:
                return ClarificationRoundAnswerResult(
                    status=ClarificationRoundAnswerStatus.INVALID_ANSWERS,
                    round_state=round_state,
                    invalid_question_ids=invalid_question_ids,
                )

            application = apply_clarification_answers(
                current.brief,
                answer_batch,
            )

            if application.status is ClarificationApplicationStatus.NO_ANSWERS:
                return ClarificationRoundAnswerResult(
                    status=ClarificationRoundAnswerStatus.NO_ANSWERS,
                    round_state=round_state,
                )

            if application.status is ClarificationApplicationStatus.REJECTED:
                return ClarificationRoundAnswerResult(
                    status=ClarificationRoundAnswerStatus.INVALID_ANSWERS,
                    round_state=round_state,
                    issues=application.issues,
                )

            if application.updated_brief is None:
                raise RuntimeError("applied clarification answers did not return a brief")

            creation = await unit.briefs.create_owned_version(
                project_id=project_id,
                owner_user_id=owner_user_id,
                created_by_user_id=owner_user_id,
                brief=application.updated_brief,
            )

            if (
                creation.status is BriefVersionCreationStatus.PROJECT_NOT_FOUND
                or creation.version is None
            ):
                return ClarificationRoundAnswerResult(
                    status=ClarificationRoundAnswerStatus.ROUND_STALE,
                    round_state=round_state,
                )

            if creation.status is BriefVersionCreationStatus.UNCHANGED:
                return ClarificationRoundAnswerResult(
                    status=ClarificationRoundAnswerStatus.VERSION_UNCHANGED,
                    round_state=round_state,
                    version=creation.version,
                )

            completed = await unit.rounds.complete_owned(
                project_id=project_id,
                owner_user_id=owner_user_id,
                round_id=round_id,
                resulting_brief_version_number=creation.version.version_number,
                answered_at=timestamp,
            )

            if completed is None:
                return ClarificationRoundAnswerResult(
                    status=ClarificationRoundAnswerStatus.ROUND_NOT_FOUND
                )

            return ClarificationRoundAnswerResult(
                status=ClarificationRoundAnswerStatus.APPLIED,
                round_state=completed,
                version=creation.version,
                next_step=self._next_step(
                    brief=creation.version.brief,
                    round_number=completed.round_number,
                ),
            )

    async def current_round(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ClarificationRound | None:
        """Return the current owner-scoped open round."""
        async with self._unit_of_work_factory() as unit:
            return await unit.rounds.get_current_open_owned(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )

    async def round_history(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[ClarificationRound, ...]:
        """Return owner-scoped clarification history."""
        async with self._unit_of_work_factory() as unit:
            return await unit.rounds.list_owned(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )

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
    def _next_step(
        *,
        brief: ProjectBrief,
        round_number: int,
    ) -> ClarificationNextStep:
        """Derive the next workflow step after one answered round."""
        if not brief.missing_fields:
            return ClarificationNextStep.BRIEF_READY_FOR_APPROVAL

        if round_number >= MAX_CLARIFICATION_ROUNDS:
            return ClarificationNextStep.PAUSED_NEEDS_HUMAN

        return ClarificationNextStep.CLARIFICATION_REQUIRED

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
