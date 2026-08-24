"""Container execution requests and runtime port for approved command plans."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Protocol
from uuid import UUID

from orchestwin.sandbox.command_plans import CommandPlan, StructuredCommand
from orchestwin.sandbox.evidence import SandboxRunEvidence
from orchestwin.sandbox.execution_policy import (
    SandboxExecutionPolicy,
    SandboxPolicyReport,
    SandboxResourceLimits,
    validate_sandbox_plan,
)

_IMAGE_REFERENCE_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}$")
_ENVIRONMENT_KEY_PATTERN: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class ContainerImageReference:
    """Immutable digest-pinned container image reference."""

    value: str

    def __post_init__(self) -> None:
        """Reject tags, moving references, whitespace, and malformed digests."""
        if not _IMAGE_REFERENCE_PATTERN.fullmatch(self.value):
            raise ValueError("container image must be pinned by a lowercase SHA-256 digest")

    @property
    def digest(self) -> str:
        """Return the content digest without its algorithm prefix."""
        return self.value.rsplit("@sha256:", maxsplit=1)[1]


@dataclass(frozen=True, slots=True)
class ContainerEnvironmentVariable:
    """Resolved process environment value carried only at the adapter boundary."""

    key: str
    value: str
    is_secret: bool

    def __post_init__(self) -> None:
        """Reject invalid keys and values that cannot enter an argument vector."""
        if not _ENVIRONMENT_KEY_PATTERN.fullmatch(self.key):
            raise ValueError("container environment key must be portable")
        if not isinstance(self.value, str):
            raise TypeError("container environment value must be a string")
        if any(character in self.value for character in ("\x00", "\r", "\n")):
            raise ValueError("container environment value contains a control separator")
        if not isinstance(self.is_secret, bool):
            raise TypeError("container environment secret marker must be a boolean")

    def to_safe_snapshot(self) -> dict[str, str | bool]:
        """Return only metadata and never the resolved environment value."""
        return {
            "key": self.key,
            "is_secret": self.is_secret,
            "value_state": "REDACTED" if self.is_secret else "PRESENT",
        }


@dataclass(frozen=True, slots=True)
class ContainerExecutionRequest:
    """Exact policy-approved input for one ephemeral container runtime."""

    run_id: UUID
    plan: CommandPlan
    execution_policy: SandboxExecutionPolicy
    policy_report: SandboxPolicyReport
    image: ContainerImageReference
    workspace_path: Path
    environment_variables: tuple[ContainerEnvironmentVariable, ...]

    def __post_init__(self) -> None:
        """Protect plan binding, workspace isolation, and environment resolution."""
        if not self.policy_report.is_accepted:
            raise ValueError("container execution requires an accepted sandbox policy report")
        if self.policy_report.plan_content_hash != self.plan.content_hash:
            raise ValueError("container execution policy report targets another command plan")
        expected_report = validate_sandbox_plan(
            self.plan,
            resources=self.policy_report.resources,
            policy=self.execution_policy,
        )
        if self.policy_report != expected_report:
            raise ValueError(
                "container execution policy report does not match deterministic validation"
            )

        workspace = Path(self.workspace_path)
        if not workspace.is_absolute():
            raise ValueError("container workspace path must be absolute")
        if workspace.is_symlink() or not workspace.is_dir():
            raise ValueError("container workspace must be a regular non-symlink directory")
        object.__setattr__(self, "workspace_path", workspace)

        environment_keys = tuple(variable.key for variable in self.environment_variables)
        if len(environment_keys) != len(set(environment_keys)):
            raise ValueError("container environment keys must be unique")

        planned_environment_keys = frozenset(
            key for command in self.plan.commands for key in command.allowed_environment_keys
        )
        if not set(environment_keys) <= planned_environment_keys:
            raise ValueError("container environment contains keys absent from the command plan")

        secret_keys = frozenset(
            reference.environment_key
            for command in self.plan.commands
            for reference in command.secret_references
        )
        for variable in self.environment_variables:
            if variable.is_secret != (variable.key in secret_keys):
                raise ValueError(
                    "container environment secret markers must match command secret references"
                )

    @property
    def resources(self) -> SandboxResourceLimits:
        """Return the exact resource values covered by the policy decision."""
        return self.policy_report.resources

    def environment_for(
        self,
        command: StructuredCommand,
    ) -> tuple[ContainerEnvironmentVariable, ...]:
        """Return only values explicitly allowed by one command."""
        return tuple(
            variable
            for variable in self.environment_variables
            if variable.key in command.allowed_environment_keys
        )

    def to_safe_snapshot(self) -> dict[str, object]:
        """Return audit metadata without host paths or environment values."""
        return {
            "run_id": str(self.run_id),
            "plan_id": self.plan.plan_id,
            "plan_content_hash": self.plan.content_hash,
            "profile_id": self.plan.profile_id,
            "profile_version": self.plan.profile_version,
            "image_reference": self.image.value,
            "policy_report": self.policy_report.to_snapshot(),
            "resources": self.resources.to_snapshot(),
            "environment": [variable.to_safe_snapshot() for variable in self.environment_variables],
            "workspace_mounted": True,
        }


class ContainerRuntimePort(Protocol):
    """Port implemented by deterministic fake and constrained real runtimes."""

    async def execute(
        self,
        request: ContainerExecutionRequest,
    ) -> SandboxRunEvidence:
        """Execute one exact approved plan and retain terminal evidence."""
        ...


class UtcClock(Protocol):
    """Injectable UTC clock for deterministic runtime evidence."""

    def now(self) -> datetime:
        """Return the current UTC-aware time."""
        ...


class SystemUtcClock:
    """Production clock using timezone-aware UTC timestamps."""

    def now(self) -> datetime:
        """Return the current UTC-aware time."""
        return datetime.now(UTC)
