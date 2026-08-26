"""Tests for exact Gate 7 high-impact operation approval."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from orchestwin.projects.domain import ProjectMode, create_project
from orchestwin.sandbox.command_plans import CommandNetworkMode
from orchestwin.sandbox.container_runtime import ContainerImageReference
from orchestwin.sandbox.execution_policy import SandboxResourceLimits
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionProfileReference,
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

PROJECT_ID = UUID("00000000-0000-4000-8000-000000007801")
OWNER_ID = UUID("00000000-0000-4000-8000-000000007802")
BASE_TIME = datetime(2026, 8, 25, 14, 0, tzinfo=UTC)
IMAGE = "example/web@sha256:" + "a" * 64
RESOURCES = SandboxResourceLimits(2.0, 4096, 256, 512)


def _request(
    *,
    network_mode: CommandNetworkMode = CommandNetworkMode.CONTROLLED,
    capability_status: ExecutionCapabilityStatus = (ExecutionCapabilityStatus.EXPERIMENTAL_LEVEL_D),
    summary: str = "Execute the owner-reviewed web validation plan.",
) -> HighImpactExecutionRequest:
    return HighImpactExecutionRequest(
        project_id=PROJECT_ID,
        operation_kind=HighImpactOperationKind.SANDBOX_EXECUTION,
        summary=summary,
        profile_reference=ExecutionProfileReference(
            profile_id="custom.web",
            profile_version="1.0.0",
            content_hash="b" * 64,
        ),
        capability_status=capability_status,
        command_plan_id="web.validation",
        command_plan_content_hash="c" * 64,
        image_reference=ContainerImageReference(IMAGE),
        network_mode=network_mode,
        secret_reference_ids=(),
        resources=RESOURCES,
        destructive_workspace_paths=(),
        requests_privileged_container=False,
        requests_docker_socket_mount=False,
        requests_host_filesystem_mount=False,
        requests_arbitrary_host_command=False,
    )


def _service() -> LocalHighImpactApprovalService:
    project = create_project(
        owner_user_id=OWNER_ID,
        display_name="Gate 7 fixture",
        mode=ProjectMode.BROWNFIELD_ASSESSMENT,
        project_id=PROJECT_ID,
        created_at=BASE_TIME,
    )
    identifiers: Iterator[UUID] = iter(UUID(int=value) for value in range(7803, 7850))
    times: Iterator[datetime] = iter(
        BASE_TIME + timedelta(seconds=value) for value in range(1, 100)
    )
    policy = HighImpactOperationPolicy(
        approved_image_references=frozenset({IMAGE}),
        baseline_resources=RESOURCES,
        protected_workspace_components=frozenset({".git", ".orchestwin", ".ssh"}),
    )
    return LocalHighImpactApprovalService(
        unit_of_work_factory=InMemoryHighImpactApprovalUnitOfWorkFactory(
            projects={PROJECT_ID: project}
        ),
        policy=policy,
        uuid_factory=lambda: next(identifiers),
        clock=lambda: next(times),
    )


def test_gate_7_approves_the_exact_current_request_and_records_events() -> None:
    service = _service()

    created = asyncio.run(
        service.create_request(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            request=_request(),
        )
    )
    assert created.status is HighImpactRequestCreateStatus.CREATED
    assert created.operation is not None

    submitted = asyncio.run(
        service.submit_gate(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            expected_reference=created.operation.version.reference,
        )
    )
    assert submitted.status is HighImpactGateSubmissionStatus.SUBMITTED
    assert submitted.gate is not None
    assert submitted.gate.status is HumanGateStatus.PENDING_APPROVAL

    decided = asyncio.run(
        service.decide_gate(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            expected_reference=created.operation.version.reference,
            action=HumanGateAction.APPROVE,
        )
    )
    assert decided.status is HighImpactGateDecisionStatus.APPLIED
    assert decided.gate is not None
    assert decided.gate.status is HumanGateStatus.APPROVED

    readiness = asyncio.run(service.readiness(project_id=PROJECT_ID, owner_user_id=OWNER_ID))
    events = asyncio.run(
        service.gate_events(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            gate_id=decided.gate.id,
        )
    )
    assert readiness.status is HighImpactApprovalReadiness.APPROVED
    assert tuple(event.kind.value for event in events) == ("SUBMIT", "APPROVE")


def test_new_request_version_stales_prior_approval_and_rejects_old_reference() -> None:
    service = _service()
    first = asyncio.run(
        service.create_request(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            request=_request(),
        )
    )
    assert first.operation is not None
    asyncio.run(
        service.submit_gate(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            expected_reference=first.operation.version.reference,
        )
    )
    asyncio.run(
        service.decide_gate(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            expected_reference=first.operation.version.reference,
            action=HumanGateAction.APPROVE,
        )
    )

    second = asyncio.run(
        service.create_request(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            request=_request(summary="Execute the revised owner-reviewed plan."),
        )
    )
    assert second.operation is not None
    assert second.operation.version.version_number == 2
    stale = asyncio.run(
        service.submit_gate(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            expected_reference=first.operation.version.reference,
        )
    )
    current_gate = asyncio.run(service.current_gate(project_id=PROJECT_ID, owner_user_id=OWNER_ID))
    assert stale.status is HighImpactGateSubmissionStatus.STALE_REQUEST
    assert current_gate is not None
    assert current_gate.status is HumanGateStatus.STALE


def test_forbidden_and_baseline_requests_cannot_be_approved_by_gate_7() -> None:
    forbidden_service = _service()
    forbidden_request = replace(_request(), requests_docker_socket_mount=True)
    forbidden = asyncio.run(
        forbidden_service.create_request(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            request=forbidden_request,
        )
    )
    assert forbidden.operation is not None
    forbidden_submission = asyncio.run(
        forbidden_service.submit_gate(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            expected_reference=forbidden.operation.version.reference,
        )
    )
    assert forbidden_submission.status is HighImpactGateSubmissionStatus.FORBIDDEN_BY_POLICY

    baseline_service = _service()
    baseline = asyncio.run(
        baseline_service.create_request(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            request=_request(
                network_mode=CommandNetworkMode.DISABLED,
                capability_status=ExecutionCapabilityStatus.VALIDATED_LEVEL_D,
            ),
        )
    )
    assert baseline.operation is not None
    baseline_submission = asyncio.run(
        baseline_service.submit_gate(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            expected_reference=baseline.operation.version.reference,
        )
    )
    assert baseline_submission.status is (HighImpactGateSubmissionStatus.APPROVAL_NOT_REQUIRED)
