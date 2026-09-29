from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings
from orchestwin.api.services import ApplicationRuntime
from orchestwin.config import ApplicationSettings, LogLevel, RuntimeEnvironment

PREFIX = "/api/v1"
DESIGN = "/projects/{project_id}/design"
PARAMETER = re.compile(r"\{([a-z_]+)\}")
REQUIRED = (
    ("GET", "/mockups/capabilities"),
    ("POST", "/mockups/jobs"),
    ("GET", "/mockups/jobs/{job_id}"),
    ("GET", "/mockups/document"),
    ("POST", "/iterations/jobs"),
    ("GET", "/iterations/jobs/{job_id}"),
    ("GET", "/iterations"),
    ("GET", "/evaluations/{run_id}/pins"),
    ("GET", "/evaluations/{run_id}/document"),
)
LITERAL = (
    ("GET", "/mockups/capabilities"),
    ("POST", "/mockups/jobs"),
    ("GET", "/mockups/document"),
    ("GET", "/evaluations"),
    ("POST", "/evaluations"),
    ("GET", "/evaluations/comparison"),
    ("GET", "/evaluations/validations"),
)


class Recorder:
    def __init__(self, application):
        self.application = application
        self.scopes = []

    async def __call__(self, scope, receive, send):
        try:
            await self.application(scope, receive, send)
        finally:
            if scope["type"] == "http":
                self.scopes.append(scope)


@pytest.fixture(scope="module")
def application():
    return create_app(
        ApplicationSettings(
            application_name="OrchesTwin Design Route Test",
            environment=RuntimeEnvironment.TEST,
            debug=False,
            log_level=LogLevel.INFO,
            api_prefix=PREFIX,
            _env_file=None,
        ),
        runtime=ApplicationRuntime(),
        auth_settings=AuthApiSettings(_env_file=None),
    )


def design_operations(application) -> list[tuple[str, str]]:
    return sorted(
        (method.upper(), path.removeprefix(PREFIX + DESIGN))
        for path, operations in application.openapi()["paths"].items()
        if path == PREFIX + DESIGN or path.startswith(f"{PREFIX}{DESIGN}/")
        for method in operations
    )


def parameters(path: str) -> dict[str, str]:
    return {
        name: f"00000000-0000-4000-8000-{index:012d}"
        for index, name in enumerate(PARAMETER.findall(DESIGN + path), start=1)
    }


def dispatched(application, method: str, path: str):
    recorder = Recorder(application)
    values = parameters(path)
    client = TestClient(recorder, raise_server_exceptions=False)
    client.request(method, PREFIX + (DESIGN + path).format(**values))
    [scope] = recorder.scopes
    route = scope.get("route")
    return (
        getattr(route, "path", None),
        method in (getattr(route, "methods", None) or ()),
        scope.get("path_params"),
    ), values


def test_the_application_serves_the_mockup_iteration_and_review_pin_routes(application):
    served = design_operations(application)
    assert [item for item in REQUIRED if item not in served] == []


@pytest.mark.parametrize(("method", "path"), LITERAL)
def test_no_route_with_a_path_parameter_captures_a_literal_design_path(application, method, path):
    handled, values = dispatched(application, method, path)
    assert list(values) == ["project_id"]
    assert handled == (DESIGN + path, True, values)


def test_every_design_path_reaches_its_own_route(application):
    operations = design_operations(application)
    assert set(REQUIRED) | set(LITERAL) <= set(operations)
    misrouted = []
    for method, path in operations:
        handled, values = dispatched(application, method, path)
        if handled != (DESIGN + path, True, values):
            misrouted.append((method, path, handled))
    assert misrouted == []
