"""Immutable high-impact execution requests and deterministic Gate 7 classification."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final
from uuid import UUID

from orchestwin.projects.requirements_primitives import (
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.sandbox.command_plans import CommandNetworkMode
from orchestwin.sandbox.container_runtime import ContainerImageReference
from orchestwin.sandbox.execution_policy import (
    DEFAULT_SANDBOX_RESOURCE_LIMITS,
    SandboxResourceLimits,
)
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionProfileReference,
)

_HIGH_IMPACT_SCHEMA_VERSION: Final = 1
_IDENTIFIER_PATTERN: Final = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)*$")
_WINDOWS_DRIVE_PATTERN: Final = re.compile(r"^[A-Za-z]:")


class HighImpactOperationKind(StrEnum):
    """Governed operation families that may require an exact owner decision."""

    SANDBOX_EXECUTION = "SANDBOX_EXECUTION"
    PROFILE_ACTIVATION = "PROFILE_ACTIVATION"
    WORKSPACE_MUTATION = "WORKSPACE_MUTATION"
    RUNTIME_POLICY_OVERRIDE = "RUNTIME_POLICY_OVERRIDE"


class HighImpactClassification(StrEnum):
    """Deterministic authorization class before Gate 7 persistence."""

    ALLOWED_WITHOUT_APPROVAL = "ALLOWED_WITHOUT_APPROVAL"
    REQUIRES_OWNER_APPROVAL = "REQUIRES_OWNER_APPROVAL"
    FORBIDDEN_BY_POLICY = "FORBIDDEN_BY_POLICY"


class HighImpactReasonCode(StrEnum):
    """Stable reasons for approval requirements or unconditional prohibition."""

    EXPERIMENTAL_PROFILE = "EXPERIMENTAL_PROFILE"
    CONTROLLED_NETWORK = "CONTROLLED_NETWORK"
    SECRET_ACCESS = "SECRET_ACCESS"
    UNAPPROVED_IMAGE = "UNAPPROVED_IMAGE"
    RESOURCE_LIMIT_INCREASE = "RESOURCE_LIMIT_INCREASE"
    DESTRUCTIVE_WORKSPACE_CHANGE = "DESTRUCTIVE_WORKSPACE_CHANGE"
    DESIGN_ONLY_EXECUTION = "DESIGN_ONLY_EXECUTION"
    PRIVILEGED_CONTAINER = "PRIVILEGED_CONTAINER"
    DOCKER_SOCKET_MOUNT = "DOCKER_SOCKET_MOUNT"
    HOST_FILESYSTEM_MOUNT = "HOST_FILESYSTEM_MOUNT"
    ARBITRARY_HOST_COMMAND = "ARBITRARY_HOST_COMMAND"
    PROTECTED_WORKSPACE_PATH = "PROTECTED_WORKSPACE_PATH"


@dataclass(frozen=True, slots=True)
class HighImpactExecutionRequest:
    """Structured execution intent containing no secret values or shell command text."""

    project_id: UUID
    operation_kind: HighImpactOperationKind
    summary: str
    profile_reference: ExecutionProfileReference
    capability_status: ExecutionCapabilityStatus
    command_plan_id: str | None
    command_plan_content_hash: str | None
    image_reference: ContainerImageReference | None
    network_mode: CommandNetworkMode
    secret_reference_ids: tuple[str, ...]
    resources: SandboxResourceLimits
    destructive_workspace_paths: tuple[str, ...]
    requests_privileged_container: bool
    requests_docker_socket_mount: bool
    requests_host_filesystem_mount: bool
    requests_arbitrary_host_command: bool
    schema_version: int = _HIGH_IMPACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Protect structured shape, canonical collections, and exact plan binding."""
        if self.schema_version != _HIGH_IMPACT_SCHEMA_VERSION:
            raise ValueError("unsupported high-impact request schema version")
        normalized_summary = " ".join(self.summary.split())
        if not normalized_summary or len(normalized_summary) > 500:
            raise ValueError("high-impact operation summary must contain at most 500 characters")
        if normalized_summary != self.summary:
            raise ValueError("high-impact operation summary must be normalized")

        if (self.command_plan_id is None) != (self.command_plan_content_hash is None):
            raise ValueError("high-impact command plan ID and hash must be supplied together")
        if self.command_plan_id is not None:
            _validate_identifier(self.command_plan_id, label="high-impact command plan ID")
            validate_sha256(
                self.command_plan_content_hash or "",
                label="high-impact command plan content hash",
            )
        if self.operation_kind is HighImpactOperationKind.SANDBOX_EXECUTION and (
            self.command_plan_id is None or self.image_reference is None
        ):
            raise ValueError("sandbox execution request requires an exact plan and image")

        if self.secret_reference_ids != tuple(sorted(set(self.secret_reference_ids))):
            raise ValueError("high-impact secret references must be canonical and unique")
        for reference_id in self.secret_reference_ids:
            _validate_identifier(reference_id, label="high-impact secret reference ID")

        canonical_paths = tuple(
            sorted(
                set(self.destructive_workspace_paths),
                key=lambda path: (path.casefold(), path),
            )
        )
        if self.destructive_workspace_paths != canonical_paths:
            raise ValueError("destructive workspace paths must be canonical and unique")
        for path in self.destructive_workspace_paths:
            _validate_workspace_path(path)

        boolean_values = (
            self.requests_privileged_container,
            self.requests_docker_socket_mount,
            self.requests_host_filesystem_mount,
            self.requests_arbitrary_host_command,
        )
        if any(not isinstance(value, bool) for value in boolean_values):
            raise TypeError("high-impact prohibited-operation markers must be boolean")

    def to_snapshot(self) -> dict[str, object]:
        """Return the exact approval payload without secrets or host paths."""
        return {
            "schema_version": self.schema_version,
            "project_id": str(self.project_id),
            "operation_kind": self.operation_kind.value,
            "summary": self.summary,
            "profile_reference": self.profile_reference.to_snapshot(),
            "capability_status": self.capability_status.value,
            "command_plan": (
                None
                if self.command_plan_id is None
                else {
                    "plan_id": self.command_plan_id,
                    "content_hash": self.command_plan_content_hash,
                }
            ),
            "image_reference": (
                None if self.image_reference is None else self.image_reference.value
            ),
            "network_mode": self.network_mode.value,
            "secret_reference_ids": list(self.secret_reference_ids),
            "resources": self.resources.to_snapshot(),
            "destructive_workspace_paths": list(self.destructive_workspace_paths),
            "requests_privileged_container": self.requests_privileged_container,
            "requests_docker_socket_mount": self.requests_docker_socket_mount,
            "requests_host_filesystem_mount": self.requests_host_filesystem_mount,
            "requests_arbitrary_host_command": self.requests_arbitrary_host_command,
        }

    @property
    def content_hash(self) -> str:
        """Return the immutable identity approved or rejected by Gate 7."""
        return snapshot_content_hash(self.to_snapshot())


@dataclass(frozen=True, slots=True)
class HighImpactOperationRequestVersion:
    """Append-only version of one exact high-impact operation request."""

    id: UUID
    project_id: UUID
    version_number: int
    based_on_version_number: int | None
    request: HighImpactExecutionRequest
    content_hash: str
    created_by_user_id: UUID
    created_at: datetime

    def __post_init__(self) -> None:
        """Protect project binding, linear lineage, content, and creation time."""
        validate_positive_integer(
            self.version_number,
            label="high-impact request version number",
        )
        validate_sha256(
            self.content_hash,
            label="high-impact request version content hash",
        )
        if self.request.project_id != self.project_id:
            raise ValueError("high-impact request payload belongs to another project")
        if self.content_hash != self.request.content_hash:
            raise ValueError("high-impact request version hash must match its payload")
        if self.version_number == 1:
            if self.based_on_version_number is not None:
                raise ValueError("first high-impact request version cannot have a predecessor")
        elif self.based_on_version_number != self.version_number - 1:
            raise ValueError("high-impact request versions require linear lineage")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("high-impact request creation time must be timezone-aware")

    @property
    def reference(self) -> HighImpactOperationReference:
        """Return the exact artifact tuple targeted by a Gate 7 decision."""
        return HighImpactOperationReference(
            request_id=self.id,
            project_id=self.project_id,
            version_number=self.version_number,
            content_hash=self.content_hash,
        )

    def to_snapshot(self) -> dict[str, object]:
        """Return immutable version metadata and approval payload."""
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "version_number": self.version_number,
            "based_on_version_number": self.based_on_version_number,
            "content_hash": self.content_hash,
            "request": self.request.to_snapshot(),
            "created_by_user_id": str(self.created_by_user_id),
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class HighImpactOperationReference:
    """Exact request ID, version, and hash used for stale-decision rejection."""

    request_id: UUID
    project_id: UUID
    version_number: int
    content_hash: str

    def __post_init__(self) -> None:
        validate_positive_integer(
            self.version_number,
            label="high-impact operation reference version",
        )
        validate_sha256(
            self.content_hash,
            label="high-impact operation reference content hash",
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "request_id": str(self.request_id),
            "project_id": str(self.project_id),
            "version_number": self.version_number,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class HighImpactOperationPolicy:
    """Deterministic trust anchors and baseline resource limits for classification."""

    approved_image_references: frozenset[str]
    baseline_resources: SandboxResourceLimits
    protected_workspace_components: frozenset[str]
    schema_version: int = _HIGH_IMPACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Require digest-pinned images and canonical protected path tokens."""
        if self.schema_version != _HIGH_IMPACT_SCHEMA_VERSION:
            raise ValueError("unsupported high-impact policy schema version")
        for image in self.approved_image_references:
            ContainerImageReference(image)
        if not self.protected_workspace_components or any(
            not component
            or component != component.casefold()
            or component != component.strip()
            or "/" in component
            or "\\" in component
            for component in self.protected_workspace_components
        ):
            raise ValueError("protected workspace components must be lowercase tokens")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "approved_image_references": sorted(self.approved_image_references),
            "baseline_resources": self.baseline_resources.to_snapshot(),
            "protected_workspace_components": sorted(self.protected_workspace_components),
        }

    @property
    def content_hash(self) -> str:
        return snapshot_content_hash(self.to_snapshot())


DEFAULT_HIGH_IMPACT_OPERATION_POLICY: Final = HighImpactOperationPolicy(
    approved_image_references=frozenset(),
    baseline_resources=DEFAULT_SANDBOX_RESOURCE_LIMITS,
    protected_workspace_components=frozenset({".git", ".orchestwin", ".ssh"}),
)


@dataclass(frozen=True, slots=True)
class HighImpactClassificationReason:
    """One deterministic reason supporting a classification result."""

    code: HighImpactReasonCode
    message: str

    def __post_init__(self) -> None:
        if not self.message or self.message != " ".join(self.message.split()):
            raise ValueError("high-impact classification reason must be normalized")

    def to_snapshot(self) -> dict[str, str]:
        return {"code": self.code.value, "message": self.message}


@dataclass(frozen=True, slots=True)
class HighImpactClassificationResult:
    """Policy decision bound to an exact request version and policy hash."""

    request_reference: HighImpactOperationReference
    policy_content_hash: str
    classification: HighImpactClassification
    reasons: tuple[HighImpactClassificationReason, ...]

    def __post_init__(self) -> None:
        validate_sha256(
            self.policy_content_hash,
            label="high-impact classification policy hash",
        )
        ordered = tuple(sorted(self.reasons, key=lambda reason: reason.code.value))
        if self.reasons != ordered or len({reason.code for reason in self.reasons}) != len(
            self.reasons
        ):
            raise ValueError("high-impact classification reasons must be canonical and unique")
        if self.classification is HighImpactClassification.ALLOWED_WITHOUT_APPROVAL:
            if self.reasons:
                raise ValueError("allowed high-impact classification cannot contain reasons")
        elif not self.reasons:
            raise ValueError("non-allowed high-impact classification requires reasons")

    @property
    def requires_owner_approval(self) -> bool:
        return self.classification is HighImpactClassification.REQUIRES_OWNER_APPROVAL

    def to_snapshot(self) -> dict[str, object]:
        return {
            "request_reference": self.request_reference.to_snapshot(),
            "policy_content_hash": self.policy_content_hash,
            "classification": self.classification.value,
            "reasons": [reason.to_snapshot() for reason in self.reasons],
        }


def classify_high_impact_operation(
    version: HighImpactOperationRequestVersion,
    *,
    policy: HighImpactOperationPolicy = DEFAULT_HIGH_IMPACT_OPERATION_POLICY,
) -> HighImpactClassificationResult:
    """Classify one exact operation without executing it or mutating gate state."""
    request = version.request
    forbidden: list[HighImpactClassificationReason] = []
    approval: list[HighImpactClassificationReason] = []

    if request.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C:
        forbidden.append(
            _reason(
                HighImpactReasonCode.DESIGN_ONLY_EXECUTION,
                "Design-only profiles cannot authorize automatic execution.",
            )
        )
    if request.requests_privileged_container:
        forbidden.append(
            _reason(
                HighImpactReasonCode.PRIVILEGED_CONTAINER,
                "Privileged containers are forbidden by platform policy.",
            )
        )
    if request.requests_docker_socket_mount:
        forbidden.append(
            _reason(
                HighImpactReasonCode.DOCKER_SOCKET_MOUNT,
                "Mounting the Docker socket is forbidden by platform policy.",
            )
        )
    if request.requests_host_filesystem_mount:
        forbidden.append(
            _reason(
                HighImpactReasonCode.HOST_FILESYSTEM_MOUNT,
                "Host filesystem mounts outside the workspace are forbidden.",
            )
        )
    if request.requests_arbitrary_host_command:
        forbidden.append(
            _reason(
                HighImpactReasonCode.ARBITRARY_HOST_COMMAND,
                "Arbitrary host commands are forbidden by platform policy.",
            )
        )
    if any(_is_protected_path(path, policy=policy) for path in request.destructive_workspace_paths):
        forbidden.append(
            _reason(
                HighImpactReasonCode.PROTECTED_WORKSPACE_PATH,
                "Protected workspace paths cannot be modified destructively.",
            )
        )

    if forbidden:
        return _classification_result(
            version,
            policy=policy,
            classification=HighImpactClassification.FORBIDDEN_BY_POLICY,
            reasons=forbidden,
        )

    if request.capability_status is ExecutionCapabilityStatus.EXPERIMENTAL_LEVEL_D:
        approval.append(
            _reason(
                HighImpactReasonCode.EXPERIMENTAL_PROFILE,
                "Experimental Level D profiles require exact owner approval.",
            )
        )
    if request.network_mode is CommandNetworkMode.CONTROLLED:
        approval.append(
            _reason(
                HighImpactReasonCode.CONTROLLED_NETWORK,
                "Controlled network access requires exact owner approval.",
            )
        )
    if request.secret_reference_ids:
        approval.append(
            _reason(
                HighImpactReasonCode.SECRET_ACCESS,
                "Resolving secret references requires exact owner approval.",
            )
        )
    if (
        request.image_reference is not None
        and request.image_reference.value not in policy.approved_image_references
    ):
        approval.append(
            _reason(
                HighImpactReasonCode.UNAPPROVED_IMAGE,
                "An image outside the approved registry requires owner approval.",
            )
        )
    if _exceeds_baseline(request.resources, policy.baseline_resources):
        approval.append(
            _reason(
                HighImpactReasonCode.RESOURCE_LIMIT_INCREASE,
                "Resource limits above the baseline require owner approval.",
            )
        )
    if request.destructive_workspace_paths:
        approval.append(
            _reason(
                HighImpactReasonCode.DESTRUCTIVE_WORKSPACE_CHANGE,
                "Destructive workspace changes require exact owner approval.",
            )
        )

    return _classification_result(
        version,
        policy=policy,
        classification=(
            HighImpactClassification.REQUIRES_OWNER_APPROVAL
            if approval
            else HighImpactClassification.ALLOWED_WITHOUT_APPROVAL
        ),
        reasons=approval,
    )


def _classification_result(
    version: HighImpactOperationRequestVersion,
    *,
    policy: HighImpactOperationPolicy,
    classification: HighImpactClassification,
    reasons: list[HighImpactClassificationReason],
) -> HighImpactClassificationResult:
    return HighImpactClassificationResult(
        request_reference=version.reference,
        policy_content_hash=policy.content_hash,
        classification=classification,
        reasons=tuple(sorted(reasons, key=lambda reason: reason.code.value)),
    )


def _reason(code: HighImpactReasonCode, message: str) -> HighImpactClassificationReason:
    return HighImpactClassificationReason(code=code, message=message)


def _exceeds_baseline(
    requested: SandboxResourceLimits,
    baseline: SandboxResourceLimits,
) -> bool:
    return (
        requested.cpu_count > baseline.cpu_count
        or requested.memory_mib > baseline.memory_mib
        or requested.pids_limit > baseline.pids_limit
        or requested.writable_tmpfs_mib > baseline.writable_tmpfs_mib
    )


def _is_protected_path(path: str, *, policy: HighImpactOperationPolicy) -> bool:
    if path == ".":
        return True
    return any(
        component.casefold() in policy.protected_workspace_components
        for component in PurePosixPath(path).parts
    )


def _validate_identifier(value: str, *, label: str) -> None:
    if _IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a normalized portable identifier")


def _validate_workspace_path(value: str) -> None:
    if (
        not value
        or value != value.strip()
        or value != unicodedata.normalize("NFC", value)
        or "\\" in value
        or "\x00" in value
        or value.startswith("/")
        or _WINDOWS_DRIVE_PATTERN.match(value) is not None
    ):
        raise ValueError("destructive workspace path must be normalized and relative")
    if value == ".":
        return
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("destructive workspace path must stay inside the workspace")
    if PurePosixPath(value).as_posix() != value:
        raise ValueError("destructive workspace path must be canonical")
