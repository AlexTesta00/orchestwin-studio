"""Tests for execution-profile contracts and capability honesty."""

from dataclasses import replace

import pytest

from orchestwin.sandbox.command_plans import CommandNetworkMode
from orchestwin.sandbox.container_runtime import ContainerImageReference
from orchestwin.sandbox.execution_policy import SandboxResourceLimits
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionProfile,
    ExecutionProfileDetection,
    ExecutionProfileMetadata,
    ExecutionProfileNetworkPolicy,
    ExecutionProfilePhase,
    ExecutionProfileProjectIssue,
    ExecutionProfileProjectIssueCode,
    ExecutionProfileProjectValidation,
    ExecutionProfileProjectValidationStatus,
    ExecutionTarget,
    create_execution_profile_metadata,
)
from orchestwin.sandbox.source_inventory import SourceTreeInventory

NETWORK_POLICY = ExecutionProfileNetworkPolicy(
    setup=CommandNetworkMode.CONTROLLED,
    static_checks=CommandNetworkMode.DISABLED,
    build=CommandNetworkMode.DISABLED,
    test=CommandNetworkMode.DISABLED,
    run=CommandNetworkMode.DISABLED,
)
RESOURCES = SandboxResourceLimits(
    cpu_count=2.0,
    memory_mib=4096,
    pids_limit=256,
    writable_tmpfs_mib=512,
)
IMAGE = ContainerImageReference("example/web@sha256:" + "a" * 64)
INVENTORY_HASH = "b" * 64


def _metadata(
    **overrides: object,
) -> ExecutionProfileMetadata:
    values: dict[str, object] = {
        "profile_id": "web.example",
        "name": "Web Example",
        "version": "1.0.0",
        "capability_status": ExecutionCapabilityStatus.VALIDATED_LEVEL_D,
        "supported_targets": (ExecutionTarget.WEB_VUE,),
        "file_indicators": ("file:package.json", "suffix:.vue"),
        "required_runners": ("container.docker",),
        "base_images": (IMAGE,),
        "network_policy": NETWORK_POLICY,
        "resource_defaults": RESOURCES,
        "command_schema_version": 1,
        "maintainer": "OrchesTwin Studio",
        "license_notes": "Apache-2.0 compatible toolchain.",
        "validation_evidence_refs": ("evidence:web-fixture-v1",),
        "requires_owner_approval": False,
    }
    values.update(overrides)
    return ExecutionProfileMetadata(**values)  # type: ignore[arg-type]


def test_profile_metadata_is_canonical_hashable_and_exactly_referenceable() -> None:
    """Bind governance to the complete metadata tuple instead of a mutable name."""
    metadata = _metadata()

    assert metadata.advertises_level_d is True
    assert metadata.reference.profile_id == "web.example"
    assert metadata.reference.profile_version == "1.0.0"
    assert metadata.reference.content_hash == metadata.content_hash
    assert metadata.to_snapshot()["content_hash"] == metadata.content_hash
    assert len(metadata.content_hash) == 64
    assert metadata.network_policy.mode_for(ExecutionProfilePhase.SETUP) is (
        CommandNetworkMode.CONTROLLED
    )
    assert metadata.network_policy.mode_for(ExecutionProfilePhase.TEST) is (
        CommandNetworkMode.DISABLED
    )


def test_profile_metadata_factory_canonicalizes_set_like_collections() -> None:
    """Keep hash output independent from declaration ordering."""
    metadata = create_execution_profile_metadata(
        profile_id="web.example",
        name="Web Example",
        version="1.0.0",
        capability_status=ExecutionCapabilityStatus.VALIDATED_LEVEL_D,
        supported_targets=(ExecutionTarget.WEB_VUE, ExecutionTarget.WEB_STATIC),
        file_indicators=("suffix:.vue", "file:package.json"),
        required_runners=("container.docker",),
        base_images=(IMAGE,),
        network_policy=NETWORK_POLICY,
        resource_defaults=RESOURCES,
        maintainer="OrchesTwin Studio",
        license_notes="Apache-2.0 compatible toolchain.",
        validation_evidence_refs=("evidence:web-fixture-v1",),
    )

    assert metadata.supported_targets == (
        ExecutionTarget.WEB_STATIC,
        ExecutionTarget.WEB_VUE,
    )
    assert metadata.file_indicators == ("file:package.json", "suffix:.vue")


def test_capability_statuses_cannot_overstate_validation_or_owner_approval() -> None:
    """Prevent design-only and experimental profiles from masquerading as validated."""
    with pytest.raises(ValueError, match="requires validation evidence"):
        _metadata(validation_evidence_refs=())

    with pytest.raises(ValueError, match="requires owner approval"):
        _metadata(
            capability_status=ExecutionCapabilityStatus.EXPERIMENTAL_LEVEL_D,
            validation_evidence_refs=(),
            requires_owner_approval=False,
        )

    with pytest.raises(ValueError, match="must not claim Level D validation evidence"):
        _metadata(
            capability_status=ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C,
            requires_owner_approval=False,
        )

    experimental = _metadata(
        capability_status=ExecutionCapabilityStatus.EXPERIMENTAL_LEVEL_D,
        validation_evidence_refs=(),
        requires_owner_approval=True,
    )
    design_only = _metadata(
        capability_status=ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C,
        base_images=(),
        validation_evidence_refs=(),
        requires_owner_approval=False,
    )

    assert experimental.advertises_level_d is True
    assert design_only.advertises_level_d is False


def test_profile_metadata_rejects_noncanonical_or_moving_contract_values() -> None:
    """Require stable targets, runners, image digests, and command schema versions."""
    with pytest.raises(ValueError, match="supported targets must be canonical"):
        _metadata(
            supported_targets=(ExecutionTarget.WEB_VUE, ExecutionTarget.WEB_STATIC),
        )

    with pytest.raises(ValueError, match="required runners must be canonical"):
        _metadata(required_runners=("host.runner", "container.docker"))

    with pytest.raises(ValueError, match="unsupported execution profile command schema"):
        _metadata(command_schema_version=2)

    with pytest.raises(ValueError, match="pinned"):
        ContainerImageReference("example/web:latest")


def test_detection_exposes_positive_conflicting_and_missing_tool_evidence() -> None:
    """Keep candidate confidence inspectable and force humans to resolve conflicts."""
    metadata = _metadata()
    detection = ExecutionProfileDetection(
        profile_reference=metadata.reference,
        detected_targets=(ExecutionTarget.WEB_VUE,),
        confidence=82,
        positive_indicators=("file:package.json", "suffix:.vue"),
        conflicting_indicators=("file:composer.json",),
        missing_tools=("runner.playwright",),
        requires_human_decision=True,
    )

    assert detection.is_candidate is True
    assert detection.to_snapshot()["confidence"] == 82

    with pytest.raises(ValueError, match="require a human decision"):
        replace(detection, requires_human_decision=False)

    with pytest.raises(ValueError, match="zero-confidence"):
        replace(detection, confidence=0)


def test_project_validation_distinguishes_invalid_and_design_only_results() -> None:
    """Do not report structural validity as execution capability."""
    metadata = _metadata()
    invalid_issue = ExecutionProfileProjectIssue(
        code=ExecutionProfileProjectIssueCode.MISSING_REQUIRED_INDICATOR,
        message="The required package manifest is missing.",
        path="package.json",
    )
    design_only_issue = ExecutionProfileProjectIssue(
        code=ExecutionProfileProjectIssueCode.DESIGN_ONLY_CAPABILITY,
        message="This profile has not been validated for automated execution.",
    )

    invalid = ExecutionProfileProjectValidation(
        profile_reference=metadata.reference,
        inventory_content_hash=INVENTORY_HASH,
        status=ExecutionProfileProjectValidationStatus.INVALID,
        issues=(invalid_issue,),
    )
    design_only = ExecutionProfileProjectValidation(
        profile_reference=metadata.reference,
        inventory_content_hash=INVENTORY_HASH,
        status=ExecutionProfileProjectValidationStatus.DESIGN_ONLY,
        issues=(design_only_issue,),
    )

    assert invalid.is_valid is False
    assert design_only.is_valid is False
    assert design_only.to_snapshot()["status"] == "DESIGN_ONLY"

    with pytest.raises(ValueError, match="requires a capability issue"):
        replace(design_only, issues=(invalid_issue,))


class ContractProfile:
    """Minimal implementation used to verify the runtime-checkable port shape."""

    def __init__(self, metadata: ExecutionProfileMetadata) -> None:
        self._metadata = metadata

    @property
    def metadata(self) -> ExecutionProfileMetadata:
        return self._metadata

    def detect(self, inventory: SourceTreeInventory) -> ExecutionProfileDetection:
        raise NotImplementedError

    def validate_project(
        self,
        inventory: SourceTreeInventory,
    ) -> ExecutionProfileProjectValidation:
        raise NotImplementedError

    def create_plan(
        self,
        phase: ExecutionProfilePhase,
        inventory: SourceTreeInventory,
    ) -> None:
        return None


def test_execution_profile_protocol_is_explicit_and_runtime_inspectable() -> None:
    """Keep registry boundaries independent from concrete profile classes."""
    profile = ContractProfile(_metadata())

    assert isinstance(profile, ExecutionProfile)
