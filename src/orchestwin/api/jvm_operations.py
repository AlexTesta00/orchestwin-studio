"""Owner-scoped Jvm operation history and explicit exact Gate 7 decisions."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy.exc import SQLAlchemyError

from orchestwin.api.auth import current_user_dependency
from orchestwin.identity.domain import UserAccount
from orchestwin.jvm_execution.operation_governance import JvmOperationError, JvmOperationKind
from orchestwin.jvm_execution.operation_persistence import SqlAlchemyJvmOperationStore
from orchestwin.workflow.gates import HumanGateAction
from orchestwin.workflow.repository import HumanGateStateConflict


class DecideJvmOperationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_gate_event_sequence: int = Field(ge=1, strict=True)
    action: HumanGateAction
    reason: str | None = Field(default=None, min_length=1, max_length=2000)


class JvmOperationResponse(BaseModel):
    snapshot: dict[str, JsonValue]


class JvmOperationListResponse(BaseModel):
    items: tuple[dict[str, JsonValue], ...]


def jvm_operation_store_dependency(request: Request) -> SqlAlchemyJvmOperationStore:
    store = getattr(request.app.state, "jvm_operation_store", None)
    if store is None:
        raise HTTPException(503, detail={"code": "JVM_OPERATION_STORE_UNAVAILABLE"})
    return store


async def _invoke(awaitable):
    try:
        return await awaitable
    except JvmOperationError as error:
        raise HTTPException(error.status_code, detail={"code": error.code}) from None
    except HumanGateStateConflict:
        raise HTTPException(409, detail={"code": "JVM_OPERATION_GATE_STATE_CONFLICT"}) from None
    except SQLAlchemyError:
        raise HTTPException(503, detail={"code": "JVM_OPERATION_STORAGE_UNAVAILABLE"}) from None


Owner = Annotated[UserAccount, Depends(current_user_dependency)]
Store = Annotated[SqlAlchemyJvmOperationStore, Depends(jvm_operation_store_dependency)]


def create_jvm_operations_router() -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/jvm-operations", tags=["jvm-operations"])

    @router.get("", response_model=JvmOperationListResponse, operation_id="listJvmOperations")
    async def history(
        project_id: UUID, user: Owner, store: Store, kind: JvmOperationKind | None = None
    ):
        return JvmOperationListResponse(
            items=await _invoke(
                store.history(owner_user_id=user.id, project_id=project_id, kind=kind)
            )
        )

    @router.get(
        "/{operation_id}", response_model=JvmOperationResponse, operation_id="getJvmOperation"
    )
    async def get(project_id: UUID, operation_id: UUID, user: Owner, store: Store):
        return JvmOperationResponse(
            snapshot=await _invoke(
                store.get(owner_user_id=user.id, project_id=project_id, operation_id=operation_id)
            )
        )

    @router.post(
        "/{operation_id}/gate",
        response_model=JvmOperationResponse,
        operation_id="decideJvmOperationGate",
    )
    async def decide(
        project_id: UUID,
        operation_id: UUID,
        body: DecideJvmOperationBody,
        user: Owner,
        store: Store,
    ):
        return JvmOperationResponse(
            snapshot=await _invoke(
                store.decide(
                    owner_user_id=user.id,
                    project_id=project_id,
                    operation_id=operation_id,
                    expected_hash=body.expected_content_hash,
                    expected_event_sequence=body.expected_gate_event_sequence,
                    action=body.action,
                    reason=body.reason,
                )
            )
        )

    return router
