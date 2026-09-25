import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.clarification import BriefAssumptionResponse
from orchestwin.api.projects import ProjectBriefVersionResponse
from orchestwin.identity.domain import UserAccount
from orchestwin.models.brief_dialogue import (
    ask_question,
    bind_question,
    bind_synthesis,
    question_context,
    question_plan,
    synthesis_context,
    synthesize_brief,
)
from orchestwin.models.proposal_evidence import (
    current_proposal_evidence,
    evidence_application,
    retain_adapter_result,
)
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.projects.brief_dialogue import (
    ACTIVE_STATUSES,
    MAX_ANSWER_CHARACTERS,
    MAX_ANSWER_ITEMS,
    MAX_DIALOGUE_QUESTIONS,
    MAX_STATEMENT_CHARACTERS,
    BriefDialogue,
    BriefDialogueStatus,
    BriefDialogueTurn,
    DialogueAnswer,
    normalized_block,
)
from orchestwin.projects.briefs import create_project_brief
from orchestwin.projects.clarification_state import BriefAssumptionSource, create_brief_assumption
from orchestwin.projects.persistence.brief_dialogue import (
    BriefDialogueWriteStatus,
    SqlAlchemyBriefDialogueRepository,
)
from orchestwin.projects.persistence.briefs import SqlAlchemyProjectBriefRepository
from orchestwin.projects.persistence.clarification import SqlAlchemyBriefAssumptionRepository
from orchestwin.projects.repository import BriefVersionCreationStatus
from orchestwin.projects.requirements_primitives import canonical_json


class StartDialogueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1, max_length=MAX_STATEMENT_CHARACTERS)


class DialogueTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_turn_count: int = Field(ge=0, le=MAX_DIALOGUE_QUESTIONS)


class DialogueAnswerRequest(DialogueTurnRequest):
    kind: Literal["TEXT", "ITEM_LIST", "UNKNOWN"]
    text: str | None = Field(default=None, max_length=MAX_ANSWER_CHARACTERS)
    items: list[str] | None = Field(default=None, max_length=MAX_ANSWER_ITEMS)


class BriefDialogueOutcome(StrEnum):
    CURRENT = "BRIEF_DIALOGUE_CURRENT"
    STARTED = "BRIEF_DIALOGUE_STARTED"
    QUESTION_ASKED = "BRIEF_QUESTION_ASKED"
    READY = "BRIEF_DIALOGUE_READY"
    SYNTHESIZED = "BRIEF_SYNTHESIZED"
    CLOSED = "BRIEF_DIALOGUE_CLOSED"


@dataclass(frozen=True)
class BriefDialogueResult:
    status: BriefDialogueOutcome
    dialogue: BriefDialogue
    brief_version: object | None
    assumptions: tuple = ()


def _changed():
    return HTTPException(409, detail={"code": "BRIEF_DIALOGUE_CHANGED"})


def _content_hash(snapshot):
    return hashlib.sha256(canonical_json(snapshot).encode("utf-8")).hexdigest()


def _answer_from(body: DialogueAnswerRequest) -> DialogueAnswer:
    if body.kind == "TEXT":
        return DialogueAnswer.text_answer(body.text)
    if body.kind == "ITEM_LIST":
        return DialogueAnswer.item_list(body.items if body.items is not None else [])
    return DialogueAnswer.unknown()


class BriefDialogueApplication:
    def __init__(self, runtime):
        self.runtime = runtime
        self._proposal_evidence_store = runtime.proposal_evidence_store

    def _sessions(self):
        database = self.runtime.database_runtime
        if database is None:
            raise HTTPException(503, detail={"code": "DATABASE_UNAVAILABLE"})
        return database.session_factory

    def _generator(self):
        real = self.runtime.real_model_runtime
        if real is None or self._proposal_evidence_store is None:
            raise HTTPException(503, detail={"code": "BRIEF_DIALOGUE_MODEL_NOT_CONFIGURED"})
        return real.team.generator

    async def _context(self, *, owner_user_id, project_id):
        async with self._sessions()() as session:
            brief_version = await SqlAlchemyProjectBriefRepository(session).get_current_owned(
                project_id=project_id, owner_user_id=owner_user_id
            )
            dialogue = await SqlAlchemyBriefDialogueRepository(
                session, owner_user_id=owner_user_id
            ).latest(project_id=project_id)
        return brief_version, dialogue

    async def _active(self, *, owner_user_id, project_id, expected_turn_count):
        brief_version, dialogue = await self._context(
            owner_user_id=owner_user_id, project_id=project_id
        )
        if dialogue is None:
            raise HTTPException(404, detail={"code": "BRIEF_DIALOGUE_NOT_FOUND"})
        if (
            dialogue.status not in ACTIVE_STATUSES
            or brief_version is None
            or expected_turn_count != dialogue.question_count
        ):
            raise _changed()
        return brief_version, dialogue

    async def _write(self, owner_user_id, operation):
        async with self._sessions()() as session, session.begin():
            status = await operation(
                SqlAlchemyBriefDialogueRepository(session, owner_user_id=owner_user_id)
            )
        if status is not BriefDialogueWriteStatus.WRITTEN:
            raise _changed()

    async def current(self, *, owner_user_id, project_id):
        brief_version, dialogue = await self._context(
            owner_user_id=owner_user_id, project_id=project_id
        )
        if dialogue is None:
            raise HTTPException(404, detail={"code": "BRIEF_DIALOGUE_NOT_FOUND"})
        return BriefDialogueResult(BriefDialogueOutcome.CURRENT, dialogue, brief_version)

    @evidence_application
    async def start(self, *, owner_user_id, project_id, body):
        generator = self._generator()
        try:
            statement = normalized_block(body.statement, maximum=MAX_STATEMENT_CHARACTERS)
        except ValueError as error:
            raise HTTPException(422, detail={"code": "BRIEF_STATEMENT_INVALID"}) from error
        async with self._sessions()() as session, session.begin():
            briefs = SqlAlchemyProjectBriefRepository(session)
            current = await briefs.get_current_owned(
                project_id=project_id, owner_user_id=owner_user_id
            )
            if current is None:
                creation = await briefs.create_owned_version(
                    project_id=project_id,
                    owner_user_id=owner_user_id,
                    created_by_user_id=owner_user_id,
                    brief=create_project_brief(description=statement),
                )
                if (
                    creation.status is BriefVersionCreationStatus.PROJECT_NOT_FOUND
                    or creation.version is None
                ):
                    raise HTTPException(404, detail={"code": "PROJECT_NOT_FOUND"})
                current = creation.version
            dialogue = BriefDialogue(
                id=uuid4(),
                project_id=project_id,
                owner_user_id=owner_user_id,
                source_brief_version_number=current.version_number,
                statement=statement,
                status=BriefDialogueStatus.OPEN,
                created_at=datetime.now(UTC),
            )
            status = await SqlAlchemyBriefDialogueRepository(
                session, owner_user_id=owner_user_id
            ).create(dialogue)
            if status is BriefDialogueWriteStatus.PROJECT_NOT_FOUND:
                raise HTTPException(404, detail={"code": "PROJECT_NOT_FOUND"})
            if status is not BriefDialogueWriteStatus.WRITTEN:
                raise HTTPException(409, detail={"code": "BRIEF_DIALOGUE_ACTIVE"})
        return await self._ask(
            generator,
            owner_user_id=owner_user_id,
            dialogue=dialogue,
            brief_version=current,
            outcome=BriefDialogueOutcome.STARTED,
        )

    @evidence_application
    async def answer(self, *, owner_user_id, project_id, body):
        generator = self._generator()
        brief_version, dialogue = await self._active(
            owner_user_id=owner_user_id,
            project_id=project_id,
            expected_turn_count=body.expected_turn_count,
        )
        if dialogue.status is not BriefDialogueStatus.OPEN or dialogue.pending_turn is None:
            raise _changed()
        try:
            answered = dialogue.with_answer(_answer_from(body), answered_at=datetime.now(UTC))
        except ValueError as error:
            raise HTTPException(422, detail={"code": "BRIEF_ANSWER_INVALID"}) from error
        await self._write(owner_user_id, lambda repo: repo.record_answer(answered.turns[-1]))
        return await self._ask(
            generator,
            owner_user_id=owner_user_id,
            dialogue=answered,
            brief_version=brief_version,
            outcome=BriefDialogueOutcome.QUESTION_ASKED,
        )

    @evidence_application
    async def next_question(self, *, owner_user_id, project_id, body):
        generator = self._generator()
        brief_version, dialogue = await self._active(
            owner_user_id=owner_user_id,
            project_id=project_id,
            expected_turn_count=body.expected_turn_count,
        )
        if dialogue.status is not BriefDialogueStatus.OPEN or dialogue.pending_turn is not None:
            raise _changed()
        return await self._ask(
            generator,
            owner_user_id=owner_user_id,
            dialogue=dialogue,
            brief_version=brief_version,
            outcome=BriefDialogueOutcome.QUESTION_ASKED,
        )

    async def _ask(self, generator, *, owner_user_id, dialogue, brief_version, outcome):
        if dialogue.questions_remaining <= 0:
            return await self._ready(owner_user_id, dialogue, brief_version)
        plan = question_plan(dialogue, brief_version.brief)
        if plan.exhausted:
            return await self._ready(owner_user_id, dialogue, brief_version)
        output = await ask_question(
            generator,
            context=question_context(
                project_id=dialogue.project_id,
                dialogue=dialogue,
                brief=brief_version.brief,
                plan=plan,
            ),
            plan=plan,
        )
        scope = current_proposal_evidence()
        try:
            bound = bind_question(output, plan=plan)
            if bound is not None and dialogue.repeats_earlier_text(bound[1]):
                bound = None
            if bound is None:
                asked = None
            else:
                asked = dialogue.with_question(
                    BriefDialogueTurn(
                        id=uuid4(),
                        dialogue_id=dialogue.id,
                        ordinal=dialogue.question_count + 1,
                        field=bound[0],
                        question=bound[1],
                        model_generation_id=scope.request.request_id,
                        asked_at=datetime.now(UTC),
                    )
                )
        except (TypeError, ValueError) as error:
            await retain_adapter_result(error=error, reason=str(error))
            raise ProposalGenerationError("INVALID_BRIEF_QUESTION") from error
        if asked is None:
            result = await self._ready(owner_user_id, dialogue, brief_version)
            await scope.event(
                "ADAPTER_ACCEPTED",
                {
                    "result": {"question": None},
                    "generated_content_hashes": {
                        "BRIEF_DIALOGUE_STOP": [_content_hash({"question": None})]
                    },
                },
            )
            return result
        turn = asked.turns[-1]
        await self._write(owner_user_id, lambda repo: repo.append_turn(turn))
        await scope.event(
            "ADAPTER_ACCEPTED",
            {
                "result": turn.to_snapshot(),
                "generated_content_hashes": {
                    "BRIEF_DIALOGUE_TURN": [_content_hash(turn.to_snapshot())]
                },
            },
        )
        return BriefDialogueResult(outcome, asked, brief_version)

    async def _ready(self, owner_user_id, dialogue, brief_version):
        ready = dialogue.as_ready()
        await self._write(owner_user_id, lambda repo: repo.update_state(ready))
        return BriefDialogueResult(BriefDialogueOutcome.READY, ready, brief_version)

    @evidence_application
    async def synthesize(self, *, owner_user_id, project_id, body):
        generator = self._generator()
        brief_version, dialogue = await self._active(
            owner_user_id=owner_user_id,
            project_id=project_id,
            expected_turn_count=body.expected_turn_count,
        )
        output = await synthesize_brief(
            generator,
            context=synthesis_context(
                project_id=project_id, dialogue=dialogue, brief=brief_version.brief
            ),
        )
        scope = current_proposal_evidence()
        try:
            brief, proposed = bind_synthesis(output, brief=brief_version.brief, dialogue=dialogue)
        except (TypeError, ValueError) as error:
            await retain_adapter_result(error=error, reason=str(error))
            raise ProposalGenerationError("INVALID_BRIEF_SYNTHESIS") from error
        now = datetime.now(UTC)
        async with self._sessions()() as session, session.begin():
            creation = await SqlAlchemyProjectBriefRepository(session).create_owned_version(
                project_id=project_id,
                owner_user_id=owner_user_id,
                created_by_user_id=owner_user_id,
                brief=brief,
            )
            if (
                creation.status is BriefVersionCreationStatus.PROJECT_NOT_FOUND
                or creation.version is None
            ):
                raise HTTPException(404, detail={"code": "PROJECT_NOT_FOUND"})
            if creation.status is BriefVersionCreationStatus.UNCHANGED:
                raise HTTPException(409, detail={"code": "BRIEF_SYNTHESIS_UNCHANGED"})
            version = creation.version
            assumptions = SqlAlchemyBriefAssumptionRepository(session)
            recorded = []
            for field, statement in proposed:
                recorded.append(
                    await assumptions.add(
                        create_brief_assumption(
                            project_id=project_id,
                            brief_version_number=version.version_number,
                            field=field,
                            statement=statement,
                            source=BriefAssumptionSource.MODEL_PROPOSED,
                            created_by_user_id=owner_user_id,
                            created_at=now,
                        )
                    )
                )
            synthesized = dialogue.as_synthesized(
                resulting_brief_version_number=version.version_number,
                synthesis_generation_id=scope.request.request_id,
                completed_at=now,
            )
            status = await SqlAlchemyBriefDialogueRepository(
                session, owner_user_id=owner_user_id
            ).update_state(synthesized)
            if status is not BriefDialogueWriteStatus.WRITTEN:
                raise _changed()
        await scope.event(
            "ADAPTER_ACCEPTED",
            {
                "result": {
                    "brief": brief.to_snapshot(),
                    "assumptions": [
                        {"field": field.value, "statement": statement}
                        for field, statement in proposed
                    ],
                },
                "generated_content_hashes": {"PROJECT_BRIEF": [version.content_hash]},
            },
        )
        return BriefDialogueResult(
            BriefDialogueOutcome.SYNTHESIZED, synthesized, version, tuple(recorded)
        )

    async def close(self, *, owner_user_id, project_id, body):
        brief_version, dialogue = await self._active(
            owner_user_id=owner_user_id,
            project_id=project_id,
            expected_turn_count=body.expected_turn_count,
        )
        closed = dialogue.as_closed(completed_at=datetime.now(UTC))
        await self._write(owner_user_id, lambda repo: repo.update_state(closed))
        return BriefDialogueResult(BriefDialogueOutcome.CLOSED, closed, brief_version)


def dialogue_response(result: BriefDialogueResult):
    dialogue = result.dialogue
    brief = None if result.brief_version is None else result.brief_version.brief
    return {
        "status": result.status.value,
        "snapshot": dialogue.to_snapshot(),
        "progress": {
            "questions_asked": dialogue.question_count,
            "question_limit": MAX_DIALOGUE_QUESTIONS,
            "open_fields": []
            if brief is None
            else [field.value for field in dialogue.open_fields(brief)],
            "open_essential_fields": []
            if brief is None
            else [field.value for field in dialogue.open_essential_fields(brief)],
        },
        "brief_version": None
        if result.brief_version is None
        else ProjectBriefVersionResponse.from_domain(result.brief_version).model_dump(mode="json"),
        "assumptions": [
            BriefAssumptionResponse.from_domain(assumption).model_dump(mode="json")
            for assumption in result.assumptions
        ],
    }


def create_brief_dialogue_router():
    router = APIRouter(prefix="/projects/{project_id}/brief-dialogue", tags=["project-brief"])

    def application(request: Request):
        return BriefDialogueApplication(request.app.state.application_runtime)

    @router.get("")
    async def current(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        return dialogue_response(
            await application(request).current(owner_user_id=user.id, project_id=project_id)
        )

    @router.post("", status_code=201)
    async def start(
        project_id: UUID,
        body: StartDialogueRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        return dialogue_response(
            await application(request).start(
                owner_user_id=user.id, project_id=project_id, body=body
            )
        )

    @router.post("/answers", status_code=201)
    async def answer(
        project_id: UUID,
        body: DialogueAnswerRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        return dialogue_response(
            await application(request).answer(
                owner_user_id=user.id, project_id=project_id, body=body
            )
        )

    @router.post("/questions", status_code=201)
    async def next_question(
        project_id: UUID,
        body: DialogueTurnRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        return dialogue_response(
            await application(request).next_question(
                owner_user_id=user.id, project_id=project_id, body=body
            )
        )

    @router.post("/synthesis", status_code=201)
    async def synthesize(
        project_id: UUID,
        body: DialogueTurnRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        return dialogue_response(
            await application(request).synthesize(
                owner_user_id=user.id, project_id=project_id, body=body
            )
        )

    @router.post("/close")
    async def close(
        project_id: UUID,
        body: DialogueTurnRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        return dialogue_response(
            await application(request).close(
                owner_user_id=user.id, project_id=project_id, body=body
            )
        )

    return router
