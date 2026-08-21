"""Tests for owner-scoped SQLAlchemy Architecture persistence adapters."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.artifacts.architecture_persistence import (
    SqlAlchemyArchitecturePackageRepository,
    SqlAlchemyArchitectureUnitOfWork,
    architecture_diff_from_record,
    architecture_diff_to_record,
    architecture_package_version_from_record,
    architecture_package_version_to_record,
)
from orchestwin.artifacts.architecture_revisions import (
    ArchitectureRevisionDecision,
    decide_architecture_revision,
    propose_architecture_revision,
)
from orchestwin.projects.architecture_application import ArchitectureVersionAppendStatus

from .architecture_fixtures import (
    ARCHITECTURE_CREATED_AT,
    OWNER_ID,
    PROJECT_ID,
    architecture_version,
)

OTHER_OWNER_ID = UUID("00000000-0000-4000-8000-000000000099")


class _FailOnExecuteSession:
    """Reject SQL execution when ownership should fail first."""

    async def execute(self, statement: Any) -> None:
        del statement
        raise AssertionError("foreign creator must be rejected before SQL")


def test_repository_rejects_a_version_created_by_another_owner() -> None:
    """Keep append operations bound to the authenticated repository owner."""
    repository = SqlAlchemyArchitecturePackageRepository(
        cast(AsyncSession, _FailOnExecuteSession()),
        owner_user_id=OWNER_ID,
    )
    foreign_version = replace(
        architecture_version(),
        created_by_user_id=OTHER_OWNER_ID,
    )

    status = asyncio.run(repository.append(foreign_version))

    assert status is ArchitectureVersionAppendStatus.PROJECT_NOT_FOUND


class _EmptyMappingsResult:
    """SQLAlchemy result fixture returning no repository row."""

    def mappings(self):
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
    repository = SqlAlchemyArchitecturePackageRepository(
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
    unit = SqlAlchemyArchitectureUnitOfWork(
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


def test_version_and_diff_records_round_trip_complete_architecture_content() -> None:
    """Preserve complete packages and immutable proposal data across JSONB records."""
    version = architecture_version()
    reconstructed_version = architecture_package_version_from_record(
        architecture_package_version_to_record(version)
    )

    assert reconstructed_version == version
    assert reconstructed_version.package.test_plan.test_cases

    proposed_package = replace(
        version.package,
        open_questions=(
            *version.package.open_questions,
            "Which execution profile should verify this package?",
        ),
    )
    proposal = propose_architecture_revision(
        diff_id=UUID("00000000-0000-4000-8000-000000000701"),
        owner_user_id=OWNER_ID,
        base_version=version,
        proposed_package=proposed_package,
        created_at=ARCHITECTURE_CREATED_AT + timedelta(minutes=1),
    )

    if proposal.diff is None:
        raise AssertionError("Architecture Package diff was not created")

    proposed = proposal.diff
    assert architecture_diff_from_record(architecture_diff_to_record(proposed)) == proposed

    decision = decide_architecture_revision(
        diff=proposed,
        current_version=version,
        decision=ArchitectureRevisionDecision.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=ARCHITECTURE_CREATED_AT + timedelta(minutes=2),
        resulting_version_id=UUID("00000000-0000-4000-8000-000000000702"),
        reason="Approve the refined review question.",
    )

    assert (
        architecture_diff_from_record(architecture_diff_to_record(decision.diff)) == decision.diff
    )


def test_version_record_rejects_tampered_package_content() -> None:
    """Reject persisted snapshots that no longer match their content digest."""
    record = architecture_package_version_to_record(architecture_version())
    snapshot = dict(cast(dict[str, object], record["package_snapshot"]))
    snapshot["open_questions"] = ["Tampered question"]
    record["package_snapshot"] = snapshot

    import pytest

    with pytest.raises(ValueError, match="hash must match"):
        architecture_package_version_from_record(record)
