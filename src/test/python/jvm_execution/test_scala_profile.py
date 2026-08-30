"""Tests for the fixed Scala 3 JVM execution profile."""

from __future__ import annotations

from dataclasses import replace

import pytest

from orchestwin.jvm_execution.profile_contracts import (
    JvmProfileIssueCode,
    JvmProfileValidationStatus,
)
from orchestwin.jvm_execution.scala_profile import ScalaJvmExecutionProfile
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionTarget,
)

from .profile_support import (
    declaration_for,
    runner_for,
    snapshot_for,
    source_revision_reference,
)


def test_scala_profile_validates_and_creates_an_sbt_contract() -> None:
    profile = ScalaJvmExecutionProfile()
    snapshot = snapshot_for(ExecutionTarget.JVM_SCALA)
    declaration = declaration_for(ExecutionTarget.JVM_SCALA)

    contract = profile.create_contract(
        snapshot,
        declaration,
        source_revision=source_revision_reference(),
        runner=runner_for(ExecutionTarget.JVM_SCALA),
    )

    assert contract.validation.status is JvmProfileValidationStatus.READY_FOR_VALIDATION
    assert contract.validation.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
    assert contract.execution_plan.target_selection.target is ExecutionTarget.JVM_SCALA
    assert contract.runner.runner_id == "jvm.sbt"


def test_scala_profile_rejects_wrong_sbt_version_and_gradle_sources() -> None:
    profile = ScalaJvmExecutionProfile()
    wrong_version = replace(
        declaration_for(ExecutionTarget.JVM_SCALA),
        build_tool_version="1.13.0",
    )

    version_validation = profile.validate(
        snapshot_for(ExecutionTarget.JVM_SCALA),
        wrong_version,
    )
    kotlin_validation = profile.validate(
        snapshot_for(ExecutionTarget.JVM_KOTLIN),
        declaration_for(ExecutionTarget.JVM_SCALA),
    )

    assert version_validation.status is JvmProfileValidationStatus.INVALID
    assert any(
        issue.code is JvmProfileIssueCode.TOOLCHAIN_POLICY_FAILED
        for issue in version_validation.issues
    )
    assert kotlin_validation.status is JvmProfileValidationStatus.INVALID
    assert any(
        issue.code is JvmProfileIssueCode.TARGET_MISMATCH for issue in kotlin_validation.issues
    )


def test_scala_profile_requires_an_application_entrypoint() -> None:
    validation = ScalaJvmExecutionProfile().validate(
        snapshot_for(
            ExecutionTarget.JVM_SCALA,
            source_content="package example\nobject Calculator",
        ),
        declaration_for(ExecutionTarget.JVM_SCALA),
    )

    assert validation.status is JvmProfileValidationStatus.INVALID
    assert any(issue.code is JvmProfileIssueCode.ENTRYPOINT_MISSING for issue in validation.issues)


def test_scala_profile_rejects_the_gradle_runner() -> None:
    profile = ScalaJvmExecutionProfile()

    with pytest.raises(ValueError, match="unexpected runner identity"):
        profile.create_contract(
            snapshot_for(ExecutionTarget.JVM_SCALA),
            declaration_for(ExecutionTarget.JVM_SCALA),
            source_revision=source_revision_reference(),
            runner=runner_for(ExecutionTarget.JVM_JAVA),
        )
