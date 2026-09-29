from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import partial
from typing import Annotated, Final
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.design_loop import DesignLoopApplication
from orchestwin.api.generation_jobs import GenerationOperation
from orchestwin.api.generation_requests import generation_request
from orchestwin.artifacts.design_discussion import (
    LOCALE_PATTERN,
    MAX_DISCUSSION_ROUNDS,
    MAX_LOCALE_LENGTH,
    DesignDiscussion,
    DiscussionStatus,
    create_discussion_round,
    normalize_owner_note,
)
from orchestwin.artifacts.design_discussion_persistence import (
    DiscussionWriteStatus,
    SqlAlchemyDesignDiscussionRepository,
)
from orchestwin.artifacts.design_evaluation import DesignEvaluationError, design_review_view
from orchestwin.identity.domain import UserAccount
from orchestwin.models.hosted_configuration import HOSTED_PROVIDER_KINDS
from orchestwin.models.proposal_evidence import (
    current_proposal_evidence,
    evidence_application,
    retain_adapter_result,
)
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.twin_discussion import (
    INVALID_TWIN_DISCUSSION_OUTPUT,
    STATEMENT_PURPOSE,
    TWIN_DISCUSSION_TASK,
    bind_statement,
    bind_synthesis,
    discussion_findings,
    moderate_discussion,
    screen_titles,
    speak_as_twin,
    statement_context,
    synthesis_context,
    twin_keys,
)

DESIGN_DISCUSSION_API_PREFIX: Final = "/projects/{project_id}/design/discussions"
DISCUSSION_ROLE: Final = "TWIN_DISCUSSION"
STATEMENT_RECORDED: Final = "TWIN_STATEMENT_RECORDED"
STATEMENT_REJECTED: Final = "TWIN_STATEMENT_REJECTED"
SYNTHESIS_REJECTED: Final = "DISCUSSION_SYNTHESIS_REJECTED"
GENERATION_ATTEMPTS: Final = 2
RETRYABLE_CODES: Final = frozenset(
    {
        INVALID_TWIN_DISCUSSION_OUTPUT,
        "INVALID_PROVIDER_OUTPUT",
        "INCOMPLETE_OUTPUT",
        "RESPONSE_SCHEMA_ERROR",
    }
)
WRITE_ERRORS: Final = {
    DiscussionWriteStatus.PROJECT_NOT_FOUND: (404, "PROJECT_NOT_FOUND"),
    DiscussionWriteStatus.DISCUSSION_NOT_FOUND: (404, "DESIGN_DISCUSSION_NOT_FOUND"),
    DiscussionWriteStatus.DISCUSSION_OPEN: (409, "DESIGN_DISCUSSION_OPEN"),
    DiscussionWriteStatus.DISCUSSION_CLOSED: (409, "DESIGN_DISCUSSION_CLOSED"),
    DiscussionWriteStatus.DISCUSSION_CHANGED: (409, "DESIGN_DISCUSSION_CHANGED"),
    DiscussionWriteStatus.DISCUSSION_FULL: (409, "DESIGN_DISCUSSION_FULL"),
}


class DiscussionAction(StrEnum):
    APPROVE = "APPROVE"
    CLOSE = "CLOSE"


class DesignDiscussionCommandStatus(StrEnum):
    STARTED = "DESIGN_DISCUSSION_STARTED"
    ROUND_RECORDED = "DESIGN_DISCUSSION_ROUND_RECORDED"


class DesignDiscussionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    design_version_id: UUID
    design_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    locale: str = Field(
        default="it-IT", min_length=2, max_length=MAX_LOCALE_LENGTH, pattern=LOCALE_PATTERN
    )
    owner_note: str | None = None


class DiscussionRoundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_round_count: int = Field(ge=1, le=MAX_DISCUSSION_ROUNDS)
    owner_note: str | None = None


class DiscussionDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: DiscussionAction


@dataclass(frozen=True)
class DesignDiscussionResult:
    status: DesignDiscussionCommandStatus
    discussion: DesignDiscussion


def discussion_route(generator):
    return generator.route(TWIN_DISCUSSION_TASK, STATEMENT_PURPOSE)


def hosted_discussion(generator) -> bool:
    return discussion_route(generator).configuration.provider_kind in HOSTED_PROVIDER_KINDS


def _refusal(status: DiscussionWriteStatus) -> HTTPException:
    code, detail = WRITE_ERRORS[status]
    return HTTPException(code, detail={"code": detail})


def _generation_id() -> UUID:
    scope = current_proposal_evidence()
    if scope is None or scope.request is None:
        return uuid4()
    return scope.request.request_id


async def _rejection(error: Exception) -> ProposalGenerationError:
    await retain_adapter_result(error=error, reason=str(error))
    return ProposalGenerationError(INVALID_TWIN_DISCUSSION_OUTPUT)


async def _retire(scope, status: str, discussion_id: UUID) -> None:
    await scope.event("APPLICATION_RESULT", {"status": status, "discussion_id": str(discussion_id)})
    scope.retire(role=DISCUSSION_ROLE, code=status)


async def _record_statement(statement, discussion_id: UUID) -> None:
    scope = current_proposal_evidence()
    if scope is None or scope.request is None:
        return
    await scope.event(
        "ADAPTER_ACCEPTED",
        {
            "result": statement.to_snapshot(),
            "generated_content_hashes": {"TWIN_STATEMENT": [statement.content_hash]},
            **(
                {"related_generations": list(scope.related_generations)}
                if scope.related_generations
                else {}
            ),
        },
    )
    await _retire(scope, STATEMENT_RECORDED, discussion_id)


async def _reject(status: str, discussion_id: UUID) -> None:
    scope = current_proposal_evidence()
    if scope is None or scope.request is None:
        return
    await _retire(scope, status, discussion_id)


async def _attempt(generation, *, rejected: str, discussion_id: UUID):
    for attempt in range(1, GENERATION_ATTEMPTS + 1):
        try:
            return await generation()
        except ProposalGenerationError as error:
            if attempt == GENERATION_ATTEMPTS or error.code not in RETRYABLE_CODES:
                raise
            await _reject(rejected, discussion_id)
    raise RuntimeError("discussion generation attempts are exhausted")


async def _speak(
    generator, *, context, speaker, keys, previous, others, owner_note, locale, hosted
):
    output = await speak_as_twin(generator, context=context, hosted=hosted)
    generation_id = _generation_id()
    try:
        return bind_statement(
            output,
            speaker=speaker,
            keys=keys,
            generation_id=generation_id,
            previous=previous,
            others=others,
            owner_note=owner_note,
            locale=locale,
        )
    except (TypeError, ValueError) as error:
        rejection = await _rejection(error)
        raise rejection from error


async def _moderate(generator, *, context, keys, ordinal, note, statements, compose, hosted):
    output = await moderate_discussion(generator, context=context, hosted=hosted)
    generation_id = _generation_id()
    try:
        return compose(
            create_discussion_round(
                ordinal=ordinal,
                owner_note=note,
                statements=tuple(statements),
                synthesis=bind_synthesis(output, keys=keys, generation_id=generation_id),
                created_at=datetime.now(UTC),
            )
        )
    except (TypeError, ValueError) as error:
        rejection = await _rejection(error)
        raise rejection from error


async def _accept_round(round_) -> None:
    scope = current_proposal_evidence()
    if scope is None or scope.request is None:
        return
    await scope.event(
        "ADAPTER_ACCEPTED",
        {
            "result": round_.to_snapshot(),
            "generated_content_hashes": {"DISCUSSION_ROUND": [round_.content_hash]},
            "related_generations": scope.related_generations,
        },
    )


class DesignDiscussionApplication:
    def __init__(self, runtime):
        self.runtime = runtime
        self._loop = DesignLoopApplication(runtime)
        self._proposal_evidence_store = self._loop._proposal_evidence_store

    @staticmethod
    def _repository(session, owner_user_id):
        return SqlAlchemyDesignDiscussionRepository(session, owner_user_id=owner_user_id)

    def _generator(self):
        generator = self._loop._generator()
        if generator is None:
            raise HTTPException(503, detail={"code": "DESIGN_DISCUSSION_NOT_CONFIGURED"})
        return generator

    @staticmethod
    def _note(value):
        try:
            return normalize_owner_note(value)
        except ValueError as error:
            raise HTTPException(422, detail={"code": "DISCUSSION_NOTE_INVALID"}) from error

    async def _design(
        self, owner_user_id, project_id, version_id, content_hash, *, generator, locale
    ):
        version = await self._loop._current(owner_user_id, project_id)
        if (version.id, version.content_hash) != (version_id, content_hash):
            raise HTTPException(409, detail={"code": "DESIGN_CONTEXT_CHANGED"})
        hosted = hosted_discussion(generator)
        try:
            view = design_review_view(version, hosted=hosted, language=locale.split("-")[0])
        except DesignEvaluationError as error:
            raise HTTPException(409, detail={"code": error.code}) from error
        return version, view, hosted

    async def _still_current(self, owner_user_id, project_id, version):
        refreshed = await self._loop._current(owner_user_id, project_id)
        if (refreshed.id, refreshed.content_hash) != (version.id, version.content_hash):
            raise HTTPException(409, detail={"code": "DESIGN_CONTEXT_CHANGED"})

    async def _findings(self, owner_user_id, project_id, version, keys):
        runs = await self._loop.runs(owner_user_id=owner_user_id, project_id=project_id)
        run = next((item for item in runs if item.design_version_id == version.id), None)
        if run is None:
            return []
        dismissed = await self._loop._dismissed(owner_user_id=owner_user_id, project_id=project_id)
        return discussion_findings(run, keys, dismissed)

    async def _discuss(
        self,
        generator,
        *,
        discussion_id,
        owner_user_id,
        project_id,
        version,
        view,
        hosted,
        twins,
        locale,
        note,
        previous,
        compose,
    ):
        keys = twin_keys(twins)
        findings = await self._findings(owner_user_id, project_id, version, keys)
        ordinal = 1 if previous is None else previous.ordinal + 1
        earlier = () if previous is None else previous.statements
        statements = []
        for speaker in keys:
            speaker_id = keys[speaker].twin_id
            context = statement_context(
                project_id=project_id,
                locale=locale,
                ordinal=ordinal,
                owner_note=note,
                keys=keys,
                speaker=speaker,
                design=view,
                findings=findings,
                previous=previous,
            )
            statement = await _attempt(
                partial(
                    _speak,
                    generator,
                    context=context,
                    speaker=speaker,
                    keys=keys,
                    previous=next(
                        (item.statement for item in earlier if item.twin_id == speaker_id), None
                    ),
                    others=tuple(item.statement for item in earlier if item.twin_id != speaker_id),
                    owner_note=note,
                    locale=locale,
                    hosted=hosted,
                ),
                rejected=STATEMENT_REJECTED,
                discussion_id=discussion_id,
            )
            statements.append(statement)
            await _record_statement(statement, discussion_id)
        discussion = await _attempt(
            partial(
                _moderate,
                generator,
                context=synthesis_context(
                    project_id=project_id,
                    locale=locale,
                    ordinal=ordinal,
                    owner_note=note,
                    keys=keys,
                    statements=statements,
                    screens=screen_titles(view) if hosted else (),
                ),
                keys=keys,
                ordinal=ordinal,
                note=note,
                statements=statements,
                compose=compose,
                hosted=hosted,
            ),
            rejected=SYNTHESIS_REJECTED,
            discussion_id=discussion_id,
        )
        await _accept_round(discussion.rounds[-1])
        return discussion

    async def discussions(self, *, owner_user_id, project_id) -> tuple[DesignDiscussion, ...]:
        sessions = self._loop._sessions()
        async with sessions() as session:
            return await self._repository(session, owner_user_id).list(project_id=project_id)

    @evidence_application
    async def start(self, *, owner_user_id, project_id, body) -> DesignDiscussionResult:
        note = self._note(body.owner_note)
        generator = self._generator()
        version, view, hosted = await self._design(
            owner_user_id,
            project_id,
            body.design_version_id,
            body.design_content_hash,
            generator=generator,
            locale=body.locale,
        )
        twins = await self._loop._twins(owner_user_id, project_id, version)
        sessions = self._loop._sessions()
        async with sessions() as session:
            existing = await self._repository(session, owner_user_id).open_for_version(
                project_id=project_id, design_version_id=version.id
            )
        if existing is not None:
            raise HTTPException(409, detail={"code": "DESIGN_DISCUSSION_OPEN"})
        package = version.package
        alternative = next(
            item
            for item in package.alternatives
            if item.id == package.owner_selected_alternative_id
        )
        discussion_id = uuid4()
        created_at = datetime.now(UTC)

        def compose(round_):
            return DesignDiscussion(
                id=discussion_id,
                project_id=project_id,
                owner_user_id=owner_user_id,
                design_version_id=version.id,
                design_version_number=version.version_number,
                design_content_hash=version.content_hash,
                alternative_id=alternative.id,
                alternative_code=alternative.code,
                locale=body.locale,
                status=DiscussionStatus.OPEN,
                rounds=(round_,),
                created_at=created_at,
                decided_at=None,
            )

        discussion = await self._discuss(
            generator,
            discussion_id=discussion_id,
            owner_user_id=owner_user_id,
            project_id=project_id,
            version=version,
            view=view,
            hosted=hosted,
            twins=twins,
            locale=body.locale,
            note=note,
            previous=None,
            compose=compose,
        )
        await self._still_current(owner_user_id, project_id, version)
        async with sessions() as session, session.begin():
            status = await self._repository(session, owner_user_id).create(discussion)
            if status is not DiscussionWriteStatus.WRITTEN:
                raise _refusal(status)
        return DesignDiscussionResult(
            status=DesignDiscussionCommandStatus.STARTED, discussion=discussion
        )

    @evidence_application
    async def next_round(
        self, *, owner_user_id, project_id, discussion_id, body
    ) -> DesignDiscussionResult:
        note = self._note(body.owner_note)
        generator = self._generator()
        sessions = self._loop._sessions()
        async with sessions() as session:
            current = await self._repository(session, owner_user_id).get(
                project_id=project_id, discussion_id=discussion_id
            )
        if current is None:
            raise _refusal(DiscussionWriteStatus.DISCUSSION_NOT_FOUND)
        if current.status is not DiscussionStatus.OPEN:
            raise _refusal(DiscussionWriteStatus.DISCUSSION_CLOSED)
        if body.expected_round_count != len(current.rounds):
            raise _refusal(DiscussionWriteStatus.DISCUSSION_CHANGED)
        if len(current.rounds) >= MAX_DISCUSSION_ROUNDS:
            raise _refusal(DiscussionWriteStatus.DISCUSSION_FULL)
        version, view, hosted = await self._design(
            owner_user_id,
            project_id,
            current.design_version_id,
            current.design_content_hash,
            generator=generator,
            locale=current.locale,
        )
        twins = await self._loop._twins(owner_user_id, project_id, version)
        discussion = await self._discuss(
            generator,
            discussion_id=current.id,
            owner_user_id=owner_user_id,
            project_id=project_id,
            version=version,
            view=view,
            hosted=hosted,
            twins=twins,
            locale=current.locale,
            note=note,
            previous=current.rounds[-1],
            compose=current.with_round,
        )
        await self._still_current(owner_user_id, project_id, version)
        async with sessions() as session, session.begin():
            status = await self._repository(session, owner_user_id).append_round(
                project_id=project_id,
                discussion_id=current.id,
                round=discussion.rounds[-1],
                expected_round_count=len(current.rounds),
            )
            if status is not DiscussionWriteStatus.WRITTEN:
                raise _refusal(status)
        return DesignDiscussionResult(
            status=DesignDiscussionCommandStatus.ROUND_RECORDED, discussion=discussion
        )

    async def decide(self, *, owner_user_id, project_id, discussion_id, body) -> DesignDiscussion:
        status = (
            DiscussionStatus.APPROVED
            if body.action is DiscussionAction.APPROVE
            else DiscussionStatus.CLOSED
        )
        sessions = self._loop._sessions()
        async with sessions() as session, session.begin():
            repository = self._repository(session, owner_user_id)
            written = await repository.decide(
                project_id=project_id,
                discussion_id=discussion_id,
                status=status,
                decided_at=datetime.now(UTC),
            )
            if written is not DiscussionWriteStatus.WRITTEN:
                raise _refusal(written)
            return await repository.get(project_id=project_id, discussion_id=discussion_id)


def create_design_discussion_router():
    router = APIRouter(prefix=DESIGN_DISCUSSION_API_PREFIX, tags=["design"])

    @router.get("")
    async def discussions(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        items = await DesignDiscussionApplication(
            request.app.state.application_runtime
        ).discussions(owner_user_id=user.id, project_id=project_id)
        return [item.to_snapshot() for item in items]

    @router.post("", status_code=201)
    async def start(
        project_id: UUID,
        body: DesignDiscussionRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        async def opening():
            result = await DesignDiscussionApplication(request.app.state.application_runtime).start(
                owner_user_id=user.id, project_id=project_id, body=body
            )
            return result.discussion.to_snapshot()

        return await generation_request(
            request,
            GenerationOperation.DISCUSSION_START,
            opening,
            owner_user_id=user.id,
            project_id=project_id,
            body=body,
        )

    @router.post("/{discussion_id}/rounds", status_code=201)
    async def next_round(
        project_id: UUID,
        discussion_id: UUID,
        body: DiscussionRoundRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        async def continuation():
            result = await DesignDiscussionApplication(
                request.app.state.application_runtime
            ).next_round(
                owner_user_id=user.id, project_id=project_id, discussion_id=discussion_id, body=body
            )
            return result.discussion.to_snapshot()

        return await generation_request(
            request,
            GenerationOperation.DISCUSSION_ROUND,
            continuation,
            owner_user_id=user.id,
            project_id=project_id,
            body=body,
        )

    @router.post("/{discussion_id}/decision")
    async def decide(
        project_id: UUID,
        discussion_id: UUID,
        body: DiscussionDecisionRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        discussion = await DesignDiscussionApplication(
            request.app.state.application_runtime
        ).decide(
            owner_user_id=user.id, project_id=project_id, discussion_id=discussion_id, body=body
        )
        return discussion.to_snapshot()

    return router


__all__ = [
    "DESIGN_DISCUSSION_API_PREFIX",
    "DesignDiscussionApplication",
    "DesignDiscussionCommandStatus",
    "DesignDiscussionRequest",
    "DesignDiscussionResult",
    "DiscussionAction",
    "DiscussionDecisionRequest",
    "DiscussionRoundRequest",
    "create_design_discussion_router",
    "discussion_route",
    "hosted_discussion",
]
