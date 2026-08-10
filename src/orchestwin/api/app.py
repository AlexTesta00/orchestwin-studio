"""FastAPI application factory for OrchesTwin Studio."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from orchestwin import __version__
from orchestwin.api.auth import (
    AuthApiSettings,
    create_auth_router,
)
from orchestwin.api.health import create_health_router
from orchestwin.api.services import (
    ApplicationRuntime,
    create_default_runtime,
)
from orchestwin.config import (
    ApplicationSettings,
    load_settings,
)


def create_app(
    settings: ApplicationSettings | None = None,
    *,
    runtime: ApplicationRuntime | None = None,
    auth_settings: AuthApiSettings | None = None,
) -> FastAPI:
    """Assemble a FastAPI application from explicit adapters."""
    resolved_settings = settings if settings is not None else load_settings()
    resolved_runtime = runtime if runtime is not None else create_default_runtime()
    resolved_auth_settings = auth_settings if auth_settings is not None else AuthApiSettings()

    @asynccontextmanager
    async def lifespan(
        application: FastAPI,
    ) -> AsyncIterator[None]:
        """Own and dispose process-level runtime resources."""
        yield
        await resolved_runtime.close()

    application = FastAPI(
        title=resolved_settings.application_name,
        version=__version__,
        debug=resolved_settings.debug,
        docs_url=(f"{resolved_settings.api_prefix}/docs"),
        openapi_url=(f"{resolved_settings.api_prefix}/openapi.json"),
        redoc_url=None,
        lifespan=lifespan,
    )

    application.state.identity_service = resolved_runtime.identity_service

    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_allowed_origins),
        allow_credentials=(resolved_settings.cors_allow_credentials),
        allow_methods=[
            "GET",
            "POST",
            "PATCH",
            "DELETE",
            "OPTIONS",
        ],
        allow_headers=[
            "Authorization",
            "Content-Type",
        ],
    )

    application.include_router(
        create_health_router(),
        prefix=resolved_settings.api_prefix,
    )
    application.include_router(
        create_auth_router(resolved_auth_settings),
        prefix=resolved_settings.api_prefix,
    )

    return application
