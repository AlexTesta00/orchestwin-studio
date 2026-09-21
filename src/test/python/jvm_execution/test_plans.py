"""Tests for structured Gradle and sbt phase plans."""

from __future__ import annotations

from orchestwin.jvm_execution.plans import (
    JvmExecutionPhase,
    JvmPhaseExecutionKind,
    create_jvm_execution_plan_bundle,
)
from orchestwin.jvm_execution.targets import selection_for
from orchestwin.sandbox.command_plans import CommandNetworkMode
from orchestwin.sandbox.execution_profiles import ExecutionTarget


def test_kotlin_gradle_bundle_is_complete_tokenized_and_offline_after_setup() -> None:
    bundle = create_jvm_execution_plan_bundle(selection_for(ExecutionTarget.JVM_KOTLIN))

    assert tuple(phase.phase for phase in bundle.phases) == tuple(JvmExecutionPhase)
    assert all(phase.execution_kind is JvmPhaseExecutionKind.GRADLE for phase in bundle.phases)
    assert len(bundle.content_hash) == 64
    for phase in bundle.phases:
        command = phase.command_plan.commands[0]
        assert command.executable == "./gradlew"
        assert command.network_mode is (
            CommandNetworkMode.CONTROLLED
            if phase.phase is JvmExecutionPhase.SETUP
            else CommandNetworkMode.DISABLED
        )
        if phase.phase not in {JvmExecutionPhase.VALIDATE, JvmExecutionPhase.SETUP}:
            assert "--offline" in command.arguments
        assert command.timeout_seconds == (
            600
            if phase.phase
            in {
                JvmExecutionPhase.SETUP,
                JvmExecutionPhase.BUILD,
                JvmExecutionPhase.TEST,
            }
            else 300
        )


def test_java_uses_same_gradle_contract_but_a_distinct_profile() -> None:
    java = create_jvm_execution_plan_bundle(selection_for(ExecutionTarget.JVM_JAVA))
    kotlin = create_jvm_execution_plan_bundle(selection_for(ExecutionTarget.JVM_KOTLIN))

    assert java.phase(JvmExecutionPhase.BUILD).command_plan.profile_id == "jvm.java-gradle"
    assert kotlin.phase(JvmExecutionPhase.BUILD).command_plan.profile_id == "jvm.kotlin-gradle"
    assert java.content_hash != kotlin.content_hash


def test_gradle_setup_materializes_artifacts_with_trusted_resolver_and_strict_checksums() -> None:
    bundle = create_jvm_execution_plan_bundle(selection_for(ExecutionTarget.JVM_JAVA))
    command = bundle.phase(JvmExecutionPhase.SETUP).command_plan.commands[0]

    assert command.arguments == (
        "--init-script",
        "/opt/orchestwin/resolve-dependencies.gradle.kts",
        "orchestwinResolveDependencies",
        "--dependency-verification",
        "strict",
        "--no-daemon",
        "--console=plain",
    )
    assert all(
        "--write-verification-metadata" not in phase.command_plan.commands[0].arguments
        for phase in bundle.phases
    )


def test_sbt_validates_launcher_offline_then_resolves_compiler_and_bridge_during_setup() -> None:
    bundle = create_jvm_execution_plan_bundle(selection_for(ExecutionTarget.JVM_SCALA))

    assert bundle.phase(JvmExecutionPhase.VALIDATE).command_plan.commands[0].arguments == (
        "-batch",
        "-no-colors",
        "--script-version",
    )
    assert bundle.phase(JvmExecutionPhase.SETUP).command_plan.commands[0].arguments == (
        "-batch",
        "-no-colors",
        "update",
        "scalaInstance",
        "scalaCompilerBridgeBinaryJar",
    )


def test_scala_sbt_bundle_never_uses_a_shell_string_or_gradle() -> None:
    bundle = create_jvm_execution_plan_bundle(selection_for(ExecutionTarget.JVM_SCALA))

    assert all(phase.execution_kind is JvmPhaseExecutionKind.SBT for phase in bundle.phases)
    for phase in bundle.phases:
        command = phase.command_plan.commands[0]
        assert command.executable == "sbt"
        assert command.arguments[:2] == ("-batch", "-no-colors")
        assert command.network_mode is (
            CommandNetworkMode.CONTROLLED
            if phase.phase is JvmExecutionPhase.SETUP
            else CommandNetworkMode.DISABLED
        )
        assert ";" not in " ".join(command.arguments)


def test_artifact_collection_is_explicit_for_gradle_and_sbt() -> None:
    gradle = create_jvm_execution_plan_bundle(selection_for(ExecutionTarget.JVM_KOTLIN))
    sbt = create_jvm_execution_plan_bundle(selection_for(ExecutionTarget.JVM_SCALA))

    assert (
        "build/libs/*.jar"
        in gradle.phase(JvmExecutionPhase.COLLECT_ARTIFACTS)
        .command_plan.commands[0]
        .artifact_patterns
    )
    assert (
        "target/scala-*/*.jar"
        in sbt.phase(JvmExecutionPhase.COLLECT_ARTIFACTS).command_plan.commands[0].artifact_patterns
    )
