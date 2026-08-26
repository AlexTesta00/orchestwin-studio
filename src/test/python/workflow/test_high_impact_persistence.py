"""Tests for high-impact operation snapshot persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.sandbox.command_plans import CommandNetworkMode
from orchestwin.sandbox.container_runtime import ContainerImageReference
from orchestwin.sandbox.execution_policy import SandboxResourceLimits
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionProfileReference,
)
from orchestwin.workflow.high_impact import (
    HighImpactExecutionRequest,
    HighImpactOperationKind,
    HighImpactOperationRequestVersion,
    classify_high_impact_operation,
)
from orchestwin.workflow.high_impact_persistence import (
    PersistedHighImpactOperation,
    high_impact_to_record,
    persisted_high_impact_from_record,
)


def _operation() -> PersistedHighImpactOperation:
    project_id = UUID(int=7901)
    owner_id = UUID(int=7902)
    request = HighImpactExecutionRequest(
        project_id=project_id,
        operation_kind=HighImpactOperationKind.SANDBOX_EXECUTION,
        summary="Run the governed experimental profile.",
        profile_reference=ExecutionProfileReference(
            "custom.jvm",
            "1.0.0",
            "a" * 64,
        ),
        capability_status=ExecutionCapabilityStatus.EXPERIMENTAL_LEVEL_D,
        command_plan_id="jvm.tests",
        command_plan_content_hash="b" * 64,
        image_reference=ContainerImageReference("example/jvm@sha256:" + "c" * 64),
        network_mode=CommandNetworkMode.CONTROLLED,
        secret_reference_ids=("provider.api",),
        resources=SandboxResourceLimits(2.0, 4096, 256, 512),
        destructive_workspace_paths=(),
        requests_privileged_container=False,
        requests_docker_socket_mount=False,
        requests_host_filesystem_mount=False,
        requests_arbitrary_host_command=False,
    )
    version = HighImpactOperationRequestVersion(
        id=UUID(int=7903),
        project_id=project_id,
        version_number=1,
        based_on_version_number=None,
        request=request,
        content_hash=request.content_hash,
        created_by_user_id=owner_id,
        created_at=datetime(2026, 8, 25, 15, 0, tzinfo=UTC),
    )
    return PersistedHighImpactOperation(version, classify_high_impact_operation(version))


def test_persisted_operation_round_trips_canonical_snapshots() -> None:
    operation = _operation()
    record = high_impact_to_record(operation)

    restored = persisted_high_impact_from_record(record)

    assert restored == operation
    assert restored.to_snapshot() == operation.to_snapshot()


def test_persisted_operation_rejects_tampered_projection() -> None:
    record = high_impact_to_record(_operation())
    record["content_hash"] = "f" * 64

    with pytest.raises(ValueError, match="hash projection"):
        persisted_high_impact_from_record(record)
