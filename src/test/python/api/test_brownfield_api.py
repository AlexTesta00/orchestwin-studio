"""API contract tests for safe brownfield source intake and capability review."""

from __future__ import annotations

import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import TracebackType
from typing import Self
from uuid import UUID

from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.services import ApplicationRuntime
from orchestwin.config import ApplicationSettings, RuntimeEnvironment
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.projects.brownfield_application import (
    BrownfieldSourceIntakeResult,
    LocalBrownfieldSourceIntakeService,
)
from orchestwin.projects.brownfield_persistence import (
    BrownfieldIntakeRepository,
    InMemoryBrownfieldIntakeRepository,
    PersistedBrownfieldIntakeVersion,
)
from orchestwin.projects.domain import Project, ProjectMode, create_project
from orchestwin.projects.execution_capabilities import CapabilityNegotiationRequest
from orchestwin.sandbox.archive_store import FileSystemSourceArchiveStore
from orchestwin.sandbox.builtin_execution_profiles import (
    create_builtin_execution_profile_registry,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000007801")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000007802")
NOW = datetime(2026, 8, 25, 14, 0, tzinfo=UTC)


def _user() -> UserAccount:
    return UserAccount(
        id=OWNER_ID,
        email=NormalizedEmail("owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _project() -> Project:
    return create_project(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        display_name="Brownfield API fixture",
        mode=ProjectMode.BROWNFIELD_ASSESSMENT,
        created_at=NOW,
    )


class _ProjectQuery:
    def __init__(self, project: Project) -> None:
        self._project = project

    async def get_owned(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> Project | None:
        if self._project.owner_user_id != owner_user_id or self._project.id != project_id:
            return None
        return self._project


class _IntakeUnitOfWork:
    def __init__(self, repository: BrownfieldIntakeRepository) -> None:
        self.intakes = repository
        self._completed = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        if not self._completed:
            await self.rollback()

    async def commit(self) -> None:
        self._completed = True

    async def rollback(self) -> None:
        self._completed = True


class _IntakeUnitOfWorkFactory:
    def __init__(self, repository: BrownfieldIntakeRepository) -> None:
        self._repository = repository

    def __call__(self, *, owner_user_id: UUID) -> _IntakeUnitOfWork:
        assert owner_user_id == OWNER_ID
        return _IntakeUnitOfWork(self._repository)


class _FakeBrownfieldApiService:
    def __init__(
        self,
        *,
        intake_service: LocalBrownfieldSourceIntakeService,
        repository: InMemoryBrownfieldIntakeRepository,
    ) -> None:
        self._intake_service = intake_service
        self._repository = repository
        self.uploaded_bytes: bytes | None = None
        self.upload_path: Path | None = None
        self.capability_request: CapabilityNegotiationRequest | None = None

    async def ingest(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        archive_path: Path,
        capability_request: CapabilityNegotiationRequest,
    ) -> BrownfieldSourceIntakeResult:
        self.uploaded_bytes = archive_path.read_bytes()
        self.upload_path = archive_path
        self.capability_request = capability_request
        return await self._intake_service.ingest(
            owner_user_id=owner_user_id,
            project_id=project_id,
            archive_path=archive_path,
            capability_request=capability_request,
        )

    async def history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[PersistedBrownfieldIntakeVersion, ...]:
        if owner_user_id != OWNER_ID:
            return ()
        return await self._repository.history(project_id=project_id)

    async def current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> PersistedBrownfieldIntakeVersion | None:
        if owner_user_id != OWNER_ID:
            return None
        return await self._repository.current(project_id=project_id)


def _service(tmp_path: Path) -> _FakeBrownfieldApiService:
    project = _project()
    repository = InMemoryBrownfieldIntakeRepository(
        owner_user_id=OWNER_ID,
        projects={PROJECT_ID: project},
    )
    intake_service = LocalBrownfieldSourceIntakeService(
        projects=_ProjectQuery(project),
        archive_store=FileSystemSourceArchiveStore(tmp_path / "archive-store"),
        profile_registry=create_builtin_execution_profile_registry(),
        uow_factory=_IntakeUnitOfWorkFactory(repository),
        workspace_root=tmp_path / "workspaces",
        clock=lambda: NOW,
    )
    return _FakeBrownfieldApiService(
        intake_service=intake_service,
        repository=repository,
    )


def _client(service: _FakeBrownfieldApiService) -> TestClient:
    application = create_app(
        ApplicationSettings(
            environment=RuntimeEnvironment.TEST,
            api_prefix="/api/v1",
        ),
        runtime=ApplicationRuntime(brownfield_service=service),
        auth_settings=AuthApiSettings(),
    )
    application.dependency_overrides[current_user_dependency] = _user
    return TestClient(application)


def _zip_bytes() -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        archive.writestr("index.html", "<!doctype html><title>Fixture</title>\n")
        archive.writestr("assets/site.css", "body { font-family: sans-serif; }\n")
    return buffer.getvalue()


def test_upload_streams_zip_into_governed_intake_and_removes_temporary_file(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    archive = _zip_bytes()

    response = _client(service).post(
        f"/api/v1/projects/{PROJECT_ID}/source-archives",
        params=[("available_runner", "runner.web"), ("available_runner", "runner.web")],
        files={"archive": ("source.zip", archive, "application/zip")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["project_id"] == str(PROJECT_ID)
    assert payload["version_number"] == 1
    assert payload["archive_size_bytes"] == len(archive)
    assert payload["capability_status"] == "DESIGN_ONLY_LEVEL_C_SELECTED"
    assert payload["selected_profile_reference"]["profile_id"] == "WEB_STATIC"
    assert service.uploaded_bytes == archive
    assert service.upload_path is not None
    assert service.upload_path.exists() is False
    assert service.capability_request is not None
    assert service.capability_request.available_runners == ("runner.web",)


def test_history_inventory_and_capability_use_one_owner_scoped_snapshot(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    client = _client(service)
    upload = client.post(
        f"/api/v1/projects/{PROJECT_ID}/source-archives",
        files={"archive": ("source.zip", _zip_bytes(), "application/zip")},
    )
    intake_id = upload.json()["id"]

    history = client.get(f"/api/v1/projects/{PROJECT_ID}/source-archives")
    detail = client.get(f"/api/v1/projects/{PROJECT_ID}/source-archives/{intake_id}")
    inventory = client.get(f"/api/v1/projects/{PROJECT_ID}/source-archives/{intake_id}/inventory")
    capability = client.get(f"/api/v1/projects/{PROJECT_ID}/capabilities")

    assert history.status_code == 200
    assert [item["id"] for item in history.json()["items"]] == [intake_id]
    assert detail.status_code == 200
    assert detail.json()["content_hash"] == upload.json()["content_hash"]
    assert inventory.status_code == 200
    assert inventory.json()["inventory"]["content_hash"] == upload.json()["inventory_content_hash"]
    assert capability.status_code == 200
    assert capability.json()["capability"]["status"] == "DESIGN_ONLY_LEVEL_C_SELECTED"


def test_upload_rejects_non_zip_empty_and_unsafe_archives(tmp_path: Path) -> None:
    service = _service(tmp_path)
    client = _client(service)

    non_zip = client.post(
        f"/api/v1/projects/{PROJECT_ID}/source-archives",
        files={"archive": ("source.txt", b"text", "text/plain")},
    )
    empty = client.post(
        f"/api/v1/projects/{PROJECT_ID}/source-archives",
        files={"archive": ("source.zip", b"", "application/zip")},
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        archive.writestr("../escape.py", "print('unsafe')\n")
    unsafe = client.post(
        f"/api/v1/projects/{PROJECT_ID}/source-archives",
        files={"archive": ("unsafe.zip", buffer.getvalue(), "application/zip")},
    )

    assert non_zip.status_code == 415
    assert non_zip.json()["detail"]["code"] == "SOURCE_ARCHIVE_ZIP_REQUIRED"
    assert empty.status_code == 422
    assert empty.json()["detail"]["code"] == "SOURCE_ARCHIVE_EMPTY"
    assert unsafe.status_code == 422
    assert unsafe.json()["detail"]["issue"] == "ARCHIVE_REJECTED"
    assert "../escape.py" not in str(unsafe.json())


def test_missing_intake_and_capability_share_owner_safe_not_found_response(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    client = _client(service)
    missing_id = UUID("00000000-0000-4000-8000-000000007899")

    detail = client.get(f"/api/v1/projects/{PROJECT_ID}/source-archives/{missing_id}")
    capability = client.get(f"/api/v1/projects/{PROJECT_ID}/capabilities")

    assert detail.status_code == 404
    assert capability.status_code == 404
    assert detail.json() == {"detail": {"code": "BROWNFIELD_INTAKE_NOT_FOUND"}}
    assert capability.json() == detail.json()


def test_application_registers_brownfield_routes_and_runtime_state(tmp_path: Path) -> None:
    marker = _service(tmp_path)
    application = create_app(
        ApplicationSettings(
            environment=RuntimeEnvironment.TEST,
            api_prefix="/api/v1",
        ),
        runtime=ApplicationRuntime(brownfield_service=marker),
        auth_settings=AuthApiSettings(),
    )
    paths = application.openapi()["paths"]

    assert "post" in paths["/api/v1/projects/{project_id}/source-archives"]
    assert "get" in paths["/api/v1/projects/{project_id}/source-archives"]
    assert "get" in paths["/api/v1/projects/{project_id}/capabilities"]
    assert application.state.brownfield_service is marker
