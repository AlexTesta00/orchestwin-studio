from __future__ import annotations

import json
from collections.abc import Callable, Coroutine, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Final
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.design_loop import RETRYABLE_REVIEW_CODES, TWIN_REVIEW_ATTEMPTS
from orchestwin.artifacts.design_critique import (
    DESIGN_CRITIQUE_FAILED,
    DESIGN_CRITIQUE_IMAGE_TOO_LARGE,
    DESIGN_CRITIQUE_INVALID,
    DESIGN_CRITIQUE_PAGE_INVALID,
    DESIGN_CRITIQUE_PROVIDER_UNSUPPORTED,
    DESIGN_CRITIQUE_SOURCE_INVALID,
    DESIGN_CRITIQUE_SOURCE_NOT_FOUND,
    DESIGN_CRITIQUE_TWINS_REQUIRED,
    MAX_SHOT_BYTES,
    MAX_SHOTS,
    MAX_TITLE_LENGTH,
    DesignCritiqueError,
    DesignCritiqueRun,
    DesignCritiqueSource,
    DesignCritiqueSourceKind,
    create_design_critique_run,
    create_design_critique_source,
    critique_anchors,
    critique_attachments,
    critique_bundle,
    critique_source_view,
    is_web_url,
)
from orchestwin.artifacts.design_critique_persistence import (
    DesignCritiqueWriteStatus,
    SqlAlchemyDesignCritiqueRepository,
)
from orchestwin.evaluation.critique_evaluator import (
    INVALID_CRITIQUE_OUTPUT,
    ProposerDesignCritiqueReviewer,
    critique_route,
)
from orchestwin.evaluation.evaluator import EvaluationUserTwinProfile, UserTwinEvaluationRequest
from orchestwin.identity.domain import UserAccount
from orchestwin.models.generation_budget import provider_result_cost_microusd
from orchestwin.models.proposal_evidence import current_proposal_evidence, evidence_application
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.structured_generation import StructuredGenerationProviderKind
from orchestwin.projects.progress import ProjectStage
from orchestwin.projects.sections import SectionState
from orchestwin.projects.sections_service import PROJECT_NOT_FOUND, SectionsFailure
from orchestwin.twins.persistence.repositories import SqlAlchemyUserTwinVersionRepository

DESIGN_CRITIQUE_API_PREFIX: Final = "/projects/{project_id}/design/critiques"
FORM_ALLOWANCE_BYTES: Final = 1024 * 1024
MAX_UPLOAD_BYTES: Final = MAX_SHOTS * MAX_SHOT_BYTES + FORM_ALLOWANCE_BYTES
MAX_PAGE_CHARACTERS: Final = 200_000
MAX_BRIEF_LENGTH: Final = 2000
MAX_REASON_LENGTH: Final = 300
SHOT_CACHE_CONTROL: Final = "private, max-age=0"
LOCALE_PATTERN: Final = r"^[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*$"
DESIGN_REVIEWER_NOT_CONFIGURED: Final = "DESIGN_REVIEWER_NOT_CONFIGURED"
ATTACHMENTS_UNSUPPORTED: Final = "ATTACHMENTS_UNSUPPORTED"
RETRYABLE_CRITIQUE_CODES: Final = RETRYABLE_REVIEW_CODES | {INVALID_CRITIQUE_OUTPUT}
TWINS_READY: Final = frozenset({SectionState.FINE, SectionState.UPDATE_AVAILABLE})


class DesignCritiqueStatus(StrEnum):
    RECORDED = "DESIGN_CRITIQUE_RECORDED"


class DesignCritiqueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: UUID
    locale: str = Field(default="it-IT", min_length=2, max_length=20, pattern=LOCALE_PATTERN)


@dataclass(frozen=True)
class DesignCritiqueResult:
    status: DesignCritiqueStatus
    run: DesignCritiqueRun
    cost_microusd: int = 0


def run_payload(run: DesignCritiqueRun, cost_microusd: int = 0) -> dict[str, object]:
    return {
        **run.to_snapshot(),
        "verdicts": list(run.verdicts()),
        "duration_seconds": round((run.completed_at - run.started_at).total_seconds(), 1),
        "cost_microusd": cost_microusd,
    }


def _refusal(code: str) -> HTTPException:
    status_code = 413 if code == DESIGN_CRITIQUE_IMAGE_TOO_LARGE else 422
    return HTTPException(status_code, detail={"code": code})


def _source_not_found() -> HTTPException:
    return HTTPException(404, detail={"code": DESIGN_CRITIQUE_SOURCE_NOT_FOUND})


def _write_refusal(status: DesignCritiqueWriteStatus) -> HTTPException:
    if status is DesignCritiqueWriteStatus.PROJECT_NOT_FOUND:
        return HTTPException(404, detail={"code": PROJECT_NOT_FOUND})
    if status is DesignCritiqueWriteStatus.SOURCE_NOT_FOUND:
        return _source_not_found()
    return HTTPException(409, detail={"code": f"DESIGN_CRITIQUE_{status.value}"})


def _failure(code: str, error: Exception) -> HTTPException:
    return HTTPException(502, detail={"code": code, "reason": str(error)[:MAX_REASON_LENGTH]})


def _route_kind(route):
    return getattr(getattr(route, "configuration", None), "provider_kind", None)


def _result_cost(result) -> int:
    return 0 if result is None else provider_result_cost_microusd(result.to_snapshot())


def _attempt_cost(error: ProposalGenerationError | None = None) -> int:
    result = getattr(current_proposal_evidence(), "result", None)
    if result is None and error is not None:
        result = error.result
    return _result_cost(result)


def _clipped(value: str, maximum: int) -> str:
    return " ".join(value.split())[:maximum].rstrip()


def _page_document(text: str | None) -> object:
    if text is None:
        return None
    if len(text) > MAX_PAGE_CHARACTERS:
        raise _refusal(DESIGN_CRITIQUE_PAGE_INVALID)
    try:
        return json.loads(text)
    except (RecursionError, ValueError) as error:
        raise _refusal(DESIGN_CRITIQUE_PAGE_INVALID) from error


def _viewport_widths(text: str | None, count: int) -> list[object]:
    if text is None:
        return [None] * count
    try:
        widths = json.loads(text)
    except (RecursionError, ValueError) as error:
        raise _refusal(DESIGN_CRITIQUE_SOURCE_INVALID) from error
    if not isinstance(widths, list) or len(widths) != count:
        raise _refusal(DESIGN_CRITIQUE_SOURCE_INVALID)
    return widths


def _title(
    title: str | None, url: str | None, page: object, files: Sequence[UploadFile], kind: str
) -> str:
    if title is not None and title.strip():
        return title
    candidates = (
        page.get("title") if isinstance(page, Mapping) else None,
        urlsplit(url).hostname if is_web_url(url) else None,
        (files[0].filename or "").rsplit(".", 1)[0] if files else None,
    )
    for candidate in candidates:
        text = _clipped(candidate, MAX_TITLE_LENGTH) if isinstance(candidate, str) else ""
        if text:
            return text
    return kind


class BoundedCritiqueRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def bounded_handler(request: Request) -> Response:
            declared = request.headers.get("content-length", "")
            if declared.isdecimal() and int(declared) > MAX_UPLOAD_BYTES:
                raise _refusal(DESIGN_CRITIQUE_IMAGE_TOO_LARGE)
            return await handler(request)

        return bounded_handler


class DesignCritiqueApplication:
    def __init__(self, runtime):
        self.runtime = runtime
        self._proposal_evidence_store = getattr(runtime, "proposal_evidence_store", None)

    def _sessions(self):
        database = getattr(self.runtime, "database_runtime", None)
        if database is None:
            raise HTTPException(503, detail={"code": "DATABASE_UNAVAILABLE"})
        return database.session_factory

    @staticmethod
    def _repository(session, owner_user_id):
        return SqlAlchemyDesignCritiqueRepository(session, owner_user_id=owner_user_id)

    async def _twins(self, owner_user_id, project_id):
        service = getattr(self.runtime, "sections_service", None)
        if service is not None:
            try:
                sections = await service.current(owner_user_id=owner_user_id, project_id=project_id)
            except SectionsFailure as error:
                raise HTTPException(
                    404 if error.code == PROJECT_NOT_FOUND else 409, detail={"code": error.code}
                ) from None
            if sections.section(ProjectStage.USER_TWINS).state not in TWINS_READY:
                raise HTTPException(409, detail={"code": DESIGN_CRITIQUE_TWINS_REQUIRED})
        sessions = self._sessions()
        async with sessions() as session:
            twins = await SqlAlchemyUserTwinVersionRepository(
                session, owner_user_id=owner_user_id
            ).list_current(project_id=project_id)
        if not twins:
            raise HTTPException(409, detail={"code": DESIGN_CRITIQUE_TWINS_REQUIRED})
        return twins

    def _generator(self):
        real = getattr(self.runtime, "real_model_runtime", None)
        if real is None or self._proposal_evidence_store is None:
            return None
        return real.user_modeling.proposal_port.generator

    def _critic(self):
        generator = self._generator()
        if generator is None:
            raise HTTPException(503, detail={"code": DESIGN_REVIEWER_NOT_CONFIGURED})
        kind = _route_kind(critique_route(generator))
        if kind is not StructuredGenerationProviderKind.CLAUDE_CODE_CLI:
            raise HTTPException(503, detail={"code": DESIGN_CRITIQUE_PROVIDER_UNSUPPORTED})
        return generator

    async def _project(self, owner_user_id, project_id):
        service = getattr(self.runtime, "project_service", None)
        if service is None:
            return None
        project = await service.get(project_id=project_id, owner_user_id=owner_user_id)
        if project is None:
            return None
        version = await service.current_brief(project_id=project_id, owner_user_id=owner_user_id)
        description = None if version is None else version.brief.description
        brief = _clipped(description or "", MAX_BRIEF_LENGTH)
        return {"name": project.display_name, **({"brief": brief} if brief else {})}

    async def create_source(
        self,
        *,
        owner_user_id,
        project_id,
        kind: str,
        title: str | None,
        url: str | None,
        page: str | None,
        files: Sequence[UploadFile],
        viewport_widths: str | None,
    ) -> DesignCritiqueSource:
        await self._twins(owner_user_id, project_id)
        if not 1 <= len(files) <= MAX_SHOTS:
            raise _refusal(DESIGN_CRITIQUE_SOURCE_INVALID)
        document = _page_document(page)
        widths = _viewport_widths(viewport_widths, len(files))
        contents = [await item.read(MAX_SHOT_BYTES + 1) for item in files]
        try:
            source, stored = create_design_critique_source(
                source_id=uuid4(),
                project_id=project_id,
                owner_user_id=owner_user_id,
                kind=kind,
                title=_title(title, url, document, files, kind),
                url=url,
                page=document,
                shots=list(zip(contents, widths, strict=True)),
                created_at=datetime.now(UTC),
            )
        except DesignCritiqueError as error:
            raise _refusal(error.code) from error
        sessions = self._sessions()
        async with sessions() as session, session.begin():
            status = await self._repository(session, owner_user_id).create_source(source, stored)
            if status is not DesignCritiqueWriteStatus.WRITTEN:
                raise _write_refusal(status)
        return source

    async def sources(self, *, owner_user_id, project_id) -> tuple[DesignCritiqueSource, ...]:
        sessions = self._sessions()
        async with sessions() as session:
            return await self._repository(session, owner_user_id).sources(project_id)

    async def source(self, *, owner_user_id, project_id, source_id) -> DesignCritiqueSource:
        sessions = self._sessions()
        async with sessions() as session:
            found = await self._repository(session, owner_user_id).source(project_id, source_id)
        if found is None:
            raise _source_not_found()
        return found

    async def shot(self, *, owner_user_id, project_id, source_id, code) -> tuple[str, bytes]:
        sessions = self._sessions()
        async with sessions() as session:
            found = await self._repository(session, owner_user_id).shot(project_id, source_id, code)
        if found is None:
            raise _source_not_found()
        return found

    async def _stored(self, owner_user_id, project_id, source_id):
        source = await self.source(
            owner_user_id=owner_user_id, project_id=project_id, source_id=source_id
        )
        contents = {}
        for shot in source.shots:
            stored = await self.shot(
                owner_user_id=owner_user_id,
                project_id=project_id,
                source_id=source.id,
                code=shot.code,
            )
            contents[shot.code] = stored[1]
        return source, contents

    @staticmethod
    async def _retire(code, run_id):
        scope = current_proposal_evidence()
        if scope is None or scope.request is None:
            return
        await scope.event("APPLICATION_RESULT", {"status": code, "evaluation_run_id": str(run_id)})
        scope.retire(role="TWIN_REVIEW", code=code)

    async def _review(self, reviewer, request):
        spent = 0
        for attempt in range(1, TWIN_REVIEW_ATTEMPTS + 1):
            try:
                response = await reviewer.evaluate(request)
            except ProposalGenerationError as error:
                if error.code == ATTACHMENTS_UNSUPPORTED:
                    raise HTTPException(
                        503, detail={"code": DESIGN_CRITIQUE_PROVIDER_UNSUPPORTED}
                    ) from error
                if attempt == TWIN_REVIEW_ATTEMPTS or error.code not in RETRYABLE_CRITIQUE_CODES:
                    raise
                spent += _attempt_cost(error)
                await self._retire("TWIN_REVIEW_REJECTED", request.evaluation_run_id)
            else:
                return response, spent + _attempt_cost()
        raise RuntimeError("design critique attempts are exhausted")

    async def _responses(self, reviewer, source, bundle, twins, run_id):
        responses = []
        cost = 0
        for index, twin in enumerate(twins):
            try:
                request = UserTwinEvaluationRequest(
                    evaluation_run_id=run_id,
                    project_id=source.project_id,
                    workflow_run_id=source.id,
                    artifact_bundle=bundle,
                    twin=EvaluationUserTwinProfile.from_version(twin),
                    evidence=(),
                    requested_at=datetime.now(UTC),
                )
                response, spent = await self._review(reviewer, request)
            except ValueError as error:
                raise _failure(DESIGN_CRITIQUE_FAILED, error) from error
            responses.append(response)
            cost += spent
            if index < len(twins) - 1:
                await self._retire("TWIN_REVIEWED", run_id)
        return responses, cost

    @evidence_application
    async def critique(self, *, owner_user_id, project_id, body) -> DesignCritiqueResult:
        source, contents = await self._stored(owner_user_id, project_id, body.source_id)
        twins = await self._twins(owner_user_id, project_id)
        generator = self._critic()
        project = await self._project(owner_user_id, project_id)
        started_at = datetime.now(UTC)
        run_id = uuid4()
        language = body.locale.split("-")[0]
        try:
            bundle = critique_bundle(source, contents, locale=body.locale, created_at=started_at)
            reviewer = ProposerDesignCritiqueReviewer(
                generator,
                source_id=source.id,
                source_view=critique_source_view(source, language),
                anchors=critique_anchors(source, language),
                attachments=critique_attachments(source, contents),
                project=project,
            )
        except ValueError as error:
            raise _failure(DESIGN_CRITIQUE_FAILED, error) from error
        responses, cost = await self._responses(reviewer, source, bundle, twins, run_id)
        try:
            run = create_design_critique_run(
                run_id=run_id,
                owner_user_id=owner_user_id,
                source=source,
                bundle=bundle,
                twins=[(twin.twin_id, twin.version_number, twin.profile.name) for twin in twins],
                responses=responses,
                started_at=started_at,
                completed_at=datetime.now(UTC),
            )
        except ValueError as error:
            raise _failure(DESIGN_CRITIQUE_INVALID, error) from error
        sessions = self._sessions()
        async with sessions() as session, session.begin():
            status = await self._repository(session, owner_user_id).create_run(run)
            if status is not DesignCritiqueWriteStatus.WRITTEN:
                raise _write_refusal(status)
        return DesignCritiqueResult(
            status=DesignCritiqueStatus.RECORDED, run=run, cost_microusd=cost
        )

    async def runs(self, *, owner_user_id, project_id) -> tuple[DesignCritiqueRun, ...]:
        sessions = self._sessions()
        async with sessions() as session:
            return await self._repository(session, owner_user_id).runs(project_id)


def create_design_critique_router() -> APIRouter:
    router = APIRouter(
        prefix=DESIGN_CRITIQUE_API_PREFIX, tags=["design"], route_class=BoundedCritiqueRoute
    )

    @router.post("/sources", status_code=201)
    async def upload_source(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        shots: Annotated[list[UploadFile] | None, File()] = None,
        kind: Annotated[str, Form()] = DesignCritiqueSourceKind.IMAGE.value,
        title: Annotated[str | None, Form()] = None,
        url: Annotated[str | None, Form()] = None,
        page: Annotated[str | None, Form()] = None,
        viewport_widths: Annotated[str | None, Form()] = None,
    ):
        application = DesignCritiqueApplication(request.app.state.application_runtime)
        source = await application.create_source(
            owner_user_id=user.id,
            project_id=project_id,
            kind=kind,
            title=title,
            url=url,
            page=page,
            files=shots or (),
            viewport_widths=viewport_widths,
        )
        return {"source": source.to_snapshot()}

    @router.get("/sources")
    async def sources(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        items = await DesignCritiqueApplication(request.app.state.application_runtime).sources(
            owner_user_id=user.id, project_id=project_id
        )
        return {"items": [item.to_snapshot() for item in items]}

    @router.get("/sources/{source_id}/shots/{code}", response_class=Response)
    async def shot(
        project_id: UUID,
        source_id: UUID,
        code: str,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        media_type, content = await DesignCritiqueApplication(
            request.app.state.application_runtime
        ).shot(owner_user_id=user.id, project_id=project_id, source_id=source_id, code=code)
        return Response(
            content=content, media_type=media_type, headers={"Cache-Control": SHOT_CACHE_CONTROL}
        )

    @router.post("", status_code=201)
    async def critique(
        project_id: UUID,
        body: DesignCritiqueRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        result = await DesignCritiqueApplication(request.app.state.application_runtime).critique(
            owner_user_id=user.id, project_id=project_id, body=body
        )
        return {"status": result.status.value, "run": run_payload(result.run, result.cost_microusd)}

    @router.get("")
    async def runs(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        items = await DesignCritiqueApplication(request.app.state.application_runtime).runs(
            owner_user_id=user.id, project_id=project_id
        )
        return {"items": [run_payload(run) for run in items]}

    return router


__all__ = [
    "DESIGN_CRITIQUE_API_PREFIX",
    "MAX_PAGE_CHARACTERS",
    "MAX_UPLOAD_BYTES",
    "RETRYABLE_CRITIQUE_CODES",
    "BoundedCritiqueRoute",
    "DesignCritiqueApplication",
    "DesignCritiqueRequest",
    "DesignCritiqueResult",
    "DesignCritiqueStatus",
    "create_design_critique_router",
    "run_payload",
]
