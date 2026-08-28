"""Tests for deterministic JVM toolchain and dependency policy validation."""

from __future__ import annotations

from orchestwin.jvm_execution.policy import (
    JvmRepository,
    JvmToolchainDeclaration,
    JvmToolchainIssueCode,
    JvmToolchainValidationStatus,
    policy_for,
    validate_toolchain,
)
from orchestwin.sandbox.execution_profiles import ExecutionTarget


def declaration_for(target: ExecutionTarget) -> JvmToolchainDeclaration:
    policy = policy_for(target)
    return JvmToolchainDeclaration(
        selection=policy.selection,
        jdk_major=21,
        build_tool_version=policy.build_tool_version,
        language_version=policy.language_version,
        launcher_files_present=True,
        launcher_integrity_verified=True,
        dependency_verification_enabled=policy.require_dependency_verification,
        repositories=(JvmRepository.MAVEN_CENTRAL,),
        plugins=policy.allowed_plugins,
        network_disabled_after_setup=True,
    )


def test_java_kotlin_and_scala_baselines_are_exact() -> None:
    java = policy_for(ExecutionTarget.JVM_JAVA)
    kotlin = policy_for(ExecutionTarget.JVM_KOTLIN)
    scala = policy_for(ExecutionTarget.JVM_SCALA)

    assert (java.build_tool_version, java.language_version) == ("9.5.0", "21")
    assert (kotlin.build_tool_version, kotlin.language_version) == ("9.5.0", "2.4.10")
    assert (scala.build_tool_version, scala.language_version) == ("1.12.14", "3.3.8")
    assert len({java.content_hash, kotlin.content_hash, scala.content_hash}) == 3


def test_matching_declaration_is_valid() -> None:
    policy = policy_for(ExecutionTarget.JVM_KOTLIN)

    result = validate_toolchain(policy, declaration_for(ExecutionTarget.JVM_KOTLIN))

    assert result.status is JvmToolchainValidationStatus.VALID
    assert result.issues == ()
    assert result.policy_content_hash == policy.content_hash


def test_version_and_launcher_failures_are_reported_together() -> None:
    policy = policy_for(ExecutionTarget.JVM_JAVA)
    declaration = JvmToolchainDeclaration(
        selection=policy.selection,
        jdk_major=25,
        build_tool_version="9.7.0",
        language_version="25",
        launcher_files_present=False,
        launcher_integrity_verified=False,
        dependency_verification_enabled=False,
        repositories=(JvmRepository.MAVEN_CENTRAL,),
        plugins=policy.allowed_plugins,
        network_disabled_after_setup=True,
    )

    result = validate_toolchain(policy, declaration)
    codes = {issue.code for issue in result.issues}

    assert result.status is JvmToolchainValidationStatus.INVALID
    assert JvmToolchainIssueCode.JDK_VERSION_MISMATCH in codes
    assert JvmToolchainIssueCode.BUILD_TOOL_VERSION_MISMATCH in codes
    assert JvmToolchainIssueCode.LANGUAGE_VERSION_MISMATCH in codes
    assert JvmToolchainIssueCode.LAUNCHER_FILES_MISSING in codes
    assert JvmToolchainIssueCode.LAUNCHER_INTEGRITY_UNVERIFIED in codes
    assert JvmToolchainIssueCode.DEPENDENCY_VERIFICATION_DISABLED in codes


def test_unapproved_plugin_is_rejected() -> None:
    policy = policy_for(ExecutionTarget.JVM_KOTLIN)
    baseline = declaration_for(ExecutionTarget.JVM_KOTLIN)
    declaration = JvmToolchainDeclaration(
        selection=baseline.selection,
        jdk_major=baseline.jdk_major,
        build_tool_version=baseline.build_tool_version,
        language_version=baseline.language_version,
        launcher_files_present=True,
        launcher_integrity_verified=True,
        dependency_verification_enabled=True,
        repositories=baseline.repositories,
        plugins=tuple(sorted((*baseline.plugins, "org.springframework.boot"))),
        network_disabled_after_setup=True,
    )

    result = validate_toolchain(policy, declaration)

    assert any(
        issue.code is JvmToolchainIssueCode.PLUGIN_NOT_ALLOWED
        and issue.subject == "org.springframework.boot"
        for issue in result.issues
    )


def test_network_must_be_disabled_after_dependency_setup() -> None:
    policy = policy_for(ExecutionTarget.JVM_SCALA)
    baseline = declaration_for(ExecutionTarget.JVM_SCALA)
    declaration = JvmToolchainDeclaration(
        selection=baseline.selection,
        jdk_major=baseline.jdk_major,
        build_tool_version=baseline.build_tool_version,
        language_version=baseline.language_version,
        launcher_files_present=True,
        launcher_integrity_verified=True,
        dependency_verification_enabled=False,
        repositories=baseline.repositories,
        plugins=baseline.plugins,
        network_disabled_after_setup=False,
    )

    result = validate_toolchain(policy, declaration)

    assert any(
        issue.code is JvmToolchainIssueCode.NETWORK_POLICY_TOO_PERMISSIVE for issue in result.issues
    )
