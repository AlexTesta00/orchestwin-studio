"""API contract tests for owner-scoped projects and briefs."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings
from orchestwin.api.services import (
    ApplicationRuntime,
)
from orchestwin.config import (
    ApplicationSettings,
    RuntimeEnvironment,
)
from orchestwin.identity.domain import (
    NormalizedEmail,
    UserAccount,
)
from orchestwin.projects.briefs import (
    ProjectBriefVersion,
    create_project_brief,
)
from orchestwin.projects.domain import (
    Project,
    ProjectMode,
    create_project,
)
from orchestwin.projects.repository import (
    BriefVersionCreationResult,
    BriefVersionCreationStatus,
)

USER_ID = UUID("00000000-0000-4000-8000-000000000001")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
VERSION_ID = UUID("00000000-0000-4000-8000-000000000020")
NOW = datetime.now(UTC)


def build_user() -> UserAccount:
    """Create the authenticated API user."""
    return UserAccount(
        id=USER_ID,
        email=NormalizedEmail("owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def build_project() -> Project:
    """Create a deterministic project."""
    return create_project(
        project_id=PROJECT_ID,
        owner_user_id=USER_ID,
        display_name="Project",
        mode=ProjectMode.GREENFIELD_GENERATION,
        created_at=NOW,
    )


def build_version() -> ProjectBriefVersion:
    """Create a deterministic brief version."""
    brief = create_project_brief(
        name="Project",
        unknown_fields=[],
    )

    return ProjectBriefVersion(
        id=VERSION_ID,
        project_id=PROJECT_ID,
        version_number=1,
        schema_version=brief.SCHEMA_VERSION,
        brief=brief,
        content_hash=brief.content_hash,
        created_by_user_id=USER_ID,
        created_at=NOW,
    )


class FakeIdentityService:
    """Identity service double used by bearer dependencies."""

    async def current_user(
        self,
        access_token: str,
    ) -> UserAccount | None:
        if access_token != "valid-access-token":
            return None

        return build_user()


class FakeProjectService:
    """Configurable project application service double."""

    def __init__(self) -> None:
        self.project: Project | None = build_project()
        self.version = build_version()

    async def create(
        self,
        *,
        owner_user_id: UUID,
        display_name: str,
        mode: ProjectMode,
    ) -> Project:
        return create_project(
            project_id=PROJECT_ID,
            owner_user_id=owner_user_id,
            display_name=display_name,
            mode=mode,
            created_at=NOW,
        )

    async def list_active(
        self,
        *,
        owner_user_id: UUID,
    ) -> tuple[Project, ...]:
        if self.project is None:
            return ()

        return (self.project,)

    async def get(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> Project | None:
        return self.project

    async def rename(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        display_name: str,
    ) -> Project | None:
        if self.project is None:
            return None

        return Project(
            id=self.project.id,
            owner_user_id=(self.project.owner_user_id),
            display_name=display_name,
            mode=self.project.mode,
            current_brief_version=(self.project.current_brief_version),
            archived_at=None,
            created_at=self.project.created_at,
            updated_at=NOW,
        )

    async def archive(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> Project | None:
        return self.project

    async def create_brief_version(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        brief,
    ) -> BriefVersionCreationResult:
        return BriefVersionCreationResult(
            status=(BriefVersionCreationStatus.CREATED),
            version=ProjectBriefVersion(
                id=VERSION_ID,
                project_id=project_id,
                version_number=1,
                schema_version=brief.SCHEMA_VERSION,
                brief=brief,
                content_hash=brief.content_hash,
                created_by_user_id=owner_user_id,
                created_at=NOW,
            ),
        )

    async def current_brief(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ProjectBriefVersion | None:
        return self.version

    async def brief_version(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        version_number: int,
    ) -> ProjectBriefVersion | None:
        if version_number != 1:
            return None

        return self.version

    async def brief_history(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[ProjectBriefVersion, ...]:
        return (self.version,)


def build_client(
    project_service: FakeProjectService | None,
) -> TestClient:
    """Create a test client with explicit service doubles."""
    settings = ApplicationSettings(
        environment=RuntimeEnvironment.TEST,
        api_prefix="/api/v1",
        cors_allowed_origins=("http://127.0.0.1:5173",),
        _env_file=None,
    )
    runtime = ApplicationRuntime(
        identity_service=FakeIdentityService(),
        project_service=project_service,
    )

    return TestClient(
        create_app(
            settings,
            runtime=runtime,
            auth_settings=AuthApiSettings(_env_file=None),
        )
    )


def authorization_header() -> dict[str, str]:
    """Return a valid bearer header."""
    return {"Authorization": ("Bearer valid-access-token")}


def test_project_routes_require_authentication() -> None:
    """Reject anonymous project access."""
    with build_client(FakeProjectService()) as client:
        response = client.get("/api/v1/projects")

    assert response.status_code == 401


def test_create_and_list_projects() -> None:
    """Create and list owner-scoped projects."""
    with build_client(FakeProjectService()) as client:
        created = client.post(
            "/api/v1/projects",
            headers=authorization_header(),
            json={
                "display_name": "Project",
                "mode": "GREENFIELD_GENERATION",
            },
        )
        listed = client.get(
            "/api/v1/projects",
            headers=authorization_header(),
        )

    assert created.status_code == 201
    assert created.json()["mode"] == ("GREENFIELD_GENERATION")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == str(PROJECT_ID)


def test_project_not_found_does_not_disclose_ownership() -> None:
    """Return the same 404 for inaccessible projects."""
    service = FakeProjectService()
    service.project = None

    with build_client(service) as client:
        response = client.get(
            f"/api/v1/projects/{PROJECT_ID}",
            headers=authorization_header(),
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "project_not_found"}


def test_create_partial_brief_exposes_field_states() -> None:
    """Return provided, unknown, and missing fields."""
    with build_client(FakeProjectService()) as client:
        response = client.post(
            (f"/api/v1/projects/{PROJECT_ID}/brief-versions"),
            headers=authorization_header(),
            json={
                "name": "Project",
                "unknown_fields": ["budget"],
            },
        )

    payload = response.json()

    assert response.status_code == 201
    assert payload["version_number"] == 1
    assert "name" in (payload["brief"]["provided_fields"])
    assert "budget" in (payload["brief"]["unknown_fields"])
    assert "problem" in (payload["brief"]["missing_fields"])


def test_project_service_unavailable_returns_503() -> None:
    """Keep project routes explicit when persistence is absent."""
    with build_client(None) as client:
        response = client.get(
            "/api/v1/projects",
            headers=authorization_header(),
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "project_service_unavailable"}
