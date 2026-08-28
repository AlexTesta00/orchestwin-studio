"""Fixed Scala 3 sbt execution profile for Sprint 09."""

from __future__ import annotations

from orchestwin.jvm_execution.profile_contracts import BaseJvmExecutionProfile
from orchestwin.sandbox.execution_profiles import ExecutionTarget


class ScalaJvmExecutionProfile(BaseJvmExecutionProfile):
    """Scala 3 single-project application profile using sbt."""

    def __init__(self) -> None:
        super().__init__(
            target=ExecutionTarget.JVM_SCALA,
            runner_id="jvm.sbt",
            source_root="src/main/scala/",
            source_suffix=".scala",
            entrypoint_markers=("@main", "def main("),
        )
