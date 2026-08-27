"""API contract tests for typed Web source, execution, and repair resources."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import JsonValue

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.services import ApplicationRuntime
from orchestwin.api.web_execution import (
    ApplyWebRepairProposalBody,
    CreateWebRepairProposalBody,
    CreateWebSourceRevisionBody,
    StartWebExecutionBody,
    WebApiCommandResult,
    WebApiCommandStatus,
    WebExecutionStartCommand,
    WebRepairProposalApplyCommand,
    WebRepairProposalCreateCommand,
    WebSourceRevisionCreateCommand,
)
from orchestwin.config import ApplicationSettings, RuntimeEnvironment
from orchestwin.identity.domain import NormalizedEmail, UserAccount

OWNER_ID = UUID("00000000-0000-4000-8000-00000000a101")
PROJECT_ID = UUID("00000000-0000-4000-8000-00000000a102")
REVISION_ID = UUID("00000000-0000-4000-8000-00000000a103")
EXECUTION_ID = UUID("00000000-0000-4000-8000-00000000a104")
PROPOSAL_ID = UUID("00000000-0000-4000-8000-00000000a105")
AUTHORIZATION_ID = UUID("00000000-0000-4000-8000-00000000a106")
NOW = datetime(2026, 8, 27, 14, 0, tzinfo=UTC)

REVISION: dict[str, JsonValue] = {
    "id": str(REVISION_ID),
    "project_id": str(PROJECT_ID),
    "version_number": 1,
    "content_hash": "a" * 64,
    "source_tree_hash": "b" * 64,
    "origin": "GENERATED_PLAN",
    "target_selection": {
        "target": "WEB_STATIC",
        "language_configuration": {
            "frontend": "STATIC_ASSETS",
            "backend": None,
        },
        "layout": "SINGLE_ROOT",
    },
    "files": [],
    "provenance_references": [],
}
EXECUTION: dict[str, JsonValue] = {
    "id": str(EXECUTION_ID),
    "project_id": str(PROJECT_ID),
    "attempt_number": 1,
    "content_hash": "c" * 64,
    "source_revision": REVISION,
    "report": {
        "status": "FAILED",
        "phase_results": [],
    },
}
BROWSER_EVIDENCE: dict[str, JsonValue] = {
    "status": "COLLECTED",
    "content_hash": "d" * 64,
    "routes": [],
}
PROPOSAL: dict[str, JsonValue] = {
    "id": str(PROPOSAL_ID),
    "project_id": str(PROJECT_ID),
    "content_hash": "e" * 64,
    "base_revision": REVISION,
    "changes": [],
}


def _user() -> UserAccount:
    return UserAccount(
        id=OWNER_ID,
        email=NormalizedEmail("owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


class FakeWebExecutionApiService:
    def __init__(self) -> None:
        self.source_command: WebSourceRevisionCreateCommand | None = None
        self.execution_command: WebExecutionStartCommand | None = None
        self.repair_command: WebRepairProposalCreateCommand | None = None
        self.apply_command: WebRepairProposalApplyCommand | None = None
        self.owner_ids: list[UUID] = []

    async def create_source_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        command: WebSourceRevisionCreateCommand,
    ) -> WebApiCommandResult:
        assert project_id == PROJECT_ID
        self.owner_ids.append(owner_user_id)
        self.source_command = command
        return WebApiCommandResult(
            WebApiCommandStatus.SOURCE_REVISION_CREATED,
            REVISION,
            "Web source revision was created.",
        )

    async def source_revision_history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]:
        self.owner_ids.append(owner_user_id)
        return (REVISION,) if project_id == PROJECT_ID else ()

    async def source_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        revision_id: UUID,
    ) -> dict[str, JsonValue] | None:
        self.owner_ids.append(owner_user_id)
        if project_id == PROJECT_ID and revision_id == REVISION_ID:
            return REVISION
        return None

    async def start_execution(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        command: WebExecutionStartCommand,
    ) -> WebApiCommandResult:
        assert project_id == PROJECT_ID
        self.owner_ids.append(owner_user_id)
        self.execution_command = command
        return WebApiCommandResult(
            WebApiCommandStatus.EXECUTION_RECORDED,
            EXECUTION,
            "Web execution evidence was recorded.",
        )

    async def execution_history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]:
        self.owner_ids.append(owner_user_id)
        return (EXECUTION,) if project_id == PROJECT_ID else ()

    async def execution(
        self,
        *,
        owner_user_id: UUID,
        execution_id: UUID,
    ) -> dict[str, JsonValue] | None:
        self.owner_ids.append(owner_user_id)
        return EXECUTION if execution_id == EXECUTION_ID else None

    async def execution_report(
        self,
        *,
        owner_user_id: UUID,
        execution_id: UUID,
    ) -> dict[str, JsonValue] | None:
        self.owner_ids.append(owner_user_id)
        return EXECUTION["report"] if execution_id == EXECUTION_ID else None

    async def browser_evidence(
        self,
        *,
        owner_user_id: UUID,
        execution_id: UUID,
    ) -> dict[str, JsonValue] | None:
        self.owner_ids.append(owner_user_id)
        return BROWSER_EVIDENCE if execution_id == EXECUTION_ID else None

    async def repair_proposals(
        self,
        *,
        owner_user_id: UUID,
        execution_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]:
        self.owner_ids.append(owner_user_id)
        return (PROPOSAL,) if execution_id == EXECUTION_ID else ()

    async def create_repair_proposal(
        self,
        *,
        owner_user_id: UUID,
        execution_id: UUID,
        command: WebRepairProposalCreateCommand,
    ) -> WebApiCommandResult:
        assert execution_id == EXECUTION_ID
        self.owner_ids.append(owner_user_id)
        self.repair_command = command
        return WebApiCommandResult(
            WebApiCommandStatus.REPAIR_PROPOSED,
            PROPOSAL,
            "Web repair proposal was recorded.",
        )

    async def apply_repair_proposal(
        self,
        *,
        owner_user_id: UUID,
        execution_id: UUID,
        proposal_id: UUID,
        command: WebRepairProposalApplyCommand,
    ) -> WebApiCommandResult:
        assert execution_id == EXECUTION_ID
        assert proposal_id == PROPOSAL_ID
        self.owner_ids.append(owner_user_id)
        self.apply_command = command
        return WebApiCommandResult(
            WebApiCommandStatus.REPAIR_APPLIED,
            REVISION,
            "Web repair revision was applied.",
        )


def _client(service: FakeWebExecutionApiService) -> TestClient:
    application = create_app(
        ApplicationSettings(
            environment=RuntimeEnvironment.TEST,
            api_prefix="/api/v1",
        ),
        runtime=ApplicationRuntime(web_execution_api_service=service),
        auth_settings=AuthApiSettings(),
    )
    application.dependency_overrides[current_user_dependency] = _user
    return TestClient(application)


def _source_body() -> dict[str, object]:
    return {
        "target_selection": {
            "target": "WEB_STATIC",
            "language_configuration": {
                "frontend": "STATIC_ASSETS",
                "backend": None,
            },
            "layout": "SINGLE_ROOT",
        },
        "rationale": "Materialize the approved deterministic static fixture.",
        "files": [
            {
                "normalized_path": "index.html",
                "content": "<!doctype html><title>Fixture</title>",
                "media_type": "text/html",
            }
        ],
        "provenance_references": [
            {
                "kind": "SOURCE_PLAN",
                "reference_id": "source-plan-1",
                "version_number": 1,
                "content_hash": "f" * 64,
            }
        ],
    }


def _execution_body() -> dict[str, object]:
    return {
        "source_revision_id": str(REVISION_ID),
        "profile_id": "web.static",
        "profile_version": "1.0.0",
        "policy_content_hash": "1" * 64,
        "runners": {
            "execution_runner_image_digest": "2" * 64,
            "browser_runner_image_digest": "3" * 64,
        },
        "purpose": "PROFILE_VALIDATION",
        "trigger": "PROFILE_VALIDATION",
        "authorization_id": str(AUTHORIZATION_ID),
        "rerun_phases": None,
        "declared_routes": [{"route_id": "root", "path": "/"}],
    }


def test_source_and_execution_commands_are_typed_and_owner_scoped() -> None:
    service = FakeWebExecutionApiService()
    client = _client(service)

    source = client.post(
        f"/api/v1/projects/{PROJECT_ID}/web-source-revisions",
        json=_source_body(),
    )
    execution = client.post(
        f"/api/v1/projects/{PROJECT_ID}/web-executions",
        json=_execution_body(),
    )

    assert source.status_code == 201
    assert source.json()["snapshot"]["id"] == str(REVISION_ID)
    assert service.source_command is not None
    assert service.source_command.files[0].normalized_path == "index.html"
    assert execution.status_code == 201
    assert service.execution_command is not None
    assert service.execution_command.authorization_id == AUTHORIZATION_ID
    assert service.execution_command.declared_routes[0].path == "/"
    assert set(service.owner_ids) == {OWNER_ID}


def test_queries_expose_revision_report_browser_and_repair_snapshots() -> None:
    service = FakeWebExecutionApiService()
    client = _client(service)

    responses = (
        client.get(f"/api/v1/projects/{PROJECT_ID}/web-source-revisions"),
        client.get(f"/api/v1/projects/{PROJECT_ID}/web-source-revisions/{REVISION_ID}"),
        client.get(f"/api/v1/projects/{PROJECT_ID}/web-executions"),
        client.get(f"/api/v1/web-executions/{EXECUTION_ID}"),
        client.get(f"/api/v1/web-executions/{EXECUTION_ID}/report"),
        client.get(f"/api/v1/web-executions/{EXECUTION_ID}/browser-evidence"),
        client.get(f"/api/v1/web-executions/{EXECUTION_ID}/repair-proposals"),
    )

    assert all(response.status_code == 200 for response in responses)
    assert responses[0].json()["items"][0]["content_hash"] == "a" * 64
    assert responses[4].json()["snapshot"]["status"] == "FAILED"
    assert responses[5].json()["snapshot"]["status"] == "COLLECTED"
    assert responses[6].json()["items"][0]["id"] == str(PROPOSAL_ID)

    missing = client.get("/api/v1/web-executions/00000000-0000-4000-8000-00000000ffff")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "WEB_EXECUTION_RESOURCE_NOT_FOUND"


def test_repair_commands_preserve_exact_failure_and_revision_hashes() -> None:
    service = FakeWebExecutionApiService()
    client = _client(service)
    proposal_body = {
        "base_revision_content_hash": "a" * 64,
        "failure_signature_digest": "4" * 64,
        "changes": [
            {
                "operation": "REPLACE",
                "normalized_path": "index.html",
                "content": "<!doctype html><title>Repaired</title>",
                "media_type": "text/html",
            }
        ],
        "rationale": "Repair the deterministic failing fixture.",
    }

    proposed = client.post(
        f"/api/v1/web-executions/{EXECUTION_ID}/repair-proposals",
        json=proposal_body,
    )
    applied = client.post(
        f"/api/v1/web-executions/{EXECUTION_ID}/repair-proposals/{PROPOSAL_ID}/apply",
        json={
            "base_revision_content_hash": "a" * 64,
            "proposal_content_hash": "e" * 64,
            "approval_id": None,
        },
    )

    assert proposed.status_code == 201
    assert applied.status_code == 200
    assert service.repair_command is not None
    assert service.repair_command.failure_signature_digest == "4" * 64
    assert service.apply_command is not None
    assert service.apply_command.proposal_content_hash == "e" * 64


def test_openapi_exposes_no_arbitrary_command_fields_in_web_inputs() -> None:
    service = FakeWebExecutionApiService()
    application = create_app(
        ApplicationSettings(
            environment=RuntimeEnvironment.TEST,
            api_prefix="/api/v1",
        ),
        runtime=ApplicationRuntime(web_execution_api_service=service),
        auth_settings=AuthApiSettings(),
    )
    openapi = application.openapi()
    serialized_paths = str(
        {
            path: value
            for path, value in openapi["paths"].items()
            if "web-source-revisions" in path or "web-executions" in path
        }
    ).casefold()
    input_models = (
        CreateWebSourceRevisionBody,
        StartWebExecutionBody,
        CreateWebRepairProposalBody,
        ApplyWebRepairProposalBody,
    )
    input_properties = {
        property_name
        for model in input_models
        for property_name in model.model_json_schema().get("properties", {})
    }

    assert "/api/v1/projects/{project_id}/web-source-revisions" in openapi["paths"]
    assert "/api/v1/projects/{project_id}/web-executions" in openapi["paths"]
    assert "shell_command" not in serialized_paths
    assert "host_command" not in input_properties
    assert "docker_arguments" not in input_properties
    assert "executable" not in input_properties
    assert application.state.web_execution_api_service is service
