from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.twins.conversations import (
    TwinConversation,
    TwinConversationTurn,
    TwinInsight,
    TwinInsightKind,
)
from orchestwin.twins.persistence.repositories import _project_is_owned

TWIN_CONVERSATIONS = sa.table(
    "twin_conversations",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("twin_id", postgresql.UUID(as_uuid=True)),
    sa.column("twin_version_id", postgresql.UUID(as_uuid=True)),
    sa.column("twin_version_number", sa.Integer()),
    sa.column("twin_content_hash", sa.String(length=64)),
    sa.column("twin_name", sa.Text()),
    sa.column("created_at", sa.DateTime(timezone=True)),
)

TWIN_CONVERSATION_TURNS = sa.table(
    "twin_conversation_turns",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("conversation_id", postgresql.UUID(as_uuid=True)),
    sa.column("ordinal", sa.Integer()),
    sa.column("question", sa.Text()),
    sa.column("reply", sa.Text()),
    sa.column("insights_json", postgresql.JSONB(astext_type=sa.Text())),
    sa.column("model_generation_id", postgresql.UUID(as_uuid=True)),
    sa.column("content_hash", sa.String(length=64)),
    sa.column("created_at", sa.DateTime(timezone=True)),
)


class TwinConversationAppendStatus(StrEnum):
    APPENDED = "APPENDED"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    CONVERSATION_NOT_FOUND = "CONVERSATION_NOT_FOUND"
    ORDINAL_CONFLICT = "ORDINAL_CONFLICT"


def _turn_record(turn: TwinConversationTurn):
    return {
        "id": turn.id,
        "conversation_id": turn.conversation_id,
        "ordinal": turn.ordinal,
        "question": turn.question,
        "reply": turn.reply,
        "insights_json": [insight.to_snapshot() for insight in turn.insights],
        "model_generation_id": turn.model_generation_id,
        "content_hash": turn.content_hash,
        "created_at": turn.created_at,
    }


def _turn_from_record(record) -> TwinConversationTurn:
    turn = TwinConversationTurn(
        id=record["id"],
        conversation_id=record["conversation_id"],
        ordinal=record["ordinal"],
        question=record["question"],
        reply=record["reply"],
        insights=tuple(
            TwinInsight(
                kind=TwinInsightKind(item["kind"]),
                text=item["text"],
                confidence=float(item["confidence"]),
                grounded_on=tuple(item["grounded_on"]),
            )
            for item in record["insights_json"]
        ),
        model_generation_id=record["model_generation_id"],
        created_at=record["created_at"],
    )
    if turn.content_hash != record["content_hash"]:
        raise ValueError("stored twin conversation turn does not match its content hash")
    return turn


class SqlAlchemyTwinConversationRepository:
    def __init__(self, session: AsyncSession, *, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id

    async def latest(self, *, project_id: UUID, twin_id: UUID) -> TwinConversation | None:
        statement = (
            sa.select(*TWIN_CONVERSATIONS.c)
            .where(
                TWIN_CONVERSATIONS.c.project_id == project_id,
                TWIN_CONVERSATIONS.c.owner_user_id == self._owner_user_id,
                TWIN_CONVERSATIONS.c.twin_id == twin_id,
            )
            .order_by(TWIN_CONVERSATIONS.c.created_at.desc(), TWIN_CONVERSATIONS.c.id.desc())
            .limit(1)
        )
        row = (await self._session.execute(statement)).mappings().one_or_none()
        if row is None:
            return None
        turns = (
            (
                await self._session.execute(
                    sa.select(*TWIN_CONVERSATION_TURNS.c)
                    .where(TWIN_CONVERSATION_TURNS.c.conversation_id == row["id"])
                    .order_by(TWIN_CONVERSATION_TURNS.c.ordinal)
                )
            )
            .mappings()
            .all()
        )
        return TwinConversation(
            id=row["id"],
            project_id=row["project_id"],
            owner_user_id=row["owner_user_id"],
            twin_id=row["twin_id"],
            twin_version_id=row["twin_version_id"],
            twin_version_number=row["twin_version_number"],
            twin_content_hash=row["twin_content_hash"],
            twin_name=row["twin_name"],
            created_at=row["created_at"],
            turns=tuple(_turn_from_record(record) for record in turns),
        )

    async def create(self, conversation: TwinConversation) -> TwinConversationAppendStatus:
        if conversation.owner_user_id != self._owner_user_id or not await _project_is_owned(
            self._session, project_id=conversation.project_id, owner_user_id=self._owner_user_id
        ):
            return TwinConversationAppendStatus.PROJECT_NOT_FOUND
        await self._session.execute(
            sa.insert(TWIN_CONVERSATIONS).values(
                id=conversation.id,
                project_id=conversation.project_id,
                owner_user_id=conversation.owner_user_id,
                twin_id=conversation.twin_id,
                twin_version_id=conversation.twin_version_id,
                twin_version_number=conversation.twin_version_number,
                twin_content_hash=conversation.twin_content_hash,
                twin_name=conversation.twin_name,
                created_at=conversation.created_at,
            )
        )
        for turn in conversation.turns:
            await self._session.execute(
                sa.insert(TWIN_CONVERSATION_TURNS).values(**_turn_record(turn))
            )
        return TwinConversationAppendStatus.APPENDED

    async def append_turn(self, turn: TwinConversationTurn) -> TwinConversationAppendStatus:
        locked = (
            await self._session.execute(
                sa.select(TWIN_CONVERSATIONS.c.id)
                .where(
                    TWIN_CONVERSATIONS.c.id == turn.conversation_id,
                    TWIN_CONVERSATIONS.c.owner_user_id == self._owner_user_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if locked is None:
            return TwinConversationAppendStatus.CONVERSATION_NOT_FOUND
        recorded = await self._session.scalar(
            sa.select(sa.func.coalesce(sa.func.max(TWIN_CONVERSATION_TURNS.c.ordinal), 0)).where(
                TWIN_CONVERSATION_TURNS.c.conversation_id == turn.conversation_id
            )
        )
        if recorded != turn.ordinal - 1:
            return TwinConversationAppendStatus.ORDINAL_CONFLICT
        await self._session.execute(sa.insert(TWIN_CONVERSATION_TURNS).values(**_turn_record(turn)))
        return TwinConversationAppendStatus.APPENDED
