"""sbt compilation and Scala test evidence normalization."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final

from orchestwin.jvm_execution.evidence import JvmNormalizedFinding
from orchestwin.jvm_execution.test_results import (
    JvmTestSummary,
    parse_junit_xml_documents,
)

_MAX_CONSOLE_BYTES: Final = 2 * 1024 * 1024
_SCALA_DIAGNOSTIC_PATTERN: Final = re.compile(
    r"^\[error\]\s+(?P<path>.+?\.scala):(?P<line>\d+):(?P<column>\d+):\s*(?P<message>.+)$"
)
_SCALA3_DIAGNOSTIC_PATTERN: Final = re.compile(
    r"^\[error\]\s+--\s+\[(?P<code>E\d+)\]\s+.+?:\s+"
    r"(?P<path>.+?\.scala):(?P<line>\d+):(?P<column>\d+)\s*$"
)
_TEST_COUNTS_PATTERN: Final = re.compile(
    r"^\[info\]\s+Tests:\s+succeeded\s+(?P<succeeded>\d+),\s+"
    r"failed\s+(?P<failed>\d+),\s+canceled\s+(?P<canceled>\d+),\s+"
    r"ignored\s+(?P<ignored>\d+),\s+pending\s+(?P<pending>\d+)\s*$"
)
_FAILED_TEST_PATTERN: Final = re.compile(
    r"^\[(?:error|info)\]\s+-\s+(?P<name>.+?)\s+\*\*\* FAILED \*\*\*.*$"
)
_FAILED_SUITE_PATTERN: Final = re.compile(r"^\[error\]\s+(?P<suite>[A-Za-z_][A-Za-z0-9_.$]+)\s*$")


class SbtCompilationStatus(StrEnum):
    """Observed sbt compilation state without inferring unreported success."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SbtReportedTestCounts:
    """sbt textual aggregate retained separately from exact JUnit cases."""

    succeeded: int
    failed: int
    canceled: int
    ignored: int
    pending: int

    def __post_init__(self) -> None:
        values = (
            self.succeeded,
            self.failed,
            self.canceled,
            self.ignored,
            self.pending,
        )
        if any(isinstance(value, bool) or value < 0 for value in values):
            raise ValueError("sbt test counts must be non-negative integers")

    @property
    def total(self) -> int:
        return self.succeeded + self.failed + self.canceled + self.ignored + self.pending

    def to_snapshot(self) -> dict[str, int]:
        return {
            "succeeded": self.succeeded,
            "failed": self.failed,
            "canceled": self.canceled,
            "ignored": self.ignored,
            "pending": self.pending,
            "total": self.total,
        }


@dataclass(frozen=True, slots=True)
class SbtEvidenceParseResult:
    """Canonical sbt/Scala result with exact and textual evidence separated."""

    compilation_status: SbtCompilationStatus
    reported_test_counts: SbtReportedTestCounts | None
    test_summary: JvmTestSummary
    failed_suites: tuple[str, ...]
    findings: tuple[JvmNormalizedFinding, ...]
    build_failed: bool

    def __post_init__(self) -> None:
        if self.failed_suites != tuple(sorted(self.failed_suites)) or len(
            self.failed_suites
        ) != len(set(self.failed_suites)):
            raise ValueError("sbt failed suites must be canonical and unique")
        if any(not value or value != " ".join(value.split()) for value in self.failed_suites):
            raise ValueError("sbt failed suites must be normalized")
        ordered_findings = tuple(
            sorted(
                self.findings,
                key=lambda finding: (
                    finding.code,
                    finding.source_tool,
                    finding.location or "",
                    finding.message,
                ),
            )
        )
        if self.findings != ordered_findings or len(self.findings) != len(set(self.findings)):
            raise ValueError("sbt findings must be canonical and unique")
        if not isinstance(self.build_failed, bool):
            raise TypeError("sbt build failure marker must be a boolean")
        reported_failure = (
            self.reported_test_counts is not None and self.reported_test_counts.failed > 0
        )
        expected_failure = (
            self.compilation_status is SbtCompilationStatus.FAILED
            or reported_failure
            or not self.test_summary.is_passing
            or bool(self.failed_suites)
            or bool(self.findings)
        )
        if self.build_failed != expected_failure:
            raise ValueError("sbt build failure marker contradicts parsed evidence")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "compilation_status": self.compilation_status.value,
            "reported_test_counts": (
                None
                if self.reported_test_counts is None
                else self.reported_test_counts.to_snapshot()
            ),
            "test_summary": self.test_summary.to_snapshot(),
            "failed_suites": list(self.failed_suites),
            "findings": [finding.to_snapshot() for finding in self.findings],
            "build_failed": self.build_failed,
        }


def parse_sbt_and_scala_test_evidence(
    console_text: str,
    *,
    junit_xml_documents: tuple[bytes, ...] = (),
) -> SbtEvidenceParseResult:
    """Parse bounded sbt output while preserving exact JUnit case evidence."""
    if not isinstance(console_text, str):
        raise TypeError("sbt console evidence must be text")
    if len(console_text.encode("utf-8")) > _MAX_CONSOLE_BYTES:
        raise ValueError("sbt console evidence exceeds the parser size limit")
    if "\x00" in console_text:
        raise ValueError("sbt console evidence contains a NUL separator")

    compilation_status = SbtCompilationStatus.UNKNOWN
    reported_counts: SbtReportedTestCounts | None = None
    findings: set[JvmNormalizedFinding] = set()
    failed_suites: set[str] = set()
    collecting_failed_suites = False

    for raw_line in console_text.splitlines():
        line = " ".join(raw_line.strip().split())
        if not line:
            continue
        if line.startswith("[info] compiling ") or (
            line.startswith("[info] done compiling")
            and compilation_status is not SbtCompilationStatus.FAILED
        ):
            compilation_status = SbtCompilationStatus.PASSED
        if (
            line.startswith("[success] Total time")
            and compilation_status is SbtCompilationStatus.UNKNOWN
        ):
            compilation_status = SbtCompilationStatus.PASSED
        if line.startswith("[error] Total time"):
            compilation_status = SbtCompilationStatus.FAILED

        diagnostic = _SCALA_DIAGNOSTIC_PATTERN.fullmatch(line)
        if diagnostic is not None:
            compilation_status = SbtCompilationStatus.FAILED
            findings.add(
                JvmNormalizedFinding(
                    code="SCALA_COMPILATION_ERROR",
                    message=" ".join(diagnostic.group("message").split()),
                    source_tool="scala-compiler",
                    location=_normalize_source_location(
                        diagnostic.group("path"),
                        diagnostic.group("line"),
                        diagnostic.group("column"),
                    ),
                )
            )
            continue
        scala3 = _SCALA3_DIAGNOSTIC_PATTERN.fullmatch(line)
        if scala3 is not None:
            compilation_status = SbtCompilationStatus.FAILED
            findings.add(
                JvmNormalizedFinding(
                    code=f"SCALA_{scala3.group('code')}",
                    message="Scala 3 compiler reported a typed error.",
                    source_tool="scala3-compiler",
                    location=_normalize_source_location(
                        scala3.group("path"),
                        scala3.group("line"),
                        scala3.group("column"),
                    ),
                )
            )
            continue

        counts_match = _TEST_COUNTS_PATTERN.fullmatch(line)
        if counts_match is not None:
            reported_counts = SbtReportedTestCounts(
                succeeded=int(counts_match.group("succeeded")),
                failed=int(counts_match.group("failed")),
                canceled=int(counts_match.group("canceled")),
                ignored=int(counts_match.group("ignored")),
                pending=int(counts_match.group("pending")),
            )
            continue

        failed_test = _FAILED_TEST_PATTERN.fullmatch(line)
        if failed_test is not None:
            test_name = " ".join(failed_test.group("name").split())
            findings.add(
                JvmNormalizedFinding(
                    code="SCALA_TEST_FAILED",
                    message=f"Scala test {test_name} failed.",
                    source_tool="sbt-test",
                    location=test_name,
                )
            )
            continue

        if line == "[error] Failed tests:":
            collecting_failed_suites = True
            continue
        if collecting_failed_suites:
            suite = _FAILED_SUITE_PATTERN.fullmatch(line)
            if suite is not None:
                failed_suites.add(suite.group("suite"))
                continue
            collecting_failed_suites = False

    test_summary = parse_junit_xml_documents(junit_xml_documents)
    if (
        reported_counts is not None
        and junit_xml_documents
        and (
            reported_counts.total != test_summary.total
            or reported_counts.failed != test_summary.failed + test_summary.errors
        )
    ):
        findings.add(
            JvmNormalizedFinding(
                code="SBT_TEST_COUNT_MISMATCH",
                message="sbt textual counts differ from the collected JUnit XML cases.",
                source_tool="sbt-test",
                location="test-summary",
            )
        )

    canonical_suites = tuple(sorted(failed_suites))
    canonical_findings = tuple(
        sorted(
            findings,
            key=lambda finding: (
                finding.code,
                finding.source_tool,
                finding.location or "",
                finding.message,
            ),
        )
    )
    reported_failure = reported_counts is not None and reported_counts.failed > 0
    build_failed = (
        compilation_status is SbtCompilationStatus.FAILED
        or reported_failure
        or not test_summary.is_passing
        or bool(canonical_suites)
        or bool(canonical_findings)
    )
    return SbtEvidenceParseResult(
        compilation_status=compilation_status,
        reported_test_counts=reported_counts,
        test_summary=test_summary,
        failed_suites=canonical_suites,
        findings=canonical_findings,
        build_failed=build_failed,
    )


def _normalize_source_location(path: str, line: str, column: str) -> str:
    normalized = path.replace("\\", "/")
    marker_index = normalized.casefold().find("src/")
    normalized = normalized[marker_index:] if marker_index >= 0 else PurePosixPath(normalized).name
    return f"{normalized}:{line}:{column}"
