from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from orchestwin.api.auth import current_user_dependency
from orchestwin.identity.domain import UserAccount
from orchestwin.workflow_inputs import (
    PROVIDED_PROTOTYPE_CODE_UNAVAILABLE,
    PROVIDED_PROTOTYPE_EVALUATION_UNAVAILABLE,
    PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE,
    PROVIDED_PROTOTYPE_REVIEW_UNAVAILABLE,
    PROVIDED_PROTOTYPE_WALKTHROUGH_UNAVAILABLE,
    WorkflowInputError,
)

CurrentUser = Annotated[UserAccount, Depends(current_user_dependency)]


def workflow_service(request: Request):
    service = getattr(request.app.state, "workflow_inputs_service", None)
    if service is None:
        raise HTTPException(503, detail={"code": "WORKFLOW_INPUTS_SERVICE_UNAVAILABLE"})
    return service


Service = Annotated[object, Depends(workflow_service)]


def failure(error):
    code = error.code
    status = (
        404
        if code in {"PROJECT_NOT_FOUND", "PROVIDED_PROTOTYPE_NOT_FOUND"}
        else 409
        if (
            code
            in {
                "WORKFLOW_CONTEXT_CHANGED",
                "PROVIDED_PROTOTYPE_VERSION_CONFLICT",
                "REQUIREMENTS_APPROVAL_REQUIRED",
                "GATE_ITERATION_LIMIT",
                "INVALID_TRANSITION",
            }
            or (code.startswith("PROVIDED_PROTOTYPE_") and code.endswith("_UNAVAILABLE"))
        )
        else 422
    )
    detail = {"code": code}
    if error.detail:
        detail["message"] = error.detail
    raise HTTPException(status, detail=detail) from None


def create_workflow_inputs_router():
    router = APIRouter(prefix="/projects/{project_id}", tags=["workflow-inputs"])

    @router.get("/workflow-inputs", operation_id="getWorkflowInputs")
    async def records(project_id: UUID, user: CurrentUser, service: Service):
        result = await service.records(owner_user_id=user.id, project_id=project_id)
        if result is None:
            raise HTTPException(404, detail={"code": "PROJECT_NOT_FOUND"})
        return result

    @router.post("/workflow-inputs/decisions", status_code=201, operation_id="declareWorkflowGap")
    async def declare(
        project_id: UUID, user: CurrentUser, service: Service, payload: Annotated[dict, Body()]
    ):
        try:
            return await service.declare(
                owner_user_id=user.id, project_id=project_id, request=payload
            )
        except WorkflowInputError as error:
            failure(error)

    @router.get("/provided-prototypes", operation_id="getProvidedPrototypes")
    async def prototypes(project_id: UUID, user: CurrentUser, service: Service):
        result = await records(project_id, user, service)
        return {"prototypes": result["prototypes"], "limits": result["limits"]}

    @router.get("/provided-prototypes/current", operation_id="getCurrentProvidedPrototype")
    async def current(project_id: UUID, user: CurrentUser, service: Service):
        try:
            result = await service.current(owner_user_id=user.id, project_id=project_id)
            if result is None:
                raise WorkflowInputError("PROVIDED_PROTOTYPE_NOT_FOUND")
            return result
        except WorkflowInputError as error:
            failure(error)

    @router.get("/provided-prototypes/state", operation_id="getProvidedPrototypeState")
    async def state(project_id: UUID, user: CurrentUser, service: Service):
        try:
            return await service.state(owner_user_id=user.id, project_id=project_id)
        except WorkflowInputError as error:
            failure(error)

    @router.post("/provided-prototypes", status_code=201, operation_id="saveProvidedPrototype")
    async def save(
        project_id: UUID, user: CurrentUser, service: Service, payload: Annotated[dict, Body()]
    ):
        try:
            return await service.save_prototype(
                owner_user_id=user.id, project_id=project_id, request=payload
            )
        except WorkflowInputError as error:
            failure(error)

    @router.get("/provided-prototypes/gate/current", operation_id="getProvidedPrototypeGate")
    async def gate_current(project_id: UUID, user: CurrentUser, service: Service):
        try:
            result = await service.gate_current(owner_user_id=user.id, project_id=project_id)
            if result is None:
                raise WorkflowInputError("PROVIDED_PROTOTYPE_NOT_FOUND")
            return result
        except WorkflowInputError as error:
            failure(error)

    @router.post("/provided-prototypes/gate/submit", operation_id="submitProvidedPrototypeGate")
    async def submit(project_id: UUID, user: CurrentUser, service: Service):
        try:
            return await service.gate_action(
                owner_user_id=user.id, project_id=project_id, action="SUBMIT"
            )
        except WorkflowInputError as error:
            failure(error)

    @router.post("/provided-prototypes/gate/decision", operation_id="decideProvidedPrototypeGate")
    async def decide(
        project_id: UUID, user: CurrentUser, service: Service, payload: Annotated[dict, Body()]
    ):
        if (
            set(payload) - {"action", "reason"}
            or not isinstance(payload.get("action"), str)
            or payload.get("action")
            not in {
                "APPROVE",
                "REJECT",
                "REQUEST_REVISION",
            }
        ):
            raise HTTPException(422, detail={"code": "WORKFLOW_RECORDS_INVALID"})
        if payload.get("reason") is not None and not isinstance(payload["reason"], str):
            raise HTTPException(422, detail={"code": "WORKFLOW_REASON_INVALID"})
        try:
            return await service.gate_action(
                owner_user_id=user.id,
                project_id=project_id,
                action=payload["action"],
                reason=payload.get("reason"),
            )
        except WorkflowInputError as error:
            failure(error)

    @router.get(
        "/provided-prototypes/{prototype_id}/document", operation_id="getProvidedPrototypeDocument"
    )
    async def document(
        project_id: UUID,
        prototype_id: UUID,
        user: CurrentUser,
        service: Service,
        entry_screen: str | None = None,
        language: str = "it",
    ):
        try:
            return await service.document(
                owner_user_id=user.id,
                project_id=project_id,
                prototype_id=prototype_id,
                entry_screen=entry_screen,
                language=language,
            )
        except WorkflowInputError as error:
            failure(error)
        except ValueError as error:
            raise HTTPException(
                422, detail={"code": getattr(error, "code", "PROVIDED_PROTOTYPE_INPUT_INVALID")}
            ) from None

    return router


def protect_provided_consumers(router):
    for route in router.routes:
        path = route.path
        code = None
        if path.endswith("/validation/walkthrough"):
            code = PROVIDED_PROTOTYPE_WALKTHROUGH_UNAVAILABLE
        elif "POST" in route.methods and "/design" in path and "/provided-prototypes" not in path:
            code = (
                PROVIDED_PROTOTYPE_REVIEW_UNAVAILABLE
                if "review" in path
                else PROVIDED_PROTOTYPE_EVALUATION_UNAVAILABLE
                if "evaluation" in path
                else PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE
            )
        elif "POST" in route.methods and ("/code-changes" in path or "/code-tasks" in path):
            code = PROVIDED_PROTOTYPE_CODE_UNAVAILABLE
        if code is not None:

            def dependency(limit):
                async def guard(project_id: UUID, request: Request, user: CurrentUser):
                    service = getattr(request.app.state, "workflow_inputs_service", None)
                    if service is None:
                        return
                    try:
                        state = await service.state(owner_user_id=user.id, project_id=project_id)
                    except WorkflowInputError as error:
                        failure(error)
                    if state["source"] == "PROVIDED_PROTOTYPE":
                        raise HTTPException(409, detail={"code": limit})

                return guard

            route.dependencies.append(Depends(dependency(code)))
    return router
