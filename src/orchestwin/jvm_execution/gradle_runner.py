"""Constrained Gradle Wrapper runner contract for Java and Kotlin JVM profiles."""

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
_GRADLE_RUNTIME_ENVIRONMENT_KEYS = frozenset({"GRADLE_USER_HOME", "HOME", "JAVA_HOME", "LANG"})


def create_gradle_jvm_runner_contract(
    image: ContainerImageReference,
) -> JvmContainerRunnerContract:
    """Create the repository-owned Gradle runner without claiming Level D."""
    return JvmContainerRunnerContract(
        runner_id="jvm.gradle",
        version="1.0.0",
        build_system=JvmBuildSystem.GRADLE_KOTLIN_DSL,
        execution_kind=JvmPhaseExecutionKind.GRADLE,
        executable="./gradlew",
        image_repository="orchestwin/jvm-gradle-runner",
        image=image,
        runtime_environment_keys=_GRADLE_RUNTIME_ENVIRONMENT_KEYS,
        execution_policy=create_jvm_runner_execution_policy(
            executable="./gradlew",
            planned_environment_keys=_PLANNED_ENVIRONMENT_KEYS,
        ),
        resources=default_jvm_runner_resources(),
    )
