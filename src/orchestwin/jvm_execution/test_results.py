"""Tool-neutral JVM test cases and bounded JUnit XML parsing."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from xml.etree import ElementTree

_MAX_XML_DOCUMENT_BYTES: Final = 2 * 1024 * 1024
_MAX_XML_TOTAL_BYTES: Final = 8 * 1024 * 1024
_MAX_TEST_CASES: Final = 10_000
_MAX_MESSAGE_LENGTH: Final = 2_048
_WHITESPACE_PATTERN: Final = re.compile(r"\s+")


class JvmTestCaseStatus(StrEnum):
    """Normalized test-case result shared by Gradle and sbt parsers."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True, slots=True, order=True)
class JvmTestCaseResult:
    """One named test case with an optional bounded diagnostic."""

    suite_name: str
    test_name: str
    status: JvmTestCaseStatus
    duration_seconds: float
    message: str | None = None

    def __post_init__(self) -> None:
        _validate_normalized_text(self.suite_name, label="JVM test suite name")
        _validate_normalized_text(self.test_name, label="JVM test case name")
        if (
            isinstance(self.duration_seconds, bool)
            or not math.isfinite(self.duration_seconds)
            or self.duration_seconds < 0
        ):
            raise ValueError("JVM test duration must be a non-negative finite number")
        if self.message is not None:
            _validate_normalized_text(self.message, label="JVM test message")
        if self.status in {JvmTestCaseStatus.FAILED, JvmTestCaseStatus.ERROR}:
            if self.message is None:
                raise ValueError("failed JVM test case requires a diagnostic")
        elif self.message is not None:
            raise ValueError("passing or skipped JVM test case must not invent a failure")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "suite_name": self.suite_name,
            "test_name": self.test_name,
            "status": self.status.value,
            "duration_seconds": self.duration_seconds,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class JvmTestSummary:
    """Canonical test aggregate whose counts are derived from exact cases."""

    total: int
    passed: int
    failed: int
    errors: int
    skipped: int
    duration_seconds: float
    cases: tuple[JvmTestCaseResult, ...]

    def __post_init__(self) -> None:
        counts = (self.total, self.passed, self.failed, self.errors, self.skipped)
        if any(isinstance(value, bool) or value < 0 for value in counts):
            raise ValueError("JVM test counts must be non-negative integers")
        if self.total != self.passed + self.failed + self.errors + self.skipped:
            raise ValueError("JVM test summary counts do not add up")
        if self.total != len(self.cases):
            raise ValueError("JVM test total must equal the exact case inventory")
        if (
            isinstance(self.duration_seconds, bool)
            or not math.isfinite(self.duration_seconds)
            or self.duration_seconds < 0
        ):
            raise ValueError("JVM test duration must be a non-negative finite number")
        ordered = tuple(
            sorted(
                self.cases,
                key=lambda case: (case.suite_name, case.test_name, case.status.value),
            )
        )
        if self.cases != ordered:
            raise ValueError("JVM test cases must use canonical order")
        identities = tuple((case.suite_name, case.test_name) for case in self.cases)
        if len(identities) != len(set(identities)):
            raise ValueError("JVM test case identities must be unique")
        derived = {
            JvmTestCaseStatus.PASSED: self.passed,
            JvmTestCaseStatus.FAILED: self.failed,
            JvmTestCaseStatus.ERROR: self.errors,
            JvmTestCaseStatus.SKIPPED: self.skipped,
        }
        for status, expected in derived.items():
            if sum(case.status is status for case in self.cases) != expected:
                raise ValueError("JVM test summary contradicts its case statuses")

    @property
    def is_passing(self) -> bool:
        return self.failed == 0 and self.errors == 0

    def to_snapshot(self) -> dict[str, object]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "duration_seconds": self.duration_seconds,
            "cases": [case.to_snapshot() for case in self.cases],
        }


def parse_junit_xml_documents(documents: tuple[bytes, ...]) -> JvmTestSummary:
    """Parse bounded JUnit XML documents without resolving external resources."""
    if not documents:
        return JvmTestSummary(
            total=0,
            passed=0,
            failed=0,
            errors=0,
            skipped=0,
            duration_seconds=0.0,
            cases=(),
        )
    if any(not isinstance(document, bytes) for document in documents):
        raise TypeError("JUnit XML documents must be bytes")
    if any(len(document) > _MAX_XML_DOCUMENT_BYTES for document in documents):
        raise ValueError("JUnit XML document exceeds the parser size limit")
    if sum(len(document) for document in documents) > _MAX_XML_TOTAL_BYTES:
        raise ValueError("JUnit XML evidence exceeds the aggregate parser size limit")

    cases: list[JvmTestCaseResult] = []
    for document in documents:
        if b"<!DOCTYPE" in document.upper() or b"<!ENTITY" in document.upper():
            raise ValueError("JUnit XML declarations and entities are forbidden")
        try:
            root = ElementTree.fromstring(document)
        except ElementTree.ParseError as error:
            raise ValueError("JUnit XML document is malformed") from error
        if root.tag not in {"testsuite", "testsuites"}:
            raise ValueError("JUnit XML root must be testsuite or testsuites")
        for testcase in root.iter("testcase"):
            cases.append(_parse_testcase(testcase))
            if len(cases) > _MAX_TEST_CASES:
                raise ValueError("JUnit XML evidence exceeds the test-case limit")

    canonical = tuple(
        sorted(
            cases,
            key=lambda case: (case.suite_name, case.test_name, case.status.value),
        )
    )
    return JvmTestSummary(
        total=len(canonical),
        passed=sum(case.status is JvmTestCaseStatus.PASSED for case in canonical),
        failed=sum(case.status is JvmTestCaseStatus.FAILED for case in canonical),
        errors=sum(case.status is JvmTestCaseStatus.ERROR for case in canonical),
        skipped=sum(case.status is JvmTestCaseStatus.SKIPPED for case in canonical),
        duration_seconds=round(sum(case.duration_seconds for case in canonical), 6),
        cases=canonical,
    )


def _parse_testcase(testcase: ElementTree.Element) -> JvmTestCaseResult:
    suite_name = _normalized(
        testcase.attrib.get("classname") or testcase.attrib.get("class") or "unnamed-suite"
    )
    test_name = _normalized(testcase.attrib.get("name") or "unnamed-test")
    try:
        duration = float(testcase.attrib.get("time", "0") or "0")
    except ValueError as error:
        raise ValueError("JUnit test-case duration is invalid") from error

    status = JvmTestCaseStatus.PASSED
    diagnostic: str | None = None
    for child_status, tag in (
        (JvmTestCaseStatus.ERROR, "error"),
        (JvmTestCaseStatus.FAILED, "failure"),
        (JvmTestCaseStatus.SKIPPED, "skipped"),
    ):
        child = testcase.find(tag)
        if child is None:
            continue
        status = child_status
        if child_status in {JvmTestCaseStatus.ERROR, JvmTestCaseStatus.FAILED}:
            diagnostic = _normalized(
                child.attrib.get("message")
                or child.text
                or f"{child_status.value.lower()} without diagnostic"
            )[:_MAX_MESSAGE_LENGTH]
        break
    return JvmTestCaseResult(
        suite_name=suite_name,
        test_name=test_name,
        status=status,
        duration_seconds=duration,
        message=diagnostic,
    )


def _normalized(value: str) -> str:
    normalized = _WHITESPACE_PATTERN.sub(" ", value).strip()
    return normalized or "unnamed"


def _validate_normalized_text(value: str, *, label: str) -> None:
    if not value or value != _normalized(value):
        raise ValueError(f"{label} must be normalized")
