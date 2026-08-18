"""Tests for clarification and assumption application services."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import TracebackType
from uuid import UUID

from orchestwin.projects.briefs import (
    BriefField,
    ProjectBriefVersion,
    create_project_brief,
)
from orchestwin.projects.clarification import (
    ClarificationAnswer,
)
from orchestwin.projects.clarification_application import (
    BriefAssumptionDecisionStatus,
    ClarificationNextStep,
    ClarificationRoundAnswerStatus,
    ClarificationRoundStartStatus,
    LocalProjectClarificationApplicationService,
)
from orchestwin.projects.clarification_state import (
    BriefAssumption,
    BriefAssumptionStatus,
    ClarificationRound,
    accept_brief_assumption,
    complete_clarification_round,
    reject_brief_assumption,
)
from orchestwin.projects.repository import (
    BriefVersionCreationResult,
    BriefVersionCreationStatus,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
NOW = datetime(
    2026,
    8,
    12,
    12,
    0,
    tzinfo=UTC,
)


class IncrementingUuidFactory:
    """Return deterministic UUID values."""

    def __init__(
        self,
        *,
        start: int,
    ) -> None:
        self._next_value = start

    def __call__(self) -> UUID:
        value = UUID(int=self._next_value)
        self._next_value += 1
        return value


class InMemoryCurrentBriefRepository:
    """Mutable owner-scoped current-brief repository."""

    def __init__(self) -> None:
        self.current: dict[
            tuple[UUID, UUID],
            ProjectBriefVersion,
        ] = {}

    def set_current(
        self,
        *,
        owner_user_id: UUID,
        version: ProjectBriefVersion,
    ) -> None:
        """Set the current brief for one owner and project."""
        self.current[
            (
                version.project_id,
                owner_user_id,
            )
        ] = version

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ProjectBriefVersion | None:
        """Return the current owner-scoped brief."""
        return self.current.get(
            (
                project_id,
                owner_user_id,
            )
        )


class InMemoryBriefVersionRepository:
    """Create immutable brief versions and update current state."""

    def __init__(
        self,
        current_briefs: InMemoryCurrentBriefRepository,
    ) -> None:
        self._current_briefs = current_briefs

    async def create_owned_version(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        created_by_user_id: UUID,
        brief,
    ) -> BriefVersionCreationResult:
        """Create the next brief version or reuse identical content."""
        current = await self._current_briefs.get_current_owned_for_update(
            project_id=project_id,
            owner_user_id=owner_user_id,
        )

        if current is None:
            return BriefVersionCreationResult(status=BriefVersionCreationStatus.PROJECT_NOT_FOUND)

        if current.content_hash == brief.content_hash:
            return BriefVersionCreationResult(
                status=BriefVersionCreationStatus.UNCHANGED,
                version=current,
            )

        version = ProjectBriefVersion(
            id=UUID(int=100 + current.version_number),
            project_id=project_id,
            version_number=(current.version_number + 1),
            schema_version=brief.SCHEMA_VERSION,
            brief=brief,
            content_hash=brief.content_hash,
            created_by_user_id=created_by_user_id,
            created_at=NOW,
        )
        self._current_briefs.set_current(
            owner_user_id=owner_user_id,
            version=version,
        )

        return BriefVersionCreationResult(
            status=BriefVersionCreationStatus.CREATED,
            version=version,
        )

    async def get_current_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ProjectBriefVersion | None:
        """Return the current brief."""
        return await self._current_briefs.get_current_owned_for_update(
            project_id=project_id,
            owner_user_id=owner_user_id,
        )

    async def get_owned_version(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        version_number: int,
    ) -> ProjectBriefVersion | None:
        """Return only the current version in this focused test double."""
        current = await self.get_current_owned(
            project_id=project_id,
            owner_user_id=owner_user_id,
        )

        if current is not None and current.version_number == version_number:
            return current

        return None

    async def list_owned_versions(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[ProjectBriefVersion, ...]:
        """Return the current version as focused history."""
        current = await self.get_current_owned(
            project_id=project_id,
            owner_user_id=owner_user_id,
        )

        return (current,) if current is not None else ()


class InMemoryRoundRepository:
    """In-memory clarification-round repository."""

    def __init__(self) -> None:
        self.rounds: list[ClarificationRound] = []

    async def add(
        self,
        round_state: ClarificationRound,
    ) -> ClarificationRound:
        """Persist one open round."""
        self.rounds.append(round_state)
        return round_state

    async def count_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> int:
        """Count rounds for the project."""
        del owner_user_id

        return sum(round_state.project_id == project_id for round_state in self.rounds)

    async def get_current_open_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ClarificationRound | None:
        """Return the latest open round."""
        del owner_user_id

        return next(
            (
                round_state
                for round_state in reversed(self.rounds)
                if (round_state.project_id == project_id and round_state.status.value == "OPEN")
            ),
            None,
        )

    async def get_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        round_id: UUID,
    ) -> ClarificationRound | None:
        """Return one owner-scoped round."""
        del owner_user_id

        return next(
            (
                round_state
                for round_state in self.rounds
                if (round_state.project_id == project_id and round_state.id == round_id)
            ),
            None,
        )

    async def list_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[ClarificationRound, ...]:
        """Return round history."""
        del owner_user_id

        return tuple(
            round_state for round_state in self.rounds if round_state.project_id == project_id
        )

    async def complete_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        round_id: UUID,
        resulting_brief_version_number: int,
        answered_at: datetime,
    ) -> ClarificationRound | None:
        """Complete one round."""
        current = await self.get_owned(
            project_id=project_id,
            owner_user_id=owner_user_id,
            round_id=round_id,
        )

        if current is None:
            return None

        completed = complete_clarification_round(
            current,
            resulting_brief_version_number=(resulting_brief_version_number),
            answered_at=answered_at,
        )
        index = self.rounds.index(current)
        self.rounds[index] = completed

        return completed


class InMemoryAssumptionRepository:
    """In-memory assumption repository."""

    def __init__(self) -> None:
        self.assumptions: list[BriefAssumption] = []

    async def add(
        self,
        assumption: BriefAssumption,
    ) -> BriefAssumption:
        """Persist one proposed assumption."""
        self.assumptions.append(assumption)
        return assumption

    async def get_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        assumption_id: UUID,
    ) -> BriefAssumption | None:
        """Return one assumption."""
        del owner_user_id

        return next(
            (
                assumption
                for assumption in self.assumptions
                if (assumption.project_id == project_id and assumption.id == assumption_id)
            ),
            None,
        )

    async def list_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[BriefAssumption, ...]:
        """Return assumptions."""
        del owner_user_id

        return tuple(
            assumption for assumption in self.assumptions if assumption.project_id == project_id
        )

    async def accept_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        assumption_id: UUID,
        decided_at: datetime,
        reason: str | None = None,
    ) -> BriefAssumption | None:
        """Accept one proposed assumption."""
        current = await self.get_owned(
            project_id=project_id,
            owner_user_id=owner_user_id,
            assumption_id=assumption_id,
        )

        if current is None:
            return None

        accepted = accept_brief_assumption(
            current,
            decided_by_user_id=owner_user_id,
            decided_at=decided_at,
            reason=reason,
        )
        self.assumptions[self.assumptions.index(current)] = accepted

        return accepted

    async def reject_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        assumption_id: UUID,
        decided_at: datetime,
        reason: str,
    ) -> BriefAssumption | None:
        """Reject one proposed assumption."""
        current = await self.get_owned(
            project_id=project_id,
            owner_user_id=owner_user_id,
            assumption_id=assumption_id,
        )

        if current is None:
            return None

        rejected = reject_brief_assumption(
            current,
            decided_by_user_id=owner_user_id,
            decided_at=decided_at,
            reason=reason,
        )
        self.assumptions[self.assumptions.index(current)] = rejected

        return rejected


class InMemoryClarificationUnitOfWork:
    """Reusable in-memory clarification transaction boundary."""

    def __init__(
        self,
        current_briefs: InMemoryCurrentBriefRepository,
        briefs: InMemoryBriefVersionRepository,
        rounds: InMemoryRoundRepository,
        assumptions: InMemoryAssumptionRepository,
    ) -> None:
        self.current_briefs = current_briefs
        self.briefs = briefs
        self.rounds = rounds
        self.assumptions = assumptions

    async def __aenter__(
        self,
    ) -> InMemoryClarificationUnitOfWork:
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


def build_fixture():
    """Create an incomplete brief and deterministic service."""
    brief = create_project_brief(name="Project")
    version = ProjectBriefVersion(
        id=UUID(int=100),
        project_id=PROJECT_ID,
        version_number=1,
        schema_version=brief.SCHEMA_VERSION,
        brief=brief,
        content_hash=brief.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=NOW,
    )
    current_briefs = InMemoryCurrentBriefRepository()
    current_briefs.set_current(
        owner_user_id=OWNER_ID,
        version=version,
    )
    briefs = InMemoryBriefVersionRepository(current_briefs)
    rounds = InMemoryRoundRepository()
    assumptions = InMemoryAssumptionRepository()
    service = LocalProjectClarificationApplicationService(
        unit_of_work_factory=lambda: InMemoryClarificationUnitOfWork(
            current_briefs,
            briefs,
            rounds,
            assumptions,
        ),
        maximum_questions_per_round=2,
        clock=lambda: NOW,
        round_id_factory=(IncrementingUuidFactory(start=1000)),
        assumption_id_factory=(IncrementingUuidFactory(start=2000)),
    )

    return (
        current_briefs,
        rounds,
        assumptions,
        service,
    )


def test_round_answers_create_new_brief_version() -> None:
    """Apply focused answers and complete the persisted round."""
    (
        current_briefs,
        rounds,
        _,
        service,
    ) = build_fixture()

    started = asyncio.run(
        service.start_round(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert started.status is (ClarificationRoundStartStatus.STARTED)
    assert started.round_state is not None

    questions = started.round_state.questions
    result = asyncio.run(
        service.answer_round(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            round_id=started.round_state.id,
            answers=(
                ClarificationAnswer.text(
                    question_id=(questions[0].question_id),
                    value="Project description",
                ),
                ClarificationAnswer.text(
                    question_id=(questions[1].question_id),
                    value="Problem statement",
                ),
            ),
        )
    )

    assert result.status is (ClarificationRoundAnswerStatus.APPLIED)
    assert result.version is not None
    assert result.version.version_number == 2
    assert result.next_step is (ClarificationNextStep.CLARIFICATION_REQUIRED)
    assert result.round_state is not None
    assert result.round_state.status.value == ("ANSWERED")
    assert len(rounds.rounds) == 1

    current = asyncio.run(
        current_briefs.get_current_owned_for_update(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert current == result.version
    assert current is not None
    assert current.brief.description == ("Project description")
    assert current.brief.problem == ("Problem statement")


def test_third_incomplete_round_pauses_for_human() -> None:
    """Stop automatic clarification after the third answered round."""
    (
        _,
        rounds,
        _,
        service,
    ) = build_fixture()

    next_step = None

    for _ in range(3):
        started = asyncio.run(
            service.start_round(
                project_id=PROJECT_ID,
                owner_user_id=OWNER_ID,
            )
        )

        assert started.round_state is not None
        first_question = started.round_state.questions[0]
        answer = ClarificationAnswer.unknown(question_id=(first_question.question_id))

        result = asyncio.run(
            service.answer_round(
                project_id=PROJECT_ID,
                owner_user_id=OWNER_ID,
                round_id=(started.round_state.id),
                answers=(answer,),
            )
        )
        next_step = result.next_step

    assert len(rounds.rounds) == 3
    assert next_step is (ClarificationNextStep.PAUSED_NEEDS_HUMAN)

    blocked = asyncio.run(
        service.start_round(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert blocked.status is (ClarificationRoundStartStatus.LIMIT_REACHED)


def test_accepting_assumption_creates_explicit_brief_version() -> None:
    """Keep assumption provenance while materializing accepted content."""
    (
        current_briefs,
        _,
        assumptions,
        service,
    ) = build_fixture()

    created = asyncio.run(
        service.create_assumption(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            field=BriefField.BUDGET,
            statement="Approximately EUR 5,000.",
        )
    )

    assert created.assumption is not None

    accepted = asyncio.run(
        service.accept_assumption(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            assumption_id=(created.assumption.id),
            reason=("Confirmed by the project owner."),
        )
    )

    assert accepted.status is (BriefAssumptionDecisionStatus.ACCEPTED)
    assert accepted.assumption is not None
    assert accepted.assumption.status is (BriefAssumptionStatus.ACCEPTED)
    assert accepted.version is not None
    assert accepted.version.version_number == 2
    assert accepted.version.brief.budget == ("Approximately EUR 5,000.")
    assert len(assumptions.assumptions) == 1

    current = asyncio.run(
        current_briefs.get_current_owned_for_update(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert current == accepted.version
