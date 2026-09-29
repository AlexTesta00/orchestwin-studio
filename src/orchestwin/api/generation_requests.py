from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from fastapi.routing import APIRoute, serialize_response
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.generation_jobs import (
    GENERATION_JOB_NOT_FOUND,
    GenerationJobKind,
    GenerationJobProgress,
    GenerationJobResponse,
    GenerationJobStatus,
    GenerationOperation,
    generation_jobs,
)
from orchestwin.identity.domain import UserAccount
from orchestwin.projects.requirements_primitives import canonical_json

GENERATION_JOBS_API_PREFIX: Final = "/projects/{project_id}/generation-jobs"
PREFER: Final = "prefer"
RESPOND_ASYNC: Final = "respond-async"
PREFERENCE_APPLIED: Final = "Preference-Applied"
ACCEPTED: Final = 202
DEFAULT_STATUS: Final = 200
SERVER_ERROR_STATUS: Final = 500
SERVER_ERROR: Final = "Internal Server Error"
EXCEPTION_HANDLERS: Final = "starlette.exception_handlers"

GenerationCall = Callable[[], Awaitable[object]]


def prefers_async(request: Request) -> bool:
    return any(
        preference.split(";", 1)[0].split("=", 1)[0].strip().lower() == RESPOND_ASYNC
        for header in request.headers.getlist(PREFER)
        for preference in header.split(",")
    )


def request_key(
    operation: GenerationOperation,
    path_parameters: Mapping[str, object],
    body: BaseModel | None = None,
) -> str:
    content = {} if body is None else body.model_dump(mode="json")
    digest = hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()
    parameters = (
        f"{name}={value}" for name, value in sorted(path_parameters.items()) if name != "project_id"
    )
    return ":".join((GenerationOperation(operation).value, *parameters, digest))


def _body(response: Response) -> object:
    if not response.body:
        return None
    try:
        return json.loads(response.body)
    except ValueError:
        return response.body.decode("utf-8", "replace")


async def _answer(route: APIRoute, value: object) -> GenerationJobResponse:
    if isinstance(value, Response):
        return GenerationJobResponse(value.status_code, _body(value))
    field = route.response_field
    content = await serialize_response(
        field=field,
        response_content=value,
        include=route.response_model_include,
        exclude=route.response_model_exclude,
        by_alias=route.response_model_by_alias,
        exclude_unset=route.response_model_exclude_unset,
        exclude_defaults=route.response_model_exclude_defaults,
        exclude_none=route.response_model_exclude_none,
        dump_json=field is not None,
    )
    return GenerationJobResponse(
        route.status_code or DEFAULT_STATUS, content if field is None else json.loads(content)
    )


def _handler(scope: Mapping[str, object], error: Exception):
    exception_handlers, status_handlers = scope.get(EXCEPTION_HANDLERS, ({}, {}))
    if isinstance(error, StarletteHTTPException) and error.status_code in status_handlers:
        return status_handlers[error.status_code]
    return next(
        (exception_handlers[kind] for kind in type(error).__mro__ if kind in exception_handlers),
        None,
    )


async def _handled(request: Request, error: Exception) -> Response | None:
    handler = _handler(request.scope, error)
    if handler is None:
        return None
    try:
        response = handler(request, error)
        return await response if inspect.isawaitable(response) else response
    except Exception:
        return None


async def _refusal(request: Request, error: Exception) -> GenerationJobResponse:
    response = await _handled(request, error)
    if not isinstance(response, Response):
        response = PlainTextResponse(SERVER_ERROR, status_code=SERVER_ERROR_STATUS)
    return GenerationJobResponse(response.status_code, _body(response))


def _request_job(request: Request, call: GenerationCall):
    route = request.scope["route"]

    async def run(_progress: GenerationJobProgress) -> GenerationJobResponse:
        try:
            return await _answer(route, await call())
        except Exception as error:
            return await _refusal(request, error)

    return run


async def generation_request(
    request: Request,
    operation: GenerationOperation,
    call: GenerationCall,
    *,
    owner_user_id: UUID,
    project_id: UUID,
    body: BaseModel | None = None,
) -> object:
    if not prefers_async(request):
        return await call()
    job = generation_jobs(request).start(
        owner_user_id,
        project_id,
        GenerationJobKind.REQUEST,
        request_key(operation, request.path_params, body),
        _request_job(request, call),
        operation=operation,
    )
    return JSONResponse(
        job.to_payload(), status_code=ACCEPTED, headers={PREFERENCE_APPLIED: RESPOND_ASYNC}
    )


def create_generation_request_router() -> APIRouter:
    router = APIRouter(prefix=GENERATION_JOBS_API_PREFIX, tags=["generation-jobs"])

    @router.get("")
    async def project_jobs(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        status: GenerationJobStatus | None = None,
    ):
        jobs = generation_jobs(request).project_jobs(user.id, project_id, status)
        return {"items": [job.to_payload() for job in jobs]}

    @router.get("/{job_id}")
    async def read_job(
        project_id: UUID,
        job_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        job = generation_jobs(request).get(user.id, project_id, job_id)
        if job is None:
            raise HTTPException(404, detail={"code": GENERATION_JOB_NOT_FOUND})
        return job.to_payload()

    return router


__all__ = [
    "GENERATION_JOBS_API_PREFIX",
    "PREFERENCE_APPLIED",
    "RESPOND_ASYNC",
    "SERVER_ERROR",
    "create_generation_request_router",
    "generation_request",
    "prefers_async",
    "request_key",
]
