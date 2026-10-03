from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from orchestwin.api import services as services_module
from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.services import ApplicationRuntime, create_default_runtime
from orchestwin.artifacts import why_runtime
from orchestwin.artifacts.why_runtime import SqlAlchemyWhyQueryService
from orchestwin.config import ApplicationSettings, RuntimeEnvironment
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.projects.sections import project_sections
from orchestwin.why import build_why_document, explain_why
from src.test.python.artifacts.test_why import chain
from src.test.python.projects.test_sections import aligned
from src.test.python.twins.test_user_modeling_persistence import snapshot_version

PROJECT_ID = UUID(int=3401)
OWNER_ID = UUID(int=3402)
NOW = datetime(2026, 10, 2, 17, tzinfo=UTC)


def owner():
    return UserAccount(
        id=OWNER_ID,
        email=NormalizedEmail("synthetic-owner@example.invalid"),
        password_hash="$argon2id$fixture",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


class Query:
    def __init__(self, document):
        self.document = document
        self.calls = []

    async def current(self, *, owner_user_id, project_id):
        self.calls.append((owner_user_id, project_id))
        return self.document


def client(query):
    app = create_app(
        ApplicationSettings(environment=RuntimeEnvironment.TEST, api_prefix="/api/v1"),
        runtime=ApplicationRuntime(why_query_service=query),
        auth_settings=AuthApiSettings(),
    )
    app.dependency_overrides[current_user_dependency] = owner
    return TestClient(app)


def test_api_document_and_answer_share_a_read_only_owner_scoped_contract():
    stages, evidence, _, _ = chain()
    document = build_why_document(project_id=str(PROJECT_ID), stages=stages, evidence=evidence)
    query = Query(document)
    browser = client(query)
    response = browser.get(
        f"/api/v1/projects/{PROJECT_ID}/artifacts/why", params={"code": "REQ-001"}
    )
    assert response.status_code == 200
    assert response.json() == explain_why(document, "REQ-001")
    response = browser.get(f"/api/v1/projects/{PROJECT_ID}/artifacts/why/document")
    assert response.json() == document
    assert query.calls == [(OWNER_ID, PROJECT_ID), (OWNER_ID, PROJECT_ID)]


@pytest.mark.parametrize(
    ("code", "status", "error"),
    [
        ("REQ-999", 404, "WHY_CODE_NOT_FOUND"),
        ("REQ 001", 422, "WHY_CODE_INVALID"),
    ],
)
def test_api_selector_errors_are_explicit_without_echoing_user_text(code, status, error):
    browser = client(Query(build_why_document(project_id=str(PROJECT_ID), stages={})))
    response = browser.get(f"/api/v1/projects/{PROJECT_ID}/artifacts/why", params={"code": code})
    assert response.status_code == status
    assert response.json() == {"detail": {"code": error}}


def test_api_ambiguous_codes_return_exact_candidates():
    stages, evidence, _, _ = chain()
    another = deepcopy(stages["requirements"])
    another.update(id=str(UUID(int=34)), version_number=2, content_hash="a" * 64)
    stages["requirements"] = [stages["requirements"], another]
    document = build_why_document(project_id=str(PROJECT_ID), stages=stages, evidence=evidence)
    response = client(Query(document)).get(
        f"/api/v1/projects/{PROJECT_ID}/artifacts/why", params={"code": "REQ-001"}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "WHY_CODE_AMBIGUOUS"
    assert len(response.json()["detail"]["candidates"]) == 2


def test_api_out_of_scope_project_is_not_found_before_code_lookup():
    response = client(Query(None)).get(
        f"/api/v1/projects/{PROJECT_ID}/artifacts/why", params={"code": "REQ-001"}
    )
    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "PROJECT_NOT_FOUND"}}


def test_api_dependency_requires_a_configured_query():
    response = client(None).get(f"/api/v1/projects/{PROJECT_ID}/artifacts/why/document")
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "WHY_SERVICE_UNAVAILABLE"}}


class Session:
    def __init__(self, *, owned=True):
        self.owned = owned
        self.statements = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def scalar(self, statement):
        self.statements.append(statement)
        return PROJECT_ID if self.owned else None


def test_runtime_rejects_non_owner_before_loading_any_stage(monkeypatch):
    session = Session(owned=False)
    query = SqlAlchemyWhyQueryService(lambda: session)
    result = asyncio.run(query.current(owner_user_id=OWNER_ID, project_id=PROJECT_ID))
    assert result is None
    compiled = session.statements[0].compile()
    assert OWNER_ID in compiled.params.values()
    assert PROJECT_ID in compiled.params.values()


def test_runtime_reads_twins_before_requirements_and_keeps_exact_historical_versions(monkeypatch):
    session = Session()
    modeling = snapshot_version()
    newer = replace(modeling, id=UUID(int=3409), version_number=2, based_on_version_number=1)
    calls = []

    class ScopedRepository:
        def __init__(self, _session, *, owner_user_id):
            assert owner_user_id == OWNER_ID

        async def history(self, *, project_id):
            assert project_id == PROJECT_ID
            calls.append(self)
            return (modeling, newer) if type(self) is ModelingRepository else ()

    class ModelingRepository(ScopedRepository):
        pass

    class UnscopedRepository:
        def __init__(self, _session):
            assert _session is session

        async def list_owned_versions(self, *, project_id, owner_user_id):
            assert (project_id, owner_user_id) == (PROJECT_ID, OWNER_ID)
            return ()

    class EvidenceRepository(ScopedRepository):
        async def dossier(self, project_id):
            assert project_id == PROJECT_ID
            return {}

    class EvaluationRepository(ScopedRepository):
        async def list(self, *, project_id, limit):
            assert project_id == PROJECT_ID
            assert limit > 50
            return ()

    class ValidationRepository(ScopedRepository):
        async def current(self, *, project_id):
            assert project_id == PROJECT_ID
            return ()

    class HumanValidationRepository(ScopedRepository):
        async def records(self, *, project_id):
            assert project_id == PROJECT_ID
            return {"hypotheses": [], "outcomes": []}

    class Sections:
        def __init__(self, _sessions):
            pass

        async def facts(self, *, owner_user_id, project_id):
            assert (owner_user_id, project_id) == (OWNER_ID, PROJECT_ID)
            return aligned()

    async def mockups(*_args, **_kwargs):
        return []

    monkeypatch.setattr(why_runtime, "SqlAlchemyProjectBriefRepository", UnscopedRepository)
    monkeypatch.setattr(why_runtime, "SqlAlchemyTeamProposalVersionRepository", UnscopedRepository)
    monkeypatch.setattr(why_runtime, "SqlAlchemyUserModelingSnapshotRepository", ModelingRepository)
    monkeypatch.setattr(
        why_runtime, "SqlAlchemyRequirementsSpecificationRepository", ScopedRepository
    )
    monkeypatch.setattr(why_runtime, "SqlAlchemyDesignPackageRepository", ScopedRepository)
    monkeypatch.setattr(why_runtime, "SqlAlchemyResearchEvidenceRepository", EvidenceRepository)
    monkeypatch.setattr(why_runtime, "SqlAlchemyDesignEvaluationRepository", EvaluationRepository)
    monkeypatch.setattr(why_runtime, "SqlAlchemyFindingValidationRepository", ValidationRepository)
    monkeypatch.setattr(
        why_runtime, "SqlAlchemyHumanValidationRepository", HumanValidationRepository
    )
    monkeypatch.setattr(why_runtime, "SqlAlchemySectionReads", Sections)
    monkeypatch.setattr(SqlAlchemyWhyQueryService, "_mockups", mockups)
    document = asyncio.run(
        SqlAlchemyWhyQueryService(lambda: session).current(
            owner_user_id=OWNER_ID, project_id=PROJECT_ID
        )
    )
    assert document["kind"] == "orchestwin.why"
    assert {node["code"] for node in document["nodes"] if node["kind"] == "USER_MODELING"} == {
        "UM-v1",
        "UM-v2",
    }
    assert len([node for node in document["nodes"] if node["kind"] == "USER_TWIN"]) == 1
    assert "requirements" in document["omitted_sections"]
    assert project_sections(aligned()).to_snapshot()["sections"]


def test_default_runtime_composes_the_why_query_from_shared_sessions(monkeypatch):
    database = SimpleNamespace(session_factory=object())
    requirements = SimpleNamespace(
        generation=object(), revisions=object(), queries=object(), gate=object(), changes=object()
    )
    design = SimpleNamespace(
        generation=object(), revisions=object(), queries=object(), gate=object()
    )
    marker = object()
    captured = []

    def query(session_factory):
        captured.append(session_factory)
        return marker

    monkeypatch.setenv(
        "ORCHESTWIN_DATABASE_URL", "postgresql+psycopg://synthetic:fixture@127.0.0.1:5432/fixture"
    )
    monkeypatch.setenv("ORCHESTWIN_AUTH_JWT_SECRET", "synthetic-secret-long-enough-to-validate")
    monkeypatch.setattr(services_module, "create_database_runtime", lambda _settings: database)
    monkeypatch.setattr(services_module, "build_requirements_services", lambda _: requirements)
    monkeypatch.setattr(services_module, "build_design_services", lambda _: design)
    monkeypatch.setattr(services_module, "SqlAlchemyWhyQueryService", query)
    runtime = create_default_runtime()
    assert runtime.why_query_service is marker
    assert captured == [database.session_factory]
