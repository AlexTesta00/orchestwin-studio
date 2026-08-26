"""FastAPI application factory for OrchesTwin Studio."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from orchestwin import __version__
from orchestwin.api.architecture import create_architecture_router
from orchestwin.api.artifacts import create_artifact_graph_router
from orchestwin.api.auth import AuthApiSettings, create_auth_router
from orchestwin.api.brownfield import create_brownfield_router
from orchestwin.api.clarification import create_clarification_router
from orchestwin.api.design import create_design_router
from orchestwin.api.execution import create_execution_router
from orchestwin.api.health import create_health_router
from orchestwin.api.projects import create_project_router
from orchestwin.api.requirements import create_requirements_router
from orchestwin.api.services import ApplicationRuntime, create_default_runtime
from orchestwin.api.teams import create_team_router
from orchestwin.config import ApplicationSettings, load_settings


def create_app(
    settings: ApplicationSettings | None = None,
    *,
    runtime: ApplicationRuntime | None = None,
    auth_settings: AuthApiSettings | None = None,
) -> FastAPI:
    """Assemble a FastAPI application from explicit adapters."""
    resolved_settings = settings if settings is not None else load_settings()
    resolved_runtime = runtime if runtime is not None else create_default_runtime(resolved_settings)
    resolved_auth_settings = auth_settings if auth_settings is not None else AuthApiSettings()

    @asynccontextmanager
    async def lifespan(
        application: FastAPI,
    ) -> AsyncIterator[None]:
        """Own and dispose process-level runtime resources."""
        del application

        yield
        await resolved_runtime.close()

    application = FastAPI(
        title=resolved_settings.application_name,
        version=__version__,
        debug=resolved_settings.debug,
        docs_url=f"{resolved_settings.api_prefix}/docs",
        openapi_url=f"{resolved_settings.api_prefix}/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
    )

    application.state.identity_service = resolved_runtime.identity_service
    application.state.project_service = resolved_runtime.project_service
    application.state.clarification_service = resolved_runtime.clarification_service
    application.state.brief_gate_service = resolved_runtime.brief_gate_service
    application.state.team_proposal_service = resolved_runtime.team_proposal_service
    application.state.agent_team_service = resolved_runtime.agent_team_service
    application.state.requirements_generation_service = (
        resolved_runtime.requirements_generation_service
    )
    application.state.requirements_revision_service = resolved_runtime.requirements_revision_service
    application.state.requirements_query_service = resolved_runtime.requirements_query_service
    application.state.requirements_gate_service = resolved_runtime.requirements_gate_service
    application.state.design_generation_service = resolved_runtime.design_generation_service
    application.state.design_revision_service = resolved_runtime.design_revision_service
    application.state.design_query_service = resolved_runtime.design_query_service
    application.state.design_gate_service = resolved_runtime.design_gate_service
    application.state.architecture_generation_service = (
        resolved_runtime.architecture_generation_service
    )
    application.state.architecture_revision_service = resolved_runtime.architecture_revision_service
    application.state.architecture_query_service = resolved_runtime.architecture_query_service
    application.state.architecture_gate_service = resolved_runtime.architecture_gate_service
    application.state.artifact_graph_query_service = resolved_runtime.artifact_graph_query_service
    application.state.brownfield_service = resolved_runtime.brownfield_service
    application.state.execution_query_service = resolved_runtime.execution_query_service
    application.state.high_impact_service = resolved_runtime.high_impact_service
    application.state.source_archive_maximum_upload_bytes = (
        resolved_settings.source_archive_maximum_upload_bytes
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_allowed_origins),
        allow_credentials=resolved_settings.cors_allow_credentials,
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

    for router in (
        create_health_router(),
        create_auth_router(resolved_auth_settings),
        create_project_router(),
        create_clarification_router(),
        create_team_router(),
        create_requirements_router(),
        create_design_router(),
        create_architecture_router(),
        create_artifact_graph_router(),
        create_brownfield_router(),
        create_execution_router(),
    ):
        application.include_router(
            router,
            prefix=resolved_settings.api_prefix,
        )

    return application
