"""Tests for owner-scoped SQLAlchemy Design persistence adapters."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.artifacts.design_persistence import (
    SqlAlchemyDesignPackageRepository,
    SqlAlchemyDesignUnitOfWork,
    design_diff_from_record,
    design_diff_to_record,
    design_package_version_from_record,
    design_package_version_to_record,
)
from orchestwin.artifacts.design_revisions import (
    DesignRevisionDecision,
    decide_design_revision,
    propose_design_revision,
)
from orchestwin.projects.design_application import DesignVersionAppendStatus

from .design_fixtures import (
    CREATED_AT,
    OWNER_ID,
    PROJECT_ID,
    design_version,
)
from .test_design_package_extension import (
    ASSERTIONS,
    VERDICTS,
    fixture_bound,
    fixture_package,
    plain_package,
    through_json,
)

OTHER_OWNER_ID = UUID("00000000-0000-4000-8000-000000000099")


class _FailOnExecuteSession:
    """Reject SQL execution when ownership should fail first."""

    async def execute(self, statement: Any) -> None:
        del statement
        raise AssertionError("foreign creator must be rejected before SQL")


def test_repository_rejects_a_version_created_by_another_owner() -> None:
    """Keep append operations bound to the authenticated repository owner."""
    repository = SqlAlchemyDesignPackageRepository(
        cast(AsyncSession, _FailOnExecuteSession()),
        owner_user_id=OWNER_ID,
    )
    foreign_version = replace(
        design_version(),
        created_by_user_id=OTHER_OWNER_ID,
    )

    status = asyncio.run(repository.append(foreign_version))

    assert status is DesignVersionAppendStatus.PROJECT_NOT_FOUND


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
    repository = SqlAlchemyDesignPackageRepository(
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
    unit = SqlAlchemyDesignUnitOfWork(
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


def test_version_and_diff_records_round_trip_complete_design_content() -> None:
    """Preserve complete packages and immutable proposal data across JSONB records."""
    version = design_version()
    reconstructed_version = design_package_version_from_record(
        design_package_version_to_record(version)
    )

    assert reconstructed_version == version
    assert reconstructed_version.package.prototype is not None

    proposed_package = replace(
        version.package,
        open_questions=(
            *version.package.open_questions,
            "Which keyboard shortcuts should be visible?",
        ),
    )
    proposal = propose_design_revision(
        diff_id=UUID("00000000-0000-4000-8000-000000000701"),
        owner_user_id=OWNER_ID,
        base_version=version,
        proposed_package=proposed_package,
        created_at=CREATED_AT + timedelta(minutes=1),
    )

    if proposal.diff is None:
        raise AssertionError("Design Package diff was not created")

    proposed = proposal.diff
    assert design_diff_from_record(design_diff_to_record(proposed)) == proposed

    decision = decide_design_revision(
        diff=proposed,
        current_version=version,
        decision=DesignRevisionDecision.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=CREATED_AT + timedelta(minutes=2),
        resulting_version_id=UUID("00000000-0000-4000-8000-000000000702"),
        reason="Approve the refined review question.",
    )

    assert design_diff_from_record(design_diff_to_record(decision.diff)) == decision.diff


def test_version_record_rejects_tampered_package_content() -> None:
    """Reject persisted snapshots that no longer match their content digest."""
    record = design_package_version_to_record(design_version())
    snapshot = dict(cast(dict[str, object], record["package_snapshot"]))
    snapshot["open_questions"] = ["Tampered question"]
    record["package_snapshot"] = snapshot

    import pytest

    with pytest.raises(ValueError, match="hash must match"):
        design_package_version_from_record(record)


def test_records_keep_the_mockup_the_assertions_and_the_verdicts_without_loss() -> None:
    base = design_version(package=plain_package())
    proposed = fixture_package()
    proposal = propose_design_revision(
        diff_id=UUID("00000000-0000-4000-8000-000000000711"),
        owner_user_id=OWNER_ID,
        base_version=base,
        proposed_package=proposed,
        created_at=CREATED_AT + timedelta(minutes=1),
    )

    if proposal.diff is None:
        raise AssertionError("Design Package diff was not created")

    decision = decide_design_revision(
        diff=proposal.diff,
        current_version=base,
        decision=DesignRevisionDecision.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=CREATED_AT + timedelta(minutes=2),
        resulting_version_id=UUID("00000000-0000-4000-8000-000000000712"),
        reason="Il mockup generato rispetta le asserzioni del proprietario.",
    )

    if decision.version is None:
        raise AssertionError("Design Package version was not created")

    version_record = through_json(
        design_package_version_to_record(decision.version),
        "package_snapshot",
    )
    snapshot = cast(dict[str, object], version_record["package_snapshot"])
    critiques = cast(list[dict[str, object]], snapshot["critiques"])

    assert version_record["schema_version"] == 1
    assert version_record["content_hash"] == proposed.content_hash
    assert snapshot["generated_mockup"] == fixture_bound().to_snapshot()
    assert snapshot["owner_assertions"] == list(ASSERTIONS)
    assert [(item["verdict"], item["quote"]) for item in critiques] == list(VERDICTS)
    assert design_package_version_from_record(version_record) == decision.version

    for diff in (proposal.diff, decision.diff):
        record = through_json(design_diff_to_record(diff), "diff_snapshot")
        assert design_diff_from_record(record) == diff


def test_version_record_rejects_a_tampered_generated_mockup() -> None:
    record = through_json(
        design_package_version_to_record(design_version(package=fixture_package())),
        "package_snapshot",
    )
    snapshot = cast(dict[str, Any], record["package_snapshot"])
    screen = snapshot["generated_mockup"]["mockup"]["screens"][0]
    reworded = json.loads(json.dumps(snapshot))
    reworded["owner_assertions"] = ["Il pulsante principale resta in basso."]
    edited = json.loads(json.dumps(snapshot))
    edited["generated_mockup"]["mockup"]["screens"][0]["markup"] = screen["markup"].replace(
        "</h1>", " aggiornati</h1>", 1
    )
    unsafe = json.loads(json.dumps(snapshot))
    unsafe["generated_mockup"]["mockup"]["screens"][0]["markup"] = (
        screen["markup"] + '<a href="#SCR-001" onclick="steal()">Apri</a>'
    )

    import pytest

    with pytest.raises(ValueError, match="hash must match"):
        design_package_version_from_record({**record, "package_snapshot": reworded})

    with pytest.raises(ValueError, match="prototype derived from the generated mockup"):
        design_package_version_from_record({**record, "package_snapshot": edited})

    with pytest.raises(ValueError, match=r"^ATTRIBUTE_FORBIDDEN"):
        design_package_version_from_record({**record, "package_snapshot": unsafe})
