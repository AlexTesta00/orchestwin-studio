from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.services import ApplicationRuntime
from orchestwin.config import ApplicationSettings, RuntimeEnvironment
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.knowledge.export import KnowledgeExportError
from orchestwin.knowledge.folder import (
    KnowledgeArchive,
    build_knowledge_folder,
    folder_archive,
)
from orchestwin.knowledge.layout import KNOWLEDGE_SCHEMA_VERSION, STAGES
from orchestwin.knowledge.package_service import KnowledgePackagePublication
from orchestwin.knowledge.packages import KnowledgePackageVersion
from src.test.python.artifacts.design_fixtures import OWNER_ID, PROJECT_ID
from src.test.python.knowledge.knowledge_fixtures import PUBLISHED_AT, sources

NOW = datetime(2026, 9, 27, 18, 0, tzinfo=UTC)
PATH = f"/api/v1/projects/{PROJECT_ID}/knowledge-packages"
VERSION_ID = UUID("00000000-0000-4000-8000-00000000c001")


def user() -> UserAccount:
    return UserAccount(
        id=OWNER_ID,
        email=NormalizedEmail("owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def published(number: int = 1) -> tuple[KnowledgePackageVersion, KnowledgeArchive]:
    folder = build_knowledge_folder(sources(), version_number=number, created_at=PUBLISHED_AT)
    archive = folder_archive(folder)
    version = KnowledgePackageVersion(
        id=VERSION_ID,
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        version_number=number,
        schema_version=KNOWLEDGE_SCHEMA_VERSION,
        content_hash=folder.content_hash,
        archive_hash=archive.archive_hash,
        file_name=archive.file_name,
        file_count=len(archive.entries),
        archive_size=len(archive.content),
        manifest=folder.manifest,
        created_at=folder.created_at,
    )
    return version, archive


class FakeKnowledgePackageService:
    def __init__(self, *, reused: bool = False, error: KnowledgeExportError | None = None):
        self.version, self.stored = published()
        self.reused = reused
        self.error = error
        self.calls: list[tuple[str, tuple]] = []

    def _answer(self, name: str, *arguments):
        self.calls.append((name, arguments))
        if self.error is not None:
            raise self.error

    async def publish(self, *, owner_user_id: UUID, project_id: UUID):
        self._answer("publish", owner_user_id, project_id)
        return KnowledgePackagePublication(version=self.version, reused=self.reused)

    async def history(self, *, owner_user_id: UUID, project_id: UUID, limit: int):
        self._answer("history", owner_user_id, project_id, limit)
        return (self.version,)

    async def archive(self, *, owner_user_id: UUID, project_id: UUID, version_number: int):
        self._answer("archive", owner_user_id, project_id, version_number)
        return self.stored


def client(service) -> TestClient:
    application = create_app(
        ApplicationSettings(environment=RuntimeEnvironment.TEST, api_prefix="/api/v1"),
        runtime=ApplicationRuntime(knowledge_package_service=service),
        auth_settings=AuthApiSettings(),
    )
    application.dependency_overrides[current_user_dependency] = user
    return TestClient(application)


def test_publication_of_a_new_version_answers_created_with_its_summary() -> None:
    service = FakeKnowledgePackageService()

    response = client(service).post(PATH)

    assert response.status_code == 201
    body = response.json()
    version = body["version"]
    manifest = service.version.manifest
    assert body["reused"] is False
    assert service.calls == [("publish", (OWNER_ID, PROJECT_ID))]
    assert version["id"] == str(VERSION_ID)
    assert version["project_id"] == str(PROJECT_ID)
    assert version["project_name"] == "Lista ospiti workshop"
    assert version["version_number"] == 1
    assert version["schema_version"] == KNOWLEDGE_SCHEMA_VERSION
    assert version["content_hash"] == service.version.content_hash
    assert version["archive_hash"] == service.version.archive_hash
    assert version["file_name"] == f"orchestwin-{PROJECT_ID}-knowledge-v1.zip"
    assert version["file_count"] == len(service.stored.entries)
    assert version["archive_size"] == len(service.stored.content)
    assert version["created_at"] == "2026-09-27T20:00:00Z"
    assert [stage["stage"] for stage in version["stages"]] == list(STAGES)
    assert version["stages"][4] == {
        "stage": "design",
        "label": "Design",
        "version_number": manifest["stages"]["design"]["version_number"],
        "content_hash": manifest["stages"]["design"]["content_hash"],
    }
    assert [twin["slug"] for twin in version["twins"]] == [
        twin["slug"] for twin in manifest["twins"]
    ]
    assert version["twins"][0]["document"] == manifest["twins"][0]["document"]
    assert version["feedback"] == {
        "reviews": 2,
        "findings": 4,
        "decisions": 2,
        "discussions": 1,
        "insights": 1,
    }
    assert version["diagram_count"] == 7
    assert version["table_count"] == 14
    assert version["entries"] == list(service.stored.entries)


def test_publication_of_an_unchanged_project_answers_ok_and_reused() -> None:
    response = client(FakeKnowledgePackageService(reused=True)).post(PATH)

    assert response.status_code == 200
    assert response.json()["reused"] is True


def test_history_lists_the_versions_with_a_bounded_limit() -> None:
    service = FakeKnowledgePackageService()
    api = client(service)

    default = api.get(PATH)
    limited = api.get(PATH, params={"limit": 5})
    too_many = api.get(PATH, params={"limit": 201})
    none = api.get(PATH, params={"limit": 0})

    assert default.status_code == 200
    assert default.json()["project_id"] == str(PROJECT_ID)
    assert [item["version_number"] for item in default.json()["versions"]] == [1]
    assert limited.status_code == 200
    assert too_many.status_code == 422
    assert none.status_code == 422
    assert service.calls == [
        ("history", (OWNER_ID, PROJECT_ID, 50)),
        ("history", (OWNER_ID, PROJECT_ID, 5)),
    ]


def test_archive_streams_the_stored_zip_with_its_hash() -> None:
    service = FakeKnowledgePackageService()

    response = client(service).get(f"{PATH}/1/archive")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="orchestwin-{PROJECT_ID}-knowledge-v1.zip"'
    )
    assert response.headers["x-content-sha256"] == service.stored.archive_hash
    assert response.content == service.stored.content
    assert service.calls == [("archive", (OWNER_ID, PROJECT_ID, 1))]


def test_archive_version_numbers_start_from_one() -> None:
    service = FakeKnowledgePackageService()

    response = client(service).get(f"{PATH}/0/archive")

    assert response.status_code == 422
    assert service.calls == []


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("PROJECT_NOT_FOUND", 404),
        ("KNOWLEDGE_PACKAGE_NOT_FOUND", 404),
        ("DESIGN_APPROVAL_REQUIRED", 409),
        ("BRIEF_APPROVAL_REQUIRED", 409),
        ("KNOWLEDGE_PACKAGE_VERSION_CONFLICT", 409),
        ("KNOWLEDGE_FOLDER_INVALID", 500),
        ("KNOWLEDGE_PACKAGE_CORRUPTED", 500),
    ],
)
def test_failures_keep_their_code_and_use_distinct_statuses(code: str, status: int) -> None:
    api = client(FakeKnowledgePackageService(error=KnowledgeExportError(code)))

    for response in (api.post(PATH), api.get(PATH), api.get(f"{PATH}/1/archive")):
        assert response.status_code == status
        assert response.json() == {"detail": {"code": code}}


def test_packages_are_unavailable_without_the_service() -> None:
    api = client(None)

    for response in (api.post(PATH), api.get(PATH), api.get(f"{PATH}/1/archive")):
        assert response.status_code == 503
        assert response.json() == {"detail": {"code": "KNOWLEDGE_PACKAGE_SERVICE_UNAVAILABLE"}}


def test_packages_are_registered_in_openapi_and_application_state() -> None:
    service = FakeKnowledgePackageService()
    application = create_app(
        ApplicationSettings(environment=RuntimeEnvironment.TEST, api_prefix="/api/v1"),
        runtime=ApplicationRuntime(knowledge_package_service=service),
        auth_settings=AuthApiSettings(),
    )
    paths = application.openapi()["paths"]
    collection = paths["/api/v1/projects/{project_id}/knowledge-packages"]
    archive = paths["/api/v1/projects/{project_id}/knowledge-packages/{version_number}/archive"]

    assert collection["post"]["operationId"] == "publishKnowledgePackage"
    assert collection["get"]["operationId"] == "listKnowledgePackages"
    assert archive["get"]["operationId"] == "downloadKnowledgePackage"
    assert application.state.knowledge_package_service is service
