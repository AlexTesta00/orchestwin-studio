from __future__ import annotations

import asyncio
import importlib
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError

from orchestwin.activity import ActivityError, active_session, journal_rows, project_activity
from orchestwin.persistence import create_database_runtime
from orchestwin.persistence.migrate import downgrade_database, upgrade_database
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.projects.persistence.usage_journal import (
    USAGE_EVENTS,
    SqlAlchemyUsageJournalRepository,
)
from src.test.python.integration.postgres_isolation import (
    assert_reversible_migration,
    catalog_snapshot,
    isolated_postgres_settings,
)
from src.test.python.integration.test_postgresql_project_import import seed_users
from src.test.python.integration.test_proposal_evidence_postgres import database, run

__all__ = ["database"]
pytestmark = pytest.mark.integration
MIGRATION = importlib.import_module("orchestwin.persistence.migrations.versions.0071_usage_journal")
TABLE = "project_usage_events"
FUNCTION = "usage_journal_append_only"
NOW = datetime(2026, 10, 4, 9, tzinfo=UTC)
ROME = timezone(timedelta(hours=2))
CODE = "SES-P01"
COLUMNS = [
    ("id", "uuid", "None", "NO"),
    ("project_id", "uuid", "None", "NO"),
    ("owner_user_id", "uuid", "None", "NO"),
    ("session_code", "character varying", "24", "NO"),
    ("sequence", "integer", "None", "NO"),
    ("source", "character varying", "8", "NO"),
    ("kind", "character varying", "32", "NO"),
    ("section", "character varying", "16", "YES"),
    ("target", "character varying", "80", "YES"),
    ("client_at", "timestamp with time zone", "None", "YES"),
    ("received_at", "timestamp with time zone", "None", "NO"),
    ("duration_ms", "integer", "None", "YES"),
    ("status", "character varying", "64", "YES"),
]
FOREIGN_KEYS = (
    "fk_project_usage_events_project_id_projects",
    "fk_project_usage_events_owner_user_id_users",
)
CONSTRAINTS = (
    "pk_project_usage_events",
    *FOREIGN_KEYS,
    "uq_project_usage_event_sequence",
    "ck_project_usage_event_session_code",
    "ck_project_usage_event_sequence",
    "ck_project_usage_event_source",
    "ck_project_usage_event_kind",
    "ck_project_usage_event_section",
    "ck_project_usage_event_target",
    "ck_project_usage_event_duration_ms",
    "ck_project_usage_event_status",
)
REJECTED = (
    ({"kind": "PAGE_SCROLLED"}, "ck_project_usage_event_kind"),
    ({"kind": "GENERATION"}, "ck_project_usage_event_kind"),
    ({"source": "SERVER"}, "ck_project_usage_event_source"),
    ({"section": "DOSSIER"}, "ck_project_usage_event_section"),
    ({"target": "two words"}, "ck_project_usage_event_target"),
    ({"target": "_details"}, "ck_project_usage_event_target"),
    ({"target": "brief\n"}, "ck_project_usage_event_target"),
    ({"status": ""}, "ck_project_usage_event_status"),
    ({"status": "not ok"}, "ck_project_usage_event_status"),
    ({"duration_ms": -1}, "ck_project_usage_event_duration_ms"),
    ({"duration_ms": 86_400_001}, "ck_project_usage_event_duration_ms"),
    ({"session_code": "SES-p01"}, "ck_project_usage_event_session_code"),
    ({"session_code": "SES--1"}, "ck_project_usage_event_session_code"),
    ({"session_code": "P01"}, "ck_project_usage_event_session_code"),
    ({"session_code": "SES-P01\n"}, "ck_project_usage_event_session_code"),
    ({"sequence": 0}, "ck_project_usage_event_sequence"),
    ({"project_id": uuid4()}, "fk_project_usage_events_project_id_projects"),
    ({"owner_user_id": uuid4()}, "fk_project_usage_events_owner_user_id_users"),
)
ACCEPTED = (
    {"session_code": "SES-" + "A" * 20, "target": "a" * 80, "status": "Z" * 64},
    {
        "source": "UT",
        "kind": "GENERATION_WAITED",
        "section": None,
        "target": "design",
        "duration_ms": 0,
        "status": "200",
    },
    {
        "source": "UT",
        "kind": "COMMAND_FINISHED",
        "section": None,
        "target": "design",
        "duration_ms": 86_400_000,
        "status": "0",
    },
    {"source": "STUDIO", "kind": "SESSION_ENDED", "section": None, "client_at": None},
    {"kind": "WHY_OPENED", "section": "PACKAGE", "target": "artifact:REQ-001_v1.2"},
)


async def seed_project(db, owner):
    project = uuid4()
    async with db.session_factory() as session, session.begin():
        session.add(
            ProjectRecord(
                id=project,
                owner_user_id=owner,
                display_name="Synthetic usage journal fixture",
                mode="GREENFIELD_GENERATION",
                created_at=NOW,
                updated_at=NOW,
            )
        )
    return project


async def stored_rows(db):
    async with db.session_factory() as session:
        return {
            table: (
                await session.execute(
                    sa.text(f"SELECT row_to_json(t)::text FROM {table} t ORDER BY id")
                )
            )
            .scalars()
            .all()
            for table in ("users", "projects")
        }


def event(project, owner, **changes):
    return {
        "id": uuid4(),
        "project_id": project,
        "owner_user_id": owner,
        "session_code": CODE,
        "sequence": 1,
        "source": "WEB",
        "kind": "SECTION_OPENED",
        "section": "BRIEF",
        "target": None,
        "client_at": NOW,
        "received_at": NOW,
        "duration_ms": None,
        "status": None,
        **changes,
    }


def studio(kind):
    return {"session_code": CODE, "source": "STUDIO", "kind": kind}


def at(seconds):
    return (NOW + timedelta(seconds=seconds)).astimezone(ROME).isoformat()


def expected(sequence, source, kind, received, *, client=None, **fields):
    return {
        "sequence": sequence,
        "session_code": CODE,
        "source": source,
        "kind": kind,
        "section": fields.get("section"),
        "target": fields.get("target"),
        "client_at": None if client is None else (NOW + timedelta(seconds=client)).isoformat(),
        "received_at": (NOW + timedelta(seconds=received)).isoformat(),
        "duration_ms": fields.get("duration_ms"),
        "status": fields.get("status"),
    }


def test_isolated_usage_journal_migration_is_reversible(database):
    assert_reversible_migration(database, MIGRATION)


def test_upgrade_on_an_isolated_schema_adds_only_the_journal_and_keeps_previous_rows(database):
    with isolated_postgres_settings(database, revision=MIGRATION.down_revision) as scoped:
        previous = catalog_snapshot(scoped)

        async def scenario():
            db = create_database_runtime(scoped)
            try:
                owner = uuid4()
                await seed_users(db, owner)
                await seed_project(db, owner)
                before = await stored_rows(db)
                await asyncio.to_thread(upgrade_database, scoped, revision=MIGRATION.revision)
                assert await stored_rows(db) == before
                async with db.session_factory() as session:
                    assert (
                        await session.scalar(sa.select(sa.func.count()).select_from(USAGE_EVENTS))
                        == 0
                    )
            finally:
                await db.dispose()

        run(scenario())
        current = catalog_snapshot(scoped)
    assert previous["revision"] == [(MIGRATION.down_revision,)]
    assert current["revision"] == [(MIGRATION.revision,)]
    for name in ("columns", "constraints", "indexes", "triggers"):
        assert [row for row in current[name] if row[0] != TABLE] == previous[name]
    assert [row for row in current["functions"] if row[0] != FUNCTION] == previous["functions"]
    assert [row[0] for row in current["functions"] if row[0] == FUNCTION] == [FUNCTION]
    assert [row[1:5] for row in current["columns"] if row[0] == TABLE] == COLUMNS
    definitions = {row[1]: row[2] for row in current["constraints"] if row[0] == TABLE}
    assert set(CONSTRAINTS) <= set(definitions)
    assert all(name.endswith("_not_null") for name in set(definitions) - set(CONSTRAINTS))
    assert all(definitions[name].endswith("ON DELETE RESTRICT") for name in FOREIGN_KEYS)
    indexes = {row[1]: row[2] for row in current["indexes"] if row[0] == TABLE}
    assert sorted(indexes) == ["pk_project_usage_events", "uq_project_usage_event_sequence"]
    assert indexes["uq_project_usage_event_sequence"].endswith("(project_id, sequence)")
    assert [row[1] for row in current["triggers"] if row[0] == TABLE] == [f"{TABLE}_immutable"]


def test_checks_reject_values_outside_the_rules_and_sequence_is_unique_per_project(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner = uuid4()
            await seed_users(db, owner)
            project = await seed_project(db, owner)
            other = await seed_project(db, owner)

            async def insert(*, into=project, **changes):
                async with db.session_factory() as session, session.begin():
                    await session.execute(
                        sa.insert(USAGE_EVENTS).values(**event(into, owner, **changes))
                    )

            for changes, constraint in REJECTED:
                with pytest.raises(IntegrityError) as rejected:
                    await insert(**changes)
                assert rejected.value.orig.diag.constraint_name == constraint, changes
            for column in ("session_code", "sequence", "source", "kind", "received_at"):
                with pytest.raises(IntegrityError) as rejected:
                    await insert(**{column: None})
                assert rejected.value.orig.sqlstate == "23502"
                assert rejected.value.orig.diag.column_name == column
            for sequence, changes in enumerate(ACCEPTED, start=1):
                await insert(sequence=sequence, **changes)
            with pytest.raises(IntegrityError) as rejected:
                await insert(sequence=1)
            assert rejected.value.orig.diag.constraint_name == "uq_project_usage_event_sequence"
            await insert(into=other, sequence=1)
            for statement in (
                sa.update(USAGE_EVENTS)
                .where(USAGE_EVENTS.c.project_id == project)
                .values(status="EDITED"),
                sa.delete(USAGE_EVENTS).where(USAGE_EVENTS.c.project_id == project),
            ):
                with pytest.raises(DBAPIError, match="append-only"):
                    async with db.session_factory() as session, session.begin():
                        await session.execute(statement)
            async with db.session_factory() as session:
                counts = dict(
                    (
                        await session.execute(
                            sa.select(USAGE_EVENTS.c.project_id, sa.func.count()).group_by(
                                USAGE_EVENTS.c.project_id
                            )
                        )
                    ).all()
                )
            assert counts == {project: len(ACCEPTED), other: 1}
        finally:
            await db.dispose()

    run(scenario())


def test_two_consecutive_writes_get_contiguous_sequences_and_read_back_in_utc(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner = uuid4()
            await seed_users(db, owner)
            project = await seed_project(db, owner)
            async with db.session_factory() as session, session.begin():
                journal = SqlAlchemyUsageJournalRepository(session, owner_user_id=owner)
                assert await journal.owned(project, lock=True) is True
                assert (
                    await journal.append(project, [studio("SESSION_STARTED")], received_at=NOW) == 1
                )
                web = journal_rows(
                    source="WEB",
                    session_code=CODE,
                    events=[
                        {"kind": "SECTION_OPENED", "section": "BRIEF", "client_at": at(1)},
                        {
                            "kind": "DETAIL_OPENED",
                            "section": "BRIEF",
                            "target": "brief-assumptions",
                            "client_at": at(2),
                        },
                    ],
                )
                assert (
                    await journal.append(project, web, received_at=NOW + timedelta(seconds=3)) == 2
                )
            async with db.session_factory() as session:
                journal = SqlAlchemyUsageJournalRepository(session, owner_user_id=owner)
                assert active_session(await journal.rows(project)) == {
                    "code": CODE,
                    "started_at": NOW.isoformat(),
                }
            async with db.session_factory() as session, session.begin():
                journal = SqlAlchemyUsageJournalRepository(session, owner_user_id=owner)
                assert await journal.owned(project, lock=True) is True
                assert await journal.count(project) == 3
                ut = journal_rows(
                    source="UT",
                    session_code=CODE,
                    events=[
                        {"kind": "COMMAND_STARTED", "target": "design", "client_at": at(5)},
                        {
                            "kind": "COMMAND_FINISHED",
                            "target": "design",
                            "status": "0",
                            "duration_ms": 1500,
                            "client_at": at(8),
                        },
                    ],
                )
                assert (
                    await journal.append(project, ut, received_at=NOW + timedelta(seconds=9)) == 2
                )
                assert (
                    await journal.append(
                        project, [studio("SESSION_ENDED")], received_at=NOW + timedelta(seconds=10)
                    )
                    == 1
                )
            async with db.session_factory() as session, session.begin():
                await session.execute(sa.text("SET LOCAL TIME ZONE 'Europe/Rome'"))
                journal = SqlAlchemyUsageJournalRepository(session, owner_user_id=owner)
                rows = await journal.rows(project)
                assert await journal.count(project) == 6
            assert rows == [
                expected(1, "STUDIO", "SESSION_STARTED", 0),
                expected(2, "WEB", "SECTION_OPENED", 3, client=1, section="BRIEF"),
                expected(
                    3,
                    "WEB",
                    "DETAIL_OPENED",
                    3,
                    client=2,
                    section="BRIEF",
                    target="brief-assumptions",
                ),
                expected(4, "UT", "COMMAND_STARTED", 9, client=5, target="design"),
                expected(
                    5,
                    "UT",
                    "COMMAND_FINISHED",
                    9,
                    client=8,
                    target="design",
                    duration_ms=1500,
                    status="0",
                ),
                expected(6, "STUDIO", "SESSION_ENDED", 10),
            ]
            assert active_session(rows) is None
            document = project_activity(project_id=str(project), facts=[], journal=rows)
            assert document["sessions"] == [
                {
                    "code": CODE,
                    "started_at": NOW.isoformat(),
                    "ended_at": (NOW + timedelta(seconds=10)).isoformat(),
                    "events": 6,
                    "sources": ["STUDIO", "UT", "WEB"],
                    "discarded_intervals": 0,
                }
            ]
            assert document["sections"][0]["journal"]["dwell_seconds"] == 1.0
        finally:
            await db.dispose()

    run(scenario())


def test_another_owner_neither_sees_nor_writes_and_an_archived_project_is_closed(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, stranger = uuid4(), uuid4()
            await seed_users(db, owner, stranger)
            project = await seed_project(db, owner)
            async with db.session_factory() as session, session.begin():
                journal = SqlAlchemyUsageJournalRepository(session, owner_user_id=owner)
                assert (
                    await journal.append(project, [studio("SESSION_STARTED")], received_at=NOW) == 1
                )
            async with db.session_factory() as session, session.begin():
                journal = SqlAlchemyUsageJournalRepository(session, owner_user_id=stranger)
                assert await journal.owned(project) is False
                assert await journal.owned(project, lock=True) is False
                assert await journal.rows(project) == []
                assert await journal.count(project) == 0
                with pytest.raises(ActivityError, match="PROJECT_NOT_FOUND"):
                    await journal.append(project, [studio("SESSION_ENDED")], received_at=NOW)
            async with db.session_factory() as session, session.begin():
                await session.execute(
                    sa.update(ProjectRecord)
                    .where(ProjectRecord.id == project)
                    .values(archived_at=NOW)
                )
            async with db.session_factory() as session, session.begin():
                journal = SqlAlchemyUsageJournalRepository(session, owner_user_id=owner)
                assert await journal.owned(project, lock=True) is False
                with pytest.raises(ActivityError, match="PROJECT_NOT_FOUND"):
                    await journal.append(project, [studio("SESSION_ENDED")], received_at=NOW)
            async with db.session_factory() as session:
                stored = (
                    await session.execute(
                        sa.select(USAGE_EVENTS.c.owner_user_id, USAGE_EVENTS.c.kind).where(
                            USAGE_EVENTS.c.project_id == project
                        )
                    )
                ).all()
            assert [tuple(row) for row in stored] == [(owner, "SESSION_STARTED")]
        finally:
            await db.dispose()

    run(scenario())


def test_append_waits_for_the_project_lock_taken_by_owned(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner = uuid4()
            await seed_users(db, owner)
            project = await seed_project(db, owner)
            async with db.session_factory() as holder, holder.begin():
                assert await SqlAlchemyUsageJournalRepository(holder, owner_user_id=owner).owned(
                    project, lock=True
                )
                with pytest.raises(sa.exc.OperationalError, match="lock timeout"):
                    async with db.session_factory() as waiter, waiter.begin():
                        await waiter.execute(sa.text("SET LOCAL lock_timeout = '200ms'"))
                        await SqlAlchemyUsageJournalRepository(waiter, owner_user_id=owner).append(
                            project, [studio("SESSION_STARTED")], received_at=NOW
                        )
            async with db.session_factory() as session, session.begin():
                journal = SqlAlchemyUsageJournalRepository(session, owner_user_id=owner)
                assert (
                    await journal.append(project, [studio("SESSION_STARTED")], received_at=NOW) == 1
                )
                assert await journal.count(project) == 1
        finally:
            await db.dispose()

    run(scenario())


def test_downgrade_refuses_a_journal_with_rows_and_keeps_them(database):
    with isolated_postgres_settings(database, revision=MIGRATION.revision) as scoped:

        async def scenario():
            db = create_database_runtime(scoped)
            try:
                owner = uuid4()
                await seed_users(db, owner)
                project = await seed_project(db, owner)
                async with db.session_factory() as session, session.begin():
                    journal = SqlAlchemyUsageJournalRepository(session, owner_user_id=owner)
                    assert (
                        await journal.append(
                            project,
                            [studio("SESSION_STARTED"), studio("SESSION_ENDED")],
                            received_at=NOW,
                        )
                        == 2
                    )
                with pytest.raises(
                    RuntimeError, match="usage journal events must be preserved before downgrade"
                ):
                    await asyncio.to_thread(
                        downgrade_database, scoped, revision=MIGRATION.down_revision
                    )
                async with db.session_factory() as session:
                    journal = SqlAlchemyUsageJournalRepository(session, owner_user_id=owner)
                    assert [row["kind"] for row in await journal.rows(project)] == [
                        "SESSION_STARTED",
                        "SESSION_ENDED",
                    ]
            finally:
                await db.dispose()

        run(scenario())
        snapshot = catalog_snapshot(scoped)
    assert snapshot["revision"] == [(MIGRATION.revision,)]
    assert [row[0] for row in snapshot["functions"] if row[0] == FUNCTION] == [FUNCTION]


def test_downgrade_of_an_empty_journal_drops_it_and_keeps_previous_rows(database):
    with isolated_postgres_settings(database, revision=MIGRATION.revision) as scoped:

        async def scenario():
            db = create_database_runtime(scoped)
            try:
                owner = uuid4()
                await seed_users(db, owner)
                await seed_project(db, owner)
                before = await stored_rows(db)
                await asyncio.to_thread(
                    downgrade_database, scoped, revision=MIGRATION.down_revision
                )
                assert await stored_rows(db) == before
                async with db.session_factory() as session:
                    assert (
                        await session.scalar(
                            sa.text("SELECT to_regclass('project_usage_events') IS NULL")
                        )
                        is True
                    )
            finally:
                await db.dispose()

        run(scenario())
        snapshot = catalog_snapshot(scoped)
    assert snapshot["revision"] == [(MIGRATION.down_revision,)]
    assert not any(row[0] == FUNCTION for row in snapshot["functions"])
    assert not any(row[0] == TABLE for row in snapshot["columns"])
