"""Tests for sbt compilation and Scala test evidence parsing."""

from __future__ import annotations

import pytest

from orchestwin.jvm_execution.sbt_evidence import (
    SbtCompilationStatus,
    parse_sbt_and_scala_test_evidence,
)

_JUNIT = b"""<testsuite name="CalculatorSpec" tests="3" failures="1" time="0.4">
  <testcase classname="example.CalculatorSpec" name="addition" time="0.1" />
  <testcase classname="example.CalculatorSpec" name="subtraction" time="0.1" />
  <testcase classname="example.CalculatorSpec" name="division by zero" time="0.2">
    <failure message="expected Left but received Right">trace</failure>
  </testcase>
</testsuite>"""


def test_sbt_parser_combines_textual_counts_and_exact_junit_cases() -> None:
    result = parse_sbt_and_scala_test_evidence(
        "\n".join(
            (
                "[info] compiling 2 Scala sources to /tmp/classes ...",
                "[info] done compiling",
                "[error] - division by zero *** FAILED ***",
                "[info] Tests: succeeded 2, failed 1, canceled 0, ignored 0, pending 0",
                "[error] Failed tests:",
                "[error] example.CalculatorSpec",
            )
        ),
        junit_xml_documents=(_JUNIT,),
    )

    assert result.compilation_status is SbtCompilationStatus.PASSED
    assert result.reported_test_counts is not None
    assert result.reported_test_counts.total == 3
    assert result.test_summary.total == 3
    assert result.test_summary.failed == 1
    assert result.failed_suites == ("example.CalculatorSpec",)
    assert result.build_failed is True


def test_sbt_parser_normalizes_scala_compiler_locations() -> None:
    result = parse_sbt_and_scala_test_evidence(
        "[error] C:\\workspace\\src\\main\\scala\\example\\Main.scala:7:12: "
        "Not found: value missing"
    )

    assert result.compilation_status is SbtCompilationStatus.FAILED
    assert result.findings[0].code == "SCALA_COMPILATION_ERROR"
    assert result.findings[0].location == "src/main/scala/example/Main.scala:7:12"


def test_sbt_parser_reports_text_xml_count_mismatch() -> None:
    result = parse_sbt_and_scala_test_evidence(
        "[info] Tests: succeeded 3, failed 0, canceled 0, ignored 0, pending 0",
        junit_xml_documents=(_JUNIT,),
    )

    assert any(finding.code == "SBT_TEST_COUNT_MISMATCH" for finding in result.findings)
    assert result.build_failed is True


def test_sbt_parser_rejects_nul_or_oversized_console_evidence() -> None:
    with pytest.raises(ValueError, match="NUL"):
        parse_sbt_and_scala_test_evidence("[info] ok\x00hidden")
    with pytest.raises(ValueError, match="size limit"):
        parse_sbt_and_scala_test_evidence("x" * (2 * 1024 * 1024 + 1))


def test_sbt_parser_recognizes_scala3_typed_diagnostics() -> None:
    result = parse_sbt_and_scala_test_evidence(
        "[error] -- [E006] Not Found Error: /tmp/workspace/src/main/scala/example/Main.scala:9:18"
    )

    assert result.compilation_status is SbtCompilationStatus.FAILED
    assert result.findings[0].code == "SCALA_E006"
    assert result.findings[0].location == "src/main/scala/example/Main.scala:9:18"
