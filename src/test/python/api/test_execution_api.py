"""API contract tests for profiles, sandbox evidence, and Gate 7 governance."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.services import ApplicationRuntime
from orchestwin.config import ApplicationSettings, RuntimeEnvironment
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.projects.brownfield_intake import BrownfieldIntakeReference
from orchestwin.projects.domain import ProjectMode, create_project
from orchestwin.sandbox.builtin_execution_profiles import (
    create_builtin_execution_profile_registry,
)
from orchestwin.sandbox.evidence import (
    SandboxCommandEvidence,
    SandboxCommandStatus,
    SandboxLogReference,
    SandboxLogStream,
    SandboxRunEvidence,
    SandboxRunStatus,
)
from orchestwin.sandbox.execution_policy import SandboxResourceLimits
from orchestwin.sandbox.execution_profiles import ExecutionProfileMetadata
from orchestwin.sandbox.project_runs import ProjectSandboxRunEvidence
from orchestwin.sandbox.run_persistence import (
    PersistedProjectSandboxRun,
    persisted_project_sandbox_run_from_domain,
)
from orchestwin.workflow.high_impact import HighImpactOperationPolicy
from orchestwin.workflow.high_impact_gate import LocalHighImpactApprovalService
from orchestwin.workflow.high_impact_persistence import (
    InMemoryHighImpactApprovalUnitOfWorkFactory,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000007901")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000007902")
RUN_ID = UUID("00000000-0000-4000-8000-000000007903")
INTAKE_ID = UUID("00000000-0000-4000-8000-000000007904")
NOW = datetime(2026, 8, 25, 15, 0, tzinfo=UTC)
FINISHED_AT = NOW + timedelta(seconds=2)
RECORDED_AT = FINISHED_AT + timedelta(seconds=1)
IMAGE = "example/web@sha256:" + "a" * 64
RESOURCES = SandboxResourceLimits(2.0, 4096, 256, 512)


def _user() -> UserAccount:
    return UserAccount(
        id=OWNER_ID,
        email=NormalizedEmail("owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _log(stream: SandboxLogStream) -> SandboxLogReference:
    digest = "b" * 64 if stream is SandboxLogStream.STDOUT else "c" * 64
    return SandboxLogReference(
        stream=stream,
        sha256_digest=digest,
        size_bytes=4,
        storage_key=f"sha256/{digest[:2]}/{digest}",
    )


def _sandbox_run() -> PersistedProjectSandboxRun:
    command = SandboxCommandEvidence(
        command_id="quality.tests",
        status=SandboxCommandStatus.SUCCEEDED,
        started_at=NOW,
        finished_at=FINISHED_AT,
        exit_code=0,
        stdout_log=_log(SandboxLogStream.STDOUT),
        stderr_log=_log(SandboxLogStream.STDERR),
        artifacts=(),
        output_parser_id="pytest.v1",
        failure_message=None,
    )
    evidence = SandboxRunEvidence(
        run_id=RUN_ID,
        plan_id="quality.plan",
        plan_content_hash="d" * 64,
        profile_id="WEB_STATIC",
        profile_version="1.0.0",
        image_reference=IMAGE,
        runtime_reference="fake.container.v1",
        status=SandboxRunStatus.SUCCEEDED,
        started_at=NOW,
        finished_at=FINISHED_AT,
        planned_command_ids=("quality.tests",),
        command_evidence=(command,),
        failure_message=None,
    )
    run = ProjectSandboxRunEvidence(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        evidence=evidence,
        brownfield_intake_reference=BrownfieldIntakeReference(
            intake_id=INTAKE_ID,
            project_id=PROJECT_ID,
            version_number=1,
            content_hash="e" * 64,
        ),
        recorded_at=RECORDED_AT,
    )
    return persisted_project_sandbox_run_from_domain(run)


class _ExecutionQueryService:
    def __init__(self, run: PersistedProjectSandboxRun | None = None) -> None:
        self._registry = create_builtin_execution_profile_registry()
        self._run = run

    async def profiles(self) -> tuple[ExecutionProfileMetadata, ...]:
        return tuple(profile.metadata for profile in self._registry.profiles)

    async def profile(
        self,
        *,
        profile_id: str,
        profile_version: str | None,
    ) -> ExecutionProfileMetadata | None:
        versions = self._registry.versions_for(profile_id)
        if profile_version is None:
            return None if not versions else versions[-1].metadata
        profile = self._registry.find(profile_id, profile_version)
        return None if profile is None else profile.metadata

    async def sandbox_history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[PersistedProjectSandboxRun, ...]:
        if owner_user_id != OWNER_ID or project_id != PROJECT_ID or self._run is None:
            return ()
        return (self._run,)

    async def sandbox_run(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
    ) -> PersistedProjectSandboxRun | None:
        if owner_user_id != OWNER_ID or self._run is None or self._run.run_id != run_id:
            return None
        return self._run


def _high_impact_service() -> LocalHighImpactApprovalService:
    project = create_project(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        display_name="Execution API fixture",
        mode=ProjectMode.BROWNFIELD_ASSESSMENT,
        created_at=NOW,
    )
    identifiers: Iterator[UUID] = iter(UUID(int=value) for value in range(7905, 7950))
    times: Iterator[datetime] = iter(NOW + timedelta(seconds=value) for value in range(1, 100))
    return LocalHighImpactApprovalService(
        unit_of_work_factory=InMemoryHighImpactApprovalUnitOfWorkFactory(
            projects={PROJECT_ID: project}
        ),
        policy=HighImpactOperationPolicy(
            approved_image_references=frozenset({IMAGE}),
            baseline_resources=RESOURCES,
            protected_workspace_components=frozenset({".git", ".orchestwin", ".ssh"}),
        ),
        uuid_factory=lambda: next(identifiers),
        clock=lambda: next(times),
    )


def _client(
    query_service: _ExecutionQueryService,
    gate_service: LocalHighImpactApprovalService,
) -> TestClient:
    application = create_app(
        ApplicationSettings(
            environment=RuntimeEnvironment.TEST,
            api_prefix="/api/v1",
        ),
        runtime=ApplicationRuntime(
            execution_query_service=query_service,
            high_impact_service=gate_service,
        ),
        auth_settings=AuthApiSettings(),
    )
    application.dependency_overrides[current_user_dependency] = _user
    return TestClient(application)


def _operation_body() -> dict[str, object]:
    return {
        "operation_kind": "SANDBOX_EXECUTION",
        "summary": "Execute the owner-reviewed web validation plan.",
        "profile_reference": {
            "profile_id": "custom.web",
            "profile_version": "1.0.0",
            "content_hash": "f" * 64,
        },
        "capability_status": "EXPERIMENTAL_LEVEL_D",
        "command_plan_id": "web.validation",
        "command_plan_content_hash": "1" * 64,
        "image_reference": IMAGE,
        "network_mode": "CONTROLLED",
        "secret_reference_ids": [],
        "resources": {
            "cpu_count": 2.0,
            "memory_mib": 4096,
            "pids_limit": 256,
            "writable_tmpfs_mib": 512,
        },
        "destructive_workspace_paths": [],
        "requests_privileged_container": False,
        "requests_docker_socket_mount": False,
        "requests_host_filesystem_mount": False,
        "requests_arbitrary_host_command": False,
    }


def test_execution_profiles_expose_capability_honesty_and_exact_versions() -> None:
    client = _client(_ExecutionQueryService(), _high_impact_service())

    listing = client.get("/api/v1/execution-profiles")
    detail = client.get(
        "/api/v1/execution-profiles/WEB_VUE",
        params={"profile_version": "1.0.0"},
    )

    assert listing.status_code == 200
    assert len(listing.json()["items"]) == 10
    assert {item["capability_status"] for item in listing.json()["items"]} == {
        "DESIGN_ONLY_LEVEL_C"
    }
    assert detail.status_code == 200
    assert detail.json()["snapshot"]["profile_id"] == "WEB_VUE"
    assert detail.json()["snapshot"]["supported_targets"] == ["WEB_VUE"]


def test_sandbox_endpoints_expose_references_without_raw_log_bytes() -> None:
    run = _sandbox_run()
    client = _client(_ExecutionQueryService(run), _high_impact_service())

    history = client.get(f"/api/v1/projects/{PROJECT_ID}/sandbox-runs")
    detail = client.get(f"/api/v1/sandbox-runs/{RUN_ID}")
    logs = client.get(f"/api/v1/sandbox-runs/{RUN_ID}/logs")

    assert history.status_code == 200
    assert history.json()["items"][0]["run_id"] == str(RUN_ID)
    assert detail.status_code == 200
    assert detail.json()["snapshot"]["evidence_content_hash"] == run.evidence_content_hash
    assert logs.status_code == 200
    stdout = logs.json()["logs"][0]["stdout"]
    assert stdout["storage_key"].startswith("sha256/")
    assert "content" not in stdout


def test_gate_7_api_approves_only_the_exact_current_operation() -> None:
    client = _client(_ExecutionQueryService(), _high_impact_service())

    created = client.post(
        f"/api/v1/projects/{PROJECT_ID}/high-impact-operations",
        json=_operation_body(),
    )
    assert created.status_code == 201
    version = created.json()["operation"]["version"]
    request_id = version["id"]
    expected = {
        "version_number": version["version_number"],
        "content_hash": version["content_hash"],
    }

    submitted = client.post(
        f"/api/v1/projects/{PROJECT_ID}/high-impact-operations/{request_id}/gate/submit",
        json=expected,
    )
    decided = client.post(
        f"/api/v1/projects/{PROJECT_ID}/high-impact-operations/{request_id}/gate/decision",
        json={**expected, "action": "APPROVE", "reason": "Owner reviewed the plan."},
    )
    readiness = client.get(
        f"/api/v1/projects/{PROJECT_ID}/high-impact-operations/{request_id}/gate"
    )
    events = client.get(
        f"/api/v1/projects/{PROJECT_ID}/high-impact-operations/{request_id}/gate/events"
    )

    assert submitted.status_code == 200
    assert submitted.json()["gate"]["status"] == "PENDING_APPROVAL"
    assert decided.status_code == 200
    assert decided.json()["gate"]["status"] == "APPROVED"
    assert readiness.json()["status"] == "APPROVED"
    assert [event["kind"] for event in events.json()] == ["SUBMIT", "APPROVE"]

    stale = client.post(
        f"/api/v1/projects/{PROJECT_ID}/high-impact-operations/{request_id}/gate/submit",
        json={"version_number": 2, "content_hash": "2" * 64},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["status"] == "STALE_REQUEST"


def test_execution_router_has_no_arbitrary_host_command_endpoint() -> None:
    query = _ExecutionQueryService()
    gate = _high_impact_service()
    application = create_app(
        ApplicationSettings(
            environment=RuntimeEnvironment.TEST,
            api_prefix="/api/v1",
        ),
        runtime=ApplicationRuntime(
            execution_query_service=query,
            high_impact_service=gate,
        ),
        auth_settings=AuthApiSettings(),
    )
    paths = application.openapi()["paths"]

    assert "/api/v1/execution-profiles" in paths
    assert "/api/v1/projects/{project_id}/sandbox-runs" in paths
    assert "/api/v1/projects/{project_id}/high-impact-operations" in paths
    assert all("command" not in path.casefold() for path in paths)
    assert application.state.execution_query_service is query
    assert application.state.high_impact_service is gate
