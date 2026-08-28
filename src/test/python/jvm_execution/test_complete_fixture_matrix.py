"""Complete contract matrix for the JVM-only Sprint 09 profile boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from orchestwin.jvm_execution.detection import (
    JvmDetectionSnapshot,
    JvmDetectionStatus,
    JvmTextFile,
    detect_jvm_project,
)
from orchestwin.jvm_execution.evidence import JvmFailureCategory
from orchestwin.jvm_execution.gradle_evidence import parse_gradle_and_junit_evidence
from orchestwin.jvm_execution.plans import JvmExecutionPhase
from orchestwin.jvm_execution.profile_registry import create_sprint09_jvm_profile_registry
from orchestwin.jvm_execution.sbt_evidence import parse_sbt_and_scala_test_evidence
from orchestwin.sandbox.command_plans import CommandNetworkMode
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

_FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "jvm_execution"
_MATRIX_PATH = _FIXTURE_ROOT / "validation-matrix.json"
_TARGETS = (
    ExecutionTarget.JVM_JAVA,
    ExecutionTarget.JVM_KOTLIN,
    ExecutionTarget.JVM_SCALA,
)


def _load_matrix() -> dict[str, object]:
    return json.loads(_MATRIX_PATH.read_text(encoding="utf-8"))


def _snapshot(files: dict[str, str]) -> JvmDetectionSnapshot:
    paths = tuple(sorted(files))
    text_files = tuple(
        JvmTextFile(
            normalized_path=path,
            content=files[path],
            sha256_digest=hashlib.sha256(files[path].encode("utf-8")).hexdigest(),
        )
        for path in paths
    )
    inventory = "\n".join(
        f"{path}:{hashlib.sha256(files[path].encode('utf-8')).hexdigest()}" for path in paths
    )
    return JvmDetectionSnapshot(
        inventory_content_hash=hashlib.sha256(inventory.encode("utf-8")).hexdigest(),
        included_paths=paths,
        text_files=text_files,
    )


def test_matrix_declares_one_formal_case_and_two_technical_fixtures_without_mobile_scope() -> None:
    matrix = _load_matrix()

    assert matrix["formal_case"] == {
        "fixture_id": "jvm-kotlin-calculator",
        "target": "JVM_KOTLIN",
        "role": "FORMAL_CASE_A",
    }
    assert matrix["technical_fixtures"] == [
        {
            "fixture_id": "jvm-java-greeting",
            "target": "JVM_JAVA",
            "role": "TECHNICAL_FIXTURE",
        },
        {
            "fixture_id": "jvm-scala-greeting",
            "target": "JVM_SCALA",
            "role": "TECHNICAL_FIXTURE",
        },
    ]
    assert matrix["mobile_target_material_present"] is False
    assert matrix["runner_build_attested"] is False
    assert matrix["fixture_execution_attested"] is False
    assert matrix["general_llm_generation_attested"] is False


@pytest.mark.parametrize("target", _TARGETS)
def test_each_target_creates_one_ready_shell_free_contract_with_offline_post_setup(
    target: ExecutionTarget,
) -> None:
    registry = create_sprint09_jvm_profile_registry()
    profile = registry.for_target(target)
    assert profile is not None

    snapshot = snapshot_for(target)
    declaration = declaration_for(target)
    validation = profile.validate(snapshot, declaration)
    contract = profile.create_contract(
        snapshot,
        declaration,
        source_revision=source_revision_reference(),
        runner=runner_for(target),
    )

    assert validation.is_ready
    assert validation.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
    assert contract.validation.content_hash == validation.content_hash
    assert tuple(phase.phase for phase in contract.execution_plan.phases) == tuple(
        JvmExecutionPhase
    )
    for phase in contract.execution_plan.phases:
        command = phase.command_plan.commands[0]
        assert command.executable in {"./gradlew", "sbt"}
        assert ";" not in " ".join(command.arguments)
        assert command.network_mode is (
            CommandNetworkMode.CONTROLLED
            if phase.phase is JvmExecutionPhase.SETUP
            else CommandNetworkMode.DISABLED
        )


def test_manifest_project_shapes_match_the_exact_registered_profiles() -> None:
    matrix = _load_matrix()
    shapes = matrix["validated_project_shapes"]
    assert isinstance(shapes, dict)
    registry = create_sprint09_jvm_profile_registry()

    for target in _TARGETS:
        profile = registry.for_target(target)
        assert profile is not None
        expected = shapes[target.value]
        assert isinstance(expected, dict)
        assert expected["build_system"] == profile.scope.build_system.value
        assert expected["jdk_major"] == profile.scope.jdk_major
        assert expected["language_version"] == profile.scope.language_version
        assert expected["runner_id"] == profile.expected_runner_id


def test_complete_failure_taxonomy_and_required_scenarios_are_explicit() -> None:
    matrix = _load_matrix()

    assert matrix["failure_categories"] == [category.value for category in JvmFailureCategory]
    assert matrix["required_scenarios"] == [
        "valid-profile-contract",
        "compile-failure",
        "unit-test-failure",
        "runtime-failure",
        "timeout",
        "resource-limit",
        "artifact-inventory",
        "repair-rerun",
        "unsupported-build-system",
        "mixed-language-conflict",
        "mobile-target-rejection",
    ]


def test_gradle_and_sbt_diagnostics_cover_java_kotlin_and_scala_compile_failures() -> None:
    java = parse_gradle_and_junit_evidence(
        "/tmp/workspace/src/main/java/example/Main.java:7: error: cannot find symbol"
    )
    kotlin = parse_gradle_and_junit_evidence(
        "e: file:///tmp/workspace/src/main/kotlin/example/Main.kt:4:12 Unresolved reference: total"
    )
    scala = parse_sbt_and_scala_test_evidence(
        "[error] -- [E006] Not Found Error: /tmp/workspace/src/main/scala/example/Main.scala:9:18"
    )

    assert java.findings[0].code == "JAVA_COMPILATION_ERROR"
    assert kotlin.findings[0].code == "KT_COMPILATION_ERROR"
    assert scala.findings[0].code == "SCALA_E006"
    assert java.build_failed and kotlin.build_failed and scala.build_failed


@pytest.mark.parametrize(
    ("files", "conflict_fragment"),
    [
        (
            {
                "pom.xml": "<project />",
                "src/main/java/example/Main.java": "class Main {}",
            },
            "Maven projects",
        ),
        (
            {
                "build.gradle.kts": "plugins { java }",
                "gradle/wrapper/gradle-wrapper.properties": "distributionUrl=x",
                "settings.gradle.kts": 'rootProject.name = "mixed"',
                "src/main/java/example/Main.java": "class Main {}",
                "src/main/kotlin/example/Main.kt": "fun main() = Unit",
            },
            "mixed JVM source languages",
        ),
        (
            {
                "AndroidManifest.xml": "<manifest />",
                "build.gradle.kts": 'plugins { id("com.android.application") }',
                "gradle/wrapper/gradle-wrapper.properties": "distributionUrl=x",
                "settings.gradle.kts": 'rootProject.name = "mobile"',
                "src/main/kotlin/example/Main.kt": "fun main() = Unit",
            },
            "Android",
        ),
    ],
)
def test_unsupported_maven_mixed_language_and_mobile_shapes_require_human_review(
    files: dict[str, str],
    conflict_fragment: str,
) -> None:
    result = detect_jvm_project(_snapshot(files))

    assert result.status is JvmDetectionStatus.HUMAN_DECISION_REQUIRED
    assert result.selected is None
    assert conflict_fragment in " ".join(result.conflicting_indicators)
