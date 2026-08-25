"""Tests for deterministic high-impact execution-request classification."""

from __future__ import annotations

from dataclasses import replace
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
    HighImpactClassification,
    HighImpactExecutionRequest,
    HighImpactOperationKind,
    HighImpactOperationPolicy,
    HighImpactOperationRequestVersion,
    HighImpactReasonCode,
    classify_high_impact_operation,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000007701")
OWNER_ID = UUID("00000000-0000-4000-8000-000000007702")
REQUEST_ID = UUID("00000000-0000-4000-8000-000000007703")
CREATED_AT = datetime(2026, 8, 25, 13, 0, tzinfo=UTC)
APPROVED_IMAGE = "example/web@sha256:" + "a" * 64
UNAPPROVED_IMAGE = "example/custom@sha256:" + "b" * 64
BASELINE_RESOURCES = SandboxResourceLimits(
    cpu_count=2.0,
    memory_mib=4096,
    pids_limit=256,
    writable_tmpfs_mib=512,
)


def _profile_reference() -> ExecutionProfileReference:
    return ExecutionProfileReference(
        profile_id="WEB_STATIC",
        profile_version="1.0.0",
        content_hash="c" * 64,
    )


def _policy(*, approved_images: frozenset[str] | None = None) -> HighImpactOperationPolicy:
    return HighImpactOperationPolicy(
        approved_image_references=(
            frozenset({APPROVED_IMAGE}) if approved_images is None else approved_images
        ),
        baseline_resources=BASELINE_RESOURCES,
        protected_workspace_components=frozenset({".git", ".orchestwin", ".ssh"}),
    )


def _request(**changes) -> HighImpactExecutionRequest:
    values = {
        "project_id": PROJECT_ID,
        "operation_kind": HighImpactOperationKind.SANDBOX_EXECUTION,
        "summary": "Execute the approved static web validation plan.",
        "profile_reference": _profile_reference(),
        "capability_status": ExecutionCapabilityStatus.VALIDATED_LEVEL_D,
        "command_plan_id": "web.validation",
        "command_plan_content_hash": "d" * 64,
        "image_reference": ContainerImageReference(APPROVED_IMAGE),
        "network_mode": CommandNetworkMode.DISABLED,
        "secret_reference_ids": (),
        "resources": BASELINE_RESOURCES,
        "destructive_workspace_paths": (),
        "requests_privileged_container": False,
        "requests_docker_socket_mount": False,
        "requests_host_filesystem_mount": False,
        "requests_arbitrary_host_command": False,
    }
    values.update(changes)
    return HighImpactExecutionRequest(**values)


def _version(
    request: HighImpactExecutionRequest | None = None,
) -> HighImpactOperationRequestVersion:
    payload = request or _request()
    return HighImpactOperationRequestVersion(
        id=REQUEST_ID,
        project_id=PROJECT_ID,
        version_number=1,
        based_on_version_number=None,
        request=payload,
        content_hash=payload.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )


def test_validated_baseline_execution_is_allowed_without_gate_7() -> None:
    """Avoid approval ceremony when every deterministic safety boundary is satisfied."""
    result = classify_high_impact_operation(_version(), policy=_policy())

    assert result.classification is HighImpactClassification.ALLOWED_WITHOUT_APPROVAL
    assert result.reasons == ()
    assert result.requires_owner_approval is False
    assert result.request_reference == _version().reference


def test_experimental_profile_requires_exact_owner_approval() -> None:
    """Keep experimental Level D distinct from validated execution capability."""
    request = _request(
        capability_status=ExecutionCapabilityStatus.EXPERIMENTAL_LEVEL_D,
    )

    result = classify_high_impact_operation(_version(request), policy=_policy())

    assert result.classification is HighImpactClassification.REQUIRES_OWNER_APPROVAL
    assert result.requires_owner_approval is True
    assert tuple(reason.code for reason in result.reasons) == (
        HighImpactReasonCode.EXPERIMENTAL_PROFILE,
    )


def test_network_secrets_image_resources_and_destructive_change_require_approval() -> None:
    """Expose every independent high-impact dimension in canonical audit order."""
    request = _request(
        image_reference=ContainerImageReference(UNAPPROVED_IMAGE),
        network_mode=CommandNetworkMode.CONTROLLED,
        secret_reference_ids=("provider.api",),
        resources=SandboxResourceLimits(
            cpu_count=3.0,
            memory_mib=6144,
            pids_limit=300,
            writable_tmpfs_mib=1024,
        ),
        destructive_workspace_paths=("dist/generated",),
    )

    result = classify_high_impact_operation(_version(request), policy=_policy())

    assert result.classification is HighImpactClassification.REQUIRES_OWNER_APPROVAL
    assert {reason.code for reason in result.reasons} == {
        HighImpactReasonCode.CONTROLLED_NETWORK,
        HighImpactReasonCode.SECRET_ACCESS,
        HighImpactReasonCode.UNAPPROVED_IMAGE,
        HighImpactReasonCode.RESOURCE_LIMIT_INCREASE,
        HighImpactReasonCode.DESTRUCTIVE_WORKSPACE_CHANGE,
    }
    assert result.reasons == tuple(sorted(result.reasons, key=lambda reason: reason.code.value))


def test_forbidden_host_boundaries_override_approvable_risks() -> None:
    """Never let Gate 7 authorize capabilities prohibited by the constitution."""
    request = _request(
        network_mode=CommandNetworkMode.CONTROLLED,
        requests_privileged_container=True,
        requests_docker_socket_mount=True,
        requests_host_filesystem_mount=True,
        requests_arbitrary_host_command=True,
    )

    result = classify_high_impact_operation(_version(request), policy=_policy())

    assert result.classification is HighImpactClassification.FORBIDDEN_BY_POLICY
    assert {reason.code for reason in result.reasons} == {
        HighImpactReasonCode.PRIVILEGED_CONTAINER,
        HighImpactReasonCode.DOCKER_SOCKET_MOUNT,
        HighImpactReasonCode.HOST_FILESYSTEM_MOUNT,
        HighImpactReasonCode.ARBITRARY_HOST_COMMAND,
    }
    assert HighImpactReasonCode.CONTROLLED_NETWORK not in {reason.code for reason in result.reasons}


def test_design_only_execution_and_protected_path_mutation_are_forbidden() -> None:
    """Reject false Level D claims and destructive changes to trusted metadata."""
    request = _request(
        capability_status=ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C,
        destructive_workspace_paths=(".git/config",),
    )

    result = classify_high_impact_operation(_version(request), policy=_policy())

    assert result.classification is HighImpactClassification.FORBIDDEN_BY_POLICY
    assert {reason.code for reason in result.reasons} == {
        HighImpactReasonCode.DESIGN_ONLY_EXECUTION,
        HighImpactReasonCode.PROTECTED_WORKSPACE_PATH,
    }


def test_request_and_policy_hashes_cover_every_approval_relevant_value() -> None:
    """Make any changed plan, resource, image, or policy invalidate prior approval."""
    request = _request()
    version = _version(request)
    changed_request = replace(request, network_mode=CommandNetworkMode.CONTROLLED)
    changed_policy = _policy(approved_images=frozenset({APPROVED_IMAGE, UNAPPROVED_IMAGE}))

    assert changed_request.content_hash != request.content_hash
    assert _policy().content_hash != changed_policy.content_hash
    assert version.reference.content_hash == request.content_hash
    assert classify_high_impact_operation(version, policy=_policy()).policy_content_hash == (
        _policy().content_hash
    )


def test_request_version_rejects_stale_hash_lineage_and_cross_project_payload() -> None:
    """Prepare Gate 7 to reject decisions against another version or project."""
    version = _version()

    with pytest.raises(ValueError, match="hash"):
        replace(version, content_hash="f" * 64)
    with pytest.raises(ValueError, match="predecessor"):
        replace(version, based_on_version_number=1)
    with pytest.raises(ValueError, match="another project"):
        replace(version, project_id=UUID(int=999))


def test_request_rejects_partial_plan_noncanonical_collections_and_host_paths() -> None:
    """Keep the approval artifact structured before policy classification."""
    with pytest.raises(ValueError, match="ID and hash"):
        _request(command_plan_content_hash=None)
    with pytest.raises(ValueError, match="canonical"):
        _request(secret_reference_ids=("z.secret", "a.secret"))
    with pytest.raises(ValueError, match="inside the workspace"):
        _request(destructive_workspace_paths=("../outside",))
    with pytest.raises(ValueError, match="relative"):
        _request(destructive_workspace_paths=("C:/outside",))
