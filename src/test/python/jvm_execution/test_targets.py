"""Tests for capability-honest Java, Kotlin, and Scala target scopes."""

from __future__ import annotations

import pytest

from orchestwin.jvm_execution.targets import (
    JvmBuildSystem,
    JvmImplementationLanguage,
    JvmProjectLayout,
    JvmTargetSelection,
    create_sprint09_jvm_validation_scopes,
    jvm_scope_for,
    selection_for,
)
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionTarget,
)


def test_sprint09_exposes_only_the_three_approved_jvm_targets() -> None:
    scopes = create_sprint09_jvm_validation_scopes()

    assert tuple(scopes) == (
        ExecutionTarget.JVM_JAVA,
        ExecutionTarget.JVM_KOTLIN,
        ExecutionTarget.JVM_SCALA,
    )
    assert all(
        scope.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
        for scope in scopes.values()
    )
    assert all(scope.validation_evidence_refs == () for scope in scopes.values())


def test_each_target_has_a_distinct_language_and_build_shape() -> None:
    java = jvm_scope_for(ExecutionTarget.JVM_JAVA)
    kotlin = jvm_scope_for(ExecutionTarget.JVM_KOTLIN)
    scala = jvm_scope_for(ExecutionTarget.JVM_SCALA)

    assert (java.language, java.build_system) == (
        JvmImplementationLanguage.JAVA,
        JvmBuildSystem.GRADLE_KOTLIN_DSL,
    )
    assert (kotlin.language, kotlin.build_system) == (
        JvmImplementationLanguage.KOTLIN,
        JvmBuildSystem.GRADLE_KOTLIN_DSL,
    )
    assert (scala.language, scala.build_system) == (
        JvmImplementationLanguage.SCALA,
        JvmBuildSystem.SBT,
    )
    assert {scope.content_hash for scope in (java, kotlin, scala)}.__len__() == 3


def test_canonical_selection_is_bound_to_the_scope() -> None:
    selection = selection_for(ExecutionTarget.JVM_KOTLIN)
    scope = jvm_scope_for(ExecutionTarget.JVM_KOTLIN)

    selection.validate_against(scope)
    assert selection.layout is JvmProjectLayout.SINGLE_MODULE
    assert selection.jdk_major == 21


def test_mismatched_language_is_rejected_at_selection_boundary() -> None:
    with pytest.raises(ValueError, match="outside the validation scope"):
        JvmTargetSelection(
            target=ExecutionTarget.JVM_JAVA,
            language=JvmImplementationLanguage.KOTLIN,
            build_system=JvmBuildSystem.GRADLE_KOTLIN_DSL,
            layout=JvmProjectLayout.SINGLE_MODULE,
            jdk_major=21,
        )


def test_non_jvm_target_is_outside_sprint09_scope() -> None:
    with pytest.raises(ValueError, match="outside the Sprint 09 JVM scope"):
        jvm_scope_for(ExecutionTarget.WEB_STATIC)


def test_android_targets_are_not_silently_reintroduced() -> None:
    scopes = create_sprint09_jvm_validation_scopes()

    assert ExecutionTarget.ANDROID_JAVA not in scopes
    assert ExecutionTarget.ANDROID_KOTLIN not in scopes
