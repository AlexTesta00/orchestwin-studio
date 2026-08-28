"""Gradle task, Java/Kotlin compiler, and JUnit evidence normalization."""

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
_TASK_PATTERN: Final = re.compile(
    r"^> Task (?P<task>:\S+?)(?: (?P<status>UP-TO-DATE|FAILED|SKIPPED|FROM-CACHE|NO-SOURCE))?$"
)
_COMPILER_PATTERN: Final = re.compile(
    r"^(?P<path>.+?\.(?P<language>java|kt)):(?P<line>\d+)"
    r"(?::(?P<column>\d+))?:\s*(?P<severity>error|warning):\s*(?P<message>.+)$",
    re.IGNORECASE,
)
_KOTLIN_COMPILER_PATTERN: Final = re.compile(
    r"^(?P<severity>[ew]):\s+(?:file://)?(?P<path>.+?\.kt):(?P<line>\d+):(?P<column>\d+)"
    r"\s+(?P<message>.+)$",
    re.IGNORECASE,
)
_EXECUTION_FAILURE_PATTERN: Final = re.compile(r"^Execution failed for task '(?P<task>:[^']+)'\.?$")


class GradleTaskStatus(StrEnum):
    """Normalized terminal state for one observed Gradle task."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    UP_TO_DATE = "UP_TO_DATE"
    SKIPPED = "SKIPPED"
    FROM_CACHE = "FROM_CACHE"
    NO_SOURCE = "NO_SOURCE"


@dataclass(frozen=True, slots=True, order=True)
class GradleTaskOutcome:
    """One Gradle task and its last observed terminal state."""

    task_path: str
    status: GradleTaskStatus

    def __post_init__(self) -> None:
        if not re.fullmatch(r":[A-Za-z0-9_.:-]+", self.task_path):
            raise ValueError("Gradle task path must be normalized")

    def to_snapshot(self) -> dict[str, str]:
        return {"task_path": self.task_path, "status": self.status.value}


@dataclass(frozen=True, slots=True)
class GradleEvidenceParseResult:
    """Canonical Gradle/JUnit result retaining tool-neutral findings."""

    tasks: tuple[GradleTaskOutcome, ...]
    test_summary: JvmTestSummary
    findings: tuple[JvmNormalizedFinding, ...]
    build_failed: bool

    def __post_init__(self) -> None:
        ordered_tasks = tuple(sorted(self.tasks, key=lambda task: task.task_path))
        if self.tasks != ordered_tasks:
            raise ValueError("Gradle task outcomes must use canonical order")
        if len({task.task_path for task in self.tasks}) != len(self.tasks):
            raise ValueError("Gradle task outcomes must have unique paths")
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
            raise ValueError("Gradle findings must be canonical and unique")
        if not isinstance(self.build_failed, bool):
            raise TypeError("Gradle build failure marker must be a boolean")
        task_failure = any(task.status is GradleTaskStatus.FAILED for task in self.tasks)
        test_failure = not self.test_summary.is_passing
        finding_failure = any(_is_blocking_finding(finding) for finding in self.findings)
        if self.build_failed != (task_failure or test_failure or finding_failure):
            raise ValueError("Gradle build failure marker contradicts parsed evidence")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "tasks": [task.to_snapshot() for task in self.tasks],
            "test_summary": self.test_summary.to_snapshot(),
            "findings": [finding.to_snapshot() for finding in self.findings],
            "build_failed": self.build_failed,
        }


def parse_gradle_and_junit_evidence(
    console_text: str,
    *,
    junit_xml_documents: tuple[bytes, ...] = (),
) -> GradleEvidenceParseResult:
    """Parse bounded Gradle output and exact JUnit XML test cases."""
    if not isinstance(console_text, str):
        raise TypeError("Gradle console evidence must be text")
    encoded = console_text.encode("utf-8")
    if len(encoded) > _MAX_CONSOLE_BYTES:
        raise ValueError("Gradle console evidence exceeds the parser size limit")
    if "\x00" in console_text:
        raise ValueError("Gradle console evidence contains a NUL separator")

    tasks: dict[str, GradleTaskStatus] = {}
    findings: set[JvmNormalizedFinding] = set()
    explicit_build_failure = False
    for raw_line in console_text.splitlines():
        line = " ".join(raw_line.strip().split())
        if not line:
            continue
        task_match = _TASK_PATTERN.fullmatch(line)
        if task_match is not None:
            raw_status = task_match.group("status")
            tasks[task_match.group("task")] = _task_status(raw_status)
            continue
        compiler_match = _COMPILER_PATTERN.fullmatch(line)
        if compiler_match is not None:
            language = compiler_match.group("language").casefold()
            severity = compiler_match.group("severity").casefold()
            location = _normalize_source_location(
                compiler_match.group("path"),
                line_number=compiler_match.group("line"),
                column=compiler_match.group("column"),
            )
            findings.add(
                JvmNormalizedFinding(
                    code=f"{language.upper()}_COMPILATION_{severity.upper()}",
                    message=" ".join(compiler_match.group("message").split()),
                    source_tool="gradle-compiler",
                    location=location,
                )
            )
            continue
        kotlin_match = _KOTLIN_COMPILER_PATTERN.fullmatch(line)
        if kotlin_match is not None:
            severity = "error" if kotlin_match.group("severity").casefold() == "e" else "warning"
            findings.add(
                JvmNormalizedFinding(
                    code=f"KT_COMPILATION_{severity.upper()}",
                    message=" ".join(kotlin_match.group("message").split()),
                    source_tool="gradle-kotlin-compiler",
                    location=_normalize_source_location(
                        kotlin_match.group("path"),
                        line_number=kotlin_match.group("line"),
                        column=kotlin_match.group("column"),
                    ),
                )
            )
            continue
        execution_failure = _EXECUTION_FAILURE_PATTERN.fullmatch(line)
        if execution_failure is not None:
            task_path = execution_failure.group("task")
            tasks[task_path] = GradleTaskStatus.FAILED
            explicit_build_failure = True
            findings.add(
                JvmNormalizedFinding(
                    code="GRADLE_TASK_FAILED",
                    message=f"Gradle task {task_path} failed.",
                    source_tool="gradle",
                    location=task_path,
                )
            )
            continue
        if line.startswith("BUILD FAILED"):
            explicit_build_failure = True
            findings.add(
                JvmNormalizedFinding(
                    code="GRADLE_BUILD_FAILED",
                    message="Gradle reported a failed build.",
                    source_tool="gradle",
                    location=None,
                )
            )

    test_summary = parse_junit_xml_documents(junit_xml_documents)
    canonical_tasks = tuple(
        GradleTaskOutcome(task_path=path, status=status) for path, status in sorted(tasks.items())
    )
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
    build_failed = (
        explicit_build_failure
        or any(task.status is GradleTaskStatus.FAILED for task in canonical_tasks)
        or not test_summary.is_passing
        or any(_is_blocking_finding(finding) for finding in canonical_findings)
    )
    return GradleEvidenceParseResult(
        tasks=canonical_tasks,
        test_summary=test_summary,
        findings=canonical_findings,
        build_failed=build_failed,
    )


def _is_blocking_finding(finding: JvmNormalizedFinding) -> bool:
    return finding.code.endswith("_ERROR") or finding.code in {
        "GRADLE_BUILD_FAILED",
        "GRADLE_TASK_FAILED",
    }


def _task_status(raw_status: str | None) -> GradleTaskStatus:
    if raw_status is None:
        return GradleTaskStatus.SUCCESS
    return {
        "FAILED": GradleTaskStatus.FAILED,
        "FROM-CACHE": GradleTaskStatus.FROM_CACHE,
        "NO-SOURCE": GradleTaskStatus.NO_SOURCE,
        "SKIPPED": GradleTaskStatus.SKIPPED,
        "UP-TO-DATE": GradleTaskStatus.UP_TO_DATE,
    }[raw_status]


def _normalize_source_location(
    raw_path: str,
    *,
    line_number: str,
    column: str | None,
) -> str:
    normalized_path = raw_path.replace("\\", "/")
    marker_index = normalized_path.casefold().find("src/")
    if marker_index >= 0:
        normalized_path = normalized_path[marker_index:]
    else:
        normalized_path = PurePosixPath(normalized_path).name
    suffix = f":{line_number}"
    if column is not None:
        suffix += f":{column}"
    return normalized_path + suffix
