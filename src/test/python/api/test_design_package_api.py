from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.services import ApplicationRuntime
from orchestwin.artifacts.design_package_export import (
    DesignPackageArchive,
    DesignPackageExportError,
)
from orchestwin.config import ApplicationSettings, RuntimeEnvironment
from orchestwin.identity.domain import NormalizedEmail, UserAccount

OWNER_ID = UUID("00000000-0000-4000-8000-000000000002")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 9, 24, 18, 0, tzinfo=UTC)
CONTENT = b"PK\x05\x06" + bytes(18)


def user() -> UserAccount:
    return UserAccount(
        id=OWNER_ID,
        email=NormalizedEmail("owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def archive() -> DesignPackageArchive:
    return DesignPackageArchive(
        project_id=PROJECT_ID,
        file_name=f"orchestwin-{PROJECT_ID}-design-package.zip",
        content=CONTENT,
        content_hash=hashlib.sha256(CONTENT).hexdigest(),
        entries=("ORCHESTWIN.md",),
    )


class FakeDesignPackageExportService:
    def __init__(self, result: DesignPackageArchive | DesignPackageExportError) -> None:
        self.result = result
        self.calls: list[tuple[UUID, UUID]] = []

    async def export(self, *, owner_user_id: UUID, project_id: UUID) -> DesignPackageArchive:
        self.calls.append((owner_user_id, project_id))
        if isinstance(self.result, DesignPackageExportError):
            raise self.result
        return self.result


def client(runtime: ApplicationRuntime) -> TestClient:
    application = create_app(
        ApplicationSettings(environment=RuntimeEnvironment.TEST, api_prefix="/api/v1"),
        runtime=runtime,
        auth_settings=AuthApiSettings(),
    )
    application.dependency_overrides[current_user_dependency] = user
    return TestClient(application)


def test_export_streams_the_zip_of_the_owner_scoped_project() -> None:
    service = FakeDesignPackageExportService(archive())

    response = client(ApplicationRuntime(design_package_export_service=service)).get(
        f"/api/v1/projects/{PROJECT_ID}/design-package"
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="orchestwin-{PROJECT_ID}-design-package.zip"'
    )
    assert response.headers["x-content-sha256"] == hashlib.sha256(CONTENT).hexdigest()
    assert response.content == CONTENT
    assert service.calls == [(OWNER_ID, PROJECT_ID)]


def test_missing_project_and_missing_approvals_use_distinct_statuses() -> None:
    not_found = FakeDesignPackageExportService(DesignPackageExportError("PROJECT_NOT_FOUND"))
    pending = FakeDesignPackageExportService(DesignPackageExportError("DESIGN_APPROVAL_REQUIRED"))

    missing = client(ApplicationRuntime(design_package_export_service=not_found)).get(
        f"/api/v1/projects/{PROJECT_ID}/design-package"
    )
    conflict = client(ApplicationRuntime(design_package_export_service=pending)).get(
        f"/api/v1/projects/{PROJECT_ID}/design-package"
    )

    assert missing.status_code == 404
    assert missing.json() == {"detail": {"code": "PROJECT_NOT_FOUND"}}
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": {"code": "DESIGN_APPROVAL_REQUIRED"}}


def test_export_is_unavailable_without_the_service() -> None:
    response = client(ApplicationRuntime()).get(f"/api/v1/projects/{PROJECT_ID}/design-package")

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "DESIGN_PACKAGE_SERVICE_UNAVAILABLE"}}


def test_export_is_registered_in_openapi_and_application_state() -> None:
    service = FakeDesignPackageExportService(archive())
    application = create_app(
        ApplicationSettings(environment=RuntimeEnvironment.TEST, api_prefix="/api/v1"),
        runtime=ApplicationRuntime(design_package_export_service=service),
        auth_settings=AuthApiSettings(),
    )

    operation = application.openapi()["paths"]["/api/v1/projects/{project_id}/design-package"]

    assert operation["get"]["operationId"] == "exportDesignPackage"
    assert application.state.design_package_export_service is service
