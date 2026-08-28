"""Structured shell-free command plans for Java, Kotlin, and Scala projects."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from orchestwin.jvm_execution.targets import JvmBuildSystem, JvmTargetSelection, jvm_scope_for
from orchestwin.sandbox.command_plans import (
    CommandNetworkMode,
    CommandPlan,
    StructuredCommand,
)


class JvmExecutionPhase(StrEnum):
    """Ordered phases exposed by the JVM execution evidence model."""

    VALIDATE = "VALIDATE"
    SETUP = "SETUP"
    STATIC_CHECKS = "STATIC_CHECKS"
    BUILD = "BUILD"
    TEST = "TEST"
    RUN = "RUN"
    COLLECT_ARTIFACTS = "COLLECT_ARTIFACTS"


class JvmPhaseExecutionKind(StrEnum):
    """Runner family selected for one phase without accepting arbitrary executables."""

    GRADLE = "GRADLE"
    SBT = "SBT"


@dataclass(frozen=True, slots=True)
class JvmPhasePlan:
    """One phase bound to an exact target selection and structured command plan."""

    phase: JvmExecutionPhase
    execution_kind: JvmPhaseExecutionKind
    target_selection: JvmTargetSelection
    command_plan: CommandPlan

    def __post_init__(self) -> None:
        scope = jvm_scope_for(self.target_selection.target)
        self.target_selection.validate_against(scope)
        expected_kind = (
            JvmPhaseExecutionKind.GRADLE
            if self.target_selection.build_system is JvmBuildSystem.GRADLE_KOTLIN_DSL
            else JvmPhaseExecutionKind.SBT
        )
        if self.execution_kind is not expected_kind:
            raise ValueError("JVM phase execution kind does not match the target build system")
        if self.command_plan.profile_id != scope.profile_id:
            raise ValueError("JVM phase plan uses a command plan from another profile")
        if self.command_plan.profile_version != scope.profile_version:
            raise ValueError("JVM phase plan uses a command plan from another profile version")
        expected_prefix = f"jvm.{self.phase.value.lower()}"
        if not self.command_plan.plan_id.startswith(expected_prefix):
            raise ValueError("JVM phase plan ID does not identify its phase")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_snapshot())).hexdigest()

    def to_snapshot(self) -> dict[str, object]:
        return {
            "phase": self.phase.value,
            "execution_kind": self.execution_kind.value,
            "target_selection": self.target_selection.to_snapshot(),
            "command_plan": self.command_plan.to_snapshot(),
        }


@dataclass(frozen=True, slots=True)
class JvmExecutionPlanBundle:
    """Complete deterministic phase set for one target selection."""

    target_selection: JvmTargetSelection
    phases: tuple[JvmPhasePlan, ...]

    def __post_init__(self) -> None:
        expected = tuple(JvmExecutionPhase)
        actual = tuple(phase.phase for phase in self.phases)
        if actual != expected:
            raise ValueError("JVM execution bundle must contain every phase in canonical order")
        if any(phase.target_selection != self.target_selection for phase in self.phases):
            raise ValueError("JVM execution bundle phases must share one target selection")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_snapshot())).hexdigest()

    def phase(self, phase: JvmExecutionPhase) -> JvmPhasePlan:
        return next(item for item in self.phases if item.phase is phase)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "target_selection": self.target_selection.to_snapshot(),
            "phases": [phase.to_snapshot() for phase in self.phases],
        }


def create_jvm_execution_plan_bundle(
    selection: JvmTargetSelection,
) -> JvmExecutionPlanBundle:
    """Create the closed Gradle or sbt phase plan for one exact JVM target."""
    scope = jvm_scope_for(selection.target)
    selection.validate_against(scope)
    if selection.build_system is JvmBuildSystem.GRADLE_KOTLIN_DSL:
        phases = tuple(_gradle_phase(selection, phase) for phase in JvmExecutionPhase)
    else:
        phases = tuple(_sbt_phase(selection, phase) for phase in JvmExecutionPhase)
    return JvmExecutionPlanBundle(target_selection=selection, phases=phases)


def _gradle_phase(
    selection: JvmTargetSelection,
    phase: JvmExecutionPhase,
) -> JvmPhasePlan:
    scope = jvm_scope_for(selection.target)
    arguments_by_phase: dict[JvmExecutionPhase, tuple[str, ...]] = {
        JvmExecutionPhase.VALIDATE: ("--version", "--no-daemon"),
        JvmExecutionPhase.SETUP: ("dependencies", "--no-daemon"),
        JvmExecutionPhase.STATIC_CHECKS: (
            "check",
            "--offline",
            "--no-daemon",
            "-x",
            "test",
        ),
        JvmExecutionPhase.BUILD: ("assemble", "--offline", "--no-daemon"),
        JvmExecutionPhase.TEST: ("test", "--offline", "--no-daemon"),
        JvmExecutionPhase.RUN: ("run", "--offline", "--no-daemon"),
        JvmExecutionPhase.COLLECT_ARTIFACTS: (
            "tasks",
            "--offline",
            "--no-daemon",
        ),
    }
    artifacts_by_phase: dict[JvmExecutionPhase, frozenset[str]] = {
        JvmExecutionPhase.BUILD: frozenset({"build/libs/*.jar"}),
        JvmExecutionPhase.TEST: frozenset(
            {
                "build/reports/tests/test/**",
                "build/test-results/test/*.xml",
            }
        ),
        JvmExecutionPhase.COLLECT_ARTIFACTS: frozenset(
            {
                "build/libs/*.jar",
                "build/reports/**",
                "build/test-results/**/*.xml",
            }
        ),
    }
    command = _command(
        command_id=f"jvm.{phase.value.lower()}.gradle",
        executable="./gradlew",
        arguments=arguments_by_phase[phase],
        network_mode=(
            CommandNetworkMode.CONTROLLED
            if phase is JvmExecutionPhase.SETUP
            else CommandNetworkMode.DISABLED
        ),
        output_parser_id="jvm.gradle",
        artifact_patterns=artifacts_by_phase.get(phase, frozenset()),
        timeout_seconds=600 if phase in {JvmExecutionPhase.BUILD, JvmExecutionPhase.TEST} else 300,
    )
    return JvmPhasePlan(
        phase=phase,
        execution_kind=JvmPhaseExecutionKind.GRADLE,
        target_selection=selection,
        command_plan=CommandPlan(
            plan_id=f"jvm.{phase.value.lower()}.gradle",
            profile_id=scope.profile_id,
            profile_version=scope.profile_version,
            commands=(command,),
        ),
    )


def _sbt_phase(
    selection: JvmTargetSelection,
    phase: JvmExecutionPhase,
) -> JvmPhasePlan:
    scope = jvm_scope_for(selection.target)
    task_by_phase: dict[JvmExecutionPhase, str] = {
        JvmExecutionPhase.VALIDATE: "sbtVersion",
        JvmExecutionPhase.SETUP: "update",
        JvmExecutionPhase.STATIC_CHECKS: "compile",
        JvmExecutionPhase.BUILD: "package",
        JvmExecutionPhase.TEST: "test",
        JvmExecutionPhase.RUN: "run",
        JvmExecutionPhase.COLLECT_ARTIFACTS: "show fullClasspath",
    }
    artifacts_by_phase: dict[JvmExecutionPhase, frozenset[str]] = {
        JvmExecutionPhase.BUILD: frozenset({"target/scala-*/*.jar"}),
        JvmExecutionPhase.TEST: frozenset(
            {
                "target/test-reports/*.xml",
                "target/scala-*/test-reports/*.xml",
            }
        ),
        JvmExecutionPhase.COLLECT_ARTIFACTS: frozenset(
            {
                "target/scala-*/*.jar",
                "target/test-reports/*.xml",
            }
        ),
    }
    command = _command(
        command_id=f"jvm.{phase.value.lower()}.sbt",
        executable="sbt",
        arguments=("-batch", "-no-colors", task_by_phase[phase]),
        network_mode=(
            CommandNetworkMode.CONTROLLED
            if phase is JvmExecutionPhase.SETUP
            else CommandNetworkMode.DISABLED
        ),
        output_parser_id="jvm.sbt",
        artifact_patterns=artifacts_by_phase.get(phase, frozenset()),
        timeout_seconds=600 if phase in {JvmExecutionPhase.BUILD, JvmExecutionPhase.TEST} else 300,
    )
    return JvmPhasePlan(
        phase=phase,
        execution_kind=JvmPhaseExecutionKind.SBT,
        target_selection=selection,
        command_plan=CommandPlan(
            plan_id=f"jvm.{phase.value.lower()}.sbt",
            profile_id=scope.profile_id,
            profile_version=scope.profile_version,
            commands=(command,),
        ),
    )


def _command(
    *,
    command_id: str,
    executable: str,
    arguments: tuple[str, ...],
    network_mode: CommandNetworkMode,
    output_parser_id: str,
    artifact_patterns: frozenset[str],
    timeout_seconds: int,
) -> StructuredCommand:
    return StructuredCommand(
        command_id=command_id,
        executable=executable,
        arguments=arguments,
        working_directory=".",
        allowed_environment_keys=frozenset(
            {
                "GRADLE_USER_HOME",
                "HOME",
                "JAVA_HOME",
                "LANG",
                "SBT_OPTS",
            }
        ),
        secret_references=frozenset(),
        timeout_seconds=timeout_seconds,
        network_mode=network_mode,
        expected_exit_codes=frozenset({0}),
        output_parser_id=output_parser_id,
        artifact_patterns=artifact_patterns,
    )


def _canonical_json(value: dict[str, object]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
