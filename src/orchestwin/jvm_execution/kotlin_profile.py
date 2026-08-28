"""Fixed Kotlin/JVM Gradle execution profile for Sprint 09."""

from __future__ import annotations

from orchestwin.jvm_execution.profile_contracts import BaseJvmExecutionProfile
from orchestwin.sandbox.execution_profiles import ExecutionTarget


class KotlinJvmExecutionProfile(BaseJvmExecutionProfile):
    """Kotlin/JVM single-module application profile selected as formal Case A."""

    def __init__(self) -> None:
        super().__init__(
            target=ExecutionTarget.JVM_KOTLIN,
            runner_id="jvm.gradle",
            source_root="src/main/kotlin/",
            source_suffix=".kt",
            entrypoint_markers=("fun main(",),
        )
