"""Tests for deterministic and capability-honest execution negotiation."""

from __future__ import annotations

from dataclasses import dataclass, replace

from orchestwin.projects.execution_capabilities import (
    CapabilityNegotiationIssueCode,
    CapabilityNegotiationRequest,
    CapabilityNegotiationStatus,
    negotiate_execution_capability,
)

from orchestwin.sandbox.archive_policy import (
    SourceArchiveEntryDisposition,
    SourceArchiveEntryKind,
)
from orchestwin.sandbox.builtin_execution_profiles import (
    create_builtin_execution_profile_registry,
)
from orchestwin.sandbox.command_plans import CommandNetworkMode, CommandPlan
from orchestwin.sandbox.container_runtime import ContainerImageReference
from orchestwin.sandbox.execution_policy import DEFAULT_SANDBOX_RESOURCE_LIMITS
from orchestwin.sandbox.execution_profile_registry import (
    create_execution_profile_registry,
)
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionProfileDetection,
    ExecutionProfileMetadata,
    ExecutionProfileNetworkPolicy,
    ExecutionProfilePhase,
    ExecutionProfileProjectValidation,
    ExecutionProfileProjectValidationStatus,
    ExecutionProfileReference,
    ExecutionTarget,
    create_execution_profile_metadata,
)
from orchestwin.sandbox.source_inventory import (
    SourceInventoryClassification,
    SourceInventoryEntry,
    SourceTreeInventory,
)

_DIGEST = "a" * 64
_NETWORK = ExecutionProfileNetworkPolicy(
    setup=CommandNetworkMode.DISABLED,
    static_checks=CommandNetworkMode.DISABLED,
    build=CommandNetworkMode.DISABLED,
    test=CommandNetworkMode.DISABLED,
    run=CommandNetworkMode.DISABLED,
)
_IMAGE = ContainerImageReference("example/fixture@sha256:" + "b" * 64)


def _inventory(*paths: str) -> SourceTreeInventory:
    entries = tuple(
        sorted(
            (
                SourceInventoryEntry(
                    normalized_path=path,
                    kind=SourceArchiveEntryKind.FILE,
                    classification=SourceInventoryClassification.SOURCE,
                    size_bytes=1,
                    sha256_digest=_DIGEST,
                    disposition=SourceArchiveEntryDisposition.INCLUDE,
                    disposition_reason=None,
                )
                for path in paths
            ),
            key=lambda entry: (entry.normalized_path.casefold(), entry.normalized_path),
        )
    )
    return SourceTreeInventory(archive_sha256="c" * 64, entries=entries)


def _request(
    *,
    requested_target: ExecutionTarget | None = None,
    available_runners: tuple[str, ...] = (),
    approved: tuple[ExecutionProfileReference, ...] = (),
) -> CapabilityNegotiationRequest:
    return CapabilityNegotiationRequest(
        requested_target=requested_target,
        available_runners=available_runners,
        approved_experimental_profiles=approved,
    )


def test_static_web_detection_selects_design_only_level_c_explicitly() -> None:
    """Select a useful target descriptor without pretending Sprint 07 can execute it."""
    result = negotiate_execution_capability(
        _inventory("index.html", "site.css", "site.js"),
        registry=create_builtin_execution_profile_registry(),
        request=_request(),
    )

    assert result.status is CapabilityNegotiationStatus.DESIGN_ONLY_LEVEL_C_SELECTED
    assert result.effective_capability_status is (ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C)
    assert result.selected_profile_reference is not None
    assert result.selected_profile_reference.profile_id == "WEB_STATIC"
    assert result.requires_human_decision is False


def test_vue_node_composition_is_preferred_over_conflicting_single_profiles() -> None:
    """Use stronger structural evidence while retaining every candidate for review."""
    result = negotiate_execution_capability(
        _inventory(
            "package.json",
            "vite.config.ts",
            "frontend/src/App.vue",
            "backend/src/server.ts",
        ),
        registry=create_builtin_execution_profile_registry(),
        request=_request(),
    )

    assert result.status is CapabilityNegotiationStatus.DESIGN_ONLY_LEVEL_C_SELECTED
    assert result.selected_profile_reference is not None
    assert result.selected_profile_reference.profile_id == "WEB_VUE_NODE"
    assert {candidate.profile_reference.profile_id for candidate in result.candidates} >= {
        "WEB_NODE_EXPRESS",
        "WEB_VUE",
        "WEB_VUE_NODE",
    }


def test_unknown_stack_degrades_to_level_c_without_a_false_profile() -> None:
    """Keep unsupported source explicit rather than generating optimistic commands."""
    result = negotiate_execution_capability(
        _inventory("src/main.unknown"),
        registry=create_builtin_execution_profile_registry(),
        request=_request(),
    )

    assert result.status is CapabilityNegotiationStatus.UNSUPPORTED
    assert result.selected_profile_reference is None
    assert result.effective_capability_status is (ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C)
    assert result.issues[0].code is CapabilityNegotiationIssueCode.NO_PROFILE_DETECTED


def test_requested_target_filters_detection_without_name_inference() -> None:
    """Honor an explicit Scala target and report unavailable mismatched targets."""
    inventory = _inventory("build.sbt", "src/main/scala/example/Main.scala")
    registry = create_builtin_execution_profile_registry()

    scala = negotiate_execution_capability(
        inventory,
        registry=registry,
        request=_request(requested_target=ExecutionTarget.JVM_SCALA),
    )
    android = negotiate_execution_capability(
        inventory,
        registry=registry,
        request=_request(requested_target=ExecutionTarget.ANDROID_KOTLIN),
    )

    assert scala.selected_profile_reference is not None
    assert scala.selected_profile_reference.profile_id == "JVM_SCALA"
    assert android.status is CapabilityNegotiationStatus.UNSUPPORTED
    assert android.issues[0].code is (CapabilityNegotiationIssueCode.REQUESTED_TARGET_UNAVAILABLE)


@dataclass(frozen=True, slots=True)
class _FixtureProfile:
    metadata: ExecutionProfileMetadata
    confidence: int = 100

    def detect(self, inventory: SourceTreeInventory) -> ExecutionProfileDetection:
        return ExecutionProfileDetection(
            profile_reference=self.metadata.reference,
            detected_targets=self.metadata.supported_targets,
            confidence=self.confidence,
            positive_indicators=("fixture:matched",),
            conflicting_indicators=(),
            missing_tools=(),
            requires_human_decision=False,
        )

    def validate_project(
        self,
        inventory: SourceTreeInventory,
    ) -> ExecutionProfileProjectValidation:
        return ExecutionProfileProjectValidation(
            profile_reference=self.metadata.reference,
            inventory_content_hash=inventory.content_hash,
            status=ExecutionProfileProjectValidationStatus.VALID,
            issues=(),
        )

    def create_plan(
        self,
        phase: ExecutionProfilePhase,
        inventory: SourceTreeInventory,
    ) -> CommandPlan | None:
        return None


def _level_d_profile(
    profile_id: str,
    *,
    status: ExecutionCapabilityStatus,
    target: ExecutionTarget = ExecutionTarget.WEB_STATIC,
) -> _FixtureProfile:
    experimental = status is ExecutionCapabilityStatus.EXPERIMENTAL_LEVEL_D
    metadata = create_execution_profile_metadata(
        profile_id=profile_id,
        name=f"Fixture {profile_id}",
        version="1.0.0",
        capability_status=status,
        supported_targets=(target,),
        file_indicators=("fixture:matched",),
        required_runners=("container.docker",),
        base_images=(_IMAGE,),
        network_policy=_NETWORK,
        resource_defaults=DEFAULT_SANDBOX_RESOURCE_LIMITS,
        maintainer="OrchesTwin Studio",
        license_notes="Test fixture profile.",
        validation_evidence_refs=(() if experimental else ("evidence:fixture-validation",)),
        requires_owner_approval=experimental,
    )
    return _FixtureProfile(metadata)


def test_validated_level_d_requires_its_runner_before_selection() -> None:
    """Degrade safely when profile evidence exists but the runtime is unavailable."""
    profile = _level_d_profile(
        "fixture.validated",
        status=ExecutionCapabilityStatus.VALIDATED_LEVEL_D,
    )
    registry = create_execution_profile_registry((profile,))
    inventory = _inventory("fixture.project")

    missing = negotiate_execution_capability(
        inventory,
        registry=registry,
        request=_request(),
    )
    available = negotiate_execution_capability(
        inventory,
        registry=registry,
        request=_request(available_runners=("container.docker",)),
    )

    assert missing.status is CapabilityNegotiationStatus.HUMAN_DECISION_REQUIRED
    assert missing.issues[0].code is CapabilityNegotiationIssueCode.RUNNER_UNAVAILABLE
    assert missing.effective_capability_status is (ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C)
    assert available.status is CapabilityNegotiationStatus.VALIDATED_LEVEL_D_SELECTED
    assert available.effective_capability_status is (ExecutionCapabilityStatus.VALIDATED_LEVEL_D)


def test_experimental_profile_requires_exact_nonstale_owner_approval() -> None:
    """Bind experimental use to the full ID, version, and metadata hash tuple."""
    profile = _level_d_profile(
        "fixture.experimental",
        status=ExecutionCapabilityStatus.EXPERIMENTAL_LEVEL_D,
    )
    registry = create_execution_profile_registry((profile,))
    inventory = _inventory("fixture.project")
    runners = ("container.docker",)

    unapproved = negotiate_execution_capability(
        inventory,
        registry=registry,
        request=_request(available_runners=runners),
    )
    stale_reference = replace(profile.metadata.reference, content_hash="f" * 64)
    stale = negotiate_execution_capability(
        inventory,
        registry=registry,
        request=_request(
            available_runners=runners,
            approved=(stale_reference,),
        ),
    )
    approved = negotiate_execution_capability(
        inventory,
        registry=registry,
        request=_request(
            available_runners=runners,
            approved=(profile.metadata.reference,),
        ),
    )

    assert unapproved.status is CapabilityNegotiationStatus.HUMAN_DECISION_REQUIRED
    assert unapproved.issues[0].code is (
        CapabilityNegotiationIssueCode.EXPERIMENTAL_APPROVAL_REQUIRED
    )
    assert stale.status is CapabilityNegotiationStatus.HUMAN_DECISION_REQUIRED
    assert stale.issues[0].code is (CapabilityNegotiationIssueCode.EXPERIMENTAL_APPROVAL_REQUIRED)
    assert approved.status is CapabilityNegotiationStatus.EXPERIMENTAL_LEVEL_D_SELECTED
    assert approved.selected_profile_reference == profile.metadata.reference


def test_equally_strong_profile_matches_require_a_human_decision() -> None:
    """Avoid silently preferring a language or framework under ambiguous evidence."""
    first = _level_d_profile(
        "fixture.first",
        status=ExecutionCapabilityStatus.VALIDATED_LEVEL_D,
    )
    second = _level_d_profile(
        "fixture.second",
        status=ExecutionCapabilityStatus.VALIDATED_LEVEL_D,
    )
    result = negotiate_execution_capability(
        _inventory("fixture.project"),
        registry=create_execution_profile_registry((second, first)),
        request=_request(available_runners=("container.docker",)),
    )

    assert result.status is CapabilityNegotiationStatus.HUMAN_DECISION_REQUIRED
    assert result.selected_profile_reference is None
    assert result.issues[0].code is (CapabilityNegotiationIssueCode.AMBIGUOUS_PROFILE_MATCH)
    assert tuple(candidate.profile_reference.profile_id for candidate in result.candidates) == (
        "fixture.first",
        "fixture.second",
    )
