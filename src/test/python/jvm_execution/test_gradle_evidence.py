"""Tests for Gradle task, compiler, and JUnit evidence parsing."""

from __future__ import annotations

import pytest

from orchestwin.jvm_execution.gradle_evidence import (
    GradleTaskStatus,
    parse_gradle_and_junit_evidence,
)

_JUNIT = b"""<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="CalculatorTest" tests="3" failures="1" skipped="1" time="0.3">
  <testcase classname="example.CalculatorTest" name="addsNumbers" time="0.1" />
  <testcase classname="example.CalculatorTest" name="dividesByZero" time="0.1">
    <failure message="expected an error message">stack trace</failure>
  </testcase>
  <testcase classname="example.CalculatorTest" name="futureFeature" time="0.1">
    <skipped />
  </testcase>
</testsuite>
"""


def test_gradle_parser_normalizes_tasks_and_exact_junit_cases() -> None:
    result = parse_gradle_and_junit_evidence(
        "\n".join(
            (
                "> Task :compileKotlin",
                "> Task :test FAILED",
                "BUILD FAILED in 2s",
            )
        ),
        junit_xml_documents=(_JUNIT,),
    )

    assert tuple((task.task_path, task.status) for task in result.tasks) == (
        (":compileKotlin", GradleTaskStatus.SUCCESS),
        (":test", GradleTaskStatus.FAILED),
    )
    assert result.test_summary.total == 3
    assert result.test_summary.passed == 1
    assert result.test_summary.failed == 1
    assert result.test_summary.skipped == 1
    assert result.build_failed is True


def test_gradle_parser_normalizes_java_and_kotlin_compiler_locations() -> None:
    result = parse_gradle_and_junit_evidence(
        "\n".join(
            (
                "C:\\workspace\\src\\main\\java\\example\\Main.java:7: error: cannot find symbol",
                "/tmp/workspace/src/main/kotlin/example/Main.kt:4:12: warning: unused value",
            )
        )
    )

    assert [finding.code for finding in result.findings] == [
        "JAVA_COMPILATION_ERROR",
        "KT_COMPILATION_WARNING",
    ]
    assert {finding.location for finding in result.findings} == {
        "src/main/java/example/Main.java:7",
        "src/main/kotlin/example/Main.kt:4:12",
    }
    assert result.build_failed is True


def test_gradle_parser_keeps_the_last_observed_task_state() -> None:
    result = parse_gradle_and_junit_evidence(
        "> Task :compileJava UP-TO-DATE\n> Task :compileJava FROM-CACHE"
    )

    assert result.tasks[0].status is GradleTaskStatus.FROM_CACHE
    assert result.build_failed is False


def test_junit_parser_rejects_malformed_or_entity_bearing_xml() -> None:
    with pytest.raises(ValueError, match="malformed"):
        parse_gradle_and_junit_evidence("", junit_xml_documents=(b"<testsuite>",))
    with pytest.raises(ValueError, match="entities are forbidden"):
        parse_gradle_and_junit_evidence(
            "",
            junit_xml_documents=(b"<!DOCTYPE x [<!ENTITY y 'z'>]><testsuite />",),
        )


def test_gradle_parser_supports_native_kotlin_diagnostics() -> None:
    result = parse_gradle_and_junit_evidence(
        "e: file:///tmp/workspace/src/main/kotlin/example/Main.kt:4:12 Unresolved reference: total"
    )

    assert result.findings[0].code == "KT_COMPILATION_ERROR"
    assert result.findings[0].location == "src/main/kotlin/example/Main.kt:4:12"
    assert result.build_failed is True


def test_gradle_warning_is_retained_without_falsely_failing_the_build() -> None:
    result = parse_gradle_and_junit_evidence(
        "/tmp/workspace/src/main/kotlin/example/Main.kt:4:12: warning: unused value"
    )

    assert result.findings[0].code == "KT_COMPILATION_WARNING"
    assert result.build_failed is False
