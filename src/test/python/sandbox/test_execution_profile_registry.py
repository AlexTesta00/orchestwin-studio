"""Tests for the immutable execution-profile registry."""

from dataclasses import replace

import pytest

from orchestwin.sandbox.command_plans import CommandNetworkMode, CommandPlan
from orchestwin.sandbox.execution_policy import SandboxResourceLimits
from orchestwin.sandbox.execution_profile_registry import (
    ExecutionProfileRegistry,
    create_execution_profile_registry,
)
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionProfileDetection,
    ExecutionProfileMetadata,
    ExecutionProfileNetworkPolicy,
    ExecutionProfilePhase,
    ExecutionProfileProjectValidation,
    ExecutionTarget,
    create_execution_profile_metadata,
)
from orchestwin.sandbox.source_inventory import SourceTreeInventory

NETWORK_POLICY = ExecutionProfileNetworkPolicy(
    setup=CommandNetworkMode.DISABLED,
    static_checks=CommandNetworkMode.DISABLED,
    build=CommandNetworkMode.DISABLED,
    test=CommandNetworkMode.DISABLED,
    run=CommandNetworkMode.DISABLED,
)
RESOURCES = SandboxResourceLimits(
    cpu_count=1.0,
    memory_mib=1024,
    pids_limit=64,
    writable_tmpfs_mib=128,
)


class StubProfile:
    """Small port implementation used to exercise registry behavior."""

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
    ) -> CommandPlan | None:
        return None


def _metadata(
    profile_id: str,
    version: str,
    target: ExecutionTarget,
) -> ExecutionProfileMetadata:
    return create_execution_profile_metadata(
        profile_id=profile_id,
        name=f"Profile {profile_id} {version}",
        version=version,
        capability_status=ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C,
        supported_targets=(target,),
        file_indicators=(f"target:{target.value}",),
        required_runners=(),
        base_images=(),
        network_policy=NETWORK_POLICY,
        resource_defaults=RESOURCES,
        maintainer="OrchesTwin Studio",
        license_notes="No execution toolchain is bundled yet.",
    )


def _profile(
    profile_id: str,
    version: str,
    target: ExecutionTarget,
) -> StubProfile:
    return StubProfile(_metadata(profile_id, version, target))


def test_registry_factory_is_order_independent_and_hashable() -> None:
    """Produce one reproducible registry snapshot regardless of input order."""
    web = _profile("web.vue", "1.0.0", ExecutionTarget.WEB_VUE)
    kotlin = _profile("jvm.kotlin", "1.0.0", ExecutionTarget.JVM_KOTLIN)

    first = create_execution_profile_registry((web, kotlin))
    second = create_execution_profile_registry((kotlin, web))

    assert first.profiles == (kotlin, web)
    assert first.to_snapshot() == second.to_snapshot()
    assert first.content_hash == second.content_hash
    assert first.references == (
        kotlin.metadata.reference,
        web.metadata.reference,
    )


def test_registry_uses_exact_version_and_content_hash_lookup() -> None:
    """Avoid silently resolving a moving latest version or stale approval tuple."""
    version_one = _profile("web.vue", "1.0.0", ExecutionTarget.WEB_VUE)
    version_two = _profile("web.vue", "2.0.0", ExecutionTarget.WEB_VUE)
    registry = create_execution_profile_registry((version_two, version_one))

    assert registry.find("web.vue", "1.0.0") is version_one
    assert registry.find("web.vue", "3.0.0") is None
    assert registry.versions_for("web.vue") == (version_one, version_two)
    assert registry.find_reference(version_two.metadata.reference) is version_two

    stale_reference = replace(
        version_two.metadata.reference,
        content_hash="f" * 64,
    )
    assert registry.find_reference(stale_reference) is None


def test_registry_filters_profiles_by_explicit_supported_target() -> None:
    """Do not infer target compatibility from profile names alone."""
    vue = _profile("web.vue", "1.0.0", ExecutionTarget.WEB_VUE)
    kotlin = _profile("jvm.kotlin", "1.0.0", ExecutionTarget.JVM_KOTLIN)
    registry = create_execution_profile_registry((vue, kotlin))

    assert registry.profiles_for_target(ExecutionTarget.WEB_VUE) == (vue,)
    assert registry.profiles_for_target(ExecutionTarget.ANDROID_KOTLIN) == ()


def test_registry_rejects_duplicate_profile_versions_even_when_metadata_matches() -> None:
    """Surface accidental double registration rather than silently deduplicating it."""
    first = _profile("web.vue", "1.0.0", ExecutionTarget.WEB_VUE)
    duplicate = StubProfile(first.metadata)

    with pytest.raises(ValueError, match="duplicate profile version"):
        create_execution_profile_registry((first, duplicate))


def test_registry_rejects_noncanonical_direct_construction_and_invalid_objects() -> None:
    """Keep direct construction as strict as the canonical factory boundary."""
    web = _profile("web.vue", "1.0.0", ExecutionTarget.WEB_VUE)
    kotlin = _profile("jvm.kotlin", "1.0.0", ExecutionTarget.JVM_KOTLIN)

    with pytest.raises(ValueError, match="canonical profile ordering"):
        ExecutionProfileRegistry(profiles=(web, kotlin))

    with pytest.raises(TypeError, match="only profile implementations"):
        ExecutionProfileRegistry(profiles=(object(),))  # type: ignore[arg-type]
