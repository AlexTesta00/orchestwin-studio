"""Authenticated, live model dependency readiness; no inference or case operations."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from orchestwin.api.auth import CurrentUser


def create_model_runtime_router():
    router = APIRouter(tags=["model-runtime"])

    @router.get("/model-runtime/readiness")
    async def readiness(request: Request, user: CurrentUser):
        runtime = request.app.state.application_runtime
        if runtime.real_model_runtime is None:
            return JSONResponse(
                status_code=503,
                content={
                    "mode": "DEVELOPMENT_FIXTURES",
                    "ready": False,
                    "code": "REAL_MODEL_RUNTIME_NOT_CONFIGURED",
                },
            )
        report = await runtime.real_model_runtime.check_readiness(
            runtime.database_runtime.session_factory
        )
        return JSONResponse(status_code=200 if report["ready"] else 503, content=report)

    return router
