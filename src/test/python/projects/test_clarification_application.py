"""Tests for clarification and assumption application services."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import TracebackType
from uuid import UUID

from orchestwin.projects.briefs import (
    BriefField,
    ProjectBrief,
    ProjectBriefVersion,
    create_project_brief,
)
from orchestwin.projects.clarification_application import (
    BriefAssumptionBulkAcceptanceResult,
    BriefAssumptionBulkAcceptanceStatus,
    BriefAssumptionDecisionResult,
    BriefAssumptionDecisionStatus,
    LocalProjectClarificationApplicationService,
)
from orchestwin.projects.clarification_state import (
    BriefAssumption,
    BriefAssumptionSource,
    BriefAssumptionStatus,
    accept_brief_assumption,
    create_brief_assumption,
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
        assumptions: InMemoryAssumptionRepository,
    ) -> None:
        self.current_briefs = current_briefs
        self.briefs = briefs
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


def build_fixture(
    brief: ProjectBrief | None = None,
):
    """Create an incomplete brief and deterministic service."""
    if brief is None:
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
    assumptions = InMemoryAssumptionRepository()
    service = LocalProjectClarificationApplicationService(
        unit_of_work_factory=lambda: InMemoryClarificationUnitOfWork(
            current_briefs,
            briefs,
            assumptions,
        ),
        clock=lambda: NOW,
        assumption_id_factory=(IncrementingUuidFactory(start=2000)),
    )

    return (
        current_briefs,
        assumptions,
        service,
    )


def propose(
    assumptions: InMemoryAssumptionRepository,
    *,
    field: BriefField,
    statement: str,
    minutes_before: int = 0,
) -> BriefAssumption:
    assumption = create_brief_assumption(
        assumption_id=UUID(int=3000 + len(assumptions.assumptions)),
        project_id=PROJECT_ID,
        brief_version_number=1,
        field=field,
        statement=statement,
        source=BriefAssumptionSource.MODEL_PROPOSED,
        created_by_user_id=OWNER_ID,
        created_at=NOW - timedelta(minutes=minutes_before),
    )
    assumptions.assumptions.append(assumption)

    return assumption


def current_version(
    current_briefs: InMemoryCurrentBriefRepository,
) -> ProjectBriefVersion:
    version = asyncio.run(
        current_briefs.get_current_owned_for_update(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert version is not None

    return version


def fill_brief(
    current_briefs: InMemoryCurrentBriefRepository,
    brief: ProjectBrief,
) -> None:
    previous = current_version(current_briefs)
    current_briefs.set_current(
        owner_user_id=OWNER_ID,
        version=ProjectBriefVersion(
            id=UUID(int=200 + previous.version_number),
            project_id=PROJECT_ID,
            version_number=previous.version_number + 1,
            schema_version=brief.SCHEMA_VERSION,
            brief=brief,
            content_hash=brief.content_hash,
            created_by_user_id=OWNER_ID,
            created_at=NOW,
        ),
    )


def accept(
    service: LocalProjectClarificationApplicationService,
    assumption_id: UUID,
) -> BriefAssumptionDecisionResult:
    return asyncio.run(
        service.accept_assumption(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            assumption_id=assumption_id,
        )
    )


def accept_all(
    service: LocalProjectClarificationApplicationService,
    reason: str | None = None,
) -> BriefAssumptionBulkAcceptanceResult:
    return asyncio.run(
        service.accept_all_assumptions(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            reason=reason,
        )
    )


def test_accepting_assumption_creates_explicit_brief_version() -> None:
    """Keep assumption provenance while materializing accepted content."""
    (
        current_briefs,
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


def test_remaining_proposals_stay_acceptable_after_one_is_accepted() -> None:
    current_briefs, assumptions, service = build_fixture()
    proposals = [
        propose(assumptions, field=BriefField.BUDGET, statement="Approximately EUR 5,000."),
        propose(assumptions, field=BriefField.DOMAIN, statement="Community events."),
        propose(assumptions, field=BriefField.GOALS, statement="Sell tickets online."),
    ]

    results = [accept(service, proposal.id) for proposal in proposals]

    assert [result.status for result in results] == [BriefAssumptionDecisionStatus.ACCEPTED] * 3
    assert [result.version.version_number for result in results if result.version is not None] == [
        2,
        3,
        4,
    ]
    assert all(
        assumption.status is BriefAssumptionStatus.ACCEPTED
        for assumption in assumptions.assumptions
    )

    brief = current_version(current_briefs).brief

    assert brief.budget == "Approximately EUR 5,000."
    assert brief.domain == "Community events."
    assert brief.goals == ("Sell tickets online.",)


def test_proposal_for_a_field_filled_meanwhile_answers_field_already_provided() -> None:
    current_briefs, assumptions, service = build_fixture()
    proposal = propose(assumptions, field=BriefField.BUDGET, statement="Approximately EUR 5,000.")
    fill_brief(current_briefs, create_project_brief(name="Project", budget="EUR 9,000."))

    result = accept(service, proposal.id)

    assert result.status is BriefAssumptionDecisionStatus.FIELD_ALREADY_PROVIDED
    assert result.version is None
    assert assumptions.assumptions == [proposal]
    assert current_version(current_briefs).version_number == 2
    assert current_version(current_briefs).brief.budget == "EUR 9,000."


def test_accept_all_materializes_every_proposal_in_one_version() -> None:
    current_briefs, assumptions, service = build_fixture(
        create_project_brief(
            name="Project",
            unknown_fields=[
                BriefField.BUDGET,
                BriefField.DOMAIN,
                BriefField.GOALS,
            ],
        )
    )
    propose(assumptions, field=BriefField.GOALS, statement="Sell tickets online.")
    propose(assumptions, field=BriefField.DOMAIN, statement="Community events.")
    propose(assumptions, field=BriefField.BUDGET, statement="Approximately EUR 5,000.")

    result = accept_all(service, reason="Confirmed together.")

    assert result.status is BriefAssumptionBulkAcceptanceStatus.ACCEPTED
    assert [assumption.field for assumption in result.accepted] == [
        BriefField.BUDGET,
        BriefField.DOMAIN,
        BriefField.GOALS,
    ]
    assert result.skipped == ()
    assert result.version is not None
    assert result.version.version_number == 2
    assert result.version.brief.budget == "Approximately EUR 5,000."
    assert result.version.brief.domain == "Community events."
    assert result.version.brief.goals == ("Sell tickets online.",)
    assert result.version.brief.unknown_fields == frozenset()
    assert current_version(current_briefs) == result.version
    assert {
        (
            assumption.status,
            assumption.decided_at,
            assumption.decision_reason,
        )
        for assumption in assumptions.assumptions
    } == {
        (
            BriefAssumptionStatus.ACCEPTED,
            NOW,
            "Confirmed together.",
        )
    }


def test_accept_all_keeps_the_first_text_proposal_and_skips_the_later_one() -> None:
    _, assumptions, service = build_fixture()
    later = propose(
        assumptions,
        field=BriefField.BUDGET,
        statement="About EUR 8,000.",
        minutes_before=1,
    )
    first = propose(
        assumptions,
        field=BriefField.BUDGET,
        statement="Approximately EUR 5,000.",
        minutes_before=2,
    )

    result = accept_all(service)

    assert result.status is BriefAssumptionBulkAcceptanceStatus.ACCEPTED
    assert [assumption.id for assumption in result.accepted] == [first.id]
    assert result.skipped == (later,)
    assert result.version is not None
    assert result.version.version_number == 2
    assert result.version.brief.budget == "Approximately EUR 5,000."
    assert assumptions.assumptions[0] == later


def test_accept_all_appends_every_statement_of_a_list_field() -> None:
    _, assumptions, service = build_fixture()
    propose(
        assumptions,
        field=BriefField.GOALS,
        statement="Check guests in at the door.",
        minutes_before=1,
    )
    propose(
        assumptions,
        field=BriefField.GOALS,
        statement="Sell tickets online.",
        minutes_before=2,
    )

    result = accept_all(service)

    assert result.status is BriefAssumptionBulkAcceptanceStatus.ACCEPTED
    assert len(result.accepted) == 2
    assert result.skipped == ()
    assert result.version is not None
    assert result.version.version_number == 2
    assert result.version.brief.goals == (
        "Sell tickets online.",
        "Check guests in at the door.",
    )


def test_accept_all_without_acceptable_proposals_creates_no_version() -> None:
    current_briefs, assumptions, service = build_fixture()
    proposal = propose(assumptions, field=BriefField.NAME, statement="Another name.")
    rejected = reject_brief_assumption(
        propose(assumptions, field=BriefField.BUDGET, statement="Approximately EUR 5,000."),
        decided_by_user_id=OWNER_ID,
        reason="Not relevant.",
        decided_at=NOW,
    )
    assumptions.assumptions[-1] = rejected

    result = accept_all(service)

    assert result.status is BriefAssumptionBulkAcceptanceStatus.NOTHING_TO_ACCEPT
    assert result.accepted == ()
    assert result.skipped == (proposal,)
    assert result.version is None
    assert current_version(current_briefs).version_number == 1
    assert assumptions.assumptions == [proposal, rejected]


def test_accept_all_without_a_brief_reports_brief_not_found() -> None:
    _, _, service = build_fixture()

    result = asyncio.run(
        service.accept_all_assumptions(
            project_id=UUID(int=999),
            owner_user_id=OWNER_ID,
        )
    )

    assert result.status is BriefAssumptionBulkAcceptanceStatus.BRIEF_NOT_FOUND
    assert result.version is None
