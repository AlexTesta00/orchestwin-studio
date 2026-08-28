"""Tests for deterministic Java, Kotlin, and Scala project detection."""

from __future__ import annotations

import hashlib

from orchestwin.jvm_execution.detection import (
    JvmDetectionStatus,
    create_jvm_detection_snapshot,
    detect_jvm_project,
)
from orchestwin.sandbox.archive_policy import (
    SourceArchiveEntryDisposition,
    SourceArchiveEntryKind,
)
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.sandbox.source_inventory import (
    SourceInventoryClassification,
    SourceInventoryEntry,
    SourceTreeInventory,
)


def snapshot(files: dict[str, str]):
    entries = tuple(
        SourceInventoryEntry(
            normalized_path=path,
            kind=SourceArchiveEntryKind.FILE,
            classification=SourceInventoryClassification.SOURCE,
            size_bytes=len(content.encode("utf-8")),
            sha256_digest=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            disposition=SourceArchiveEntryDisposition.INCLUDE,
            disposition_reason=None,
        )
        for path, content in sorted(files.items())
    )
    inventory = SourceTreeInventory(archive_sha256="a" * 64, entries=entries)
    return create_jvm_detection_snapshot(inventory, text_content_by_path=files)


def gradle_files(source_path: str, source: str) -> dict[str, str]:
    return {
        "build.gradle.kts": "plugins { application }",
        "settings.gradle.kts": 'rootProject.name = "fixture"',
        "gradle/wrapper/gradle-wrapper.properties": "distributionUrl=https://services.gradle.org",
        source_path: source,
    }


def test_detects_single_module_java_gradle_project() -> None:
    result = detect_jvm_project(
        snapshot(gradle_files("src/main/java/example/Main.java", "class Main {}"))
    )

    assert result.status is JvmDetectionStatus.SELECTED
    assert result.selected is not None
    assert result.selected.selection.target is ExecutionTarget.JVM_JAVA


def test_detects_single_module_kotlin_gradle_project() -> None:
    result = detect_jvm_project(
        snapshot(gradle_files("src/main/kotlin/example/Main.kt", "fun main() = Unit"))
    )

    assert result.status is JvmDetectionStatus.SELECTED
    assert result.selected is not None
    assert result.selected.selection.target is ExecutionTarget.JVM_KOTLIN


def test_detects_single_project_scala_sbt_project() -> None:
    files = {
        "build.sbt": 'scalaVersion := "3.3.8"',
        "project/build.properties": "sbt.version=1.13.0",
        "src/main/scala/example/Main.scala": "object Main",
    }

    result = detect_jvm_project(snapshot(files))

    assert result.status is JvmDetectionStatus.SELECTED
    assert result.selected is not None
    assert result.selected.selection.target is ExecutionTarget.JVM_SCALA


def test_mixed_jvm_languages_require_a_human_decision() -> None:
    files = gradle_files("src/main/java/example/Main.java", "class Main {}")
    files["src/main/kotlin/example/Helper.kt"] = "class Helper"

    result = detect_jvm_project(snapshot(files))

    assert result.status is JvmDetectionStatus.HUMAN_DECISION_REQUIRED
    assert result.selected is None
    assert "mixed JVM source languages" in result.conflicting_indicators[0]


def test_maven_and_gradle_groovy_are_recognized_but_not_selected() -> None:
    files = {
        "pom.xml": "<project />",
        "build.gradle": "plugins { id 'java' }",
        "src/main/java/example/Main.java": "class Main {}",
    }

    result = detect_jvm_project(snapshot(files))

    assert result.status is JvmDetectionStatus.HUMAN_DECISION_REQUIRED
    assert result.selected is None
    assert any("Maven" in conflict for conflict in result.conflicting_indicators)
    assert any("Groovy" in conflict for conflict in result.conflicting_indicators)


def test_android_gradle_plugin_is_not_silently_treated_as_jvm_kotlin() -> None:
    files = gradle_files(
        "src/main/kotlin/example/Main.kt",
        "fun main() = Unit",
    )
    files["build.gradle.kts"] = 'plugins { id("com.android.application") }'
    files["src/main/AndroidManifest.xml"] = "<manifest />"

    result = detect_jvm_project(snapshot(files))

    assert result.status is JvmDetectionStatus.HUMAN_DECISION_REQUIRED
    assert result.selected is None
    assert any("Android" in conflict for conflict in result.conflicting_indicators)


def test_non_jvm_snapshot_is_explicitly_unsupported() -> None:
    result = detect_jvm_project(snapshot({"README.md": "No source yet."}))

    assert result.status is JvmDetectionStatus.UNSUPPORTED
    assert result.candidates == ()
    assert result.conflicting_indicators == ()
