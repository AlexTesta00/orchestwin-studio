"""Fixed Java 21 Gradle execution profile for Sprint 09."""

from __future__ import annotations

from orchestwin.jvm_execution.profile_contracts import BaseJvmExecutionProfile
from orchestwin.sandbox.execution_profiles import ExecutionTarget


class JavaJvmExecutionProfile(BaseJvmExecutionProfile):
    """Java 21 single-module application profile using the Gradle Kotlin DSL."""

    def __init__(self) -> None:
        super().__init__(
            target=ExecutionTarget.JVM_JAVA,
            runner_id="jvm.gradle",
            source_root="src/main/java/",
            source_suffix=".java",
            entrypoint_markers=("static void main(",),
        )
