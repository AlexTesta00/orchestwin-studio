from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.projects.requirements import (
    RequirementKind,
    RequirementPriority,
    create_requirement,
    create_user_story,
)
from orchestwin.projects.requirements_application import (
    RequirementsVersionAppendStatus,
)
from orchestwin.projects.requirements_persistence import (
    SqlAlchemyRequirementsSpecificationRepository,
    SqlAlchemyRequirementsUnitOfWork,
    diff_from_record,
    diff_to_record,
    specification_version_from_record,
    specification_version_to_record,
)
from orchestwin.projects.requirements_primitives import (
    RequirementsContextKind,
    RequirementsContextReference,
    RequirementSourceKind,
    RequirementSourceReference,
    UserTwinVersionReference,
)
from orchestwin.projects.requirements_quality import (
    DefinitionOfDoneApplicability,
    VerificationMethod,
    create_acceptance_criterion,
    create_definition_of_done_item,
    create_usage_scenario,
)
from orchestwin.projects.requirements_revisions import (
    RequirementsDiffStatus,
    approve_requirements_diff,
    propose_requirements_diff,
)
from orchestwin.projects.requirements_specifications import (
    RequirementsSpecificationVersion,
    create_requirements_specification,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000001")
OWNER_ID = UUID("00000000-0000-4000-8000-000000000002")
OTHER_OWNER_ID = UUID("00000000-0000-4000-8000-000000000099")
VERSION_ID = UUID("00000000-0000-4000-8000-000000000003")
NEXT_VERSION_ID = UUID("00000000-0000-4000-8000-000000000004")
REQUIREMENT_ID = UUID("00000000-0000-4000-8000-000000000010")
STORY_ID = UUID("00000000-0000-4000-8000-000000000020")
CRITERION_ID = UUID("00000000-0000-4000-8000-000000000030")
SCENARIO_ID = UUID("00000000-0000-4000-8000-000000000040")
DOD_ID = UUID("00000000-0000-4000-8000-000000000050")
TWIN_ID = UUID("00000000-0000-4000-8000-000000000060")
DIFF_ID = UUID("00000000-0000-4000-8000-000000000070")
CREATED_AT = datetime(2026, 8, 18, 10, 0, tzinfo=UTC)


def context_reference(
    kind: RequirementsContextKind,
    ordinal: int,
) -> RequirementsContextReference:
    """Create one exact governed context reference."""
    return RequirementsContextReference(
        kind=kind,
        artifact_id=UUID(int=ordinal),
        version_number=1,
        content_hash=f"{ordinal:x}" * 64,
    )


def twin_reference() -> UserTwinVersionReference:
    """Create one exact User Twin reference."""
    return UserTwinVersionReference(
        twin_id=TWIN_ID,
        version_number=2,
        content_hash="a" * 64,
        name="Hotel Receptionist Twin",
    )


def source() -> RequirementSourceReference:
    """Create one exact Project Brief source."""
    return RequirementSourceReference(
        kind=RequirementSourceKind.PROJECT_BRIEF,
        source_id="brief-version",
        source_version=1,
        content_hash="b" * 64,
        locator="functional_requirements[0]",
    )


def specification_version() -> RequirementsSpecificationVersion:
    """Create one complete versioned requirements fixture."""
    requirement = create_requirement(
        requirement_id=REQUIREMENT_ID,
        code="REQ-001",
        title="Create reservations",
        statement="The system must create reservations.",
        kind=RequirementKind.FUNCTIONAL,
        priority=RequirementPriority.MUST,
        sources=(source(),),
        user_twin_references=(twin_reference(),),
    )
    story = create_user_story(
        story_id=STORY_ID,
        code="USR-001",
        user_twin_reference=twin_reference(),
        goal="create a reservation",
        benefit="serve a guest accurately",
        requirement_ids=(REQUIREMENT_ID,),
    )
    criterion = create_acceptance_criterion(
        criterion_id=CRITERION_ID,
        code="AC-001",
        statement="A reservation receives a unique identifier.",
        verification_method=VerificationMethod.AUTOMATED_TEST,
        requirement_ids=(REQUIREMENT_ID,),
        user_story_ids=(STORY_ID,),
    )
    scenario = create_usage_scenario(
        scenario_id=SCENARIO_ID,
        code="SCN-001",
        title="Create a reservation",
        actor=twin_reference(),
        preconditions=(),
        trigger="A guest requests a room.",
        steps=("Save the reservation.",),
        expected_outcome="The reservation can be retrieved.",
        requirement_ids=(REQUIREMENT_ID,),
        acceptance_criterion_ids=(CRITERION_ID,),
    )
    done = create_definition_of_done_item(
        item_id=DOD_ID,
        code="DOD-001",
        statement="All automated acceptance tests pass.",
        verification_method=VerificationMethod.AUTOMATED_TEST,
        applicability=DefinitionOfDoneApplicability.REQUIRED,
        requirement_ids=(REQUIREMENT_ID,),
    )
    specification = create_requirements_specification(
        project_id=PROJECT_ID,
        project_brief_reference=context_reference(
            RequirementsContextKind.PROJECT_BRIEF,
            11,
        ),
        agent_team_reference=context_reference(
            RequirementsContextKind.AGENT_TEAM,
            12,
        ),
        user_modeling_reference=context_reference(
            RequirementsContextKind.USER_MODELING,
            13,
        ),
        catalog_version=1,
        catalog_content_hash="c" * 64,
        user_twin_references=(twin_reference(),),
        requirements=(requirement,),
        user_stories=(story,),
        acceptance_criteria=(criterion,),
        scenarios=(scenario,),
        risks=(),
        definition_of_done=(done,),
    )

    return RequirementsSpecificationVersion(
        id=VERSION_ID,
        project_id=PROJECT_ID,
        version_number=1,
        specification=specification,
        content_hash=specification.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )


def proposed_diff():
    """Create one explicit requirements diff fixture."""
    base = specification_version()
    requirement = replace(
        base.specification.requirements[0],
        statement="The system must create and update reservations.",
    )
    proposed = replace(
        base.specification,
        requirements=(requirement,),
    )
    result = propose_requirements_diff(
        base_version=base,
        proposed_specification=proposed,
        diff_id=DIFF_ID,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT + timedelta(minutes=1),
    )

    if result.diff is None:
        raise AssertionError("requirements diff fixture was not created")

    return result.diff


def test_specification_record_round_trips_traceability_and_coverage() -> None:
    """Preserve the complete canonical version and derived audit views."""
    version = specification_version()
    record = specification_version_to_record(version)

    reconstructed = specification_version_from_record(record)

    assert reconstructed == version
    assert record["traceability_hash"]
    assert record["traceability_snapshot"]
    assert record["coverage_snapshot"]


def test_specification_record_rejects_tampered_traceability() -> None:
    """Do not trust a persisted traceability payload that no longer matches."""
    record = specification_version_to_record(specification_version())
    record["traceability_hash"] = "0" * 64

    with pytest.raises(
        ValueError,
        match="traceability hash does not match",
    ):
        specification_version_from_record(record)


def test_requirements_diff_records_round_trip_before_and_after_decision() -> None:
    """Preserve immutable proposal data and later owner decision metadata."""
    proposed = proposed_diff()
    reconstructed = diff_from_record(diff_to_record(proposed))

    assert reconstructed == proposed
    assert reconstructed.status is RequirementsDiffStatus.PROPOSED

    decision = approve_requirements_diff(
        proposed,
        actor_user_id=OWNER_ID,
        occurred_at=CREATED_AT + timedelta(minutes=2),
        applied_specification_version_id=NEXT_VERSION_ID,
    )
    approved = decision.diff
    approved_record = diff_to_record(approved)

    assert diff_from_record(approved_record) == approved
    assert approved.applied_specification_version_id == NEXT_VERSION_ID


class _FailOnExecuteSession:
    """Reject SQL execution when ownership should fail first."""

    async def execute(self, statement: Any) -> None:
        del statement
        raise AssertionError("foreign creator must be rejected before SQL")


def test_repository_rejects_a_version_created_by_another_owner() -> None:
    """Keep append operations bound to the authenticated repository owner."""
    repository = SqlAlchemyRequirementsSpecificationRepository(
        cast(AsyncSession, _FailOnExecuteSession()),
        owner_user_id=OWNER_ID,
    )
    foreign_version = replace(
        specification_version(),
        created_by_user_id=OTHER_OWNER_ID,
    )

    status = asyncio.run(repository.append(foreign_version))

    assert status is RequirementsVersionAppendStatus.PROJECT_NOT_FOUND


class _EmptyMappingsResult:
    """SQLAlchemy result fixture returning no repository row."""

    def mappings(self) -> _EmptyMappingsResult:
        return self

    def one_or_none(self) -> None:
        return None


class _RecordingSession:
    """Capture SQL statements without contacting PostgreSQL."""

    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> _EmptyMappingsResult:
        self.statements.append(statement)
        return _EmptyMappingsResult()


async def _read_current_with_recording_session(
    session: _RecordingSession,
) -> None:
    repository = SqlAlchemyRequirementsSpecificationRepository(
        cast(AsyncSession, session),
        owner_user_id=OWNER_ID,
    )

    await repository.current(project_id=PROJECT_ID)


def test_repository_current_query_is_owner_scoped() -> None:
    """Keep foreign and missing projects observationally equivalent."""
    session = _RecordingSession()

    asyncio.run(_read_current_with_recording_session(session))

    statement = session.statements[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "EXISTS" in sql.upper()
    assert "owner_user_id" in sql
    assert str(OWNER_ID) in sql


class _TransactionalSession:
    """Record Unit of Work commit and rollback behavior."""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


async def _exercise_unit_of_work(
    session: _TransactionalSession,
    *,
    commit: bool,
) -> None:
    unit = SqlAlchemyRequirementsUnitOfWork(
        cast(AsyncSession, session),
        owner_user_id=OWNER_ID,
    )

    async with unit:
        if commit:
            await unit.commit()


def test_unit_of_work_commits_explicitly_and_rolls_back_otherwise() -> None:
    """Keep transaction completion explicit at the application boundary."""
    committed = _TransactionalSession()
    rolled_back = _TransactionalSession()

    asyncio.run(_exercise_unit_of_work(committed, commit=True))
    asyncio.run(_exercise_unit_of_work(rolled_back, commit=False))

    assert committed.commits == 1
    assert committed.rollbacks == 0
    assert rolled_back.commits == 0
    assert rolled_back.rollbacks == 1
