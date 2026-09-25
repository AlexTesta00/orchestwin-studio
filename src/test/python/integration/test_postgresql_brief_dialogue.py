from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import sqlalchemy as sa

from orchestwin.identity.persistence.models import UserRecord
from orchestwin.models.proposal_evidence import current_proposal_evidence
from orchestwin.models.proposal_evidence_persistence import SqlAlchemyProposalEvidenceStore
from orchestwin.models.twin_chat import TwinChatOutput
from orchestwin.persistence import create_database_runtime, load_database_settings
from orchestwin.projects.brief_dialogue import (
    BriefDialogue,
    BriefDialogueStatus,
    BriefDialogueTurn,
    DialogueAnswer,
)
from orchestwin.projects.briefs import BriefField, create_project_brief
from orchestwin.projects.persistence.brief_dialogue import (
    DIALOGUES,
    TURNS,
    BriefDialogueWriteStatus,
    SqlAlchemyBriefDialogueRepository,
)
from orchestwin.projects.persistence.models import ProjectBriefVersionRecord, ProjectRecord
from src.test.python.integration.postgres_isolation import assert_reversible_migration
from src.test.python.integration.test_proposal_evidence_postgres import database, run
from src.test.python.models.test_proposal_evidence import Command, audited_generator

__all__ = ["database"]

pytestmark = pytest.mark.integration

MIGRATION = importlib.import_module(
    "orchestwin.persistence.migrations.versions.0055_brief_dialogue"
)
OUTPUT = {"reply": "Ok.", "insights": []}
NOW = datetime(2026, 9, 25, 10, 0, tzinfo=UTC)


async def seed(db):
    owner, project = uuid4(), uuid4()
    brief = create_project_brief(description="Una lista ospiti per il workshop.")
    async with db.session_factory() as session, session.begin():
        session.add(
            UserRecord(
                id=owner,
                email_normalized=f"{owner}@synthetic.invalid",
                password_hash="NO_LOGIN_SYNTHETIC",
            )
        )
        await session.flush()
        session.add(
            ProjectRecord(
                id=project,
                owner_user_id=owner,
                display_name="Synthetic brief dialogue",
                mode="GREENFIELD_GENERATION",
                current_brief_version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.flush()
        session.add(
            ProjectBriefVersionRecord(
                id=uuid4(),
                project_id=project,
                version_number=1,
                schema_version=brief.SCHEMA_VERSION,
                content=brief.to_snapshot(),
                content_hash=brief.content_hash,
                created_by_user_id=owner,
                created_at=NOW,
            )
        )
    return owner, project


async def add_brief_version(db, owner, project, number):
    brief = create_project_brief(name=f"Versione {number}", description="Descrizione sintetica.")
    async with db.session_factory() as session, session.begin():
        session.add(
            ProjectBriefVersionRecord(
                id=uuid4(),
                project_id=project,
                version_number=number,
                schema_version=brief.SCHEMA_VERSION,
                content=brief.to_snapshot(),
                content_hash=brief.content_hash,
                created_by_user_id=owner,
                created_at=NOW + timedelta(minutes=number),
            )
        )
        await session.execute(
            sa.update(ProjectRecord)
            .where(ProjectRecord.id == project)
            .values(current_brief_version=number)
        )


async def record_generation(db, generator, owner, project):
    captured = {}

    async def operation():
        await generator.generate(
            task="twin-chat",
            context={"project_id": str(project), "purpose": "TWIN_CHAT", "question": "Ciao?"},
            output_type=TwinChatOutput,
            instruction="Answer briefly.",
        )
        captured["id"] = current_proposal_evidence().request.request_id
        return SimpleNamespace(status=SimpleNamespace(value="RECORDED"))

    await Command(SqlAlchemyProposalEvidenceStore(db.session_factory), operation).run(
        owner_user_id=owner, project_id=project
    )
    return captured["id"]


def new_dialogue(owner, project, statement="Una lista ospiti.\nPer i volontari."):
    return BriefDialogue(
        id=uuid4(),
        project_id=project,
        owner_user_id=owner,
        source_brief_version_number=1,
        statement=statement,
        status=BriefDialogueStatus.OPEN,
        created_at=NOW,
    )


def question(dialogue, ordinal, field, generation_id):
    return BriefDialogueTurn(
        id=uuid4(),
        dialogue_id=dialogue.id,
        ordinal=ordinal,
        field=field,
        question=f"Domanda {ordinal}?",
        model_generation_id=generation_id,
        asked_at=NOW + timedelta(minutes=ordinal),
    )


async def write(db, owner, operation):
    async with db.session_factory() as session, session.begin():
        return await operation(SqlAlchemyBriefDialogueRepository(session, owner_user_id=owner))


def test_dialogue_rows_round_trip_through_the_owner_scoped_repository(database, tmp_path):
    generator, _ = audited_generator(tmp_path, OUTPUT)

    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project = await seed(db)
            generations = [await record_generation(db, generator, owner, project) for _ in range(3)]
            assert await write(db, owner, lambda repo: repo.latest(project_id=project)) is None
            dialogue = new_dialogue(owner, project)
            assert (
                await write(db, owner, lambda repo: repo.create(dialogue))
                is BriefDialogueWriteStatus.WRITTEN
            )
            assert (
                await write(db, owner, lambda repo: repo.create(new_dialogue(owner, project)))
                is BriefDialogueWriteStatus.DIALOGUE_CHANGED
            )
            foreign = uuid4()
            assert (
                await write(db, foreign, lambda repo: repo.create(new_dialogue(foreign, project)))
                is BriefDialogueWriteStatus.PROJECT_NOT_FOUND
            )
            assert await write(db, foreign, lambda repo: repo.latest(project_id=project)) is None
            first = question(dialogue, 1, BriefField.PROBLEM, generations[0])
            assert (
                await write(db, owner, lambda repo: repo.append_turn(first))
                is BriefDialogueWriteStatus.WRITTEN
            )
            second = question(dialogue, 2, BriefField.GOALS, generations[1])
            assert (
                await write(db, owner, lambda repo: repo.append_turn(second))
                is BriefDialogueWriteStatus.DIALOGUE_CHANGED
            )
            answered_first = first.with_answer(
                DialogueAnswer.text_answer("Carta e penna.\nSi perdono i nomi."),
                answered_at=NOW + timedelta(minutes=1, seconds=30),
            )
            assert (
                await write(db, owner, lambda repo: repo.record_answer(answered_first))
                is BriefDialogueWriteStatus.WRITTEN
            )
            assert (
                await write(db, owner, lambda repo: repo.record_answer(answered_first))
                is BriefDialogueWriteStatus.DIALOGUE_CHANGED
            )
            assert (
                await write(db, owner, lambda repo: repo.append_turn(second))
                is BriefDialogueWriteStatus.WRITTEN
            )
            answered_second = second.with_answer(
                DialogueAnswer.item_list(["Aggiungere ospiti", "Vedere la lista"]),
                answered_at=NOW + timedelta(minutes=2, seconds=30),
            )
            assert (
                await write(db, owner, lambda repo: repo.record_answer(answered_second))
                is BriefDialogueWriteStatus.WRITTEN
            )
            loaded = await write(db, owner, lambda repo: repo.active(project_id=project))
            assert loaded.turns == (answered_first, answered_second)
            assert loaded.asked_fields == frozenset({BriefField.PROBLEM, BriefField.GOALS})
            assert loaded.statement == dialogue.statement
            ready = loaded.as_ready()
            assert (
                await write(db, owner, lambda repo: repo.update_state(ready))
                is BriefDialogueWriteStatus.WRITTEN
            )
            assert (
                await write(
                    db,
                    owner,
                    lambda repo: repo.append_turn(
                        question(dialogue, 3, BriefField.NAME, generations[2])
                    ),
                )
                is BriefDialogueWriteStatus.DIALOGUE_CHANGED
            )
            current = await write(db, owner, lambda repo: repo.get(dialogue_id=dialogue.id))
            assert current.status is BriefDialogueStatus.READY
            await add_brief_version(db, owner, project, 2)
            synthesized = current.as_synthesized(
                resulting_brief_version_number=2,
                synthesis_generation_id=generations[2],
                completed_at=NOW + timedelta(minutes=5),
            )
            assert (
                await write(db, owner, lambda repo: repo.update_state(synthesized))
                is BriefDialogueWriteStatus.WRITTEN
            )
            assert (
                await write(db, owner, lambda repo: repo.update_state(synthesized))
                is BriefDialogueWriteStatus.DIALOGUE_CHANGED
            )
            assert await write(db, owner, lambda repo: repo.active(project_id=project)) is None
            latest = await write(db, owner, lambda repo: repo.latest(project_id=project))
            assert latest == synthesized
            assert (
                await write(db, owner, lambda repo: repo.create(new_dialogue(owner, project)))
                is BriefDialogueWriteStatus.WRITTEN
            )
            async with db.session_factory() as session, session.begin():
                definition = await session.scalar(
                    sa.text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
                        " WHERE conname = 'ck_model_proposal_generations_task_valid'"
                    )
                )
                assert "proposal-brief-dialogue-v1" in definition
                with pytest.raises(sa.exc.IntegrityError):
                    await session.execute(
                        sa.insert(TURNS).values(
                            id=uuid4(),
                            dialogue_id=dialogue.id,
                            ordinal=3,
                            field=BriefField.NAME.value,
                            question="Nome?",
                            model_generation_id=uuid4(),
                            asked_at=NOW,
                            answer_kind="ITEM_LIST",
                            answer_text=None,
                            answer_items=["a"],
                            answered_at=NOW,
                        )
                    )
            async with db.session_factory() as session, session.begin():
                with pytest.raises(sa.exc.IntegrityError):
                    await session.execute(
                        sa.insert(DIALOGUES).values(
                            id=uuid4(),
                            project_id=project,
                            owner_user_id=owner,
                            source_brief_version_number=1,
                            statement="Secondo dialogo aperto.",
                            status="OPEN",
                            created_at=NOW,
                        )
                    )
        finally:
            await db.dispose()

    run(scenario())


def test_downgrade_restores_the_previous_revision_schema_exactly():
    assert_reversible_migration(load_database_settings(env_file=None), MIGRATION)
