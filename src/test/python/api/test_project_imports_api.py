from __future__ import annotations

from datetime import UTC, datetime
from functools import cache
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile
from starlette.types import Message, Receive, Scope, Send

from orchestwin.api import project_imports as module
from orchestwin.api.auth import current_user_dependency
from orchestwin.api.project_imports import create_project_import_router
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.knowledge.archive import read_verified_folder
from orchestwin.knowledge.folder import build_knowledge_folder, folder_archive
from orchestwin.knowledge.layout import STAGES
from orchestwin.knowledge.project_import_service import (
    ProjectImportError,
    ProjectImportResult,
    import_record,
    planned_import,
)
from orchestwin.projects.briefs import ProjectBriefVersion
from orchestwin.projects.domain import ProjectMode, create_project
from src.test.python.knowledge.knowledge_fixtures import (
    PUBLISHED_AT,
    REAL_PROJECT_ID,
    real_sources,
)

OWNER = UUID("33333333-3333-4333-8333-333333333333")
NEW_PROJECT = UUID("11111111-1111-4111-8111-111111111111")
NEW_BRIEF = UUID("22222222-2222-4222-8222-222222222222")
RECORD_ID = UUID("44444444-4444-4444-8444-444444444444")
OTHER_PROJECT = UUID("55555555-5555-4555-8555-555555555555")
IMPORTED_AT = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)
IMPORTS = "/api/v1/project-imports"
ORIGIN = f"/api/v1/projects/{NEW_PROJECT}/import"
ARCHIVE = b"PK\x03\x04uploaded knowledge folder"


def user() -> UserAccount:
    return UserAccount(
        id=OWNER,
        email=NormalizedEmail("owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=IMPORTED_AT,
        updated_at=IMPORTED_AT,
    )


@cache
def imported() -> ProjectImportResult:
    folder = build_knowledge_folder(real_sources(), version_number=1, created_at=PUBLISHED_AT)
    content = folder_archive(folder).content
    plan = planned_import(
        read_verified_folder(content),
        project_id=NEW_PROJECT,
        brief_version_id=NEW_BRIEF,
        owner_user_id=OWNER,
        created_at=IMPORTED_AT,
    )
    project = create_project(
        owner_user_id=OWNER,
        display_name="Import di prova",
        mode=ProjectMode.GREENFIELD_GENERATION,
        project_id=NEW_PROJECT,
        created_at=IMPORTED_AT,
    )
    return ProjectImportResult(
        project=project,
        record=import_record(
            plan,
            record_id=RECORD_ID,
            owner_user_id=OWNER,
            content=content,
            imported_at=IMPORTED_AT,
        ),
        plan=plan,
        brief_version=ProjectBriefVersion(
            id=NEW_BRIEF,
            project_id=NEW_PROJECT,
            version_number=1,
            schema_version=plan.brief.SCHEMA_VERSION,
            brief=plan.brief,
            content_hash=plan.brief.content_hash,
            created_by_user_id=OWNER,
            created_at=IMPORTED_AT,
        ),
    )


class FakeProjectImportService:
    def __init__(self, *, error: ProjectImportError | None = None) -> None:
        self.result = imported()
        self.error = error
        self.calls: list[tuple] = []

    async def import_archive(
        self, *, owner_user_id: UUID, content: bytes, display_name: str | None = None
    ) -> ProjectImportResult:
        self.calls.append(("import", owner_user_id, content, display_name))
        if self.error is not None:
            raise self.error
        return self.result

    async def origin(self, *, owner_user_id: UUID, project_id: UUID):
        self.calls.append(("origin", owner_user_id, project_id))
        return self.result.record if project_id == self.result.project.id else None


def application(service) -> FastAPI:
    app = FastAPI()
    app.include_router(create_project_import_router(), prefix="/api/v1")
    app.state.project_import_service = service
    app.dependency_overrides[current_user_dependency] = user
    return app


def client(service) -> TestClient:
    return TestClient(application(service))


def upload(content: bytes = ARCHIVE) -> dict[str, tuple[str, bytes, str]]:
    return {"archive": ("orchestwin-knowledge-v1.zip", content, "application/zip")}


def expected_stages() -> dict[str, dict[str, object]]:
    return {stage: imported().record.stage_versions[stage] for stage in STAGES}


def test_import_answers_created_with_the_new_project_its_origin_and_the_steps_to_approve() -> None:
    service = FakeProjectImportService()
    result = service.result

    response = client(service).post(
        IMPORTS, files=upload(), data={"display_name": "Import di prova"}
    )

    assert response.status_code == 201
    body = response.json()
    assert service.calls == [("import", OWNER, ARCHIVE, "Import di prova")]
    assert body["project"] == {
        "id": str(NEW_PROJECT),
        "display_name": "Import di prova",
        "mode": "GREENFIELD_GENERATION",
        "created_at": "2026-09-28T09:00:00Z",
    }
    assert body["origin"] == {
        "project_id": str(REAL_PROJECT_ID),
        "project_name": "Lista ospiti workshop",
        "package_version": 1,
        "package_content_hash": result.plan.origin.package_content_hash,
        "schema_version": 3,
    }
    assert list(body["stages"]) == list(STAGES)
    assert body["stages"] == expected_stages()
    assert body["stages"]["brief"]["version_id"] == str(NEW_BRIEF)
    assert body["stages"]["design"]["version_id"] == str(result.plan.design.id)
    assert body["twins"] == [
        {"twin_id": str(twin.twin_id), "name": twin.profile.name} for twin in result.plan.twins
    ]
    assert len(body["twins"]) == 2
    assert body["imported_at"] == "2026-09-28T09:00:00Z"
    assert body["approval_required"] == ["brief", "team", "twins", "requirements", "design"]


def test_import_without_a_display_name_lets_the_service_use_the_folder_name() -> None:
    service = FakeProjectImportService()

    response = client(service).post(IMPORTS, files=upload())

    assert response.status_code == 201
    assert service.calls == [("import", OWNER, ARCHIVE, None)]


@pytest.mark.parametrize(
    ("code", "detail", "status"),
    [
        ("FOLDER_ARCHIVE_INVALID", None, 422),
        ("FOLDER_ARCHIVE_TOO_LARGE", None, 413),
        ("FOLDER_DOCUMENT_MISSING", "design/design.json", 422),
        ("FOLDER_DOCUMENT_INVALID", "requirements: missing code", 422),
        ("FOLDER_SCHEMA_UNSUPPORTED", None, 422),
        ("FOLDER_TAMPERED", "brief/brief.md", 422),
        ("FOLDER_INCONSISTENT", "DESIGN_OUTDATED", 422),
        ("FOLDER_INCOMPLETE", "requirements", 422),
        ("PROJECT_NAME_INVALID", "display_name", 422),
        ("PROJECT_IMPORT_REJECTED", "design", 409),
    ],
)
def test_failures_keep_their_code_and_location_with_distinct_statuses(
    code: str, detail: str | None, status: int
) -> None:
    service = FakeProjectImportService(error=ProjectImportError(code, detail))

    response = client(service).post(IMPORTS, files=upload())

    assert response.status_code == status
    assert response.json() == {"detail": {"code": code, "location": detail}}
    assert len(service.calls) == 1


def test_upload_beyond_the_limit_is_refused_without_reading_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[int] = []
    original = UploadFile.read

    async def counted(self, size: int = -1) -> bytes:
        requested.append(size)
        return await original(self, size)

    monkeypatch.setattr(module, "MAX_ARCHIVE_SIZE", 8)
    monkeypatch.setattr(UploadFile, "read", counted)
    service = FakeProjectImportService()
    api = client(service)

    refused = api.post(IMPORTS, files=upload(b"123456789" * 50))
    accepted = api.post(IMPORTS, files=upload(b"12345678"))

    assert refused.status_code == 413
    assert refused.json() == {"detail": {"code": "FOLDER_ARCHIVE_TOO_LARGE", "location": None}}
    assert accepted.status_code == 201
    assert requested == [9, 9]
    assert service.calls == [("import", OWNER, b"12345678", None)]


def test_a_declared_length_beyond_the_limit_is_refused_before_the_form_is_read() -> None:
    service = FakeProjectImportService()
    app = application(service)
    received: list[str] = []

    async def counted(scope: Scope, receive: Receive, send: Send) -> None:
        async def counted_receive() -> Message:
            message = await receive()
            received.append(message["type"])
            return message

        await app(scope, counted_receive, send)

    api = TestClient(counted)
    limit = module.MAX_IMPORT_REQUEST_SIZE

    refused = api.post(IMPORTS, files=upload(), headers={"Content-Length": str(limit + 1)})
    unread = list(received)
    accepted = api.post(IMPORTS, files=upload(), headers={"Content-Length": str(limit)})

    assert limit == module.MAX_ARCHIVE_SIZE + 64 * 1024
    assert refused.status_code == 413
    assert refused.json() == {"detail": {"code": "FOLDER_ARCHIVE_TOO_LARGE", "location": None}}
    assert unread == []
    assert accepted.status_code == 201
    assert "http.request" in received
    assert service.calls == [("import", OWNER, ARCHIVE, None)]


def test_import_without_an_archive_is_a_validation_error() -> None:
    service = FakeProjectImportService()

    response = client(service).post(IMPORTS, data={"display_name": "Import di prova"})

    assert response.status_code == 422
    assert service.calls == []


def test_origin_of_an_imported_project_names_its_folder_and_versions() -> None:
    service = FakeProjectImportService()
    record = service.result.record

    response = client(service).get(ORIGIN)

    assert response.status_code == 200
    assert response.json() == {
        "origin": {
            "project_id": str(REAL_PROJECT_ID),
            "project_name": "Lista ospiti workshop",
            "package_version": 1,
            "package_content_hash": record.package_content_hash,
            "schema_version": 3,
        },
        "stages": expected_stages(),
        "imported_at": "2026-09-28T09:00:00Z",
        "archive_hash": record.archive_hash,
    }
    assert service.calls == [("origin", OWNER, NEW_PROJECT)]


def test_origin_of_a_project_that_was_not_imported_is_not_found() -> None:
    service = FakeProjectImportService()

    response = client(service).get(f"/api/v1/projects/{OTHER_PROJECT}/import")
    malformed = client(service).get("/api/v1/projects/not-a-project/import")

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "PROJECT_IMPORT_NOT_FOUND", "location": None}}
    assert malformed.status_code == 422
    assert service.calls == [("origin", OWNER, OTHER_PROJECT)]


def test_imports_are_unavailable_without_the_service() -> None:
    api = client(None)

    for response in (api.post(IMPORTS, files=upload()), api.get(ORIGIN)):
        assert response.status_code == 503
        assert response.json() == {
            "detail": {"code": "PROJECT_IMPORT_SERVICE_UNAVAILABLE", "location": None}
        }


def test_operations_are_published_with_stable_ids() -> None:
    paths = application(FakeProjectImportService()).openapi()["paths"]
    imports = paths["/api/v1/project-imports"]["post"]
    origin = paths["/api/v1/projects/{project_id}/import"]["get"]

    assert imports["operationId"] == "importProjectFromKnowledgeFolder"
    assert "201" in imports["responses"]
    assert "multipart/form-data" in imports["requestBody"]["content"]
    assert origin["operationId"] == "getProjectImportOrigin"
