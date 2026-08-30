"""Deterministic builders shared by JVM profile contract tests."""

from __future__ import annotations

import hashlib
from uuid import UUID

from orchestwin.artifacts.jvm_sources import JvmSourceRevisionReference
from orchestwin.jvm_execution.detection import JvmDetectionSnapshot, JvmTextFile
from orchestwin.jvm_execution.gradle_runner import create_gradle_jvm_runner_contract
from orchestwin.jvm_execution.policy import (
    JvmRepository,
    JvmToolchainDeclaration,
    policy_for,
)
from orchestwin.jvm_execution.runner_contracts import JvmContainerRunnerContract
from orchestwin.jvm_execution.sbt_runner import create_sbt_jvm_runner_contract
from orchestwin.sandbox.container_runtime import ContainerImageReference
from orchestwin.sandbox.execution_profiles import ExecutionTarget


def snapshot_for(
    target: ExecutionTarget,
    *,
    source_content: str | None = None,
) -> JvmDetectionSnapshot:
    files = _files_for(target)
    source_path = _source_path_for(target)
    if source_content is not None:
        files[source_path] = source_content
    paths = tuple(sorted(files))
    text_files = tuple(
        JvmTextFile(
            normalized_path=path,
            content=files[path],
            sha256_digest=hashlib.sha256(files[path].encode("utf-8")).hexdigest(),
        )
        for path in paths
    )
    inventory_projection = "\n".join(
        f"{path}:{hashlib.sha256(files[path].encode('utf-8')).hexdigest()}" for path in paths
    )
    return JvmDetectionSnapshot(
        inventory_content_hash=hashlib.sha256(inventory_projection.encode("utf-8")).hexdigest(),
        included_paths=paths,
        text_files=text_files,
    )


def declaration_for(target: ExecutionTarget) -> JvmToolchainDeclaration:
    policy = policy_for(target)
    return JvmToolchainDeclaration(
        selection=policy.selection,
        jdk_major=policy.selection.jdk_major,
        build_tool_version=policy.build_tool_version,
        language_version=policy.language_version,
        launcher_files_present=True,
        launcher_integrity_verified=True,
        dependency_verification_enabled=policy.require_dependency_verification,
        repositories=(JvmRepository.MAVEN_CENTRAL,),
        plugins=policy.allowed_plugins,
        network_disabled_after_setup=True,
    )


def runner_for(target: ExecutionTarget) -> JvmContainerRunnerContract:
    if target is ExecutionTarget.JVM_SCALA:
        return create_sbt_jvm_runner_contract(
            ContainerImageReference("orchestwin/jvm-sbt-runner@sha256:" + "c" * 64)
        )
    return create_gradle_jvm_runner_contract(
        ContainerImageReference("orchestwin/jvm-gradle-runner@sha256:" + "d" * 64)
    )


def source_revision_reference() -> JvmSourceRevisionReference:
    return JvmSourceRevisionReference(
        revision_id=UUID("33333333-3333-4333-8333-333333333333"),
        project_id=UUID("44444444-4444-4444-8444-444444444444"),
        version_number=1,
        content_hash="e" * 64,
        source_tree_hash="f" * 64,
    )


def _source_path_for(target: ExecutionTarget) -> str:
    return {
        ExecutionTarget.JVM_JAVA: "src/main/java/example/Main.java",
        ExecutionTarget.JVM_KOTLIN: "src/main/kotlin/example/Main.kt",
        ExecutionTarget.JVM_SCALA: "src/main/scala/example/Main.scala",
    }[target]


def _files_for(target: ExecutionTarget) -> dict[str, str]:
    if target is ExecutionTarget.JVM_JAVA:
        return {
            "build.gradle.kts": "plugins { application; java }",
            "gradle/wrapper/gradle-wrapper.properties": (
                "distributionUrl=https://services.gradle.org/distributions/gradle-9.5.0-bin.zip"
            ),
            "settings.gradle.kts": 'rootProject.name = "sample"',
            _source_path_for(target): (
                "package example; public final class Main { "
                'public static void main(String[] args) { System.out.println("ready"); } }'
            ),
        }
    if target is ExecutionTarget.JVM_KOTLIN:
        return {
            "build.gradle.kts": 'plugins { application; kotlin("jvm") version "2.4.10" }',
            "gradle/wrapper/gradle-wrapper.properties": (
                "distributionUrl=https://services.gradle.org/distributions/gradle-9.5.0-bin.zip"
            ),
            "settings.gradle.kts": 'rootProject.name = "sample"',
            _source_path_for(target): 'package example\nfun main() = println("ready")',
        }
    if target is ExecutionTarget.JVM_SCALA:
        return {
            "build.sbt": 'scalaVersion := "3.3.8"',
            "project/build.properties": "sbt.version=1.12.14",
            _source_path_for(target): 'package example\n@main def run(): Unit = println("ready")',
        }
    raise ValueError("profile test support requires one Sprint 09 JVM target")
