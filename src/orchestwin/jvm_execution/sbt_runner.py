"""Constrained sbt runner contract for the Scala JVM profile."""

from __future__ import annotations

from orchestwin.jvm_execution.plans import JvmPhaseExecutionKind
from orchestwin.jvm_execution.runner_contracts import (
    JvmContainerRunnerContract,
    create_jvm_runner_execution_policy,
    default_jvm_runner_resources,
)
from orchestwin.jvm_execution.targets import JvmBuildSystem
from orchestwin.sandbox.container_runtime import ContainerImageReference

_PLANNED_ENVIRONMENT_KEYS = frozenset({"GRADLE_USER_HOME", "HOME", "JAVA_HOME", "LANG", "SBT_OPTS"})
_SBT_RUNTIME_ENVIRONMENT_KEYS = frozenset({"HOME", "JAVA_HOME", "LANG", "SBT_OPTS"})


def create_sbt_jvm_runner_contract(
    image: ContainerImageReference,
) -> JvmContainerRunnerContract:
    """Create the repository-owned sbt runner without claiming Level D."""
    return JvmContainerRunnerContract(
        runner_id="jvm.sbt",
        version="1.0.0",
        build_system=JvmBuildSystem.SBT,
        execution_kind=JvmPhaseExecutionKind.SBT,
        executable="sbt",
        image_repository="orchestwin/jvm-sbt-runner",
        image=image,
        runtime_environment_keys=_SBT_RUNTIME_ENVIRONMENT_KEYS,
        execution_policy=create_jvm_runner_execution_policy(
            executable="sbt",
            planned_environment_keys=_PLANNED_ENVIRONMENT_KEYS,
        ),
        resources=default_jvm_runner_resources(),
    )
