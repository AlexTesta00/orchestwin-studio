"""Contract tests for the versioned API health endpoint."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
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


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Provide a client bound to an isolated application instance."""
    with TestClient(create_app(build_test_settings())) as test_client:
        yield test_client


def test_health_endpoint_returns_liveness_contract(client: TestClient) -> None:
    """Return a stable success payload from the versioned liveness route."""
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_endpoint_uses_configured_api_prefix() -> None:
    """Mount the route only below the prefix selected by application settings."""
    application = create_app(build_test_settings(api_prefix="/internal/v2"))

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
    application = create_app(build_test_settings())

    assert application.title == "OrchesTwin Test API"
    assert application.version == "0.0.0"
    assert application.docs_url == "/api/v1/docs"
    assert application.openapi_url == "/api/v1/openapi.json"
    assert application.redoc_url is None
