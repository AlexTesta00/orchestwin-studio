from __future__ import annotations

import json
from dataclasses import replace
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
from orchestwin.knowledge.sources import KnowledgeSources
from src.test.python.artifacts.design_fixtures import OWNER_ID, PROJECT_ID
from src.test.python.knowledge.knowledge_fixtures import (
    ALIGNED_COMMIT,
    PUBLISHED_AT,
    partial_sources,
    real_sources,
    sources,
    state_sources,
)

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


def published(
    number: int = 1, package: KnowledgeSources | None = None
) -> tuple[KnowledgePackageVersion, KnowledgeArchive]:
    folder = build_knowledge_folder(
        sources() if package is None else package, version_number=number, created_at=PUBLISHED_AT
    )
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


def schema_two(version: KnowledgePackageVersion) -> KnowledgePackageVersion:
    manifest = json.loads(json.dumps(version.manifest))
    for key in ("progress", "state"):
        del manifest[key]
    for key in ("changes", "change_reviews", "tests", "test_runs"):
        del manifest["feedback"][key]
    manifest["schema_version"] = 2
    return replace(version, schema_version=2, manifest=manifest)


def before_tests(version: KnowledgePackageVersion) -> KnowledgePackageVersion:
    manifest = json.loads(json.dumps(version.manifest))
    for key in ("tests", "test_runs"):
        del manifest["feedback"][key]
    return replace(version, manifest=manifest)


class FakeKnowledgePackageService:
    def __init__(
        self,
        *,
        reused: bool = False,
        error: KnowledgeExportError | None = None,
        package: KnowledgeSources | None = None,
    ):
        self.version, self.stored = published(package=package)
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
        "change_reviews": 0,
        "test_runs": 0,
    }
    assert version["progress"] == {"approved": list(STAGES), "pending": None, "complete": True}
    assert version["state"] == {
        "changes": 0,
        "pending_changes": 0,
        "aligned_commit": None,
        "open_tasks": 0,
    }
    assert version["diagram_count"] == 7
    assert version["table_count"] == 14
    assert version["entries"] == list(service.stored.entries)


def test_a_folder_of_the_first_steps_lists_only_the_approved_stages() -> None:
    service = FakeKnowledgePackageService(package=partial_sources("twins"))

    version = client(service).post(PATH).json()["version"]

    assert [stage["stage"] for stage in version["stages"]] == ["brief", "team", "twins"]
    assert version["progress"] == {
        "approved": ["brief", "team", "twins"],
        "pending": "requirements",
        "complete": False,
    }
    assert version["feedback"] == dict.fromkeys(
        (
            "reviews",
            "findings",
            "decisions",
            "discussions",
            "insights",
            "change_reviews",
            "test_runs",
        ),
        0,
    )
    assert version["diagram_count"] == 0
    assert version["table_count"] == 0
    assert len(version["twins"]) == 2
    assert "state/state.json" in version["entries"]
    assert "requirements/requirements.json" not in version["entries"]


def test_the_state_of_the_development_reaches_the_summary() -> None:
    service = FakeKnowledgePackageService(package=real_sources(state=state_sources()))

    version = client(service).post(PATH).json()["version"]

    assert version["state"] == {
        "changes": 2,
        "pending_changes": 1,
        "aligned_commit": ALIGNED_COMMIT,
        "open_tasks": 1,
    }
    assert version["feedback"]["change_reviews"] == 1
    assert version["feedback"]["test_runs"] == 1


def test_a_folder_published_before_the_acceptance_tests_has_no_test_count() -> None:
    service = FakeKnowledgePackageService(package=real_sources(state=state_sources()))
    service.version = before_tests(service.version)

    version = client(service).get(PATH).json()["versions"][0]

    assert version["schema_version"] == 3
    assert "test_runs" not in version["feedback"]
    assert version["feedback"]["change_reviews"] == 1


def test_a_stored_folder_of_schema_two_is_summarised_as_complete_without_changes() -> None:
    service = FakeKnowledgePackageService()
    service.version = schema_two(service.version)

    version = client(service).get(PATH).json()["versions"][0]

    assert version["schema_version"] == 2
    assert [stage["stage"] for stage in version["stages"]] == list(STAGES)
    assert version["progress"] == {"approved": list(STAGES), "pending": None, "complete": True}
    assert version["state"] == {
        "changes": 0,
        "pending_changes": 0,
        "aligned_commit": None,
        "open_tasks": 0,
    }
    assert version["feedback"]["change_reviews"] == 0
    assert version["feedback"]["reviews"] == 2
    assert "test_runs" not in version["feedback"]


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
    document = application.openapi()
    paths = document["paths"]
    collection = paths["/api/v1/projects/{project_id}/knowledge-packages"]
    archive = paths["/api/v1/projects/{project_id}/knowledge-packages/{version_number}/archive"]
    feedback = document["components"]["schemas"]["PackageFeedbackPayload"]

    assert "test_runs" in feedback["properties"]
    assert "test_runs" not in feedback["required"]
    assert "change_reviews" in feedback["required"]
    assert collection["post"]["operationId"] == "publishKnowledgePackage"
    assert collection["get"]["operationId"] == "listKnowledgePackages"
    assert archive["get"]["operationId"] == "downloadKnowledgePackage"
    assert application.state.knowledge_package_service is service
