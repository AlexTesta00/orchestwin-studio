"""Shared least-privilege contracts for JVM container runner adapters."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from uuid import UUID

from orchestwin.jvm_execution.plans import (
    JvmExecutionPhase,
    JvmExecutionPlanBundle,
    JvmPhaseExecutionKind,
    create_jvm_execution_plan_bundle,
)
from orchestwin.jvm_execution.targets import JvmBuildSystem
from orchestwin.sandbox.command_plans import CommandNetworkMode
from orchestwin.sandbox.container_runtime import (
    ContainerEnvironmentVariable,
    ContainerExecutionRequest,
    ContainerImageReference,
)
from orchestwin.sandbox.execution_policy import (
    SandboxExecutionPolicy,
    SandboxResourceLimits,
    validate_sandbox_plan,
)
from orchestwin.sandbox.execution_profiles import ExecutionCapabilityStatus

_RUNNER_ID_PATTERN: Final = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_VERSION_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_REPOSITORY_PATTERN: Final = re.compile(r"^[a-z0-9]+(?:[._/-][a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class JvmContainerRunnerContract:
    """One exact runner identity and policy for shell-free JVM phase execution."""

    runner_id: str
    version: str
    build_system: JvmBuildSystem
    execution_kind: JvmPhaseExecutionKind
    executable: str
    image_repository: str
    image: ContainerImageReference
    runtime_environment_keys: frozenset[str]
    execution_policy: SandboxExecutionPolicy
    resources: SandboxResourceLimits
    capability_status: ExecutionCapabilityStatus = ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
    validation_evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if _RUNNER_ID_PATTERN.fullmatch(self.runner_id) is None:
            raise ValueError("JVM runner ID must be a normalized portable identifier")
        if _VERSION_PATTERN.fullmatch(self.version) is None:
            raise ValueError("JVM runner version must be normalized")
        if _REPOSITORY_PATTERN.fullmatch(self.image_repository) is None:
            raise ValueError("JVM runner image repository must be normalized")
        if self.image.value.split("@sha256:", maxsplit=1)[0] != self.image_repository:
            raise ValueError("JVM runner image does not match its repository identity")
        if not self.executable or self.executable != self.executable.strip():
            raise ValueError("JVM runner executable must be normalized")
        expected_kind = (
            JvmPhaseExecutionKind.GRADLE
            if self.build_system is JvmBuildSystem.GRADLE_KOTLIN_DSL
            else JvmPhaseExecutionKind.SBT
        )
        if self.execution_kind is not expected_kind:
            raise ValueError("JVM runner execution kind does not match its build system")
        if self.execution_policy.allowed_executables != frozenset({self.executable}):
            raise ValueError("JVM runner policy must allow only its exact executable")
        if self.execution_policy.allowed_network_modes != frozenset(
            {CommandNetworkMode.CONTROLLED, CommandNetworkMode.DISABLED}
        ):
            raise ValueError("JVM runner policy must separate setup and offline phases")
        if not self.runtime_environment_keys <= self.execution_policy.allowed_environment_keys:
            raise ValueError("JVM runner environment exceeds its execution policy")
        if self.resources.cpu_count > self.execution_policy.maximum_cpu_count:
            raise ValueError("JVM runner CPU request exceeds its policy")
        if self.resources.memory_mib > self.execution_policy.maximum_memory_mib:
            raise ValueError("JVM runner memory request exceeds its policy")
        if self.resources.pids_limit > self.execution_policy.maximum_pids:
            raise ValueError("JVM runner PID request exceeds its policy")
        if self.resources.writable_tmpfs_mib > self.execution_policy.maximum_writable_tmpfs_mib:
            raise ValueError("JVM runner temporary storage exceeds its policy")
        _require_canonical_text(
            self.validation_evidence_refs,
            label="JVM runner validation evidence",
        )
        if self.capability_status is ExecutionCapabilityStatus.VALIDATED_LEVEL_D:
            if not self.validation_evidence_refs:
                raise ValueError("validated JVM runner requires durable evidence references")
        elif self.validation_evidence_refs:
            raise ValueError("non-validated JVM runner must not claim validation evidence")

    def create_request(
        self,
        *,
        run_id: UUID,
        execution_plan: JvmExecutionPlanBundle,
        phase: JvmExecutionPhase,
        workspace_path: Path,
        environment_variables: tuple[ContainerEnvironmentVariable, ...] = (),
    ) -> ContainerExecutionRequest:
        """Create one policy-bound request for an exact canonical phase plan."""
        if execution_plan.target_selection.build_system is not self.build_system:
            raise ValueError("JVM runner cannot execute another build-system family")
        canonical = create_jvm_execution_plan_bundle(execution_plan.target_selection)
        if execution_plan.content_hash != canonical.content_hash:
            raise ValueError("JVM runner accepts only the canonical execution plan")
        phase_plan = execution_plan.phase(phase)
        if phase_plan.execution_kind is not self.execution_kind:
            raise ValueError("JVM runner phase uses another execution kind")
        command_plan = phase_plan.command_plan
        if len(command_plan.commands) != 1:
            raise ValueError("JVM runner phase requires exactly one command")
        command = command_plan.commands[0]
        if command.executable != self.executable:
            raise ValueError("JVM runner phase contains an unexpected executable")
        expected_network = (
            CommandNetworkMode.CONTROLLED
            if phase is JvmExecutionPhase.SETUP
            else CommandNetworkMode.DISABLED
        )
        if command.network_mode is not expected_network:
            raise ValueError("JVM runner phase violates the setup/offline network boundary")

        ordered_environment = tuple(
            sorted(environment_variables, key=lambda variable: variable.key)
        )
        if environment_variables != ordered_environment:
            raise ValueError("JVM runner environment must use canonical key order")
        environment_keys = tuple(variable.key for variable in environment_variables)
        if len(environment_keys) != len(set(environment_keys)):
            raise ValueError("JVM runner environment keys must be unique")
        if not set(environment_keys) <= self.runtime_environment_keys:
            raise ValueError("JVM runner received an environment key outside its contract")
        if not set(environment_keys) <= command.allowed_environment_keys:
            raise ValueError("JVM runner environment key is absent from the command plan")

        report = validate_sandbox_plan(
            command_plan,
            resources=self.resources,
            policy=self.execution_policy,
        )
        if not report.is_accepted:
            raise ValueError("JVM runner command plan was rejected by its execution policy")
        return ContainerExecutionRequest(
            run_id=run_id,
            plan=command_plan,
            execution_policy=self.execution_policy,
            policy_report=report,
            image=self.image,
            workspace_path=workspace_path,
            environment_variables=environment_variables,
        )

    def to_safe_snapshot(self) -> dict[str, object]:
        """Expose runner identity without host paths or environment values."""
        return {
            "runner_id": self.runner_id,
            "version": self.version,
            "build_system": self.build_system.value,
            "execution_kind": self.execution_kind.value,
            "executable": self.executable,
            "image_repository": self.image_repository,
            "image_reference": self.image.value,
            "runtime_environment_keys": sorted(self.runtime_environment_keys),
            "capability_status": self.capability_status.value,
            "validation_evidence_refs": list(self.validation_evidence_refs),
            "execution_policy_hash": self.execution_policy.content_hash,
            "resources": self.resources.to_snapshot(),
        }


def create_jvm_runner_execution_policy(
    *,
    executable: str,
    planned_environment_keys: frozenset[str],
) -> SandboxExecutionPolicy:
    """Create the narrow common policy used by Gradle and sbt runners."""
    return SandboxExecutionPolicy(
        allowed_executables=frozenset({executable}),
        allowed_environment_keys=planned_environment_keys,
        allowed_secret_reference_ids=frozenset(),
        allowed_network_modes=frozenset(
            {CommandNetworkMode.CONTROLLED, CommandNetworkMode.DISABLED}
        ),
        prohibited_workspace_components=frozenset({".git", ".orchestwin", ".ssh"}),
        maximum_commands=1,
        maximum_command_timeout_seconds=600,
        maximum_plan_timeout_seconds=600,
        maximum_artifact_patterns_per_command=16,
        maximum_artifact_pattern_length=240,
        maximum_cpu_count=2.0,
        maximum_memory_mib=4096,
        maximum_pids=256,
        maximum_writable_tmpfs_mib=512,
    )


def default_jvm_runner_resources() -> SandboxResourceLimits:
    """Return bounded resources shared by initial JVM runner contracts."""
    return SandboxResourceLimits(
        cpu_count=2.0,
        memory_mib=4096,
        pids_limit=256,
        writable_tmpfs_mib=512,
    )


def _require_canonical_text(values: tuple[str, ...], *, label: str) -> None:
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError(f"{label} must be canonical and unique")
    if any(not value or value != " ".join(value.split()) for value in values):
        raise ValueError(f"{label} must contain normalized values")
