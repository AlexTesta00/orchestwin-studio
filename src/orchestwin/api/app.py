"""FastAPI application factory for OrchesTwin Studio."""

from fastapi import FastAPI

from orchestwin import __version__
from orchestwin.api.health import create_health_router
from orchestwin.config import ApplicationSettings, load_settings


def create_app(settings: ApplicationSettings | None = None) -> FastAPI:
    """Assemble a FastAPI application from explicit immutable settings."""
    resolved_settings = settings if settings is not None else load_settings()

    application = FastAPI(
        title=resolved_settings.application_name,
        version=__version__,
        debug=resolved_settings.debug,
        docs_url=f"{resolved_settings.api_prefix}/docs",
        openapi_url=f"{resolved_settings.api_prefix}/openapi.json",
        redoc_url=None,
    )
    application.include_router(
        create_health_router(),
        prefix=resolved_settings.api_prefix,
    )

    return application
