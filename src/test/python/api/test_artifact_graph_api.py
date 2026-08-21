"""API contract tests for cross-stage artifact traceability and export."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from uuid import UUID

from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.services import ApplicationRuntime
from orchestwin.artifacts.traceability import (
    CrossStageArtifactGraph,
    build_cross_stage_artifact_graph,
)
from orchestwin.config import ApplicationSettings, RuntimeEnvironment
from orchestwin.identity.domain import NormalizedEmail, UserAccount

FIXTURE_DIRECTORY = Path(__file__).resolve().parents[1] / "artifacts"
FIXTURE_PACKAGE_NAME = "artifact_graph_api_fixtures"
OWNER_ID = UUID("00000000-0000-4000-8000-000000000002")
NOW = datetime(2026, 8, 21, 16, 0, tzinfo=UTC)


def load_architecture_fixtures() -> ModuleType:
    """Load package-local fixtures without introducing production fixture imports."""
    package = ModuleType(FIXTURE_PACKAGE_NAME)
    package.__path__ = [str(FIXTURE_DIRECTORY)]
    sys.modules[FIXTURE_PACKAGE_NAME] = package

    module_name = f"{FIXTURE_PACKAGE_NAME}.architecture_fixtures"
    spec = importlib.util.spec_from_file_location(
        module_name,
        FIXTURE_DIRECTORY / "architecture_fixtures.py",
    )

    if spec is None or spec.loader is None:
        raise AssertionError("could not load artifact graph API fixtures")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    return module


FIXTURES = load_architecture_fixtures()
DESIGN_FIXTURES = sys.modules[f"{FIXTURE_PACKAGE_NAME}.design_fixtures"]
PROJECT_ID: UUID = FIXTURES.PROJECT_ID


def graph() -> CrossStageArtifactGraph:
    """Create one complete current-stage traceability graph."""
    return build_cross_stage_artifact_graph(
        DESIGN_FIXTURES.requirements_version(),
        DESIGN_FIXTURES.design_version(),
        FIXTURES.architecture_version(),
    )


def user() -> UserAccount:
    """Create one authenticated project owner."""
    return UserAccount(
        id=OWNER_ID,
        email=NormalizedEmail("owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


class FakeArtifactGraphQueryService:
    """Return one configurable owner-scoped graph and capture its query."""

    def __init__(self, current: CrossStageArtifactGraph | None) -> None:
        self.current_value = current
        self.calls: list[tuple[UUID, UUID]] = []

    async def current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> CrossStageArtifactGraph | None:
        self.calls.append((owner_user_id, project_id))
        return self.current_value


def client(service: FakeArtifactGraphQueryService) -> TestClient:
    """Create one test app with explicit artifact graph dependencies."""
    application = create_app(
        ApplicationSettings(
            environment=RuntimeEnvironment.TEST,
            api_prefix="/api/v1",
        ),
        runtime=ApplicationRuntime(artifact_graph_query_service=service),
        auth_settings=AuthApiSettings(),
    )
    application.dependency_overrides[current_user_dependency] = user

    return TestClient(application)


def test_current_artifact_graph_exposes_exact_roots_and_stage_counts() -> None:
    """Return the current owner-scoped graph with its reproducibility hash."""
    current = graph()
    service = FakeArtifactGraphQueryService(current)

    response = client(service).get(f"/api/v1/projects/{PROJECT_ID}/artifacts/graph")

    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == str(PROJECT_ID)
    assert payload["requirements_reference"]["artifact_id"] == str(
        current.requirements_reference.artifact_id
    )
    assert payload["design_reference"]["artifact_id"] == str(current.design_reference.artifact_id)
    assert payload["architecture_reference"]["artifact_id"] == str(
        current.architecture_reference.artifact_id
    )
    assert payload["stage_counts"]["DESIGN"] > 0
    assert payload["stage_counts"]["TESTING"] > 0
    assert payload["content_hash"] == current.content_hash
    assert service.calls == [(OWNER_ID, PROJECT_ID)]


def test_artifact_graph_export_uses_a_safe_filename_and_hash_header() -> None:
    """Download one complete JSON graph without exposing an arbitrary filename."""
    current = graph()
    service = FakeArtifactGraphQueryService(current)

    response = client(service).get(f"/api/v1/projects/{PROJECT_ID}/artifacts/graph/export")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["x-content-sha256"] == current.content_hash
    assert response.headers["content-disposition"] == (
        f'attachment; filename="orchestwin-{PROJECT_ID}-artifact-graph.json"'
    )
    payload = json.loads(response.content)
    assert payload["content_hash"] == current.content_hash
    assert len(payload["nodes"]) == len(current.nodes)
    assert len(payload["links"]) == len(current.links)


def test_missing_and_foreign_artifact_graphs_share_the_same_lookup_response() -> None:
    """Keep owner/project authorization leakage out of the graph boundary."""
    service = FakeArtifactGraphQueryService(None)

    response = client(service).get(f"/api/v1/projects/{PROJECT_ID}/artifacts/graph")

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "ARTIFACT_GRAPH_NOT_FOUND"}}


def test_application_registers_artifact_graph_routes_and_runtime_state() -> None:
    """Expose graph query and export through the standard composition root."""
    marker = FakeArtifactGraphQueryService(None)
    application = create_app(
        ApplicationSettings(
            environment=RuntimeEnvironment.TEST,
            api_prefix="/api/v1",
        ),
        runtime=ApplicationRuntime(artifact_graph_query_service=marker),
        auth_settings=AuthApiSettings(),
    )
    paths = application.openapi()["paths"]
    graph_path = "/api/v1/projects/{project_id}/artifacts/graph"
    export_path = "/api/v1/projects/{project_id}/artifacts/graph/export"

    assert "get" in paths[graph_path]
    assert "get" in paths[export_path]
    assert application.state.artifact_graph_query_service is marker
