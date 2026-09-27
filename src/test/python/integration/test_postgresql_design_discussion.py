from __future__ import annotations

import importlib
import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError

from orchestwin.api import design_loop
from orchestwin.api.design_discussion import (
    DesignDiscussionApplication,
    DesignDiscussionCommandStatus,
    DesignDiscussionRequest,
    DiscussionAction,
    DiscussionDecisionRequest,
    DiscussionRoundRequest,
)
from orchestwin.api.services import ApplicationRuntime
from orchestwin.artifacts.design_discussion import MAX_DISCUSSION_ROUNDS, DiscussionStatus
from orchestwin.artifacts.design_discussion_persistence import (
    DISCUSSIONS,
    ROUNDS,
    DiscussionWriteStatus,
    SqlAlchemyDesignDiscussionRepository,
)
from orchestwin.models.proposal_evidence_persistence import (
    GENERATIONS,
    SqlAlchemyProposalEvidenceStore,
)
from orchestwin.models.twin_discussion import speak_as_twin, statement_context, twin_keys
from orchestwin.persistence import create_database_runtime, load_database_settings
from orchestwin.persistence.migrate import downgrade_database
from orchestwin.projects.insight_applications import (
    InsightSourceKind,
    InsightTarget,
    create_insight_application,
)
from orchestwin.projects.persistence.insight_applications import (
    APPLICATIONS,
    InsightApplicationWriteStatus,
    SqlAlchemyInsightApplicationRepository,
)
from orchestwin.twins.epistemics import ObservationValue
from src.test.python.artifacts import design_fixtures
from src.test.python.artifacts.test_design_discussion import NOW, discussion, discussion_round
from src.test.python.integration.postgres_isolation import assert_reversible_migration
from src.test.python.integration.test_postgresql_design_loop import seed
from src.test.python.integration.test_proposal_evidence_postgres import database, run
from src.test.python.models.test_proposal_evidence import Command, audited_generator
from src.test.python.models.test_twin_discussion import STATEMENT, twins
from src.test.python.twins.test_user_modeling_persistence import observation

__all__ = ["database"]

pytestmark = pytest.mark.integration

MIGRATION = importlib.import_module(
    "orchestwin.persistence.migrations.versions.0059_twin_discussions"
)


def seeded(version, *, rounds=1, hours=0):
    return discussion(
        id=uuid4(),
        project_id=version.project_id,
        owner_user_id=design_fixtures.OWNER_ID,
        design_version_id=version.id,
        design_version_number=version.version_number,
        design_content_hash=version.content_hash,
        alternative_id=design_fixtures.ALTERNATIVE_ONE_ID,
        alternative_code="DES-001",
        locale="en-US",
        created_at=NOW + timedelta(hours=hours),
        rounds=tuple(
            discussion_round(ordinal, minutes=60 * hours + ordinal)
            for ordinal in range(1, rounds + 1)
        ),
    )


async def count(session, table):
    return (await session.execute(sa.select(sa.func.count()).select_from(table))).scalar_one()


def header_row(item, **changes):
    return {
        "id": uuid4(),
        "project_id": item.project_id,
        "owner_user_id": item.owner_user_id,
        "design_version_id": item.design_version_id,
        "design_version_number": item.design_version_number,
        "design_content_hash": item.design_content_hash,
        "alternative_id": item.alternative_id,
        "alternative_code": item.alternative_code,
        "locale": item.locale,
        "status": DiscussionStatus.CLOSED.value,
        "created_at": item.created_at,
        "decided_at": item.created_at,
        **changes,
    }


def test_discussions_round_trip_and_stay_unique_while_open(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, version = await seed(db)
            first = seeded(version)
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyDesignDiscussionRepository(session, owner_user_id=owner)
                assert (
                    await repository.open_for_version(
                        project_id=project, design_version_id=version.id
                    )
                    is None
                )
                assert await repository.create(first) is DiscussionWriteStatus.WRITTEN
                assert (
                    await repository.create(seeded(version, hours=1))
                    is DiscussionWriteStatus.DISCUSSION_OPEN
                )
                stranger = SqlAlchemyDesignDiscussionRepository(session, owner_user_id=uuid4())
                assert await stranger.create(first) is DiscussionWriteStatus.PROJECT_NOT_FOUND
                assert await stranger.list(project_id=project) == ()
                assert await stranger.get(project_id=project, discussion_id=first.id) is None
            async with db.session_factory() as session:
                repository = SqlAlchemyDesignDiscussionRepository(session, owner_user_id=owner)
                assert await repository.get(project_id=project, discussion_id=first.id) == first
                assert await repository.get(project_id=uuid4(), discussion_id=first.id) is None
                assert (
                    await repository.open_for_version(
                        project_id=project, design_version_id=version.id
                    )
                    == first
                )
                assert await repository.list(project_id=project) == (first,)
                stored = (
                    await session.execute(sa.select(ROUNDS.c.round_snapshot, ROUNDS.c.content_hash))
                ).one()
                assert stored.round_snapshot == first.rounds[0].to_snapshot()
                assert stored.content_hash == first.rounds[0].content_hash
                assert await session.scalar(sa.select(DISCUSSIONS.c.locale)) == "en-US"
            async with db.session_factory() as session, session.begin():
                racing = SqlAlchemyDesignDiscussionRepository(session, owner_user_id=owner)

                async def unseen(*_):
                    return None

                racing._open_discussion_id = unseen
                assert (
                    await racing.create(seeded(version, hours=2))
                    is DiscussionWriteStatus.DISCUSSION_OPEN
                )
                assert await racing.list(project_id=project) == (first,)
            async with db.session_factory() as session:
                assert await count(session, DISCUSSIONS) == 1
                assert await count(session, ROUNDS) == 1
        finally:
            await db.dispose()

    run(scenario())


def test_rounds_append_in_order_until_the_limit_and_a_decision_is_final(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, version = await seed(db)
            first = seeded(version)
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyDesignDiscussionRepository(session, owner_user_id=owner)
                assert await repository.create(first) is DiscussionWriteStatus.WRITTEN
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyDesignDiscussionRepository(session, owner_user_id=owner)
                for arguments, status in (
                    ({"discussion_id": uuid4()}, DiscussionWriteStatus.DISCUSSION_NOT_FOUND),
                    ({"project_id": uuid4()}, DiscussionWriteStatus.DISCUSSION_NOT_FOUND),
                    ({"expected_round_count": 0}, DiscussionWriteStatus.DISCUSSION_CHANGED),
                    ({"round": discussion_round(3)}, DiscussionWriteStatus.DISCUSSION_CHANGED),
                ):
                    values = {
                        "project_id": project,
                        "discussion_id": first.id,
                        "round": discussion_round(2),
                        "expected_round_count": 1,
                        **arguments,
                    }
                    assert await repository.append_round(**values) is status
                for ordinal in range(2, MAX_DISCUSSION_ROUNDS + 1):
                    assert (
                        await repository.append_round(
                            project_id=project,
                            discussion_id=first.id,
                            round=discussion_round(ordinal),
                            expected_round_count=ordinal - 1,
                        )
                        is DiscussionWriteStatus.WRITTEN
                    )
                assert (
                    await repository.append_round(
                        project_id=project,
                        discussion_id=first.id,
                        round=discussion_round(MAX_DISCUSSION_ROUNDS),
                        expected_round_count=MAX_DISCUSSION_ROUNDS,
                    )
                    is DiscussionWriteStatus.DISCUSSION_FULL
                )
            decided_at = NOW + timedelta(hours=1)
            full = seeded(version, rounds=MAX_DISCUSSION_ROUNDS)
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyDesignDiscussionRepository(session, owner_user_id=owner)
                current = await repository.get(project_id=project, discussion_id=first.id)
                assert current.rounds == full.rounds
                assert (
                    await repository.decide(
                        project_id=uuid4(),
                        discussion_id=first.id,
                        status=DiscussionStatus.APPROVED,
                        decided_at=decided_at,
                    )
                    is DiscussionWriteStatus.DISCUSSION_NOT_FOUND
                )
                assert (
                    await repository.decide(
                        project_id=project,
                        discussion_id=first.id,
                        status=DiscussionStatus.APPROVED,
                        decided_at=decided_at,
                    )
                    is DiscussionWriteStatus.WRITTEN
                )
                assert (
                    await repository.decide(
                        project_id=project,
                        discussion_id=first.id,
                        status=DiscussionStatus.CLOSED,
                        decided_at=decided_at,
                    )
                    is DiscussionWriteStatus.DISCUSSION_CLOSED
                )
                assert (
                    await repository.append_round(
                        project_id=project,
                        discussion_id=first.id,
                        round=discussion_round(2),
                        expected_round_count=1,
                    )
                    is DiscussionWriteStatus.DISCUSSION_CLOSED
                )
            second = seeded(version, hours=2)
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyDesignDiscussionRepository(session, owner_user_id=owner)
                approved = await repository.get(project_id=project, discussion_id=first.id)
                assert approved.status is DiscussionStatus.APPROVED
                assert approved.decided_at == decided_at
                assert (
                    await repository.open_for_version(
                        project_id=project, design_version_id=version.id
                    )
                    is None
                )
                assert await repository.create(second) is DiscussionWriteStatus.WRITTEN
                assert await repository.list(project_id=project) == (second, approved)
            invalid_headers = (
                {"status": "PAUSED"},
                {"status": DiscussionStatus.OPEN.value},
                {"decided_at": NOW - timedelta(days=1)},
                {"alternative_code": "ALT-1"},
                {"locale": "x"},
                {"design_content_hash": "F" * 64},
            )
            for changes in invalid_headers:
                with pytest.raises(IntegrityError):
                    async with db.session_factory() as session, session.begin():
                        await session.execute(
                            sa.insert(DISCUSSIONS).values(header_row(second, **changes))
                        )
            snapshot = second.rounds[0].to_snapshot()
            for changes in (
                {"ordinal": MAX_DISCUSSION_ROUNDS + 1},
                {"ordinal": 0},
                {"content_hash": "not-a-hash"},
                {"owner_note": ""},
            ):
                with pytest.raises(IntegrityError):
                    async with db.session_factory() as session, session.begin():
                        await session.execute(
                            sa.insert(ROUNDS).values(
                                {
                                    "discussion_id": second.id,
                                    "ordinal": 2,
                                    "owner_note": None,
                                    "content_hash": snapshot["content_hash"],
                                    "created_at": NOW,
                                    "round_snapshot": snapshot,
                                    **changes,
                                }
                            )
                        )
            async with db.session_factory() as session, session.begin():
                await session.execute(sa.delete(DISCUSSIONS).where(DISCUSSIONS.c.id == first.id))
            async with db.session_factory() as session:
                assert await count(session, DISCUSSIONS) == 1
                assert await count(session, ROUNDS) == 1
        finally:
            await db.dispose()

    run(scenario())


def test_the_replaced_checks_accept_the_discussion_task_and_source_kind(database, tmp_path):
    generator, transport = audited_generator(tmp_path, STATEMENT)

    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, version = await seed(db)
            context = statement_context(
                project_id=project,
                locale="it-IT",
                ordinal=1,
                owner_note=None,
                keys=twin_keys(twins()),
                speaker="T1",
                design={},
                findings=(),
                previous=None,
            )

            async def operation():
                await speak_as_twin(generator, context=context)
                return SimpleNamespace(status=DesignDiscussionCommandStatus.STARTED)

            await Command(SqlAlchemyProposalEvidenceStore(db.session_factory), operation).run(
                owner_user_id=owner, project_id=project
            )
            assert len(transport.calls) == 1
            async with db.session_factory() as session:
                tasks = (await session.execute(sa.select(GENERATIONS.c.task_id))).scalars().all()
                definition = await session.scalar(
                    sa.text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
                        " WHERE conname = 'ck_model_proposal_generations_task_valid'"
                        " AND connamespace = current_schema()::regnamespace"
                    )
                )
            assert tasks == ["proposal-twin-discussion-v1"]
            assert "proposal-brief-dialogue-v1" in definition
            assert "proposal-user-twin-evaluation-v1" in definition
            application = create_insight_application(
                application_id=uuid4(),
                project_id=project,
                owner_user_id=owner,
                source_kind=InsightSourceKind.TWIN_DISCUSSION,
                source_id=f"discussion:{uuid4()}:1:PRP-001",
                source_twin_id=None,
                text="Show the accepted date format.",
                target=InsightTarget.DESIGN,
                target_field=None,
                target_version_id=version.id,
                target_version_number=version.version_number,
                target_code="DRK-002",
                created_at=NOW,
            )
            async with db.session_factory() as session, session.begin():
                assert (
                    await SqlAlchemyInsightApplicationRepository(
                        session, owner_user_id=owner
                    ).create(application)
                    is InsightApplicationWriteStatus.WRITTEN
                )
            async with db.session_factory() as session:
                assert await SqlAlchemyInsightApplicationRepository(
                    session, owner_user_id=owner
                ).list(project_id=project) == (application,)
            with pytest.raises(IntegrityError):
                async with db.session_factory() as session, session.begin():
                    await session.execute(
                        sa.insert(APPLICATIONS).values(
                            id=uuid4(),
                            project_id=project,
                            owner_user_id=owner,
                            source_kind="TWIN_DEBATE",
                            source_id="discussion:unknown",
                            source_twin_id=None,
                            text="Unknown source.",
                            target=InsightTarget.DESIGN.value,
                            target_field=None,
                            target_version_id=version.id,
                            target_version_number=1,
                            target_code="DRK-003",
                            created_at=NOW,
                            content_hash="0" * 64,
                        )
                    )
        finally:
            await db.dispose()

    run(scenario())


class GroundedTwins:
    def __init__(self, session, *, owner_user_id):
        self.owner_user_id = owner_user_id

    async def get(self, *, project_id, twin_id, version_number):
        reference = design_fixtures.twin_reference()
        if (twin_id, version_number) != (reference.twin_id, reference.version_number):
            return None
        return SimpleNamespace(
            twin_id=twin_id,
            version_number=version_number,
            content_hash=reference.content_hash,
            profile=SimpleNamespace(
                name=reference.name,
                observations=(
                    observation("user_twin.role", ObservationValue.from_text("Receptionist")),
                ),
            ),
        )


def test_audited_rounds_pass_the_evidence_triggers_and_are_recorded(
    database, tmp_path, monkeypatch
):
    spoken = {
        "argument": "The guided flow is clear, but I need the date format at the desk.",
        "confidence": 0.8,
        "grounded_on": ["user_twin.role"],
        "proposals": ["Show the date format next to the field."],
        "replies_to": [],
        "stance": "CONCERN",
    }
    moderated = {
        "agreements": [],
        "conflicts": [],
        "proposals": [
            {
                "supported_by": ["T1"],
                "target": "DESIGN",
                "text": "Show the date format next to the field.",
            }
        ],
        "questions_for_owner": ["Should the desk accept other date formats?"],
    }
    generator, transport = audited_generator(tmp_path, spoken)
    outputs = iter((spoken, moderated, spoken, moderated))
    deliver = transport.post_json

    async def scripted(**kwargs):
        transport.output = next(outputs)
        return await deliver(**kwargs)

    transport.post_json = scripted
    monkeypatch.setattr(design_loop, "SqlAlchemyUserTwinVersionRepository", GroundedTwins)

    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, version = await seed(db)

            async def current(**_):
                return version

            application = DesignDiscussionApplication(
                ApplicationRuntime(
                    database_runtime=db,
                    real_model_runtime=SimpleNamespace(
                        user_modeling=SimpleNamespace(
                            proposal_port=SimpleNamespace(generator=generator)
                        )
                    ),
                    proposal_evidence_store=SqlAlchemyProposalEvidenceStore(db.session_factory),
                    design_query_service=SimpleNamespace(current=current),
                )
            )
            started = await application.start(
                owner_user_id=owner,
                project_id=project,
                body=DesignDiscussionRequest(
                    design_version_id=version.id,
                    design_content_hash=version.content_hash,
                    locale="en-US",
                ),
            )
            assert started.status is DesignDiscussionCommandStatus.STARTED
            continued = await application.next_round(
                owner_user_id=owner,
                project_id=project,
                discussion_id=started.discussion.id,
                body=DiscussionRoundRequest(expected_round_count=1, owner_note="Be concrete."),
            )
            assert continued.status is DesignDiscussionCommandStatus.ROUND_RECORDED
            approved = await application.decide(
                owner_user_id=owner,
                project_id=project,
                discussion_id=started.discussion.id,
                body=DiscussionDecisionRequest(action=DiscussionAction.APPROVE),
            )
            assert approved.status is DiscussionStatus.APPROVED
            assert approved.rounds == continued.discussion.rounds
            listed = await application.discussions(owner_user_id=owner, project_id=project)
            assert listed == (approved,)
            assert len(transport.calls) == 4
            rounds = approved.rounds
            generations = [
                str(item)
                for current_round in rounds
                for item in (
                    current_round.statements[0].model_generation_id,
                    current_round.synthesis.model_generation_id,
                )
            ]
            async with db.session_factory() as session:
                rows = (
                    await session.execute(sa.select(GENERATIONS.c.id, GENERATIONS.c.task_id))
                ).all()
                events = (
                    await session.execute(
                        sa.text(
                            "SELECT generation_id, kind, snapshot_json"
                            " FROM model_proposal_generation_events"
                        )
                    )
                ).all()
            assert sorted(str(row.id) for row in rows) == sorted(generations)
            assert {row.task_id for row in rows} == {"proposal-twin-discussion-v1"}
            observed = {}
            for generation_id, kind, raw in events:
                observed.setdefault(str(generation_id), {})[kind] = json.loads(raw)["payload"]
            for ordinal, current_round in enumerate(rounds, 1):
                statement_generation, synthesis_generation = generations[
                    2 * ordinal - 2 : 2 * ordinal
                ]
                assert set(observed[statement_generation]) == {
                    "HTTP_REQUEST",
                    "HTTP_RESPONSE",
                    "PROVIDER_RESULT",
                    "ADAPTER_ACCEPTED",
                    "APPLICATION_RESULT",
                }
                assert observed[statement_generation]["APPLICATION_RESULT"] == {
                    "status": "TWIN_STATEMENT_RECORDED",
                    "discussion_id": str(approved.id),
                }
                accepted = observed[synthesis_generation]["ADAPTER_ACCEPTED"]
                assert accepted["generated_content_hashes"] == {
                    "DISCUSSION_ROUND": [current_round.content_hash]
                }
                assert [item["generation_id"] for item in accepted["related_generations"]] == [
                    statement_generation
                ]
            assert [
                observed[generations[index]]["APPLICATION_RESULT"]["status"] for index in (1, 3)
            ] == ["DESIGN_DISCUSSION_STARTED", "DESIGN_DISCUSSION_ROUND_RECORDED"]
            sent = json.loads(transport.calls[2]["payload"]["messages"][1]["content"])["context"]
            assert (sent["round"], sent["locale"], sent["owner_note"]) == (
                2,
                "en-US",
                "Be concrete.",
            )
            assert sent["previous_round"]["statements"][0]["statement"] == spoken["argument"]
        finally:
            await db.dispose()

    run(scenario())


def test_downgrade_refuses_to_drop_retained_discussions(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, _, version = await seed(db)
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyDesignDiscussionRepository(session, owner_user_id=owner)
                assert await repository.create(seeded(version)) is DiscussionWriteStatus.WRITTEN
        finally:
            await db.dispose()

    run(scenario())
    with pytest.raises(DBAPIError, match="Cannot remove retained design discussions"):
        downgrade_database(database, revision=MIGRATION.down_revision)


def test_downgrade_restores_the_previous_revision_schema_exactly():
    assert_reversible_migration(load_database_settings(env_file=None), MIGRATION)
