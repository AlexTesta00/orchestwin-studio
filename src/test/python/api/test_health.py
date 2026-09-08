"""Contract tests for the versioned API health endpoint."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings
from orchestwin.api.services import ApplicationRuntime
from orchestwin.config import ApplicationSettings, LogLevel, RuntimeEnvironment


def build_test_settings(*, api_prefix: str = "/api/v1") -> ApplicationSettings:
    """Create deterministic settings without reading local environment files."""
    return ApplicationSettings(
        application_name="OrchesTwin Test API",
        environment=RuntimeEnvironment.TEST,
        debug=False,
        log_level=LogLevel.INFO,
        api_prefix=api_prefix,
        _env_file=None,
    )


# S12-C51-R1: isolate liveness tests from local configuration.
@pytest.fixture(autouse=True)
def isolate_health_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate only this test module; pytest restores the original environment."""
    for name in tuple(os.environ):
        if name.upper().startswith("ORCHESTWIN_"):
            monkeypatch.delenv(name, raising=False)


def build_test_application(*, api_prefix: str = "/api/v1") -> FastAPI:
    """Liveness tests need no database, JWT credentials, or default runtime."""
    return create_app(
        build_test_settings(api_prefix=api_prefix),
        runtime=ApplicationRuntime(),
        auth_settings=AuthApiSettings(_env_file=None),
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Provide a client bound to an isolated application instance."""
    with TestClient(build_test_application()) as test_client:
        yield test_client


def test_health_endpoint_returns_liveness_contract(client: TestClient) -> None:
    """Return a stable success payload from the versioned liveness route."""
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_endpoint_uses_configured_api_prefix() -> None:
    """Mount the route only below the prefix selected by application settings."""
    application = build_test_application(api_prefix="/internal/v2")

    with TestClient(application) as test_client:
        configured_response = test_client.get("/internal/v2/health")
        default_response = test_client.get("/api/v1/health")
        unversioned_response = test_client.get("/health")

    assert configured_response.status_code == 200
    assert configured_response.json() == {"status": "ok"}
    assert default_response.status_code == 404
    assert unversioned_response.status_code == 404


def test_application_metadata_and_documentation_are_versioned() -> None:
    """Expose deterministic metadata and API documentation under the API prefix."""
    application = build_test_application()

    assert application.title == "OrchesTwin Test API"
    assert application.version == "0.0.0"
    assert application.docs_url == "/api/v1/docs"
    assert application.openapi_url == "/api/v1/openapi.json"
    assert application.redoc_url is None


def test_health_ignores_invalid_local_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A temporary invalid dotenv must not affect the isolated liveness app."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "ORCHESTWIN_DATABASE_URL=invalid-test-only-url\n"
        "ORCHESTWIN_AUTH_JWT_SECRET=short-test-only-secret\n",
        encoding="utf-8",
    )

    with TestClient(build_test_application()) as test_client:
        response = test_client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
