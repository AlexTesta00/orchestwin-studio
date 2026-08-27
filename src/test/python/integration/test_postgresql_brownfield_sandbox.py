"""PostgreSQL integration test for Sprint 07 brownfield, sandbox, and Gate 7 state."""

from __future__ import annotations

import asyncio
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from alembic.script import ScriptDirectory
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from orchestwin.api.sprint07_runtime import SqlAlchemyBrownfieldProjectQuery
from orchestwin.identity.application import AuthenticationStatus, LocalIdentityApplicationService
from orchestwin.identity.passwords import Argon2PasswordService
from orchestwin.identity.persistence import SqlAlchemyIdentityUnitOfWorkFactory
from orchestwin.identity.tokens import AccessTokenSettings, JwtAccessTokenService
from orchestwin.persistence import create_database_runtime, load_database_settings
from orchestwin.persistence.migrate import create_alembic_config
from orchestwin.projects.application import LocalProjectApplicationService
from orchestwin.projects.brownfield_application import (
    BrownfieldSourceIntakeStatus,
    LocalBrownfieldSourceIntakeService,
)
from orchestwin.projects.brownfield_intake import BrownfieldIntakeReference
from orchestwin.projects.brownfield_persistence import (
    SqlAlchemyBrownfieldIntakeUnitOfWorkFactory,
)
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.execution_capabilities import CapabilityNegotiationRequest
from orchestwin.projects.persistence import SqlAlchemyProjectUnitOfWorkFactory
from orchestwin.sandbox.archive_store import FileSystemSourceArchiveStore
from orchestwin.sandbox.builtin_execution_profiles import (
    create_builtin_execution_profile_registry,
)
from orchestwin.sandbox.command_plans import CommandNetworkMode
from orchestwin.sandbox.container_runtime import ContainerImageReference
from orchestwin.sandbox.evidence import (
    SandboxCommandEvidence,
    SandboxCommandStatus,
    SandboxLogReference,
    SandboxLogStream,
    SandboxRunEvidence,
    SandboxRunStatus,
)
from orchestwin.sandbox.execution_policy import SandboxResourceLimits
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionProfileReference,
    ExecutionTarget,
)
from orchestwin.sandbox.project_runs import ProjectSandboxRunEvidence
from orchestwin.sandbox.run_persistence import (
    SandboxRunStoreStatus,
    SqlAlchemySandboxRunUnitOfWorkFactory,
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
    SqlAlchemyHighImpactApprovalUnitOfWorkFactory,
)

pytestmark = pytest.mark.integration

BASE_TIME = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)
RUN_ID = UUID("00000000-0000-4000-8000-000000009201")
IMAGE = "example/web@sha256:" + "8" * 64
RESOURCES = SandboxResourceLimits(2.0, 4096, 256, 512)


async def truncate_application_data(runtime) -> None:
    """Reset owner-scoped data while preserving the migrated schema."""
    async with runtime.engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE users CASCADE"))


def create_source_archive(path: Path) -> None:
    """Create one deterministic archive with source and ignored generated content."""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("index.html", "<!doctype html><title>Sprint 07</title>")
        archive.writestr("assets/app.js", "document.body.dataset.ready = 'true';")
        archive.writestr("node_modules/example/index.js", "generated dependency")


def log_reference(stream: SandboxLogStream) -> SandboxLogReference:
    digest = "a" * 64 if stream is SandboxLogStream.STDOUT else "b" * 64
    return SandboxLogReference(
        stream=stream,
        sha256_digest=digest,
        size_bytes=9,
        storage_key=f"sha256/{digest[:2]}/{digest}",
    )


def project_sandbox_run(
    *,
    project_id: UUID,
    owner_user_id: UUID,
    intake_reference: BrownfieldIntakeReference,
) -> ProjectSandboxRunEvidence:
    """Create terminal evidence bound to the exact persisted brownfield intake."""
    started_at = BASE_TIME + timedelta(minutes=5)
    finished_at = started_at + timedelta(seconds=2)
    command = SandboxCommandEvidence(
        command_id="quality.tests",
        status=SandboxCommandStatus.SUCCEEDED,
        started_at=started_at,
        finished_at=finished_at,
        exit_code=0,
        stdout_log=log_reference(SandboxLogStream.STDOUT),
        stderr_log=log_reference(SandboxLogStream.STDERR),
        artifacts=(),
        output_parser_id="pytest.v1",
        failure_message=None,
    )
    evidence = SandboxRunEvidence(
        run_id=RUN_ID,
        plan_id="quality.plan",
        plan_content_hash="c" * 64,
        profile_id="custom.web",
        profile_version="1.0.0",
        image_reference=IMAGE,
        runtime_reference="fake.container.v1",
        status=SandboxRunStatus.SUCCEEDED,
        started_at=started_at,
        finished_at=finished_at,
        planned_command_ids=("quality.tests",),
        command_evidence=(command,),
        failure_message=None,
    )
    return ProjectSandboxRunEvidence(
        project_id=project_id,
        owner_user_id=owner_user_id,
        evidence=evidence,
        brownfield_intake_reference=intake_reference,
        recorded_at=finished_at + timedelta(seconds=1),
    )


def high_impact_request(project_id: UUID) -> HighImpactExecutionRequest:
    """Create an experimental controlled-network request that requires Gate 7."""
    return HighImpactExecutionRequest(
        project_id=project_id,
        operation_kind=HighImpactOperationKind.SANDBOX_EXECUTION,
        summary="Execute the exact owner-reviewed validation plan.",
        profile_reference=ExecutionProfileReference(
            profile_id="custom.web",
            profile_version="1.0.0",
            content_hash="d" * 64,
        ),
        capability_status=ExecutionCapabilityStatus.EXPERIMENTAL_LEVEL_D,
        command_plan_id="quality.plan",
        command_plan_content_hash="c" * 64,
        image_reference=ContainerImageReference(IMAGE),
        network_mode=CommandNetworkMode.CONTROLLED,
        secret_reference_ids=(),
        resources=RESOURCES,
        destructive_workspace_paths=(),
        requests_privileged_container=False,
        requests_docker_socket_mount=False,
        requests_host_filesystem_mount=False,
        requests_arbitrary_host_command=False,
    )


async def mutation_is_rejected(runtime, *, statement: str, identifier: UUID) -> bool:
    """Return whether an immutable Sprint 07 row rejected a direct update."""
    try:
        async with runtime.session_factory.begin() as session:
            await session.execute(text(statement), {"identifier": identifier})
    except DBAPIError:
        return True
    return False


async def run_integration_scenario(tmp_path: Path) -> None:
    """Exercise source intake, run evidence, Gate 7, ownership, and immutability."""
    database_settings = load_database_settings(env_file=None)
    runtime = create_database_runtime(database_settings)

    try:
        await truncate_application_data(runtime)
        identity = LocalIdentityApplicationService(
            unit_of_work_factory=SqlAlchemyIdentityUnitOfWorkFactory(runtime.session_factory),
            password_service=Argon2PasswordService(),
            access_token_service=JwtAccessTokenService(
                AccessTokenSettings(
                    jwt_secret=SecretStr(
                        "integration-test-jwt-secret-with-more-than-32-characters"
                    ),
                    access_token_leeway_seconds=0,
                    _env_file=None,
                )
            ),
        )
        projects = LocalProjectApplicationService(
            unit_of_work_factory=SqlAlchemyProjectUnitOfWorkFactory(runtime.session_factory)
        )

        owner_result = await identity.register(
            email="sprint-seven-owner@example.com",
            password="correct horse battery staple",
        )
        foreign_result = await identity.register(
            email="sprint-seven-foreign@example.com",
            password="another correct battery staple",
        )
        assert owner_result.status is AuthenticationStatus.AUTHENTICATED
        assert foreign_result.status is AuthenticationStatus.AUTHENTICATED
        assert owner_result.authenticated is not None
        assert foreign_result.authenticated is not None
        owner = owner_result.authenticated.user
        foreign = foreign_result.authenticated.user

        project = await projects.create(
            owner_user_id=owner.id,
            display_name="Sprint 07 PostgreSQL fixture",
            mode=ProjectMode.BROWNFIELD_ASSESSMENT,
        )
        archive_path = tmp_path / "source.zip"
        create_source_archive(archive_path)
        registry = create_builtin_execution_profile_registry()
        intake_factory = SqlAlchemyBrownfieldIntakeUnitOfWorkFactory(runtime.session_factory)
        intake_service = LocalBrownfieldSourceIntakeService(
            projects=SqlAlchemyBrownfieldProjectQuery(runtime.session_factory),
            archive_store=FileSystemSourceArchiveStore(tmp_path / "archives"),
            profile_registry=registry,
            uow_factory=intake_factory,
            workspace_root=tmp_path / "workspaces",
        )
        capability_request = CapabilityNegotiationRequest(
            requested_target=ExecutionTarget.WEB_STATIC,
            available_runners=(),
            approved_experimental_profiles=(),
        )

        created = await intake_service.ingest(
            owner_user_id=owner.id,
            project_id=project.id,
            archive_path=archive_path,
            capability_request=capability_request,
        )
        repeated = await intake_service.ingest(
            owner_user_id=owner.id,
            project_id=project.id,
            archive_path=archive_path,
            capability_request=capability_request,
        )
        assert created.status is BrownfieldSourceIntakeStatus.CREATED
        assert repeated.status is BrownfieldSourceIntakeStatus.REUSED
        assert created.version is not None
        assert repeated.version == created.version

        async with intake_factory(owner_user_id=owner.id) as unit:
            owner_history = await unit.intakes.history(project_id=project.id)
        async with intake_factory(owner_user_id=foreign.id) as unit:
            foreign_history = await unit.intakes.history(project_id=project.id)
        assert owner_history == (created.version,)
        assert foreign_history == ()

        intake_reference = BrownfieldIntakeReference(
            intake_id=created.version.id,
            project_id=project.id,
            version_number=created.version.version_number,
            content_hash=created.version.content_hash,
        )
        sandbox_run = project_sandbox_run(
            project_id=project.id,
            owner_user_id=owner.id,
            intake_reference=intake_reference,
        )
        sandbox_factory = SqlAlchemySandboxRunUnitOfWorkFactory(runtime.session_factory)
        async with sandbox_factory(owner_user_id=owner.id) as unit:
            stored = await unit.runs.store(sandbox_run)
            await unit.commit()
        async with sandbox_factory(owner_user_id=owner.id) as unit:
            reused = await unit.runs.store(sandbox_run)
            await unit.commit()
        async with sandbox_factory(owner_user_id=foreign.id) as unit:
            foreign_run = await unit.runs.get(run_id=RUN_ID)
        assert stored.status is SandboxRunStoreStatus.STORED
        assert reused.status is SandboxRunStoreStatus.ALREADY_PRESENT
        assert stored.run is not None
        assert foreign_run is None
        assert "content" not in stored.run.command_results[0].stdout_log

        approval = LocalHighImpactApprovalService(
            unit_of_work_factory=SqlAlchemyHighImpactApprovalUnitOfWorkFactory(
                runtime.session_factory
            ),
            policy=HighImpactOperationPolicy(
                approved_image_references=frozenset({IMAGE}),
                baseline_resources=RESOURCES,
                protected_workspace_components=frozenset({".git", ".orchestwin", ".ssh"}),
            ),
        )
        operation = await approval.create_request(
            project_id=project.id,
            owner_user_id=owner.id,
            request=high_impact_request(project.id),
        )
        assert operation.status is HighImpactRequestCreateStatus.CREATED
        assert operation.operation is not None
        reference = operation.operation.version.reference
        submitted = await approval.submit_gate(
            project_id=project.id,
            owner_user_id=owner.id,
            expected_reference=reference,
        )
        decided = await approval.decide_gate(
            project_id=project.id,
            owner_user_id=owner.id,
            expected_reference=reference,
            action=HumanGateAction.APPROVE,
            reason="The exact reviewed plan is accepted.",
        )
        readiness = await approval.readiness(
            project_id=project.id,
            owner_user_id=owner.id,
        )
        foreign_readiness = await approval.readiness(
            project_id=project.id,
            owner_user_id=foreign.id,
        )
        events = await approval.gate_events(
            project_id=project.id,
            owner_user_id=owner.id,
            gate_id=decided.gate.id if decided.gate is not None else UUID(int=0),
        )
        assert submitted.status is HighImpactGateSubmissionStatus.SUBMITTED
        assert decided.status is HighImpactGateDecisionStatus.APPLIED
        assert decided.gate is not None
        assert decided.gate.status is HumanGateStatus.APPROVED
        assert readiness.status is HighImpactApprovalReadiness.APPROVED
        assert foreign_readiness.status is HighImpactApprovalReadiness.REQUEST_NOT_FOUND
        assert tuple(event.kind.value for event in events) == ("SUBMIT", "APPROVE")

        assert await mutation_is_rejected(
            runtime,
            statement=(
                "UPDATE brownfield_intake_versions SET content_hash = repeat('0', 64) "
                "WHERE id = :identifier"
            ),
            identifier=created.version.id,
        )
        assert await mutation_is_rejected(
            runtime,
            statement=(
                "UPDATE sandbox_runs SET evidence_content_hash = repeat('0', 64) "
                "WHERE run_id = :identifier"
            ),
            identifier=RUN_ID,
        )
        assert await mutation_is_rejected(
            runtime,
            statement=(
                "UPDATE high_impact_operation_versions "
                "SET content_hash = repeat('0', 64) WHERE id = :identifier"
            ),
            identifier=operation.operation.version.id,
        )

        async with runtime.engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        scripts = ScriptDirectory.from_config(
            create_alembic_config(database_settings.url.get_secret_value())
        )
        current_head = scripts.get_current_head()
        assert current_head is not None
        assert revision == current_head
        assert "0019_high_impact_gate_type" in {
            script.revision for script in scripts.walk_revisions(base="base", head=current_head)
        }
    finally:
        await truncate_application_data(runtime)
        await runtime.dispose()


def test_postgresql_brownfield_sandbox_and_gate_7_integration(tmp_path: Path) -> None:
    """Verify the complete Sprint 07 PostgreSQL persistence boundary."""
    asyncio.run(
        run_integration_scenario(tmp_path),
        loop_factory=asyncio.SelectorEventLoop,
    )
