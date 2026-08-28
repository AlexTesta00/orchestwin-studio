"""API contract tests for typed JVM source, execution, and repair resources."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import JsonValue

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.jvm_execution import (
    JvmApiCommandResult,
    JvmApiCommandStatus,
    JvmExecutionStartCommand,
    JvmRepairProposalApplyCommand,
    JvmRepairProposalCreateCommand,
    JvmSourceRevisionCreateCommand,
)
from orchestwin.api.services import ApplicationRuntime
from orchestwin.config import ApplicationSettings, RuntimeEnvironment
from orchestwin.identity.domain import NormalizedEmail, UserAccount

OWNER_ID = UUID("00000000-0000-4000-8000-00000000b101")
PROJECT_ID = UUID("00000000-0000-4000-8000-00000000b102")
REVISION_ID = UUID("00000000-0000-4000-8000-00000000b103")
EXECUTION_ID = UUID("00000000-0000-4000-8000-00000000b104")
PROPOSAL_ID = UUID("00000000-0000-4000-8000-00000000b105")
AUTHORIZATION_ID = UUID("00000000-0000-4000-8000-00000000b106")
NOW = datetime(2026, 8, 28, 19, 30, tzinfo=UTC)

PROFILE: dict[str, JsonValue] = {
    "profile_id": "jvm.kotlin-gradle",
    "profile_version": "1.0.0",
    "target": "JVM_KOTLIN",
    "capability_status": "DESIGN_ONLY_LEVEL_C",
}
REVISION: dict[str, JsonValue] = {
    "id": str(REVISION_ID),
    "project_id": str(PROJECT_ID),
    "version_number": 1,
    "content_hash": "a" * 64,
    "source_tree_hash": "b" * 64,
    "origin": "DETERMINISTIC_FIXTURE",
    "target_selection": {"target": "JVM_KOTLIN"},
    "files": [],
    "provenance_references": [],
}
EXECUTION: dict[str, JsonValue] = {
    "id": str(EXECUTION_ID),
    "project_id": str(PROJECT_ID),
    "attempt_number": 1,
    "content_hash": "c" * 64,
    "source_revision": REVISION,
    "report": {"status": "FAILED", "phase_results": []},
}
PROPOSAL: dict[str, JsonValue] = {
    "id": str(PROPOSAL_ID),
    "project_id": str(PROJECT_ID),
    "content_hash": "d" * 64,
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


class FakeJvmExecutionApiService:
    def __init__(self) -> None:
        self.source_command: JvmSourceRevisionCreateCommand | None = None
        self.execution_command: JvmExecutionStartCommand | None = None
        self.repair_command: JvmRepairProposalCreateCommand | None = None
        self.apply_command: JvmRepairProposalApplyCommand | None = None
        self.owner_ids: list[UUID] = []

    async def profiles(self, *, owner_user_id: UUID) -> tuple[dict[str, JsonValue], ...]:
        self.owner_ids.append(owner_user_id)
        return (PROFILE,)

    async def create_source_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        command: JvmSourceRevisionCreateCommand,
    ) -> JvmApiCommandResult:
        assert project_id == PROJECT_ID
        self.owner_ids.append(owner_user_id)
        self.source_command = command
        return JvmApiCommandResult(
            JvmApiCommandStatus.SOURCE_REVISION_CREATED,
            REVISION,
            "JVM source revision was created.",
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
        command: JvmExecutionStartCommand,
    ) -> JvmApiCommandResult:
        assert project_id == PROJECT_ID
        self.owner_ids.append(owner_user_id)
        self.execution_command = command
        return JvmApiCommandResult(
            JvmApiCommandStatus.EXECUTION_RECORDED,
            EXECUTION,
            "JVM execution evidence was recorded.",
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
        command: JvmRepairProposalCreateCommand,
    ) -> JvmApiCommandResult:
        assert execution_id == EXECUTION_ID
        self.owner_ids.append(owner_user_id)
        self.repair_command = command
        return JvmApiCommandResult(
            JvmApiCommandStatus.REPAIR_PROPOSED,
            PROPOSAL,
            "JVM repair proposal was recorded.",
        )

    async def apply_repair_proposal(
        self,
        *,
        owner_user_id: UUID,
        execution_id: UUID,
        proposal_id: UUID,
        command: JvmRepairProposalApplyCommand,
    ) -> JvmApiCommandResult:
        assert execution_id == EXECUTION_ID
        assert proposal_id == PROPOSAL_ID
        self.owner_ids.append(owner_user_id)
        self.apply_command = command
        return JvmApiCommandResult(
            JvmApiCommandStatus.REPAIR_APPLIED,
            REVISION,
            "JVM repair revision was applied.",
        )


def _client(service: FakeJvmExecutionApiService | None) -> TestClient:
    application = create_app(
        ApplicationSettings(
            environment=RuntimeEnvironment.TEST,
            api_prefix="/api/v1",
        ),
        runtime=ApplicationRuntime(jvm_execution_api_service=service),
        auth_settings=AuthApiSettings(),
    )
    application.dependency_overrides[current_user_dependency] = _user
    return TestClient(application)


def _source_body() -> dict[str, object]:
    return {
        "target": "JVM_KOTLIN",
        "rationale": "Materialize the approved Kotlin/JVM formal case.",
        "files": [
            {
                "normalized_path": "src/main/kotlin/example/Main.kt",
                "content": "fun main() = println(42)",
                "media_type": "text/x-kotlin",
            }
        ],
        "provenance_references": [
            {
                "kind": "SOURCE_PLAN",
                "reference_id": "source-plan:kotlin-case",
                "version_number": 1,
                "content_hash": "e" * 64,
            }
        ],
    }


def _execution_body() -> dict[str, object]:
    return {
        "source_revision_id": str(REVISION_ID),
        "profile_id": "jvm.kotlin-gradle",
        "profile_version": "1.0.0",
        "policy_content_hash": "f" * 64,
        "runner_image_digest": "1" * 64,
        "purpose": "PROFILE_VALIDATION",
        "trigger": "PROFILE_VALIDATION",
        "authorization_id": str(AUTHORIZATION_ID),
        "rerun_phases": None,
    }


def test_profile_source_and_execution_routes_preserve_typed_commands() -> None:
    service = FakeJvmExecutionApiService()
    client = _client(service)

    profiles = client.get("/api/v1/jvm-execution-profiles")
    created = client.post(
        f"/api/v1/projects/{PROJECT_ID}/jvm-source-revisions",
        json=_source_body(),
    )
    started = client.post(
        f"/api/v1/projects/{PROJECT_ID}/jvm-executions",
        json=_execution_body(),
    )

    assert profiles.status_code == 200
    assert profiles.json()["items"] == [PROFILE]
    assert created.status_code == 201
    assert started.status_code == 201
    assert service.source_command is not None
    assert service.source_command.target.value == "JVM_KOTLIN"
    assert service.execution_command is not None
    assert service.execution_command.profile_id == "jvm.kotlin-gradle"
    assert service.owner_ids and set(service.owner_ids) == {OWNER_ID}


def test_query_routes_return_owner_scoped_snapshots_and_uniform_404() -> None:
    client = _client(FakeJvmExecutionApiService())

    revisions = client.get(f"/api/v1/projects/{PROJECT_ID}/jvm-source-revisions")
    execution = client.get(f"/api/v1/jvm-executions/{EXECUTION_ID}")
    report = client.get(f"/api/v1/jvm-executions/{EXECUTION_ID}/report")
    missing = client.get(f"/api/v1/jvm-executions/{UUID('00000000-0000-4000-8000-00000000b199')}")

    assert revisions.json()["items"] == [REVISION]
    assert execution.json()["snapshot"] == EXECUTION
    assert report.json()["snapshot"] == EXECUTION["report"]
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "JVM_EXECUTION_RESOURCE_NOT_FOUND"


def test_repair_routes_validate_change_shape_and_forward_exact_hashes() -> None:
    service = FakeJvmExecutionApiService()
    client = _client(service)
    body = {
        "base_revision_content_hash": "a" * 64,
        "failure_signature": "b" * 64,
        "changes": [
            {
                "operation": "REPLACE",
                "normalized_path": "src/main/kotlin/example/Main.kt",
                "content": "fun main() = println(43)",
                "media_type": "text/x-kotlin",
            }
        ],
        "rationale": "Repair the exact normalized JVM failure.",
    }

    proposed = client.post(
        f"/api/v1/jvm-executions/{EXECUTION_ID}/repair-proposals",
        json=body,
    )
    applied = client.post(
        f"/api/v1/jvm-executions/{EXECUTION_ID}/repair-proposals/{PROPOSAL_ID}/apply",
        json={
            "base_revision_content_hash": "a" * 64,
            "proposal_content_hash": "d" * 64,
            "approval_id": None,
        },
    )
    invalid_delete = client.post(
        f"/api/v1/jvm-executions/{EXECUTION_ID}/repair-proposals",
        json={
            **body,
            "changes": [
                {
                    "operation": "DELETE",
                    "normalized_path": "src/main/kotlin/example/Main.kt",
                    "content": "must-not-exist",
                    "media_type": "text/x-kotlin",
                }
            ],
        },
    )

    assert proposed.status_code == 201
    assert applied.status_code == 200
    assert invalid_delete.status_code == 422
    assert service.repair_command is not None
    assert service.repair_command.failure_signature == "b" * 64
    assert service.apply_command is not None
    assert service.apply_command.proposal_content_hash == "d" * 64


def test_android_target_is_rejected_by_jvm_source_contract() -> None:
    client = _client(FakeJvmExecutionApiService())
    body = _source_body()
    body["target"] = "ANDROID_KOTLIN"

    response = client.post(
        f"/api/v1/projects/{PROJECT_ID}/jvm-source-revisions",
        json=body,
    )

    assert response.status_code == 422


def test_router_returns_service_unavailable_without_runtime_adapter() -> None:
    client = _client(None)

    response = client.get("/api/v1/jvm-execution-profiles")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "JVM_EXECUTION_API_SERVICE_UNAVAILABLE"
