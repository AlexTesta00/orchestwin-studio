"""Tests for Requirements API runtime wiring."""

from __future__ import annotations

from orchestwin.api.app import (
    create_app,
)
from orchestwin.api.auth import (
    AuthApiSettings,
)
from orchestwin.api.services import (
    ApplicationRuntime,
)
from orchestwin.config import (
    ApplicationSettings,
    RuntimeEnvironment,
)

CURRENT_REQUIREMENTS_PATH = "/api/v1/projects/{project_id}/requirements/current"

REQUIREMENTS_GATE_DECISION_PATH = "/api/v1/projects/{project_id}/requirements/gate/decision"


def test_application_registers_requirements_routes_and_runtime_state() -> None:
    """Expose Requirements endpoints through the standard API factory."""
    marker = object()

    runtime = ApplicationRuntime(
        requirements_generation_service=marker,
        requirements_revision_service=marker,
        requirements_query_service=marker,
        requirements_gate_service=marker,
    )

    app = create_app(
        ApplicationSettings(
            environment=(RuntimeEnvironment.TEST),
            api_prefix="/api/v1",
        ),
        runtime=runtime,
        auth_settings=(AuthApiSettings()),
    )

    openapi_paths = app.openapi()["paths"]

    assert CURRENT_REQUIREMENTS_PATH in openapi_paths

    assert "get" in openapi_paths[CURRENT_REQUIREMENTS_PATH]

    assert REQUIREMENTS_GATE_DECISION_PATH in openapi_paths

    assert "post" in openapi_paths[REQUIREMENTS_GATE_DECISION_PATH]

    assert app.state.requirements_generation_service is marker

    assert app.state.requirements_revision_service is marker

    assert app.state.requirements_query_service is marker

    assert app.state.requirements_gate_service is marker
