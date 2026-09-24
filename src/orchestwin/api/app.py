"""FastAPI application factory for OrchesTwin Studio."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from orchestwin import __version__
from orchestwin.api.artifacts import create_artifact_graph_router
from orchestwin.api.auth import AuthApiSettings, create_auth_router
from orchestwin.api.clarification import create_clarification_router
from orchestwin.api.design import create_design_router
from orchestwin.api.design_mockups import create_design_mockup_router
from orchestwin.api.health import create_health_router
from orchestwin.api.model_runtime import create_model_runtime_router
from orchestwin.api.projects import create_project_router
from orchestwin.api.proposal_evidence import create_proposal_evidence_router
from orchestwin.api.requirements import create_requirements_router
from orchestwin.api.services import ApplicationRuntime, create_default_runtime
from orchestwin.api.teams import create_team_router
from orchestwin.api.training import create_training_router
from orchestwin.api.twin_chat import create_twin_chat_router
from orchestwin.api.user_modeling_runtime import create_runtime_user_modeling_router
from orchestwin.api.validation import request_validation_error
from orchestwin.config import ApplicationSettings, load_settings
from orchestwin.models.proposal_evidence import ProposalEvidenceError
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.real_runtime import RealModelRuntimeError
from orchestwin.workflow.repository import HumanGateStateConflict


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

        try:
            if resolved_runtime.real_model_runtime is not None:
                await resolved_runtime.real_model_runtime.check_readiness(
                    resolved_runtime.database_runtime.session_factory
                )
            yield
        finally:
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

    application.add_exception_handler(RequestValidationError, request_validation_error)

    @application.exception_handler(HumanGateStateConflict)
    async def gate_conflict(_request, _error):
        return JSONResponse(status_code=409, content={"detail": "gate_state_conflict"})

    @application.exception_handler(ProposalGenerationError)
    async def proposal_failure(_request, error: ProposalGenerationError):
        unavailable = error.code in {"PROVIDER_UNAVAILABLE", "TIMEOUT", "RATE_LIMITED"}
        return JSONResponse(
            status_code=503 if unavailable else 502,
            content={"detail": {"code": error.code, "stage": "MODEL_PROPOSAL"}},
        )

    @application.exception_handler(RealModelRuntimeError)
    async def real_model_runtime_failure(_request, error: RealModelRuntimeError):
        return JSONResponse(
            status_code=503, content={"detail": {"code": str(error), "stage": "MODEL_RUNTIME"}}
        )

    application.state.application_runtime = resolved_runtime

    @application.exception_handler(ProposalEvidenceError)
    async def proposal_evidence_failure(_request, error: ProposalEvidenceError):
        return JSONResponse(
            status_code=503,
            content={"detail": {"code": str(error), "stage": "MODEL_PROPOSAL_EVIDENCE"}},
        )

    application.state.proposal_evidence_store = resolved_runtime.proposal_evidence_store
    application.state.final_evaluator_runtime = resolved_runtime.final_evaluator_runtime
    application.state.identity_service = resolved_runtime.identity_service
    application.state.project_service = resolved_runtime.project_service
    application.state.clarification_service = resolved_runtime.clarification_service
    application.state.brief_gate_service = resolved_runtime.brief_gate_service
    application.state.team_proposal_service = resolved_runtime.team_proposal_service
    application.state.agent_team_service = resolved_runtime.agent_team_service
    application.state.user_modeling_services = resolved_runtime.user_modeling_services
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
    application.state.artifact_graph_query_service = resolved_runtime.artifact_graph_query_service
    application.state.training_api_service = resolved_runtime.training_api_service

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
        create_runtime_user_modeling_router(resolved_runtime.user_modeling_services),
        create_twin_chat_router(),
        create_requirements_router(),
        create_design_router(),
        create_design_mockup_router(),
        create_artifact_graph_router(),
        create_training_router(),
        create_proposal_evidence_router(),
        create_model_runtime_router(),
    ):
        application.include_router(
            router,
            prefix=resolved_settings.api_prefix,
        )

    return application
