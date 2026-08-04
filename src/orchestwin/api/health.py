"""Liveness endpoint for the OrchesTwin Studio HTTP API."""

from typing import ClassVar, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Stable response returned by the liveness endpoint."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"


def create_health_router() -> APIRouter:
    """Create the health router without retaining mutable module state."""
    router = APIRouter(tags=["health"])

    @router.get(
        "/health",
        response_model=HealthResponse,
        status_code=status.HTTP_200_OK,
        summary="Check service liveness",
        operation_id="getHealth",
    )
    async def get_health() -> HealthResponse:
        """Report that the API process can serve HTTP requests."""
        return HealthResponse()

    return router
