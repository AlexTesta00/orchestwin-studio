"""Sprint 07 acceptance journey for governed brownfield intake and sandbox evidence."""

from __future__ import annotations

import asyncio
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Self
from uuid import UUID

from orchestwin.projects.brownfield_application import (
    BrownfieldSourceIntakeStatus,
    LocalBrownfieldSourceIntakeService,
)
from orchestwin.projects.brownfield_intake import BrownfieldIntakeReference
from orchestwin.projects.brownfield_persistence import (
    BrownfieldIntakeRepository,
    InMemoryBrownfieldIntakeRepository,
)
from orchestwin.projects.domain import Project, ProjectMode, create_project
from orchestwin.projects.execution_capabilities import (
    CapabilityNegotiationRequest,
    CapabilityNegotiationStatus,
)
from orchestwin.sandbox.archive_store import FileSystemSourceArchiveStore
from orchestwin.sandbox.builtin_execution_profiles import (
    create_builtin_execution_profile_registry,
)
from orchestwin.sandbox.command_plans import (
    CommandNetworkMode,
    CommandPlan,
    StructuredCommand,
)
from orchestwin.sandbox.container_runtime import (
    ContainerExecutionRequest,
    ContainerImageReference,
)
from orchestwin.sandbox.execution_policy import (
    DEFAULT_SANDBOX_EXECUTION_POLICY,
    DEFAULT_SANDBOX_RESOURCE_LIMITS,
    validate_sandbox_plan,
)
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionProfileReference,
    ExecutionTarget,
)
from orchestwin.sandbox.fake_container import (
    FakeArtifactOutput,
    FakeCommandOutcome,
    FakeCommandOutcomeKind,
    FakeContainerRuntimeAdapter,
)
from orchestwin.sandbox.project_runs import ProjectSandboxRunEvidence
from orchestwin.sandbox.run_persistence import (
    InMemorySandboxRunRepository,
    SandboxRunStoreStatus,
)
from orchestwin.workflow.gates import HumanGateAction, HumanGateStatus
from orchestwin.workflow.high_impact import (
    HighImpactExecutionRequest,
    HighImpactOperationKind,
    HighImpactOperationPolicy,
)
from orchestwin.workflow.high_impact_gate import (
    HighImpactApprovalReadiness,
    HighImpactGateDecisionStatus,
    HighImpactGateSubmissionStatus,
    HighImpactRequestCreateStatus,
    LocalHighImpactApprovalService,
)
from orchestwin.workflow.high_impact_persistence import (
    InMemoryHighImpactApprovalUnitOfWorkFactory,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000009301")
OWNER_ID = UUID("00000000-0000-4000-8000-000000009302")
RUN_ID = UUID("00000000-0000-4000-8000-000000009303")
BASE_TIME = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)
IMAGE = "example/web@sha256:" + "9" * 64


class ProjectQuery:
    """Owner-scoped deterministic project lookup for the acceptance journey."""

    def __init__(self, project: Project) -> None:
        self._project = project

    async def get_owned(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> Project | None:
        if (
            self._project.id != project_id
            or self._project.owner_user_id != owner_user_id
            or self._project.archived_at is not None
        ):
            return None
        return self._project


class IntakeUnitOfWork:
    """No-op transaction around one in-memory intake repository."""

    def __init__(self, repository: BrownfieldIntakeRepository) -> None:
        self.intakes = repository
        self.committed = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        return None


class IntakeUnitOfWorkFactory:
    """Return owner-bound units over one shared intake repository."""

    def __init__(self, repository: BrownfieldIntakeRepository) -> None:
        self._repository = repository

    def __call__(self, *, owner_user_id: UUID) -> IntakeUnitOfWork:
        assert owner_user_id == OWNER_ID
        return IntakeUnitOfWork(self._repository)


def create_archive(path: Path) -> Path:
    """Create a small static project plus one generated directory to ignore."""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("index.html", "<!doctype html><title>Governed fixture</title>")
        archive.writestr("assets/site.css", "body { font-family: sans-serif; }")
        archive.writestr("node_modules/pkg/index.js", "generated dependency")
    return path


def experimental_request(
    *,
    summary: str,
    plan_content_hash: str,
    docker_socket: bool = False,
) -> HighImpactExecutionRequest:
    """Describe one exact custom-profile execution without a shell string."""
    return HighImpactExecutionRequest(
        project_id=PROJECT_ID,
        operation_kind=HighImpactOperationKind.SANDBOX_EXECUTION,
        summary=summary,
        profile_reference=ExecutionProfileReference(
            profile_id="custom.web",
            profile_version="1.0.0",
            content_hash="a" * 64,
        ),
        capability_status=ExecutionCapabilityStatus.EXPERIMENTAL_LEVEL_D,
        command_plan_id="quality.plan",
        command_plan_content_hash=plan_content_hash,
        image_reference=ContainerImageReference(IMAGE),
        network_mode=CommandNetworkMode.CONTROLLED,
        secret_reference_ids=(),
        resources=DEFAULT_SANDBOX_RESOURCE_LIMITS,
        destructive_workspace_paths=(),
        requests_privileged_container=False,
        requests_docker_socket_mount=docker_socket,
        requests_host_filesystem_mount=False,
        requests_arbitrary_host_command=False,
    )


def command_plan() -> CommandPlan:
    """Return a shell-free validation plan accepted by the deterministic policy."""
    command = StructuredCommand(
        command_id="quality.tests",
        executable="pytest",
        arguments=("-q",),
        working_directory=".",
        allowed_environment_keys=frozenset({"CI"}),
        secret_references=frozenset(),
        timeout_seconds=60,
        network_mode=CommandNetworkMode.DISABLED,
        expected_exit_codes=frozenset({0}),
        output_parser_id="pytest.v1",
        artifact_patterns=frozenset({"reports/tests.txt"}),
    )
    return CommandPlan(
        plan_id="quality.plan",
        profile_id="custom.web",
        profile_version="1.0.0",
        commands=(command,),
    )


async def governed_journey(tmp_path: Path) -> None:
    """Run the complete deterministic Sprint 07 acceptance path."""
    project = create_project(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        display_name="Governed brownfield fixture",
        mode=ProjectMode.BROWNFIELD_ASSESSMENT,
        created_at=BASE_TIME,
    )
    intake_repository = InMemoryBrownfieldIntakeRepository(
        owner_user_id=OWNER_ID,
        projects={PROJECT_ID: project},
    )
    intake_service = LocalBrownfieldSourceIntakeService(
        projects=ProjectQuery(project),
        archive_store=FileSystemSourceArchiveStore(tmp_path / "archive-store"),
        profile_registry=create_builtin_execution_profile_registry(),
        uow_factory=IntakeUnitOfWorkFactory(intake_repository),
        workspace_root=tmp_path / "workspaces",
        clock=lambda: BASE_TIME,
    )
    intake_result = await intake_service.ingest(
        owner_user_id=OWNER_ID,
        project_id=PROJECT_ID,
        archive_path=create_archive(tmp_path / "source.zip"),
        capability_request=CapabilityNegotiationRequest(
            requested_target=ExecutionTarget.WEB_STATIC,
            available_runners=(),
            approved_experimental_profiles=(),
        ),
    )
    assert intake_result.status is BrownfieldSourceIntakeStatus.CREATED
    assert intake_result.version is not None
    assert intake_result.version.capability_status is (
        CapabilityNegotiationStatus.DESIGN_ONLY_LEVEL_C_SELECTED
    )
    assert intake_result.version.effective_capability_status is (
        ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
    )
    inventory = intake_result.version.snapshot["inventory"]
    assert isinstance(inventory, dict)
    inventory_entries = inventory["entries"]
    assert isinstance(inventory_entries, list)
    assert any(
        isinstance(entry, dict)
        and entry.get("normalized_path") == "node_modules/pkg/index.js"
        and entry.get("disposition") == "IGNORE"
        for entry in inventory_entries
    )
    assert list((tmp_path / "workspaces").iterdir()) == []

    plan = command_plan()
    identifiers: Iterator[UUID] = iter(UUID(int=value) for value in range(9304, 9400))
    times: Iterator[datetime] = iter(
        BASE_TIME + timedelta(seconds=value) for value in range(1, 200)
    )
    gate_service = LocalHighImpactApprovalService(
        unit_of_work_factory=InMemoryHighImpactApprovalUnitOfWorkFactory(
            projects={PROJECT_ID: project}
        ),
        policy=HighImpactOperationPolicy(
            approved_image_references=frozenset({IMAGE}),
            baseline_resources=DEFAULT_SANDBOX_RESOURCE_LIMITS,
            protected_workspace_components=frozenset({".git", ".orchestwin", ".ssh"}),
        ),
        uuid_factory=lambda: next(identifiers),
        clock=lambda: next(times),
    )
    created = await gate_service.create_request(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        request=experimental_request(
            summary="Execute the owner-reviewed experimental validation plan.",
            plan_content_hash=plan.content_hash,
        ),
    )
    assert created.status is HighImpactRequestCreateStatus.CREATED
    assert created.operation is not None
    reference = created.operation.version.reference
    submitted = await gate_service.submit_gate(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        expected_reference=reference,
    )
    decided = await gate_service.decide_gate(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        expected_reference=reference,
        action=HumanGateAction.APPROVE,
        reason="The exact experimental plan is accepted for this fixture.",
    )
    assert submitted.status is HighImpactGateSubmissionStatus.SUBMITTED
    assert decided.status is HighImpactGateDecisionStatus.APPLIED
    assert decided.gate is not None
    assert decided.gate.status is HumanGateStatus.APPROVED
    assert (
        await gate_service.readiness(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    ).status is HighImpactApprovalReadiness.APPROVED

    policy_report = validate_sandbox_plan(plan)
    assert policy_report.is_accepted
    workspace = tmp_path / "runtime-workspace"
    workspace.mkdir()
    runtime = FakeContainerRuntimeAdapter(
        {
            "quality.tests": FakeCommandOutcome(
                kind=FakeCommandOutcomeKind.PROCESS_EXIT,
                exit_code=0,
                stdout=b"1 passed\n",
                stderr=b"",
                duration=timedelta(seconds=1),
                artifacts=(
                    FakeArtifactOutput(
                        normalized_path="reports/tests.txt",
                        content=b"1 passed\n",
                        media_type="text/plain",
                    ),
                ),
                failure_message=None,
            )
        },
        started_at=BASE_TIME + timedelta(minutes=1),
    )
    evidence = await runtime.execute(
        ContainerExecutionRequest(
            run_id=RUN_ID,
            plan=plan,
            execution_policy=DEFAULT_SANDBOX_EXECUTION_POLICY,
            policy_report=policy_report,
            image=ContainerImageReference(IMAGE),
            workspace_path=workspace.resolve(),
            environment_variables=(),
        )
    )
    intake_reference = BrownfieldIntakeReference(
        intake_id=intake_result.version.id,
        project_id=PROJECT_ID,
        version_number=intake_result.version.version_number,
        content_hash=intake_result.version.content_hash,
    )
    project_run = ProjectSandboxRunEvidence(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        evidence=evidence,
        brownfield_intake_reference=intake_reference,
        recorded_at=evidence.finished_at + timedelta(seconds=1),
    )
    run_repository = InMemorySandboxRunRepository(
        owner_user_id=OWNER_ID,
        projects={PROJECT_ID: project},
        intake_references=(intake_reference,),
    )
    stored = await run_repository.store(project_run)
    assert stored.status is SandboxRunStoreStatus.STORED
    assert stored.run is not None
    stdout = evidence.command_evidence[0].stdout_log
    assert runtime.evidence_store.read(stdout.storage_key) == b"1 passed\n"
    assert stored.run.command_results[0].artifacts[0]["normalized_path"] == ("reports/tests.txt")

    revised = await gate_service.create_request(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        request=experimental_request(
            summary="Execute the revised owner-reviewed experimental validation plan.",
            plan_content_hash=plan.content_hash,
        ),
    )
    assert revised.operation is not None
    assert revised.operation.version.version_number == 2
    stale = await gate_service.submit_gate(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        expected_reference=reference,
    )
    assert stale.status is HighImpactGateSubmissionStatus.STALE_REQUEST
    current_gate = await gate_service.current_gate(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
    )
    assert current_gate is not None
    assert current_gate.status is HumanGateStatus.STALE

    forbidden = await gate_service.create_request(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        request=experimental_request(
            summary="Attempt a prohibited Docker socket operation.",
            plan_content_hash=plan.content_hash,
            docker_socket=True,
        ),
    )
    assert forbidden.operation is not None
    forbidden_submission = await gate_service.submit_gate(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        expected_reference=forbidden.operation.version.reference,
    )
    assert forbidden_submission.status is (HighImpactGateSubmissionStatus.FORBIDDEN_BY_POLICY)


def test_governed_brownfield_intake_sandbox_and_gate_7_journey(tmp_path: Path) -> None:
    """Verify safe intake, honest capability, exact approval, and raw evidence."""
    asyncio.run(governed_journey(tmp_path))
