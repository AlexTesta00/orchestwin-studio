"""Execution-profile contracts and capability-honest metadata."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol, runtime_checkable

from orchestwin.sandbox.command_plans import CommandNetworkMode, CommandPlan
from orchestwin.sandbox.container_runtime import ContainerImageReference
from orchestwin.sandbox.execution_policy import SandboxResourceLimits
from orchestwin.sandbox.source_inventory import SourceTreeInventory

_PROFILE_ID_PATTERN: Final = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)*$")
_PROFILE_VERSION_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_SUPPORTED_COMMAND_SCHEMA_VERSION: Final = 1
_MAX_TEXT_LENGTH: Final = 512
_MAX_INDICATOR_LENGTH: Final = 240


class ExecutionCapabilityStatus(StrEnum):
    """Honest automation level exposed by one execution profile."""

    VALIDATED_LEVEL_D = "VALIDATED_LEVEL_D"
    EXPERIMENTAL_LEVEL_D = "EXPERIMENTAL_LEVEL_D"
    DESIGN_ONLY_LEVEL_C = "DESIGN_ONLY_LEVEL_C"


class ExecutionTarget(StrEnum):
    """Approved target families from the amended Sprint 08 and Sprint 09 scope."""

    WEB_STATIC = "WEB_STATIC"
    WEB_VUE = "WEB_VUE"
    WEB_NODE_EXPRESS = "WEB_NODE_EXPRESS"
    WEB_PHP = "WEB_PHP"
    WEB_VUE_NODE = "WEB_VUE_NODE"
    JVM_JAVA = "JVM_JAVA"
    JVM_KOTLIN = "JVM_KOTLIN"
    JVM_SCALA = "JVM_SCALA"
    ANDROID_JAVA = "ANDROID_JAVA"
    ANDROID_KOTLIN = "ANDROID_KOTLIN"
    CUSTOM_DECLARATIVE = "CUSTOM_DECLARATIVE"


class ExecutionProfilePhase(StrEnum):
    """Structured lifecycle phases that a profile may plan independently."""

    SETUP = "SETUP"
    STATIC_CHECKS = "STATIC_CHECKS"
    BUILD = "BUILD"
    TEST = "TEST"
    RUN = "RUN"


class ExecutionProfileProjectValidationStatus(StrEnum):
    """Outcome of validating a source snapshot against a profile contract."""

    VALID = "VALID"
    INVALID = "INVALID"
    DESIGN_ONLY = "DESIGN_ONLY"


class ExecutionProfileProjectIssueCode(StrEnum):
    """Stable project/profile incompatibility reasons."""

    MISSING_REQUIRED_INDICATOR = "MISSING_REQUIRED_INDICATOR"
    CONFLICTING_INDICATOR = "CONFLICTING_INDICATOR"
    UNSUPPORTED_PROJECT = "UNSUPPORTED_PROJECT"
    DESIGN_ONLY_CAPABILITY = "DESIGN_ONLY_CAPABILITY"
    COMMAND_POLICY_REJECTED = "COMMAND_POLICY_REJECTED"


@dataclass(frozen=True, slots=True)
class ExecutionProfileReference:
    """Exact immutable profile metadata identity suitable for human approval."""

    profile_id: str
    profile_version: str
    content_hash: str

    def __post_init__(self) -> None:
        """Reject ambiguous profile references and malformed integrity values."""
        _validate_profile_id(self.profile_id)
        _validate_profile_version(self.profile_version)
        _validate_sha256(self.content_hash, label="execution profile reference hash")

    def to_snapshot(self) -> dict[str, str]:
        """Return stable reference metadata."""
        return {
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class ExecutionProfileNetworkPolicy:
    """Explicit network mode for every profile phase."""

    setup: CommandNetworkMode
    static_checks: CommandNetworkMode
    build: CommandNetworkMode
    test: CommandNetworkMode
    run: CommandNetworkMode

    def __post_init__(self) -> None:
        """Require concrete network modes instead of permissive sentinel values."""
        values = (
            self.setup,
            self.static_checks,
            self.build,
            self.test,
            self.run,
        )
        if any(not isinstance(value, CommandNetworkMode) for value in values):
            raise ValueError("execution profile network policy requires valid phase modes")

    def mode_for(self, phase: ExecutionProfilePhase) -> CommandNetworkMode:
        """Resolve the declared network mode for one phase."""
        modes = {
            ExecutionProfilePhase.SETUP: self.setup,
            ExecutionProfilePhase.STATIC_CHECKS: self.static_checks,
            ExecutionProfilePhase.BUILD: self.build,
            ExecutionProfilePhase.TEST: self.test,
            ExecutionProfilePhase.RUN: self.run,
        }
        return modes[phase]

    def to_snapshot(self) -> dict[str, str]:
        """Return deterministic phase policy metadata."""
        return {
            "setup": self.setup.value,
            "static_checks": self.static_checks.value,
            "build": self.build.value,
            "test": self.test.value,
            "run": self.run.value,
        }


@dataclass(frozen=True, slots=True)
class ExecutionProfileMetadata:
    """Inspectable and hashable execution-profile metadata."""

    profile_id: str
    name: str
    version: str
    capability_status: ExecutionCapabilityStatus
    supported_targets: tuple[ExecutionTarget, ...]
    file_indicators: tuple[str, ...]
    required_runners: tuple[str, ...]
    base_images: tuple[ContainerImageReference, ...]
    network_policy: ExecutionProfileNetworkPolicy
    resource_defaults: SandboxResourceLimits
    command_schema_version: int
    maintainer: str
    license_notes: str
    validation_evidence_refs: tuple[str, ...]
    requires_owner_approval: bool

    def __post_init__(self) -> None:
        """Protect canonical metadata and capability-status semantics."""
        _validate_profile_id(self.profile_id)
        _validate_normalized_text(self.name, label="execution profile name")
        _validate_profile_version(self.version)

        _validate_canonical_enum_tuple(
            self.supported_targets,
            label="execution profile supported targets",
        )
        if not self.supported_targets:
            raise ValueError("execution profile must support at least one target")

        _validate_canonical_text_tuple(
            self.file_indicators,
            label="execution profile file indicators",
            maximum_length=_MAX_INDICATOR_LENGTH,
        )
        _validate_canonical_identifier_tuple(
            self.required_runners,
            label="execution profile required runners",
        )

        ordered_images = tuple(sorted(self.base_images, key=lambda image: image.value))
        if self.base_images != ordered_images or len(self.base_images) != len(
            {image.value for image in self.base_images}
        ):
            raise ValueError("execution profile base images must be canonical and unique")

        if (
            isinstance(self.command_schema_version, bool)
            or self.command_schema_version != _SUPPORTED_COMMAND_SCHEMA_VERSION
        ):
            raise ValueError("unsupported execution profile command schema version")

        _validate_normalized_text(self.maintainer, label="execution profile maintainer")
        _validate_normalized_text(
            self.license_notes,
            label="execution profile license notes",
        )
        _validate_canonical_text_tuple(
            self.validation_evidence_refs,
            label="execution profile validation evidence references",
            maximum_length=_MAX_TEXT_LENGTH,
        )

        if not isinstance(self.requires_owner_approval, bool):
            raise TypeError("execution profile owner-approval marker must be a boolean")

        if self.capability_status is ExecutionCapabilityStatus.VALIDATED_LEVEL_D:
            if not self.validation_evidence_refs:
                raise ValueError("validated Level D profile requires validation evidence")
            if self.requires_owner_approval:
                raise ValueError("validated Level D profile must not require experimental approval")
        elif self.capability_status is ExecutionCapabilityStatus.EXPERIMENTAL_LEVEL_D:
            if not self.requires_owner_approval:
                raise ValueError("experimental Level D profile requires owner approval")
        else:
            if self.validation_evidence_refs:
                raise ValueError("design-only profile must not claim Level D validation evidence")
            if self.requires_owner_approval:
                raise ValueError("design-only profile must not request execution approval")

    @property
    def content_hash(self) -> str:
        """Return a SHA-256 digest covering all capability metadata."""
        return hashlib.sha256(_canonical_json_bytes(self._content_snapshot())).hexdigest()

    @property
    def reference(self) -> ExecutionProfileReference:
        """Return the exact profile tuple used by governance decisions."""
        return ExecutionProfileReference(
            profile_id=self.profile_id,
            profile_version=self.version,
            content_hash=self.content_hash,
        )

    @property
    def advertises_level_d(self) -> bool:
        """Return whether the nominal profile can plan automated execution."""
        return self.capability_status in {
            ExecutionCapabilityStatus.VALIDATED_LEVEL_D,
            ExecutionCapabilityStatus.EXPERIMENTAL_LEVEL_D,
        }

    def to_snapshot(self) -> dict[str, object]:
        """Return canonical metadata including its integrity digest."""
        return {
            **self._content_snapshot(),
            "content_hash": self.content_hash,
        }

    def _content_snapshot(self) -> dict[str, object]:
        """Build the exact metadata payload covered by the content hash."""
        return {
            "profile_id": self.profile_id,
            "name": self.name,
            "version": self.version,
            "capability_status": self.capability_status.value,
            "supported_targets": [target.value for target in self.supported_targets],
            "file_indicators": list(self.file_indicators),
            "required_runners": list(self.required_runners),
            "base_images": [image.value for image in self.base_images],
            "network_policy": self.network_policy.to_snapshot(),
            "resource_defaults": self.resource_defaults.to_snapshot(),
            "command_schema_version": self.command_schema_version,
            "maintainer": self.maintainer,
            "license_notes": self.license_notes,
            "validation_evidence_refs": list(self.validation_evidence_refs),
            "requires_owner_approval": self.requires_owner_approval,
        }


@dataclass(frozen=True, slots=True)
class ExecutionProfileDetection:
    """One profile-specific stack detection result with visible uncertainty."""

    profile_reference: ExecutionProfileReference
    detected_targets: tuple[ExecutionTarget, ...]
    confidence: int
    positive_indicators: tuple[str, ...]
    conflicting_indicators: tuple[str, ...]
    missing_tools: tuple[str, ...]
    requires_human_decision: bool

    def __post_init__(self) -> None:
        """Protect confidence, canonical ordering, and conflict semantics."""
        _validate_canonical_enum_tuple(
            self.detected_targets,
            label="execution profile detected targets",
        )
        if isinstance(self.confidence, bool) or not 0 <= self.confidence <= 100:
            raise ValueError("execution profile detection confidence must be from zero to 100")

        _validate_canonical_text_tuple(
            self.positive_indicators,
            label="execution profile positive indicators",
            maximum_length=_MAX_INDICATOR_LENGTH,
        )
        _validate_canonical_text_tuple(
            self.conflicting_indicators,
            label="execution profile conflicting indicators",
            maximum_length=_MAX_INDICATOR_LENGTH,
        )
        _validate_canonical_identifier_tuple(
            self.missing_tools,
            label="execution profile missing tools",
        )

        if self.confidence == 0 and self.positive_indicators:
            raise ValueError("zero-confidence detection must not contain positive indicators")
        if self.confidence > 0 and not self.positive_indicators:
            raise ValueError("positive-confidence detection requires positive indicators")
        if self.conflicting_indicators and not self.requires_human_decision:
            raise ValueError("conflicting detection indicators require a human decision")
        if not isinstance(self.requires_human_decision, bool):
            raise TypeError("execution profile human-decision marker must be a boolean")

    @property
    def is_candidate(self) -> bool:
        """Return whether the profile has at least one positive project indicator."""
        return self.confidence > 0

    def to_snapshot(self) -> dict[str, object]:
        """Return deterministic detection metadata."""
        return {
            "profile_reference": self.profile_reference.to_snapshot(),
            "detected_targets": [target.value for target in self.detected_targets],
            "confidence": self.confidence,
            "positive_indicators": list(self.positive_indicators),
            "conflicting_indicators": list(self.conflicting_indicators),
            "missing_tools": list(self.missing_tools),
            "requires_human_decision": self.requires_human_decision,
        }


@dataclass(frozen=True, slots=True)
class ExecutionProfileProjectIssue:
    """One inspectable incompatibility between a profile and source snapshot."""

    code: ExecutionProfileProjectIssueCode
    message: str
    path: str | None = None

    def __post_init__(self) -> None:
        """Keep issue details normalized for stable API serialization."""
        _validate_normalized_text(self.message, label="execution profile project issue message")
        if self.path is not None:
            _validate_normalized_text(self.path, label="execution profile project issue path")

    def to_snapshot(self) -> dict[str, str | None]:
        """Return stable issue metadata."""
        return {
            "code": self.code.value,
            "message": self.message,
            "path": self.path,
        }


@dataclass(frozen=True, slots=True)
class ExecutionProfileProjectValidation:
    """Validation outcome bound to one exact profile and inventory snapshot."""

    profile_reference: ExecutionProfileReference
    inventory_content_hash: str
    status: ExecutionProfileProjectValidationStatus
    issues: tuple[ExecutionProfileProjectIssue, ...]

    def __post_init__(self) -> None:
        """Protect exact inventory binding and status-specific issue shapes."""
        _validate_sha256(
            self.inventory_content_hash,
            label="execution profile inventory content hash",
        )
        if self.status is ExecutionProfileProjectValidationStatus.VALID:
            if self.issues:
                raise ValueError("valid execution profile project report must not contain issues")
        elif not self.issues:
            raise ValueError("non-valid execution profile project report requires issues")

        if self.status is ExecutionProfileProjectValidationStatus.DESIGN_ONLY and not any(
            issue.code is ExecutionProfileProjectIssueCode.DESIGN_ONLY_CAPABILITY
            for issue in self.issues
        ):
            raise ValueError("design-only project report requires a capability issue")

    @property
    def is_valid(self) -> bool:
        """Return whether automatic profile execution may be planned."""
        return self.status is ExecutionProfileProjectValidationStatus.VALID

    def to_snapshot(self) -> dict[str, object]:
        """Return deterministic validation evidence."""
        return {
            "profile_reference": self.profile_reference.to_snapshot(),
            "inventory_content_hash": self.inventory_content_hash,
            "status": self.status.value,
            "issues": [issue.to_snapshot() for issue in self.issues],
        }


@runtime_checkable
class ExecutionProfile(Protocol):
    """Stack-specific detector, validator, and structured plan factory."""

    @property
    def metadata(self) -> ExecutionProfileMetadata:
        """Return immutable inspectable profile metadata."""
        ...

    def detect(self, inventory: SourceTreeInventory) -> ExecutionProfileDetection:
        """Inspect one canonical source inventory without executing project code."""
        ...

    def validate_project(
        self,
        inventory: SourceTreeInventory,
    ) -> ExecutionProfileProjectValidation:
        """Validate one inventory against profile-specific structural rules."""
        ...

    def create_plan(
        self,
        phase: ExecutionProfilePhase,
        inventory: SourceTreeInventory,
    ) -> CommandPlan | None:
        """Return a shell-free plan, or none when the phase is unavailable."""
        ...


def create_execution_profile_metadata(
    *,
    profile_id: str,
    name: str,
    version: str,
    capability_status: ExecutionCapabilityStatus,
    supported_targets: Iterable[ExecutionTarget],
    file_indicators: Iterable[str],
    required_runners: Iterable[str],
    base_images: Iterable[ContainerImageReference],
    network_policy: ExecutionProfileNetworkPolicy,
    resource_defaults: SandboxResourceLimits,
    maintainer: str,
    license_notes: str,
    validation_evidence_refs: Iterable[str] = (),
    requires_owner_approval: bool = False,
) -> ExecutionProfileMetadata:
    """Canonicalize collections before constructing immutable profile metadata."""
    return ExecutionProfileMetadata(
        profile_id=profile_id,
        name=name,
        version=version,
        capability_status=capability_status,
        supported_targets=tuple(sorted(set(supported_targets), key=lambda target: target.value)),
        file_indicators=tuple(sorted(set(file_indicators))),
        required_runners=tuple(sorted(set(required_runners))),
        base_images=tuple(sorted(set(base_images), key=lambda image: image.value)),
        network_policy=network_policy,
        resource_defaults=resource_defaults,
        command_schema_version=_SUPPORTED_COMMAND_SCHEMA_VERSION,
        maintainer=maintainer,
        license_notes=license_notes,
        validation_evidence_refs=tuple(sorted(set(validation_evidence_refs))),
        requires_owner_approval=requires_owner_approval,
    )


def _validate_profile_id(value: str) -> None:
    """Require a stable portable execution-profile identifier."""
    if _PROFILE_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("execution profile ID must be a normalized portable identifier")


def _validate_profile_version(value: str) -> None:
    """Require one compact portable version identifier."""
    if _PROFILE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("execution profile version must be normalized")


def _validate_sha256(value: str, *, label: str) -> None:
    """Require one lowercase SHA-256 digest."""
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase SHA-256")


def _validate_normalized_text(value: str, *, label: str) -> None:
    """Require compact human-readable metadata without hidden whitespace."""
    if (
        not isinstance(value, str)
        or not value
        or value != " ".join(value.split())
        or len(value) > _MAX_TEXT_LENGTH
    ):
        raise ValueError(f"{label} must be normalized and bounded")


def _validate_canonical_text_tuple(
    values: tuple[str, ...],
    *,
    label: str,
    maximum_length: int,
) -> None:
    """Require unique normalized strings in lexical order."""
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError(f"{label} must be canonical and unique")
    for value in values:
        if not value or value != " ".join(value.split()) or len(value) > maximum_length:
            raise ValueError(f"{label} must contain normalized bounded values")


def _validate_canonical_identifier_tuple(
    values: tuple[str, ...],
    *,
    label: str,
) -> None:
    """Require unique portable identifiers in lexical order."""
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError(f"{label} must be canonical and unique")
    if any(_PROFILE_ID_PATTERN.fullmatch(value) is None for value in values):
        raise ValueError(f"{label} must contain portable identifiers")


def _validate_canonical_enum_tuple(
    values: tuple[ExecutionTarget, ...],
    *,
    label: str,
) -> None:
    """Require unique target values in stable lexical order."""
    if any(not isinstance(value, ExecutionTarget) for value in values):
        raise ValueError(f"{label} must contain execution targets")
    ordered = tuple(sorted(values, key=lambda value: value.value))
    if values != ordered or len(values) != len(set(values)):
        raise ValueError(f"{label} must be canonical and unique")


def _canonical_json_bytes(value: dict[str, object]) -> bytes:
    """Serialize one metadata snapshot deterministically."""
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
