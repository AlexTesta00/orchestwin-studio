from __future__ import annotations

import asyncio
import importlib
from datetime import timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from orchestwin.persistence import create_database_runtime
from orchestwin.persistence.migrate import downgrade_database, upgrade_database
from orchestwin.projects.knowledge_alignment import (
    ProposalAlreadyDecided,
    ProposalSection,
    ProposalStatus,
    create_run,
    run_from_snapshot,
)
from orchestwin.projects.persistence.knowledge_alignment import (
    PROPOSALS,
    RUNS,
    SqlAlchemyKnowledgeAlignmentRepository,
)
from orchestwin.projects.persistence.models import ProjectRecord
from src.test.python.integration.postgres_isolation import (
    assert_reversible_migration,
    catalog_snapshot,
    isolated_postgres_settings,
)
from src.test.python.integration.test_postgresql_project_import import seed_users
from src.test.python.integration.test_proposal_evidence_postgres import database, run
from src.test.python.projects.test_knowledge_alignment_domain import (
    DIFF_ID,
    FIRST,
    LATER,
    NOW,
    REQUEST,
    SECOND,
    SUMMARY,
    THIRD,
    update,
)

__all__ = ["database"]
pytestmark = pytest.mark.integration
MIGRATION = importlib.import_module(
    "orchestwin.persistence.migrations.versions.0073_knowledge_alignment"
)
RUNS_TABLE = "knowledge_alignment_runs"
PROPOSALS_TABLE = "knowledge_alignment_proposals"
TABLES = (RUNS_TABLE, PROPOSALS_TABLE)
RUN_COLUMNS = [
    ("id", "uuid", "None", "NO"),
    ("project_id", "uuid", "None", "NO"),
    ("owner_user_id", "uuid", "None", "NO"),
    ("from_commit", "character varying", "64", "YES"),
    ("to_commit", "character varying", "64", "NO"),
    ("commits", "jsonb", "None", "NO"),
    ("locale", "character varying", "20", "NO"),
    ("requirements_version_number", "integer", "None", "NO"),
    ("design_version_number", "integer", "None", "NO"),
    ("alternative_code", "character varying", "16", "NO"),
    ("summary", "text", "None", "NO"),
    ("created_at", "timestamp with time zone", "None", "NO"),
    ("cost_microusd", "integer", "None", "NO"),
    ("generation_ids", "jsonb", "None", "NO"),
]
PROPOSAL_COLUMNS = [
    ("id", "uuid", "None", "NO"),
    ("run_id", "uuid", "None", "NO"),
    ("project_id", "uuid", "None", "NO"),
    ("owner_user_id", "uuid", "None", "NO"),
    ("number", "integer", "None", "NO"),
    ("section", "character varying", "16", "NO"),
    ("title", "character varying", "200", "NO"),
    ("request", "text", "None", "NO"),
    ("rationale", "text", "None", "NO"),
    ("subjects", "jsonb", "None", "NO"),
    ("origin", "jsonb", "None", "NO"),
    ("status", "character varying", "16", "NO"),
    ("created_at", "timestamp with time zone", "None", "NO"),
    ("decided_at", "timestamp with time zone", "None", "YES"),
    ("decision_note", "text", "None", "YES"),
    ("applied_text", "text", "None", "YES"),
    ("applied_diff_id", "uuid", "None", "YES"),
]
RUN_FOREIGN_KEYS = ("fk_knowledge_alignment_runs_project", "fk_knowledge_alignment_runs_owner")
RUN_CONSTRAINTS = (
    "pk_knowledge_alignment_runs",
    *RUN_FOREIGN_KEYS,
    "ck_knowledge_alignment_runs_to_commit",
    "ck_knowledge_alignment_runs_from_commit",
    "ck_knowledge_alignment_runs_commits",
    "ck_knowledge_alignment_runs_locale",
    "ck_knowledge_alignment_runs_versions",
    "ck_knowledge_alignment_runs_alternative_code",
    "ck_knowledge_alignment_runs_summary",
    "ck_knowledge_alignment_runs_cost",
    "ck_knowledge_alignment_runs_generation_ids",
)
PROPOSAL_FOREIGN_KEYS = (
    "fk_knowledge_alignment_proposals_run",
    "fk_knowledge_alignment_proposals_project",
    "fk_knowledge_alignment_proposals_owner",
)
PROPOSAL_CONSTRAINTS = (
    "pk_knowledge_alignment_proposals",
    "uq_knowledge_alignment_proposals_number",
    *PROPOSAL_FOREIGN_KEYS,
    "ck_knowledge_alignment_proposals_number",
    "ck_knowledge_alignment_proposals_section",
    "ck_knowledge_alignment_proposals_title",
    "ck_knowledge_alignment_proposals_request",
    "ck_knowledge_alignment_proposals_rationale",
    "ck_knowledge_alignment_proposals_subjects",
    "ck_knowledge_alignment_proposals_origin",
    "ck_knowledge_alignment_proposals_status",
    "ck_knowledge_alignment_proposals_decision_time",
    "ck_knowledge_alignment_proposals_decision_note",
    "ck_knowledge_alignment_proposals_applied_text",
    "ck_knowledge_alignment_proposals_applied_diff",
)
REJECTED_RUNS = (
    ({"to_commit": "xyz"}, "ck_knowledge_alignment_runs_to_commit"),
    ({"to_commit": FIRST.upper() + "A"}, "ck_knowledge_alignment_runs_to_commit"),
    ({"from_commit": "XYZ"}, "ck_knowledge_alignment_runs_from_commit"),
    ({"commits": []}, "ck_knowledge_alignment_runs_commits"),
    ({"commits": [f"{index:040x}" for index in range(51)]}, "ck_knowledge_alignment_runs_commits"),
    ({"commits": "abc"}, "ck_knowledge_alignment_runs_commits"),
    ({"commits": {"a": 1}}, "ck_knowledge_alignment_runs_commits"),
    ({"locale": "i"}, "ck_knowledge_alignment_runs_locale"),
    ({"requirements_version_number": 0}, "ck_knowledge_alignment_runs_versions"),
    ({"design_version_number": -1}, "ck_knowledge_alignment_runs_versions"),
    ({"alternative_code": "DES-1"}, "ck_knowledge_alignment_runs_alternative_code"),
    ({"summary": ""}, "ck_knowledge_alignment_runs_summary"),
    ({"summary": "x" * 601}, "ck_knowledge_alignment_runs_summary"),
    ({"cost_microusd": -1}, "ck_knowledge_alignment_runs_cost"),
    ({"generation_ids": {}}, "ck_knowledge_alignment_runs_generation_ids"),
    ({"commits": None}, "ck_knowledge_alignment_runs_commits"),
    ({"generation_ids": None}, "ck_knowledge_alignment_runs_generation_ids"),
    ({"project_id": uuid4()}, "fk_knowledge_alignment_runs_project"),
    ({"owner_user_id": uuid4()}, "fk_knowledge_alignment_runs_owner"),
)
REJECTED_PROPOSALS = (
    ({"number": 0}, "ck_knowledge_alignment_proposals_number"),
    ({"number": 1000000}, "ck_knowledge_alignment_proposals_number"),
    ({"section": "MOCKUP"}, "ck_knowledge_alignment_proposals_section"),
    ({"section": "design"}, "ck_knowledge_alignment_proposals_section"),
    ({"title": ""}, "ck_knowledge_alignment_proposals_title"),
    ({"request": ""}, "ck_knowledge_alignment_proposals_request"),
    ({"request": "x" * 2001}, "ck_knowledge_alignment_proposals_request"),
    ({"rationale": "x" * 401}, "ck_knowledge_alignment_proposals_rationale"),
    ({"subjects": []}, "ck_knowledge_alignment_proposals_subjects"),
    ({"origin": "testo"}, "ck_knowledge_alignment_proposals_origin"),
    ({"subjects": None}, "ck_knowledge_alignment_proposals_subjects"),
    ({"origin": None}, "ck_knowledge_alignment_proposals_origin"),
    ({"status": "OPEN", "decided_at": LATER}, "ck_knowledge_alignment_proposals_status"),
    ({"decided_at": LATER}, "ck_knowledge_alignment_proposals_decision_time"),
    ({"status": "APPLIED"}, "ck_knowledge_alignment_proposals_decision_time"),
    ({"decision_note": "Nota."}, "ck_knowledge_alignment_proposals_decision_note"),
    (
        {"status": "SKIPPED", "decided_at": LATER, "decision_note": ""},
        "ck_knowledge_alignment_proposals_decision_note",
    ),
    (
        {"status": "SKIPPED", "decided_at": LATER, "decision_note": "x" * 301},
        "ck_knowledge_alignment_proposals_decision_note",
    ),
    (
        {"status": "SKIPPED", "decided_at": LATER, "applied_text": REQUEST},
        "ck_knowledge_alignment_proposals_applied_text",
    ),
    (
        {"status": "APPLIED", "decided_at": LATER, "applied_text": ""},
        "ck_knowledge_alignment_proposals_applied_text",
    ),
    (
        {"status": "SKIPPED", "decided_at": LATER, "applied_diff_id": DIFF_ID},
        "ck_knowledge_alignment_proposals_applied_diff",
    ),
    ({"run_id": uuid4()}, "fk_knowledge_alignment_proposals_run"),
    ({"project_id": uuid4()}, "fk_knowledge_alignment_proposals_project"),
    ({"owner_user_id": uuid4()}, "fk_knowledge_alignment_proposals_owner"),
)


async def seed_project(db, owner):
    project = uuid4()
    async with db.session_factory() as session, session.begin():
        session.add(
            ProjectRecord(
                id=project,
                owner_user_id=owner,
                display_name="Synthetic knowledge alignment fixture",
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


async def count(db, table):
    async with db.session_factory() as session:
        return await session.scalar(sa.select(sa.func.count()).select_from(table))


def run_row(project, owner, /, **changes):
    return {
        "id": uuid4(),
        "project_id": project,
        "owner_user_id": owner,
        "from_commit": None,
        "to_commit": SECOND,
        "commits": [FIRST, SECOND],
        "locale": "it-IT",
        "requirements_version_number": 1,
        "design_version_number": 1,
        "alternative_code": "DES-001",
        "summary": SUMMARY,
        "created_at": NOW,
        "cost_microusd": 0,
        "generation_ids": [],
        **changes,
    }


def proposal_row(run_id, project, owner, /, **changes):
    return {
        "id": uuid4(),
        "run_id": run_id,
        "project_id": project,
        "owner_user_id": owner,
        "number": 1,
        "section": "REQUIREMENTS",
        "title": "Registrare la data di arrivo",
        "request": REQUEST,
        "rationale": "Il diff salva la data di arrivo.",
        "subjects": {"requirements": ["REQ-001"], "screens": [], "criteria": []},
        "origin": {"commits": [FIRST], "files": ["src/app.js"], "excerpt": "+new"},
        "status": "PROPOSED",
        "created_at": NOW,
        "decided_at": None,
        "decision_note": None,
        "applied_text": None,
        "applied_diff_id": None,
        **changes,
    }


def alignment_run(project, owner, proposals, *, from_commit=None, commits=(FIRST, SECOND), at=NOW):
    return create_run(
        project_id=project,
        owner_user_id=owner,
        from_commit=from_commit,
        commits=commits,
        locale="it-IT",
        requirements_version_number=1,
        design_version_number=1,
        alternative_code="DES-001",
        summary=SUMMARY,
        created_at=at,
        proposals=proposals,
        cost_microusd=120_000,
        generation_ids=(uuid4(),),
    )


def test_isolated_knowledge_alignment_migration_is_reversible(database):
    assert_reversible_migration(database, MIGRATION)


def test_upgrade_on_an_isolated_schema_adds_only_the_two_tables_and_keeps_previous_rows(database):
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
                assert await count(db, RUNS) == 0
                assert await count(db, PROPOSALS) == 0
            finally:
                await db.dispose()

        run(scenario())
        current = catalog_snapshot(scoped)
    assert previous["revision"] == [(MIGRATION.down_revision,)]
    assert current["revision"] == [(MIGRATION.revision,)]
    for name in ("columns", "constraints", "indexes", "triggers"):
        assert [row for row in current[name] if row[0] not in TABLES] == previous[name]
    assert current["functions"] == previous["functions"]
    assert [row[1:5] for row in current["columns"] if row[0] == RUNS_TABLE] == RUN_COLUMNS
    assert [row[1:5] for row in current["columns"] if row[0] == PROPOSALS_TABLE] == (
        PROPOSAL_COLUMNS
    )
    for table, expected, foreign_keys in (
        (RUNS_TABLE, RUN_CONSTRAINTS, RUN_FOREIGN_KEYS),
        (PROPOSALS_TABLE, PROPOSAL_CONSTRAINTS, PROPOSAL_FOREIGN_KEYS),
    ):
        definitions = {row[1]: row[2] for row in current["constraints"] if row[0] == table}
        assert set(expected) <= set(definitions)
        assert all(name.endswith("_not_null") for name in set(definitions) - set(expected))
        assert all(definitions[name].endswith("ON DELETE RESTRICT") for name in foreign_keys)
    indexes = {row[1]: row[2] for row in current["indexes"] if row[0] == RUNS_TABLE}
    assert sorted(indexes) == [
        "ix_knowledge_alignment_runs_project_created",
        "pk_knowledge_alignment_runs",
    ]
    assert indexes["ix_knowledge_alignment_runs_project_created"].endswith(
        "(project_id, created_at)"
    )
    indexes = {row[1]: row[2] for row in current["indexes"] if row[0] == PROPOSALS_TABLE}
    assert sorted(indexes) == [
        "ix_knowledge_alignment_proposals_project_status",
        "pk_knowledge_alignment_proposals",
        "uq_knowledge_alignment_proposals_number",
    ]
    assert indexes["uq_knowledge_alignment_proposals_number"].endswith("(project_id, number)")
    assert [row for row in current["triggers"] if row[0] in TABLES] == []


def test_checks_reject_rows_outside_the_rules_and_numbers_are_unique_per_project(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner = uuid4()
            await seed_users(db, owner)
            project = await seed_project(db, owner)
            other = await seed_project(db, owner)
            run_id = uuid4()

            async def insert(table, row):
                async with db.session_factory() as session, session.begin():
                    await session.execute(sa.insert(table).values(**row))

            for changes, constraint in REJECTED_RUNS:
                with pytest.raises(IntegrityError) as rejected:
                    await insert(RUNS, run_row(project, owner, **changes))
                assert rejected.value.orig.diag.constraint_name == constraint, changes
            for column in ("to_commit", "commits", "locale", "summary", "created_at"):
                with pytest.raises(IntegrityError) as rejected:
                    await insert(RUNS, run_row(project, owner, **{column: sa.null()}))
                assert rejected.value.orig.sqlstate == "23502"
                assert rejected.value.orig.diag.column_name == column
            await insert(RUNS, run_row(project, owner, id=run_id, from_commit=THIRD))
            for changes, constraint in REJECTED_PROPOSALS:
                with pytest.raises(IntegrityError) as rejected:
                    await insert(PROPOSALS, proposal_row(run_id, project, owner, **changes))
                assert rejected.value.orig.diag.constraint_name == constraint, changes
            for column in ("number", "section", "title", "request", "subjects", "status"):
                with pytest.raises(IntegrityError) as rejected:
                    await insert(
                        PROPOSALS, proposal_row(run_id, project, owner, **{column: sa.null()})
                    )
                assert rejected.value.orig.sqlstate == "23502"
                assert rejected.value.orig.diag.column_name == column
            await insert(PROPOSALS, proposal_row(run_id, project, owner))
            await insert(
                PROPOSALS,
                proposal_row(
                    run_id,
                    project,
                    owner,
                    number=2,
                    status="APPLIED",
                    decided_at=LATER,
                    decision_note="Testo rivisto.",
                    applied_text=REQUEST,
                    applied_diff_id=DIFF_ID,
                ),
            )
            await insert(
                PROPOSALS,
                proposal_row(run_id, project, owner, number=3, status="SKIPPED", decided_at=LATER),
            )
            with pytest.raises(IntegrityError) as rejected:
                await insert(PROPOSALS, proposal_row(run_id, project, owner, number=2))
            assert (
                rejected.value.orig.diag.constraint_name
                == "uq_knowledge_alignment_proposals_number"
            )
            other_run = uuid4()
            await insert(RUNS, run_row(other, owner, id=other_run))
            await insert(PROPOSALS, proposal_row(other_run, other, owner, number=1))
            async with db.session_factory() as session, session.begin():
                with pytest.raises(IntegrityError) as rejected:
                    await session.execute(sa.delete(RUNS).where(RUNS.c.id == run_id))
            assert rejected.value.orig.diag.constraint_name == (
                "fk_knowledge_alignment_proposals_run"
            )
            assert await count(db, RUNS) == 2
            assert await count(db, PROPOSALS) == 4
        finally:
            await db.dispose()

    run(scenario())


def test_runs_and_proposals_round_trip_and_are_decided_once(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner = uuid4()
            await seed_users(db, owner)
            project = await seed_project(db, owner)
            first = alignment_run(
                project,
                owner,
                [
                    update(),
                    update(ProposalSection.DESIGN, title="Mostrare la data"),
                    update(ProposalSection.TESTS, title="Coprire la data"),
                ],
            )
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyKnowledgeAlignmentRepository(session, owner_user_id=owner)
                assert await repository.project_exists(project)
                assert await repository.next_number(project) == 1
                stored_first = await repository.create_run(first)
                assert [item.code for item in stored_first.proposals] == [
                    "ALN-001",
                    "ALN-002",
                    "ALN-003",
                ]
                assert stored_first.id == first.id
                assert await repository.next_number(project) == 4
            second = alignment_run(
                project,
                owner,
                [update(title="Seconda corsa"), update(ProposalSection.TESTS, title="Altro")],
                from_commit=SECOND,
                commits=(THIRD,),
                at=NOW + timedelta(hours=2),
            )
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyKnowledgeAlignmentRepository(session, owner_user_id=owner)
                stored_second = await repository.create_run(second)
                assert [item.code for item in stored_second.proposals] == ["ALN-004", "ALN-005"]
            async with db.session_factory() as session:
                repository = SqlAlchemyKnowledgeAlignmentRepository(session, owner_user_id=owner)
                assert await repository.runs(project) == (stored_second, stored_first)
                assert await repository.latest_run(project) == stored_second
                assert await repository.run(project, first.id) == stored_first
                assert await repository.run(project, uuid4()) is None
                assert [item.code for item in await repository.proposals(project)] == [
                    "ALN-005",
                    "ALN-004",
                    "ALN-003",
                    "ALN-002",
                    "ALN-001",
                ]
                assert await repository.proposals(project, waiting_only=True) == (
                    await repository.proposals(project)
                )
                assert await repository.proposal(project, "aln-002") == stored_first.proposals[1]
                assert await repository.proposal(project, "ALN-999") is None
                assert await repository.proposal(project, "TSK-001") is None
                snapshot = stored_second.to_snapshot()
                assert run_from_snapshot(snapshot, owner_user_id=owner) == stored_second
                assert snapshot["from_commit"] == SECOND
                assert snapshot["to_commit"] == THIRD
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyKnowledgeAlignmentRepository(session, owner_user_id=owner)
                applied = await repository.decide(
                    project,
                    "ALN-001",
                    status=ProposalStatus.APPLIED,
                    decided_at=LATER,
                    applied_text=f" {REQUEST} ",
                    applied_diff_id=DIFF_ID,
                )
                assert applied is not None
                assert (applied.status, applied.decided_at) == (ProposalStatus.APPLIED, LATER)
                assert (applied.applied_text, applied.applied_diff_id) == (REQUEST, DIFF_ID)
                skipped = await repository.decide(
                    project,
                    "ALN-004",
                    status=ProposalStatus.SKIPPED,
                    decided_at=LATER,
                    note="  Non riguarda la Definizione.  ",
                )
                assert skipped is not None
                assert (skipped.status, skipped.decision_note) == (
                    ProposalStatus.SKIPPED,
                    "Non riguarda la Definizione.",
                )
                assert (
                    await repository.decide(
                        project, "ALN-999", status=ProposalStatus.SKIPPED, decided_at=LATER
                    )
                    is None
                )
                assert (
                    await repository.decide(
                        project, "ALN-", status=ProposalStatus.SKIPPED, decided_at=LATER
                    )
                    is None
                )
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyKnowledgeAlignmentRepository(session, owner_user_id=owner)
                with pytest.raises(ProposalAlreadyDecided) as refused:
                    await repository.decide(
                        project, "ALN-001", status=ProposalStatus.SKIPPED, decided_at=LATER
                    )
                assert (refused.value.proposal, refused.value.status) == (
                    "ALN-001",
                    ProposalStatus.APPLIED,
                )
            async with db.session_factory() as session, session.begin():
                await session.execute(sa.text("SET LOCAL TIME ZONE 'Europe/Rome'"))
                repository = SqlAlchemyKnowledgeAlignmentRepository(session, owner_user_id=owner)
                waiting = await repository.proposals(project, waiting_only=True)
                assert [item.code for item in waiting] == ["ALN-005", "ALN-003", "ALN-002"]
                assert await repository.proposal(project, "ALN-001") == applied
                assert await repository.proposal(project, "ALN-004") == skipped
                latest = await repository.latest_run(project)
                assert [item.code for item in latest.waiting] == ["ALN-005"]
                assert latest.proposals[0] == skipped
                first_again = await repository.run(project, first.id)
                assert first_again.proposals[0] == applied
                assert first_again.proposals[0].decided_at == LATER
                assert first_again.created_at == NOW
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
                repository = SqlAlchemyKnowledgeAlignmentRepository(session, owner_user_id=owner)
                stored = await repository.create_run(alignment_run(project, owner, [update()]))
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyKnowledgeAlignmentRepository(session, owner_user_id=stranger)
                assert not await repository.project_exists(project)
                assert await repository.runs(project) == ()
                assert await repository.latest_run(project) is None
                assert await repository.run(project, stored.id) is None
                assert await repository.proposals(project) == ()
                assert await repository.proposal(project, "ALN-001") is None
                assert (
                    await repository.decide(
                        project, "ALN-001", status=ProposalStatus.SKIPPED, decided_at=LATER
                    )
                    is None
                )
                with pytest.raises(ValueError, match="owned active project"):
                    await repository.create_run(alignment_run(project, stranger, [update()]))
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyKnowledgeAlignmentRepository(session, owner_user_id=owner)
                with pytest.raises(ValueError, match="owned active project"):
                    await repository.create_run(alignment_run(project, stranger, [update()]))
                with pytest.raises(ValueError, match="owned active project"):
                    await repository.create_run(alignment_run(uuid4(), owner, [update()]))
            async with db.session_factory() as session, session.begin():
                await session.execute(
                    sa.update(ProjectRecord)
                    .where(ProjectRecord.id == project)
                    .values(archived_at=NOW)
                )
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyKnowledgeAlignmentRepository(session, owner_user_id=owner)
                assert not await repository.project_exists(project)
                with pytest.raises(ValueError, match="owned active project"):
                    await repository.create_run(alignment_run(project, owner, [update()]))
                assert (
                    await repository.decide(
                        project, "ALN-001", status=ProposalStatus.SKIPPED, decided_at=LATER
                    )
                    is None
                )
                assert await repository.latest_run(project) == stored
            assert await count(db, RUNS) == 1
            assert await count(db, PROPOSALS) == 1
            async with db.session_factory() as session:
                statuses = (await session.execute(sa.select(PROPOSALS.c.status))).scalars().all()
            assert statuses == ["PROPOSED"]
        finally:
            await db.dispose()

    run(scenario())


def test_writes_wait_for_the_project_lock(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner = uuid4()
            await seed_users(db, owner)
            project = await seed_project(db, owner)
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyKnowledgeAlignmentRepository(session, owner_user_id=owner)
                await repository.create_run(alignment_run(project, owner, [update()]))
            async with db.session_factory() as holder, holder.begin():
                await holder.execute(
                    sa.select(ProjectRecord.id).where(ProjectRecord.id == project).with_for_update()
                )
                for attempt in (
                    lambda repository: repository.create_run(
                        alignment_run(
                            project, owner, [update()], from_commit=SECOND, commits=(THIRD,)
                        )
                    ),
                    lambda repository: repository.decide(
                        project, "ALN-001", status=ProposalStatus.SKIPPED, decided_at=LATER
                    ),
                ):
                    with pytest.raises(sa.exc.OperationalError, match="lock timeout"):
                        async with db.session_factory() as waiter, waiter.begin():
                            await waiter.execute(sa.text("SET LOCAL lock_timeout = '200ms'"))
                            await attempt(
                                SqlAlchemyKnowledgeAlignmentRepository(waiter, owner_user_id=owner)
                            )
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyKnowledgeAlignmentRepository(session, owner_user_id=owner)
                decided = await repository.decide(
                    project, "ALN-001", status=ProposalStatus.SKIPPED, decided_at=LATER
                )
                assert decided is not None and decided.status is ProposalStatus.SKIPPED
            assert await count(db, RUNS) == 1
        finally:
            await db.dispose()

    run(scenario())


def test_downgrade_drops_the_two_tables_and_keeps_previous_rows(database):
    with isolated_postgres_settings(database, revision=MIGRATION.revision) as scoped:

        async def scenario():
            db = create_database_runtime(scoped)
            try:
                owner = uuid4()
                await seed_users(db, owner)
                project = await seed_project(db, owner)
                async with db.session_factory() as session, session.begin():
                    repository = SqlAlchemyKnowledgeAlignmentRepository(
                        session, owner_user_id=owner
                    )
                    await repository.create_run(alignment_run(project, owner, [update()]))
                before = await stored_rows(db)
                await asyncio.to_thread(
                    downgrade_database, scoped, revision=MIGRATION.down_revision
                )
                assert await stored_rows(db) == before
                async with db.session_factory() as session:
                    for table in TABLES:
                        assert (
                            await session.scalar(sa.text(f"SELECT to_regclass('{table}') IS NULL"))
                            is True
                        )
            finally:
                await db.dispose()

        run(scenario())
        snapshot = catalog_snapshot(scoped)
    assert snapshot["revision"] == [(MIGRATION.down_revision,)]
    assert not any(row[0] in TABLES for row in snapshot["columns"])
