"""Tests for the fixed Java JVM execution profile."""

from __future__ import annotations

import pytest

from orchestwin.jvm_execution.java_profile import JavaJvmExecutionProfile
from orchestwin.jvm_execution.profile_contracts import (
    JvmExecutionProfile,
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


def test_java_profile_validates_and_creates_an_exact_contract() -> None:
    profile = JavaJvmExecutionProfile()
    snapshot = snapshot_for(ExecutionTarget.JVM_JAVA)
    declaration = declaration_for(ExecutionTarget.JVM_JAVA)

    validation = profile.validate(snapshot, declaration)
    contract = profile.create_contract(
        snapshot,
        declaration,
        source_revision=source_revision_reference(),
        runner=runner_for(ExecutionTarget.JVM_JAVA),
    )

    assert isinstance(profile, JvmExecutionProfile)
    assert validation.status is JvmProfileValidationStatus.READY_FOR_VALIDATION
    assert validation.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
    assert validation.validation_evidence_refs == ()
    assert contract.execution_plan.target_selection.target is ExecutionTarget.JVM_JAVA
    assert contract.runner.runner_id == "jvm.gradle"
    assert len(contract.content_hash) == 64


def test_java_profile_rejects_a_kotlin_source_snapshot() -> None:
    validation = JavaJvmExecutionProfile().validate(
        snapshot_for(ExecutionTarget.JVM_KOTLIN),
        declaration_for(ExecutionTarget.JVM_JAVA),
    )

    assert validation.status is JvmProfileValidationStatus.INVALID
    assert any(issue.code is JvmProfileIssueCode.TARGET_MISMATCH for issue in validation.issues)


def test_java_profile_requires_a_deterministic_main_entrypoint() -> None:
    validation = JavaJvmExecutionProfile().validate(
        snapshot_for(
            ExecutionTarget.JVM_JAVA,
            source_content="package example; public final class Main {}",
        ),
        declaration_for(ExecutionTarget.JVM_JAVA),
    )

    assert validation.status is JvmProfileValidationStatus.INVALID
    assert any(issue.code is JvmProfileIssueCode.ENTRYPOINT_MISSING for issue in validation.issues)


def test_java_profile_rejects_the_sbt_runner() -> None:
    profile = JavaJvmExecutionProfile()
    snapshot = snapshot_for(ExecutionTarget.JVM_JAVA)
    declaration = declaration_for(ExecutionTarget.JVM_JAVA)

    with pytest.raises(ValueError, match="unexpected runner identity"):
        profile.create_contract(
            snapshot,
            declaration,
            source_revision=source_revision_reference(),
            runner=runner_for(ExecutionTarget.JVM_SCALA),
        )
