"""Tests for the Kotlin/JVM profile selected as the formal Case A."""

from __future__ import annotations

from dataclasses import replace

import pytest

from orchestwin.jvm_execution.kotlin_profile import KotlinJvmExecutionProfile
from orchestwin.jvm_execution.policy import JvmToolchainIssueCode
from orchestwin.jvm_execution.profile_contracts import (
    JvmProfileIssueCode,
    JvmProfileValidationStatus,
)
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


def test_kotlin_profile_creates_the_formal_case_contract_without_overclaiming() -> None:
    profile = KotlinJvmExecutionProfile()
    snapshot = snapshot_for(ExecutionTarget.JVM_KOTLIN)
    declaration = declaration_for(ExecutionTarget.JVM_KOTLIN)

    contract = profile.create_contract(
        snapshot,
        declaration,
        source_revision=source_revision_reference(),
        runner=runner_for(ExecutionTarget.JVM_KOTLIN),
    )

    assert contract.validation.status is JvmProfileValidationStatus.READY_FOR_VALIDATION
    assert contract.validation.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
    assert contract.execution_plan.target_selection.target is ExecutionTarget.JVM_KOTLIN
    assert contract.runner.runner_id == "jvm.gradle"
    assert "android" not in str(contract.to_snapshot()).casefold()


def test_kotlin_profile_reports_toolchain_version_drift() -> None:
    profile = KotlinJvmExecutionProfile()
    declaration = replace(
        declaration_for(ExecutionTarget.JVM_KOTLIN),
        language_version="2.5.0",
    )

    validation = profile.validate(
        snapshot_for(ExecutionTarget.JVM_KOTLIN),
        declaration,
    )

    assert validation.status is JvmProfileValidationStatus.INVALID
    assert any(
        issue.code is JvmProfileIssueCode.TOOLCHAIN_POLICY_FAILED
        and issue.subject.startswith(JvmToolchainIssueCode.LANGUAGE_VERSION_MISMATCH.value)
        for issue in validation.issues
    )


def test_kotlin_profile_rejects_java_sources_and_missing_main() -> None:
    java_validation = KotlinJvmExecutionProfile().validate(
        snapshot_for(ExecutionTarget.JVM_JAVA),
        declaration_for(ExecutionTarget.JVM_KOTLIN),
    )
    missing_main = KotlinJvmExecutionProfile().validate(
        snapshot_for(
            ExecutionTarget.JVM_KOTLIN,
            source_content="package example\nclass Calculator",
        ),
        declaration_for(ExecutionTarget.JVM_KOTLIN),
    )

    assert java_validation.status is JvmProfileValidationStatus.INVALID
    assert any(
        issue.code is JvmProfileIssueCode.TARGET_MISMATCH for issue in java_validation.issues
    )
    assert any(
        issue.code is JvmProfileIssueCode.ENTRYPOINT_MISSING for issue in missing_main.issues
    )


def test_kotlin_profile_rejects_an_sbt_runner() -> None:
    profile = KotlinJvmExecutionProfile()

    with pytest.raises(ValueError, match="unexpected runner identity"):
        profile.create_contract(
            snapshot_for(ExecutionTarget.JVM_KOTLIN),
            declaration_for(ExecutionTarget.JVM_KOTLIN),
            source_revision=source_revision_reference(),
            runner=runner_for(ExecutionTarget.JVM_SCALA),
        )
