from __future__ import annotations

import asyncio
import importlib
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from orchestwin.knowledge.state import ProjectStateSources
from orchestwin.persistence import create_database_runtime, load_database_settings
from orchestwin.projects.code_change_state import SqlAlchemyProjectStateQueryService
from orchestwin.projects.persistence.twin_learning import (
    OBSERVATIONS,
    UPDATES,
    SqlAlchemyTwinLearningRepository,
    TwinLearningWriteStatus,
)
from orchestwin.projects.twin_learning import (
    KeptObservation,
    LearningSource,
    ObservationDraft,
    UpdateDecisionKind,
    UpdateStatus,
    build_twin_learning,
    twin_learning_from_snapshot,
)
from src.test.python.integration.postgres_isolation import assert_reversible_migration
from src.test.python.integration.test_postgresql_design_loop import seed
from src.test.python.integration.test_proposal_evidence_postgres import database, run
from src.test.python.integration.test_twin_chat_postgres import seeded_twin
from src.test.python.projects.test_twin_learning import NOW, TWIN, twin_update

__all__ = ["database"]

pytestmark = pytest.mark.integration

MIGRATION = importlib.import_module("orchestwin.persistence.migrations.versions.0066_twin_learning")
OTHER_TWIN = UUID("00000000-0000-4000-8000-000000000b02")


def draft(statement="Il gruppo usa il tablet alla reception."):
    return ObservationDraft(statement=statement, requirement="REQ-001")


async def count(session, table):
    return (await session.execute(sa.select(sa.func.count()).select_from(table))).scalar_one()


def test_observations_updates_and_decisions_round_trip(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, _ = await seed(db)
            stranger_id = uuid4()
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyTwinLearningRepository(session, owner_user_id=owner)
                assert await repository.project_exists(project)
                assert await repository.next_observation_number(project) == 1
                assert await repository.development_version(project, TWIN) == 0
                written = await repository.add(project, TWIN, (draft(),), approved_at=NOW)
                assert written.status is TwinLearningWriteStatus.RECORDED
                [first] = written.observations
                assert (first.code, first.added_in_version, first.source) == (
                    "OBS-001",
                    1,
                    LearningSource.OWNER,
                )
                other = await repository.add(
                    project, OTHER_TWIN, (draft("Il gruppo lavora di notte."),), approved_at=NOW
                )
                assert [item.code for item in other.observations] == ["OBS-002"]
                stranger = SqlAlchemyTwinLearningRepository(session, owner_user_id=stranger_id)
                assert not await stranger.project_exists(project)
                refused = await stranger.add(project, TWIN, (draft(),), approved_at=NOW)
                assert refused.status is TwinLearningWriteStatus.PROJECT_NOT_FOUND
                assert await stranger.observations(project, TWIN) == ()
                with pytest.raises(ValueError):
                    await repository.add(project, TWIN, (), approved_at=NOW)

            proposal = twin_update(base_development_version=1, created_at=NOW + timedelta(hours=1))
            empty = twin_update(
                id=uuid4(),
                twin_id=OTHER_TWIN,
                twin_name="Night Auditor Twin",
                status=UpdateStatus.EMPTY,
                observations=(),
                base_development_version=1,
            )
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyTwinLearningRepository(session, owner_user_id=owner)
                assert (await repository.create_update(project, proposal)).update == proposal
                assert (await repository.create_update(project, empty)).status is (
                    TwinLearningWriteStatus.RECORDED
                )
                again = await repository.create_update(project, twin_update(id=uuid4()))
                assert again.status is TwinLearningWriteStatus.UPDATE_PENDING
                assert again.pending == proposal
                blocked = await repository.add(project, TWIN, (draft("Altro."),), approved_at=NOW)
                assert blocked.status is TwinLearningWriteStatus.UPDATE_PENDING
                retiring = await repository.retire(project, TWIN, 1, retired_at=NOW)
                assert retiring.status is TwinLearningWriteStatus.UPDATE_PENDING
                with pytest.raises(ValueError):
                    await repository.create_update(
                        project,
                        proposal.decided(UpdateDecisionKind.REJECT, decided_at=NOW),
                    )
            async with db.session_factory() as session:
                repository = SqlAlchemyTwinLearningRepository(session, owner_user_id=owner)
                assert await repository.update(project, proposal.id) == proposal
                assert await repository.update(project, uuid4()) is None
                assert await repository.pending_update(project, TWIN) == proposal
                assert await repository.pending_update(project, OTHER_TWIN) is None
                assert await repository.latest_update(project, OTHER_TWIN) == empty
                assert await repository.updates(project, TWIN) == (proposal,)
                active = await repository.active(project)
                assert {twin: [item.code for item in items] for twin, items in active.items()} == {
                    TWIN: ["OBS-001"],
                    OTHER_TWIN: ["OBS-002"],
                }
                stranger = SqlAlchemyTwinLearningRepository(session, owner_user_id=stranger_id)
                assert await stranger.update(project, proposal.id) is None

            decided_at = NOW + timedelta(hours=2)
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyTwinLearningRepository(session, owner_user_id=owner)
                unknown = await repository.decide_update(
                    project, uuid4(), UpdateDecisionKind.REJECT, decided_at=decided_at
                )
                assert unknown.status is TwinLearningWriteStatus.UPDATE_NOT_FOUND
                outside = await repository.decide_update(
                    project,
                    proposal.id,
                    UpdateDecisionKind.APPROVE,
                    (KeptObservation(index=0), KeptObservation(index=9)),
                    decided_at=decided_at,
                )
                assert (outside.status, outside.position) == (
                    TwinLearningWriteStatus.INDEX_UNKNOWN,
                    1,
                )
                result = await repository.decide_update(
                    project,
                    proposal.id,
                    UpdateDecisionKind.APPROVE,
                    (
                        KeptObservation(index=2),
                        KeptObservation(index=0, statement="Il gruppo usa il telefono."),
                    ),
                    decided_at=decided_at,
                    reason="Utili.",
                )
                assert result.status is TwinLearningWriteStatus.RECORDED
                assert result.update.status is UpdateStatus.APPROVED
                assert result.update.decision.kept == (0, 2)
                assert [item.code for item in result.observations] == ["OBS-003", "OBS-004"]
                assert result.observations[0].statement == "Il gruppo usa il telefono."
                assert {item.added_in_version for item in result.observations} == {2}
                assert {item.update_id for item in result.observations} == {proposal.id}
                repeated = await repository.decide_update(
                    project, proposal.id, UpdateDecisionKind.REJECT, decided_at=decided_at
                )
                assert repeated.status is TwinLearningWriteStatus.ALREADY_DECIDED
                closed = await repository.decide_update(
                    project, empty.id, UpdateDecisionKind.REJECT, decided_at=decided_at
                )
                assert closed.status is TwinLearningWriteStatus.ALREADY_DECIDED
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyTwinLearningRepository(session, owner_user_id=owner)
                assert await repository.update(project, proposal.id) == result.update
                assert await repository.pending_update(project, TWIN) is None
                retired = await repository.retire(
                    project, TWIN, 1, retired_at=decided_at, reason="Superata."
                )
                assert retired.status is TwinLearningWriteStatus.RECORDED
                assert retired.observations[0].retired_in_version == 3
                for number, twin in ((1, TWIN), (2, TWIN), (9, TWIN)):
                    missing = await repository.retire(project, twin, number, retired_at=NOW)
                    assert missing.status is TwinLearningWriteStatus.OBSERVATION_NOT_FOUND
            async with db.session_factory() as session:
                repository = SqlAlchemyTwinLearningRepository(session, owner_user_id=owner)
                records = await repository.observations(project, TWIN)
                assert [(item.code, item.active) for item in records] == [
                    ("OBS-001", False),
                    ("OBS-003", True),
                    ("OBS-004", True),
                ]
                assert await repository.development_version(project, TWIN) == 3
                assert await repository.next_observation_number(project) == 5
                entry = build_twin_learning(
                    twin_id=TWIN,
                    twin_name="Receptionist Twin",
                    profile_version_number=1,
                    records=records,
                )
                assert entry.label == "1.3"
                assert entry.retired[0].reason == "Superata."
                assert records[1].basis == proposal.observations[0].basis
                assert records[2].statement == proposal.observations[2].statement
        finally:
            await db.dispose()

    run(scenario())


def test_an_approval_needs_the_base_version_and_room_for_the_kept_observations(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, _ = await seed(db)
            stale = twin_update(base_development_version=0)
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyTwinLearningRepository(session, owner_user_id=owner)
                added = await repository.add(
                    project,
                    TWIN,
                    tuple(draft(f"Osservazione numero {index}.") for index in range(19)),
                    approved_at=NOW,
                )
                assert added.observations[-1].code == "OBS-019"
                assert {item.added_in_version for item in added.observations} == {1}
                await repository.create_update(project, stale)
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyTwinLearningRepository(session, owner_user_id=owner)
                moved = await repository.decide_update(
                    project,
                    stale.id,
                    UpdateDecisionKind.APPROVE,
                    (KeptObservation(index=0),),
                    decided_at=NOW,
                )
                assert moved.status is TwinLearningWriteStatus.CONTEXT_CHANGED
                rejected = await repository.decide_update(
                    project, stale.id, UpdateDecisionKind.REJECT, decided_at=NOW
                )
                assert rejected.status is TwinLearningWriteStatus.RECORDED
                fresh = twin_update(id=uuid4(), base_development_version=1)
                await repository.create_update(project, fresh)
                full = await repository.decide_update(
                    project,
                    fresh.id,
                    UpdateDecisionKind.APPROVE,
                    (KeptObservation(index=0), KeptObservation(index=1)),
                    decided_at=NOW,
                )
                assert full.status is TwinLearningWriteStatus.LIMIT_REACHED
                fitting = await repository.decide_update(
                    project,
                    fresh.id,
                    UpdateDecisionKind.APPROVE,
                    (KeptObservation(index=1),),
                    decided_at=NOW,
                )
                assert fitting.status is TwinLearningWriteStatus.RECORDED
                assert [item.code for item in fitting.observations] == ["OBS-020"]
                limit = await repository.add(
                    project, TWIN, (draft("Una di troppo."),), approved_at=NOW
                )
                assert limit.status is TwinLearningWriteStatus.LIMIT_REACHED
        finally:
            await db.dispose()

    run(scenario())


def test_two_concurrent_decisions_on_the_same_update_cannot_both_apply(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, _ = await seed(db)
            proposal = twin_update(base_development_version=0)
            async with db.session_factory() as session, session.begin():
                await SqlAlchemyTwinLearningRepository(session, owner_user_id=owner).create_update(
                    project, proposal
                )

            async def rejecting():
                async with db.session_factory() as session, session.begin():
                    return await SqlAlchemyTwinLearningRepository(
                        session, owner_user_id=owner
                    ).decide_update(project, proposal.id, UpdateDecisionKind.REJECT, decided_at=NOW)

            async with db.session_factory() as session:
                transaction = await session.begin()
                approval = await SqlAlchemyTwinLearningRepository(
                    session, owner_user_id=owner
                ).decide_update(
                    project,
                    proposal.id,
                    UpdateDecisionKind.APPROVE,
                    (KeptObservation(index=0),),
                    decided_at=NOW,
                )
                second = asyncio.create_task(rejecting())
                await asyncio.sleep(0)
                await transaction.commit()
            rejection = await second
            assert approval.status is TwinLearningWriteStatus.RECORDED
            assert rejection.status is TwinLearningWriteStatus.ALREADY_DECIDED
            async with db.session_factory() as session:
                repository = SqlAlchemyTwinLearningRepository(session, owner_user_id=owner)
                stored = await repository.update(project, proposal.id)
                assert stored.status is UpdateStatus.APPROVED
                assert [item.code for item in await repository.observations(project, TWIN)] == [
                    "OBS-001"
                ]
        finally:
            await db.dispose()

    run(scenario())


def test_the_tables_refuse_rows_outside_the_limits(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, _ = await seed(db)
            proposal = twin_update()
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyTwinLearningRepository(session, owner_user_id=owner)
                await repository.create_update(project, proposal)
            update_row = {
                "id": uuid4(),
                "project_id": project,
                "owner_user_id": owner,
                "twin_id": OTHER_TWIN,
                "twin_name": "Night Auditor Twin",
                "created_at": NOW,
                "locale": "it-IT",
                "status": "PROPOSED",
                "base_profile_version": 1,
                "base_development_version": 0,
                "comment": "Ho imparato qualcosa sul mio gruppo di lavoro.",
                "observations": [{"index": 0}],
                "material_changes": 1,
                "material_tests": 0,
                "decided_at": None,
                "kept": None,
                "decision_reason": None,
                "generation_ids": [],
                "cost_microusd": 0,
            }
            for changes in (
                {"twin_id": TWIN},
                {"status": "LATER"},
                {"status": "EMPTY"},
                {"observations": []},
                {"observations": {}},
                {"observations": [{"index": index} for index in range(7)]},
                {"twin_name": ""},
                {"locale": "i"},
                {"comment": ""},
                {"base_profile_version": 0},
                {"base_development_version": -1},
                {"material_changes": 0},
                {"material_changes": 9},
                {"material_tests": 5},
                {"status": "APPROVED"},
                {"status": "APPROVED", "decided_at": NOW, "kept": []},
                {"status": "REJECTED", "decided_at": NOW, "kept": [0]},
                {"status": "REJECTED", "decided_at": NOW, "kept": {}},
                {"decided_at": NOW, "kept": [0]},
                {"status": "REJECTED", "decided_at": NOW},
                {"decision_reason": "Perché sì."},
                {"status": "REJECTED", "decided_at": NOW, "kept": [], "decision_reason": ""},
                {"generation_ids": {}},
                {"cost_microusd": -1},
                {"project_id": uuid4()},
                {"owner_user_id": uuid4()},
            ):
                with pytest.raises(IntegrityError):
                    async with db.session_factory() as session, session.begin():
                        await session.execute(sa.insert(UPDATES).values({**update_row, **changes}))
            async with db.session_factory() as session, session.begin():
                await session.execute(
                    sa.insert(UPDATES).values(
                        {
                            **update_row,
                            "status": "REJECTED",
                            "decided_at": NOW,
                            "kept": [],
                            "decision_reason": "Non serve.",
                        }
                    )
                )
            observation_row = {
                "project_id": project,
                "owner_user_id": owner,
                "twin_id": TWIN,
                "number": 1,
                "code": "OBS-001",
                "statement": "Il gruppo usa il tablet.",
                "basis": None,
                "source": "OWNER",
                "requirement": None,
                "screen": None,
                "contradicts_profile": None,
                "added_in_version": 1,
                "approved_at": NOW,
                "update_id": None,
                "retired_in_version": None,
                "retired_at": None,
                "retire_reason": None,
            }
            async with db.session_factory() as session, session.begin():
                await session.execute(sa.insert(OBSERVATIONS).values(observation_row))
            for changes in (
                {"number": 1},
                {"number": 0, "code": "OBS-000"},
                {"code": "OBS-1"},
                {"statement": ""},
                {"basis": "Tre critiche."},
                {"source": "LATER"},
                {"source": "TWIN_CRITIQUE"},
                {"source": "TWIN_CRITIQUE", "basis": "Tre critiche."},
                {"source": "TWIN_CRITIQUE", "update_id": proposal.id},
                {"update_id": proposal.id},
                {"requirement": "REQ-1"},
                {"screen": "scr-001"},
                {"contradicts_profile": ""},
                {"added_in_version": 0},
                {"retired_in_version": 2},
                {"retired_at": NOW},
                {"retired_in_version": 1, "retired_at": NOW},
                {"retire_reason": "Superata."},
                {"retired_in_version": 2, "retired_at": NOW, "retire_reason": ""},
                {
                    "source": "TWIN_CRITIQUE",
                    "basis": "Tre critiche.",
                    "update_id": uuid4(),
                },
                {"project_id": uuid4()},
                {"owner_user_id": uuid4()},
            ):
                number = changes.get("number", 2)
                code = changes.get("code", f"OBS-{number:03d}")
                with pytest.raises(IntegrityError):
                    async with db.session_factory() as session, session.begin():
                        await session.execute(
                            sa.insert(OBSERVATIONS).values(
                                {**observation_row, **changes, "number": number, "code": code}
                            )
                        )
            async with db.session_factory() as session, session.begin():
                await session.execute(
                    sa.insert(OBSERVATIONS).values(
                        {
                            **observation_row,
                            "number": 2,
                            "code": "OBS-002",
                            "source": "TWIN_CRITIQUE",
                            "basis": "Tre critiche.",
                            "update_id": proposal.id,
                        }
                    )
                )
            with pytest.raises(IntegrityError):
                async with db.session_factory() as session, session.begin():
                    await session.execute(sa.delete(UPDATES).where(UPDATES.c.id == proposal.id))
            async with db.session_factory() as session:
                assert (await count(session, UPDATES), await count(session, OBSERVATIONS)) == (
                    2,
                    2,
                )
        finally:
            await db.dispose()

    run(scenario())


def test_the_state_sources_carry_every_twin_that_learned_something(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, _ = await seed(db)
            service = SqlAlchemyProjectStateQueryService(db.session_factory)
            before = await service.current(owner_user_id=owner, project_id=project)
            assert before.learning == ()
            twin = await seeded_twin(db, owner, project)
            assert twin.twin_id == TWIN
            proposal = twin_update(base_development_version=0)
            async with db.session_factory() as session, session.begin():
                repository = SqlAlchemyTwinLearningRepository(session, owner_user_id=owner)
                await repository.create_update(project, proposal)
                approval = await repository.decide_update(
                    project,
                    proposal.id,
                    UpdateDecisionKind.APPROVE,
                    (KeptObservation(index=0), KeptObservation(index=1)),
                    decided_at=NOW + timedelta(hours=1),
                )
                assert approval.status is TwinLearningWriteStatus.RECORDED
                written = await repository.add(
                    project,
                    TWIN,
                    (draft("Il gruppo lavora anche di notte."),),
                    approved_at=NOW + timedelta(hours=2),
                )
                assert written.status is TwinLearningWriteStatus.RECORDED
                retired = await repository.retire(
                    project, TWIN, 1, retired_at=NOW + timedelta(hours=3), reason="Superata."
                )
                assert retired.status is TwinLearningWriteStatus.RECORDED
                unknown = await repository.add(
                    project, OTHER_TWIN, (draft("Un twin senza profilo."),), approved_at=NOW
                )
                assert [item.code for item in unknown.observations] == ["OBS-004"]
            async with db.session_factory() as session:
                records = await SqlAlchemyTwinLearningRepository(
                    session, owner_user_id=owner
                ).observations(project, TWIN)
            sources = await service.current(owner_user_id=owner, project_id=project)
            [entry] = sources.learning
            assert entry == (
                build_twin_learning(
                    twin_id=TWIN,
                    twin_name=twin.profile.name,
                    profile_version_number=twin.version_number,
                    records=records,
                ).to_snapshot()
            )
            assert (entry["twin_id"], entry["development_version_number"], entry["label"]) == (
                str(TWIN),
                3,
                f"{twin.version_number}.3",
            )
            assert [
                (item["code"], item["source"], item["added_in_version"])
                for item in entry["observations"]
            ] == [("OBS-002", "TWIN_CRITIQUE", 1), ("OBS-003", "OWNER", 2)]
            assert entry["observations"][0]["update_id"] == str(proposal.id)
            assert entry["observations"][0]["basis"] == proposal.observations[1].basis
            assert entry["retired"] == [
                {
                    "code": "OBS-001",
                    "statement": proposal.observations[0].statement,
                    "retired_in_version": 3,
                    "retired_at": (NOW + timedelta(hours=3)).isoformat(),
                    "reason": "Superata.",
                }
            ]
            assert twin_learning_from_snapshot(entry).to_snapshot() == entry
            assert sources.has_learning
            assert not sources.is_empty
            stranger = await service.current(owner_user_id=uuid4(), project_id=project)
            assert stranger == ProjectStateSources()
        finally:
            await db.dispose()

    run(scenario())


def test_downgrade_restores_the_previous_revision_schema_exactly():
    assert MIGRATION.revision == "0066_twin_learning"
    assert MIGRATION.down_revision == "0065_code_task_sources"
    assert_reversible_migration(load_database_settings(env_file=None), MIGRATION)
