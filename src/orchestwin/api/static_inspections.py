"""Authenticated preparation, explicit Gate 7 decisions, execution and recovery."""

from __future__ import annotations

import logging
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy.exc import SQLAlchemyError

from orchestwin.api.auth import current_user_dependency
from orchestwin.identity.domain import UserAccount
from orchestwin.web_execution.static_browser_jobs import StaticBrowserError
from orchestwin.web_execution.static_inspections import (
    InspectionError,
    StaticInspectionService,
    scenarios_from_snapshot,
)
from orchestwin.workflow.gates import HumanGateAction
from orchestwin.workflow.repository import HumanGateStateConflict

_LOG = logging.getLogger(__name__)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActionBody(ApiModel):
    kind: Literal["click", "fill", "press", "expect_text"]
    selector: str = Field(min_length=1, max_length=160)
    value: str | None = Field(default=None, max_length=1000)


class ScenarioBody(ApiModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,39}$")
    route: str = Field(default="/", min_length=1, max_length=201)
    actions: tuple[ActionBody, ...] = Field(min_length=1, max_length=8)


class PrepareInspectionBody(ApiModel):
    request_id: UUID
    source_revision_id: UUID
    scenarios: tuple[ScenarioBody, ...] = Field(min_length=1, max_length=2)


class ExpectedPlanBody(ApiModel):
    expected_plan_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class DecideInspectionBody(ExpectedPlanBody):
    expected_gate_event_sequence: int = Field(ge=1, strict=True)
    action: HumanGateAction
    reason: str | None = Field(default=None, min_length=1, max_length=2000)


class InspectionResponse(ApiModel):
    snapshot: dict[str, JsonValue]


class InspectionListResponse(ApiModel):
    items: tuple[dict[str, JsonValue], ...]


def static_inspection_service_dependency(request: Request) -> StaticInspectionService:
    service = getattr(request.app.state, "static_inspection_service", None)
    if service is None:
        raise HTTPException(503, detail={"code": "STATIC_INSPECTION_SERVICE_DISABLED"})
    return service


async def _invoke(awaitable):
    try:
        return await awaitable
    except InspectionError as error:
        raise HTTPException(error.status_code, detail={"code": error.code}) from None
    except StaticBrowserError:
        raise HTTPException(
            409, detail={"code": "STATIC_INSPECTION_INPUT_OR_EVIDENCE_INVALID"}
        ) from None
    except HumanGateStateConflict:
        raise HTTPException(409, detail={"code": "GATE_7_STATE_CONFLICT"}) from None
    except SQLAlchemyError as error:
        _LOG.error("Static inspection persistence error: %s", type(error).__name__)
        raise HTTPException(503, detail={"code": "STATIC_INSPECTION_STORAGE_UNAVAILABLE"}) from None
    except OSError as error:
        _LOG.error("Static inspection evidence error: %s", type(error).__name__)
        raise HTTPException(
            503, detail={"code": "STATIC_INSPECTION_EVIDENCE_UNAVAILABLE"}
        ) from None


Owner = Annotated[UserAccount, Depends(current_user_dependency)]
Service = Annotated[StaticInspectionService, Depends(static_inspection_service_dependency)]


def create_static_inspection_router() -> APIRouter:
    router = APIRouter(
        prefix="/projects/{project_id}/static-browser-inspections",
        tags=["static-browser-inspections"],
    )

    @router.post(
        "",
        response_model=InspectionResponse,
        status_code=201,
        operation_id="prepareStaticBrowserInspection",
    )
    async def prepare(project_id: UUID, body: PrepareInspectionBody, user: Owner, service: Service):
        try:
            scenarios = scenarios_from_snapshot(
                [item.model_dump(mode="json") for item in body.scenarios]
            )
        except (InspectionError, StaticBrowserError):
            raise HTTPException(
                422, detail={"code": "STATIC_INSPECTION_SCENARIOS_INVALID"}
            ) from None
        return InspectionResponse(
            snapshot=await _invoke(
                service.prepare(
                    owner_user_id=user.id,
                    project_id=project_id,
                    request_id=body.request_id,
                    revision_id=body.source_revision_id,
                    scenarios=scenarios,
                )
            )
        )

    @router.get(
        "", response_model=InspectionListResponse, operation_id="listStaticBrowserInspections"
    )
    async def history(project_id: UUID, user: Owner, service: Service):
        return InspectionListResponse(
            items=await _invoke(service.history(owner_user_id=user.id, project_id=project_id))
        )

    @router.get(
        "/{request_id}",
        response_model=InspectionResponse,
        operation_id="getStaticBrowserInspection",
    )
    async def get(project_id: UUID, request_id: UUID, user: Owner, service: Service):
        return InspectionResponse(
            snapshot=await _invoke(
                service.get(
                    owner_user_id=user.id,
                    project_id=project_id,
                    request_id=request_id,
                )
            )
        )

    @router.post(
        "/{request_id}/gate",
        response_model=InspectionResponse,
        operation_id="decideStaticBrowserInspectionGate",
    )
    async def decide(
        project_id: UUID,
        request_id: UUID,
        body: DecideInspectionBody,
        user: Owner,
        service: Service,
    ):
        return InspectionResponse(
            snapshot=await _invoke(
                service.decide(
                    owner_user_id=user.id,
                    project_id=project_id,
                    request_id=request_id,
                    expected_hash=body.expected_plan_content_hash,
                    expected_event_sequence=body.expected_gate_event_sequence,
                    action=body.action,
                    reason=body.reason,
                )
            )
        )

    @router.post(
        "/{request_id}/execute",
        response_model=InspectionResponse,
        operation_id="executeStaticBrowserInspection",
    )
    async def execute(
        project_id: UUID, request_id: UUID, body: ExpectedPlanBody, user: Owner, service: Service
    ):
        return InspectionResponse(
            snapshot=await _invoke(
                service.execute(
                    owner_user_id=user.id,
                    project_id=project_id,
                    request_id=request_id,
                    expected_hash=body.expected_plan_content_hash,
                )
            )
        )

    @router.post(
        "/{request_id}/recover",
        response_model=InspectionResponse,
        operation_id="recoverStaticBrowserInspection",
    )
    async def recover(
        project_id: UUID, request_id: UUID, body: ExpectedPlanBody, user: Owner, service: Service
    ):
        return InspectionResponse(
            snapshot=await _invoke(
                service.recover(
                    owner_user_id=user.id,
                    project_id=project_id,
                    request_id=request_id,
                    expected_hash=body.expected_plan_content_hash,
                )
            )
        )

    return router
