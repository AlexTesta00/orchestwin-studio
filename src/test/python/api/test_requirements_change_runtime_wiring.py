from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from orchestwin.api import services as services_module
from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.generation_requests import RESPOND_ASYNC
from orchestwin.config import ApplicationSettings, RuntimeEnvironment
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.models.fake_requirements import FakeDeterministicRequirementsAdapter
from orchestwin.projects.requirements_change_application import LocalRequirementsChangeService
from orchestwin.projects.requirements_runtime import SqlAlchemyRequirementsGovernanceAdapter

OWNER_ID = UUID("00000000-0000-4000-8000-000000000701")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000702")
NOW = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
CHANGES = f"/api/v1/projects/{PROJECT_ID}/requirements/change-requests"
JOBS = f"/api/v1/projects/{PROJECT_ID}/generation-jobs"
REFUSED = {"detail": {"code": "PROJECT_NOT_FOUND"}}


class FakeDatabaseRuntime:
    def __init__(self) -> None:
        self.session_factory = object()

    async def dispose(self) -> None:
        return None


def account() -> UserAccount:
    return UserAccount(
        id=OWNER_ID,
        email=NormalizedEmail("owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def test_the_default_offline_studio_answers_the_change_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    for name in tuple(os.environ):
        if name.upper().startswith("ORCHESTWIN_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "ORCHESTWIN_DATABASE_URL",
        "postgresql+psycopg://orchestwin:test@127.0.0.1:5432/orchestwin",
    )
    monkeypatch.setenv(
        "ORCHESTWIN_AUTH_JWT_SECRET",
        "a-runtime-test-secret-that-is-long-enough-for-validation",
    )
    monkeypatch.setattr(
        services_module, "create_database_runtime", lambda _settings: FakeDatabaseRuntime()
    )
    loaded = []

    async def absent_project(self, *, owner_user_id, project_id):
        loaded.append((owner_user_id, project_id))
        return None

    monkeypatch.setattr(SqlAlchemyRequirementsGovernanceAdapter, "load_current", absent_project)
    settings = ApplicationSettings(
        environment=RuntimeEnvironment.TEST,
        api_prefix="/api/v1",
        debug=False,
        _env_file=None,
    )
    runtime = services_module.create_default_runtime(settings)
    application = create_app(
        settings, runtime=runtime, auth_settings=AuthApiSettings(_env_file=None)
    )
    application.dependency_overrides[current_user_dependency] = account

    with TestClient(application) as client:
        synchronous = client.post(CHANGES, json={"request": "Aggiungi l'export in PDF"})
        started = client.post(
            CHANGES,
            json={"request": "Aggiungi l'export in PDF"},
            headers={"Prefer": RESPOND_ASYNC},
        )
        job_id = started.json()["job_id"]
        client.portal.call(application.state.generation_jobs.wait, UUID(job_id))
        job = client.get(f"{JOBS}/{job_id}").json()

    service = application.state.requirements_change_service

    assert isinstance(service, LocalRequirementsChangeService)
    assert service is runtime.requirements_change_service
    assert isinstance(service._proposals, FakeDeterministicRequirementsAdapter)
    assert service._revisions is runtime.requirements_revision_service
    assert synchronous.status_code == 404
    assert synchronous.json() == REFUSED
    assert started.status_code == 202
    assert job["operation"] == "REQUIREMENTS_CHANGE"
    assert job["response"] == {"status_code": 404, "body": REFUSED}
    assert loaded == [(OWNER_ID, PROJECT_ID), (OWNER_ID, PROJECT_ID)]
