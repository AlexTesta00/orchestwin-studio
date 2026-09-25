from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.projects.brief_dialogue import (
    ACTIVE_STATUSES,
    BriefDialogue,
    BriefDialogueStatus,
    BriefDialogueTurn,
    DialogueAnswer,
    DialogueAnswerKind,
)
from orchestwin.projects.briefs import BriefField
from orchestwin.projects.persistence.models import ProjectRecord

DIALOGUES = sa.table(
    "brief_dialogues",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("source_brief_version_number", sa.Integer()),
    sa.column("statement", sa.Text()),
    sa.column("status", sa.String(length=16)),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("resulting_brief_version_number", sa.Integer()),
    sa.column("synthesis_generation_id", postgresql.UUID(as_uuid=True)),
    sa.column("completed_at", sa.DateTime(timezone=True)),
)

TURNS = sa.table(
    "brief_dialogue_turns",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("dialogue_id", postgresql.UUID(as_uuid=True)),
    sa.column("ordinal", sa.Integer()),
    sa.column("field", sa.String(length=48)),
    sa.column("question", sa.Text()),
    sa.column("model_generation_id", postgresql.UUID(as_uuid=True)),
    sa.column("asked_at", sa.DateTime(timezone=True)),
    sa.column("answer_kind", sa.String(length=16)),
    sa.column("answer_text", sa.Text()),
    sa.column("answer_items", postgresql.JSONB(none_as_null=True)),
    sa.column("answered_at", sa.DateTime(timezone=True)),
)

ACTIVE_STATUS_VALUES = tuple(sorted(status.value for status in ACTIVE_STATUSES))


class BriefDialogueWriteStatus(StrEnum):
    WRITTEN = "WRITTEN"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    DIALOGUE_NOT_FOUND = "DIALOGUE_NOT_FOUND"
    DIALOGUE_CHANGED = "DIALOGUE_CHANGED"


def _answer_columns(answer: DialogueAnswer | None):
    if answer is None:
        return {"answer_kind": None, "answer_text": None, "answer_items": None}
    return {
        "answer_kind": answer.kind.value,
        "answer_text": answer.text,
        "answer_items": None if answer.items is None else list(answer.items),
    }


def _turn_values(turn: BriefDialogueTurn):
    return {
        "id": turn.id,
        "dialogue_id": turn.dialogue_id,
        "ordinal": turn.ordinal,
        "field": None if turn.field is None else turn.field.value,
        "question": turn.question,
        "model_generation_id": turn.model_generation_id,
        "asked_at": turn.asked_at,
        "answered_at": turn.answered_at,
        **_answer_columns(turn.answer),
    }


def _answer_from_row(row) -> DialogueAnswer | None:
    if row["answer_kind"] is None:
        return None
    return DialogueAnswer(
        kind=DialogueAnswerKind(row["answer_kind"]),
        text=row["answer_text"],
        items=None if row["answer_items"] is None else tuple(row["answer_items"]),
    )


def _turn_from_row(row) -> BriefDialogueTurn:
    return BriefDialogueTurn(
        id=row["id"],
        dialogue_id=row["dialogue_id"],
        ordinal=row["ordinal"],
        field=None if row["field"] is None else BriefField(row["field"]),
        question=row["question"],
        model_generation_id=row["model_generation_id"],
        asked_at=row["asked_at"],
        answer=_answer_from_row(row),
        answered_at=row["answered_at"],
    )


class SqlAlchemyBriefDialogueRepository:
    def __init__(self, session: AsyncSession, *, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id

    def _owned(self):
        return (
            sa.select(*DIALOGUES.c)
            .where(DIALOGUES.c.owner_user_id == self._owner_user_id)
            .order_by(DIALOGUES.c.created_at.desc(), DIALOGUES.c.id.desc())
        )

    async def _load(self, statement) -> BriefDialogue | None:
        row = (await self._session.execute(statement.limit(1))).mappings().one_or_none()
        if row is None:
            return None
        turns = (
            (
                await self._session.execute(
                    sa.select(*TURNS.c)
                    .where(TURNS.c.dialogue_id == row["id"])
                    .order_by(TURNS.c.ordinal)
                )
            )
            .mappings()
            .all()
        )
        return BriefDialogue(
            id=row["id"],
            project_id=row["project_id"],
            owner_user_id=row["owner_user_id"],
            source_brief_version_number=row["source_brief_version_number"],
            statement=row["statement"],
            status=BriefDialogueStatus(row["status"]),
            created_at=row["created_at"],
            turns=tuple(_turn_from_row(turn) for turn in turns),
            resulting_brief_version_number=row["resulting_brief_version_number"],
            synthesis_generation_id=row["synthesis_generation_id"],
            completed_at=row["completed_at"],
        )

    async def latest(self, *, project_id: UUID) -> BriefDialogue | None:
        return await self._load(self._owned().where(DIALOGUES.c.project_id == project_id))

    async def active(self, *, project_id: UUID) -> BriefDialogue | None:
        return await self._load(
            self._owned().where(
                DIALOGUES.c.project_id == project_id,
                DIALOGUES.c.status.in_(ACTIVE_STATUS_VALUES),
            )
        )

    async def get(self, *, dialogue_id: UUID) -> BriefDialogue | None:
        return await self._load(self._owned().where(DIALOGUES.c.id == dialogue_id))

    async def _project_is_owned(self, project_id: UUID) -> bool:
        return (
            await self._session.scalar(
                sa.select(ProjectRecord.id).where(
                    ProjectRecord.id == project_id,
                    ProjectRecord.owner_user_id == self._owner_user_id,
                    ProjectRecord.archived_at.is_(None),
                )
            )
        ) is not None

    async def _lock(self, dialogue_id: UUID):
        return (
            (
                await self._session.execute(
                    sa.select(DIALOGUES.c.id, DIALOGUES.c.status)
                    .where(
                        DIALOGUES.c.id == dialogue_id,
                        DIALOGUES.c.owner_user_id == self._owner_user_id,
                    )
                    .with_for_update()
                )
            )
            .mappings()
            .one_or_none()
        )

    async def create(self, dialogue: BriefDialogue) -> BriefDialogueWriteStatus:
        if dialogue.owner_user_id != self._owner_user_id or not await self._project_is_owned(
            dialogue.project_id
        ):
            return BriefDialogueWriteStatus.PROJECT_NOT_FOUND
        if await self.active(project_id=dialogue.project_id) is not None:
            return BriefDialogueWriteStatus.DIALOGUE_CHANGED
        await self._session.execute(
            sa.insert(DIALOGUES).values(
                id=dialogue.id,
                project_id=dialogue.project_id,
                owner_user_id=dialogue.owner_user_id,
                source_brief_version_number=dialogue.source_brief_version_number,
                statement=dialogue.statement,
                status=dialogue.status.value,
                created_at=dialogue.created_at,
                resulting_brief_version_number=dialogue.resulting_brief_version_number,
                synthesis_generation_id=dialogue.synthesis_generation_id,
                completed_at=dialogue.completed_at,
            )
        )
        for turn in dialogue.turns:
            await self._session.execute(sa.insert(TURNS).values(**_turn_values(turn)))
        return BriefDialogueWriteStatus.WRITTEN

    async def append_turn(self, turn: BriefDialogueTurn) -> BriefDialogueWriteStatus:
        locked = await self._lock(turn.dialogue_id)
        if locked is None:
            return BriefDialogueWriteStatus.DIALOGUE_NOT_FOUND
        if locked["status"] != BriefDialogueStatus.OPEN.value:
            return BriefDialogueWriteStatus.DIALOGUE_CHANGED
        last = (
            (
                await self._session.execute(
                    sa.select(TURNS.c.ordinal, TURNS.c.answer_kind)
                    .where(TURNS.c.dialogue_id == turn.dialogue_id)
                    .order_by(TURNS.c.ordinal.desc())
                    .limit(1)
                )
            )
            .mappings()
            .one_or_none()
        )
        recorded = 0 if last is None else last["ordinal"]
        if recorded != turn.ordinal - 1 or (last is not None and last["answer_kind"] is None):
            return BriefDialogueWriteStatus.DIALOGUE_CHANGED
        await self._session.execute(sa.insert(TURNS).values(**_turn_values(turn)))
        return BriefDialogueWriteStatus.WRITTEN

    async def record_answer(self, turn: BriefDialogueTurn) -> BriefDialogueWriteStatus:
        if turn.answer is None:
            raise ValueError("an answered turn is required")
        locked = await self._lock(turn.dialogue_id)
        if locked is None:
            return BriefDialogueWriteStatus.DIALOGUE_NOT_FOUND
        if locked["status"] != BriefDialogueStatus.OPEN.value:
            return BriefDialogueWriteStatus.DIALOGUE_CHANGED
        result = await self._session.execute(
            sa.update(TURNS)
            .where(
                TURNS.c.id == turn.id,
                TURNS.c.dialogue_id == turn.dialogue_id,
                TURNS.c.ordinal == turn.ordinal,
                TURNS.c.answer_kind.is_(None),
            )
            .values(answered_at=turn.answered_at, **_answer_columns(turn.answer))
        )
        if result.rowcount != 1:
            return BriefDialogueWriteStatus.DIALOGUE_CHANGED
        return BriefDialogueWriteStatus.WRITTEN

    async def update_state(self, dialogue: BriefDialogue) -> BriefDialogueWriteStatus:
        locked = await self._lock(dialogue.id)
        if locked is None:
            return BriefDialogueWriteStatus.DIALOGUE_NOT_FOUND
        if locked["status"] not in ACTIVE_STATUS_VALUES:
            return BriefDialogueWriteStatus.DIALOGUE_CHANGED
        await self._session.execute(
            sa.update(DIALOGUES)
            .where(DIALOGUES.c.id == dialogue.id)
            .values(
                status=dialogue.status.value,
                resulting_brief_version_number=dialogue.resulting_brief_version_number,
                synthesis_generation_id=dialogue.synthesis_generation_id,
                completed_at=dialogue.completed_at,
            )
        )
        return BriefDialogueWriteStatus.WRITTEN
