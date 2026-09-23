from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from orchestwin.api.auth import current_user_dependency
from orchestwin.identity.domain import UserAccount
from orchestwin.models.proposal_evidence import (
    current_proposal_evidence,
    evidence_application,
    retain_adapter_result,
)
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.twin_chat import answer_as_twin, bind_insights, twin_chat_context
from orchestwin.projects.persistence.briefs import SqlAlchemyProjectBriefRepository
from orchestwin.twins.conversations import (
    MAX_QUESTION_CHARACTERS,
    MAX_TURNS_PER_CONVERSATION,
    TwinConversation,
    TwinConversationTurn,
    normalized_reply,
    normalized_text,
)
from orchestwin.twins.persistence.conversations import (
    SqlAlchemyTwinConversationRepository,
    TwinConversationAppendStatus,
)
from orchestwin.twins.persistence.repositories import SqlAlchemyUserTwinVersionRepository


class AskTwinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARACTERS)
    expected_turn_count: int = Field(ge=0, le=MAX_TURNS_PER_CONVERSATION)


class TwinChatStatus(StrEnum):
    TURN_RECORDED = "TWIN_TURN_RECORDED"


@dataclass(frozen=True)
class TwinChatResult:
    status: TwinChatStatus
    conversation: TwinConversation


class TwinChatApplication:
    def __init__(self, runtime):
        self.runtime = runtime
        self._proposal_evidence_store = runtime.proposal_evidence_store

    def _sessions(self):
        database = self.runtime.database_runtime
        if database is None:
            raise HTTPException(503, detail={"code": "DATABASE_UNAVAILABLE"})
        return database.session_factory

    async def conversation(self, *, owner_user_id, project_id, twin_id):
        async with self._sessions()() as session:
            latest = await SqlAlchemyTwinConversationRepository(
                session, owner_user_id=owner_user_id
            ).latest(project_id=project_id, twin_id=twin_id)
        if latest is None:
            raise HTTPException(404, detail={"code": "TWIN_CONVERSATION_NOT_FOUND"})
        return latest

    @evidence_application
    async def ask(self, *, owner_user_id, project_id, twin_id, body):
        sessions = self._sessions()
        try:
            question = normalized_text(body.question, maximum=MAX_QUESTION_CHARACTERS)
        except ValueError as error:
            raise HTTPException(422, detail={"code": "TWIN_QUESTION_INVALID"}) from error
        async with sessions() as session:
            twin = await SqlAlchemyUserTwinVersionRepository(
                session, owner_user_id=owner_user_id
            ).current(project_id=project_id, twin_id=twin_id)
            if twin is None:
                raise HTTPException(404, detail={"code": "USER_TWIN_NOT_FOUND"})
            latest = await SqlAlchemyTwinConversationRepository(
                session, owner_user_id=owner_user_id
            ).latest(project_id=project_id, twin_id=twin_id)
            briefs = await SqlAlchemyProjectBriefRepository(session).list_owned_versions(
                project_id=project_id, owner_user_id=owner_user_id
            )
        current = latest if latest is not None and latest.twin_version_id == twin.id else None
        turns = current.turns if current is not None else ()
        if body.expected_turn_count != len(turns):
            raise HTTPException(409, detail={"code": "TWIN_CONVERSATION_CHANGED"})
        if len(turns) >= MAX_TURNS_PER_CONVERSATION:
            raise HTTPException(409, detail={"code": "TWIN_CONVERSATION_FULL"})
        real = self.runtime.real_model_runtime
        if real is None or self._proposal_evidence_store is None:
            raise HTTPException(503, detail={"code": "TWIN_CHAT_MODEL_NOT_CONFIGURED"})
        output = await answer_as_twin(
            real.user_modeling.proposal_port.generator,
            context=twin_chat_context(
                project_id=project_id,
                twin_version=twin,
                brief=briefs[-1].brief if briefs else None,
                turns=turns,
                question=question,
            ),
        )
        scope = current_proposal_evidence()
        now = datetime.now(UTC)
        conversation = current or TwinConversation(
            id=uuid4(),
            project_id=project_id,
            owner_user_id=owner_user_id,
            twin_id=twin_id,
            twin_version_id=twin.id,
            twin_version_number=twin.version_number,
            twin_content_hash=twin.content_hash,
            twin_name=twin.profile.name,
            created_at=now,
            turns=(),
        )
        try:
            turn = TwinConversationTurn(
                id=uuid4(),
                conversation_id=conversation.id,
                ordinal=len(turns) + 1,
                question=question,
                reply=normalized_reply(output.reply),
                insights=bind_insights(output),
                model_generation_id=scope.request.request_id,
                created_at=now,
            )
        except (TypeError, ValueError) as error:
            await retain_adapter_result(error=error, reason=str(error))
            raise ProposalGenerationError("INVALID_TWIN_CHAT_OUTPUT") from error
        recorded = conversation.with_turn(turn)
        async with sessions() as session, session.begin():
            repository = SqlAlchemyTwinConversationRepository(session, owner_user_id=owner_user_id)
            status = (
                await repository.create(recorded)
                if current is None
                else await repository.append_turn(turn)
            )
            if status is not TwinConversationAppendStatus.APPENDED:
                raise HTTPException(409, detail={"code": "TWIN_CONVERSATION_CHANGED"})
        await scope.event(
            "ADAPTER_ACCEPTED",
            {
                "result": recorded.to_snapshot(),
                "generated_content_hashes": {"TWIN_CHAT_TURN": [turn.content_hash]},
            },
        )
        return TwinChatResult(status=TwinChatStatus.TURN_RECORDED, conversation=recorded)


def create_twin_chat_router():
    router = APIRouter(
        prefix="/projects/{project_id}/user-twins/{twin_id}/conversation", tags=["user-modeling"]
    )

    @router.get("")
    async def conversation(
        project_id: UUID,
        twin_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        result = await TwinChatApplication(request.app.state.application_runtime).conversation(
            owner_user_id=user.id, project_id=project_id, twin_id=twin_id
        )
        return {"snapshot": result.to_snapshot()}

    @router.post("/turns", status_code=201)
    async def ask(
        project_id: UUID,
        twin_id: UUID,
        body: AskTwinRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        result = await TwinChatApplication(request.app.state.application_runtime).ask(
            owner_user_id=user.id, project_id=project_id, twin_id=twin_id, body=body
        )
        return {"status": result.status.value, "snapshot": result.conversation.to_snapshot()}

    return router
