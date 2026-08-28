"""Deterministic structural detection for Java, Kotlin, and Scala JVM projects."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final

from orchestwin.jvm_execution.targets import (
    JvmBuildSystem,
    JvmImplementationLanguage,
    JvmTargetSelection,
    selection_for,
)
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.sandbox.source_inventory import SourceTreeInventory

_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_GRADLE_KOTLIN_INDICATORS: Final = frozenset(
    {
        "build.gradle.kts",
        "settings.gradle.kts",
        "gradle/wrapper/gradle-wrapper.properties",
    }
)
_GRADLE_GROOVY_INDICATORS: Final = frozenset({"build.gradle", "settings.gradle"})
_SBT_INDICATORS: Final = frozenset({"build.sbt", "project/build.properties"})
_MAVEN_INDICATORS: Final = frozenset({"pom.xml", ".mvn/wrapper/maven-wrapper.properties"})
_ANDROID_PATH_NAMES: Final = frozenset({"AndroidManifest.xml", "local.properties"})
_ANDROID_MARKERS: Final = (
    "com.android.application",
    "com.android.library",
    "android {",
)
_KOTLIN_MULTIPLATFORM_MARKERS: Final = (
    'kotlin("multiplatform")',
    "org.jetbrains.kotlin.multiplatform",
)


class JvmDetectionStatus(StrEnum):
    """Capability-neutral result of deterministic JVM source inspection."""

    SELECTED = "SELECTED"
    HUMAN_DECISION_REQUIRED = "HUMAN_DECISION_REQUIRED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True, slots=True, order=True)
class JvmTextFile:
    """UTF-8 source content bound to the digest recorded by the inventory."""

    normalized_path: str
    content: str
    sha256_digest: str

    def __post_init__(self) -> None:
        _validate_relative_path(self.normalized_path)
        if _SHA256_PATTERN.fullmatch(self.sha256_digest) is None:
            raise ValueError("JVM text file digest must be lowercase SHA-256")
        actual = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        if actual != self.sha256_digest:
            raise ValueError("JVM text file content does not match its inventory digest")


@dataclass(frozen=True, slots=True)
class JvmDetectionSnapshot:
    """Minimal inspectable source material required for JVM stack detection."""

    inventory_content_hash: str
    included_paths: tuple[str, ...]
    text_files: tuple[JvmTextFile, ...]

    def __post_init__(self) -> None:
        if _SHA256_PATTERN.fullmatch(self.inventory_content_hash) is None:
            raise ValueError("JVM detection inventory hash must be lowercase SHA-256")
        _require_canonical_paths(self.included_paths)
        ordered = tuple(sorted(self.text_files, key=lambda item: item.normalized_path))
        if self.text_files != ordered:
            raise ValueError("JVM detection text files must use canonical path order")
        paths = tuple(item.normalized_path for item in self.text_files)
        if len(paths) != len(set(paths)):
            raise ValueError("JVM detection text file paths must be unique")
        if not set(paths) <= set(self.included_paths):
            raise ValueError("JVM detection text files must belong to the source inventory")

    def text_by_path(self) -> Mapping[str, str]:
        return {item.normalized_path: item.content for item in self.text_files}


@dataclass(frozen=True, slots=True)
class JvmDetectionCandidate:
    """One target candidate and the exact structural indicators supporting it."""

    selection: JvmTargetSelection
    match_score: int
    positive_indicators: tuple[str, ...]

    def __post_init__(self) -> None:
        if isinstance(self.match_score, bool) or not 1 <= self.match_score <= 100:
            raise ValueError("JVM detection match score must be from one to 100")
        _require_canonical_text(self.positive_indicators, label="positive indicators")
        if not self.positive_indicators:
            raise ValueError("JVM detection candidate requires positive indicators")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "selection": self.selection.to_snapshot(),
            "match_score": self.match_score,
            "positive_indicators": list(self.positive_indicators),
        }


@dataclass(frozen=True, slots=True)
class JvmDetectionResult:
    """Deterministic target result without an unearned Level D claim."""

    inventory_content_hash: str
    status: JvmDetectionStatus
    candidates: tuple[JvmDetectionCandidate, ...]
    selected: JvmDetectionCandidate | None
    conflicting_indicators: tuple[str, ...]

    def __post_init__(self) -> None:
        if _SHA256_PATTERN.fullmatch(self.inventory_content_hash) is None:
            raise ValueError("JVM detection result requires a valid inventory hash")
        ordered = tuple(
            sorted(
                self.candidates,
                key=lambda item: (-item.match_score, item.selection.target.value),
            )
        )
        if self.candidates != ordered:
            raise ValueError("JVM detection candidates must use deterministic ranking order")
        if len({item.selection.target for item in self.candidates}) != len(self.candidates):
            raise ValueError("JVM detection candidates must have unique targets")
        _require_canonical_text(
            self.conflicting_indicators,
            label="conflicting indicators",
        )
        if self.status is JvmDetectionStatus.SELECTED:
            if self.selected is None or self.selected not in self.candidates:
                raise ValueError("selected JVM detection requires one ranked candidate")
            if self.conflicting_indicators:
                raise ValueError("selected JVM detection must not hide conflicts")
        elif self.selected is not None:
            raise ValueError("non-selected JVM detection must not expose a selected target")
        if self.status is JvmDetectionStatus.UNSUPPORTED and (
            self.candidates or self.conflicting_indicators
        ):
            raise ValueError("unsupported JVM detection must not contain candidates or conflicts")
        if self.status is JvmDetectionStatus.HUMAN_DECISION_REQUIRED and not (
            self.conflicting_indicators or len(self.candidates) > 1
        ):
            raise ValueError("human decision requires conflicts or multiple candidates")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "inventory_content_hash": self.inventory_content_hash,
            "status": self.status.value,
            "candidates": [candidate.to_snapshot() for candidate in self.candidates],
            "selected": None if self.selected is None else self.selected.to_snapshot(),
            "conflicting_indicators": list(self.conflicting_indicators),
        }


def create_jvm_detection_snapshot(
    inventory: SourceTreeInventory,
    *,
    text_content_by_path: Mapping[str, str],
) -> JvmDetectionSnapshot:
    """Bind caller-supplied UTF-8 content to exact source inventory digests."""
    included = {
        entry.normalized_path: entry.sha256_digest
        for entry in inventory.included_entries
        if entry.sha256_digest is not None
    }
    text_files: list[JvmTextFile] = []
    for path, content in sorted(text_content_by_path.items()):
        expected_digest = included.get(path)
        if expected_digest is None:
            raise ValueError("JVM detection text content is absent from the source inventory")
        text_files.append(
            JvmTextFile(
                normalized_path=path,
                content=content,
                sha256_digest=expected_digest,
            )
        )
    return JvmDetectionSnapshot(
        inventory_content_hash=inventory.content_hash,
        included_paths=tuple(sorted(included)),
        text_files=tuple(text_files),
    )


def detect_jvm_project(snapshot: JvmDetectionSnapshot) -> JvmDetectionResult:
    """Detect one supported JVM family from structural indicators only."""
    paths = frozenset(snapshot.included_paths)
    text_by_path = snapshot.text_by_path()
    conflicts = set(_configuration_conflicts(paths, text_by_path))
    languages = _detected_languages(paths)
    if len(languages) > 1:
        conflicts.add("mixed JVM source languages are outside the validated single-language scope")

    candidates: list[JvmDetectionCandidate] = []
    if len(languages) == 1:
        language = next(iter(languages))
        build_system = _detected_build_system(paths)
        expected = _expected_build_system(language)
        if build_system is None:
            conflicts.add("supported JVM source requires one recognized build system")
        elif build_system is not expected:
            conflicts.add(
                f"{language.value.lower()} source uses an unsupported build-system combination"
            )
        elif not conflicts:
            candidates.append(_candidate(language, build_system, paths))

    ranked = tuple(
        sorted(
            candidates,
            key=lambda item: (-item.match_score, item.selection.target.value),
        )
    )
    canonical_conflicts = tuple(sorted(conflicts))
    if canonical_conflicts or len(ranked) > 1:
        status = JvmDetectionStatus.HUMAN_DECISION_REQUIRED
        selected = None
    elif ranked:
        status = JvmDetectionStatus.SELECTED
        selected = ranked[0]
    else:
        status = JvmDetectionStatus.UNSUPPORTED
        selected = None
    return JvmDetectionResult(
        inventory_content_hash=snapshot.inventory_content_hash,
        status=status,
        candidates=ranked,
        selected=selected,
        conflicting_indicators=canonical_conflicts,
    )


def _detected_languages(paths: frozenset[str]) -> frozenset[JvmImplementationLanguage]:
    languages: set[JvmImplementationLanguage] = set()
    for path in paths:
        suffix = PurePosixPath(path).suffix.casefold()
        if suffix == ".java":
            languages.add(JvmImplementationLanguage.JAVA)
        elif suffix == ".kt":
            languages.add(JvmImplementationLanguage.KOTLIN)
        elif suffix == ".scala":
            languages.add(JvmImplementationLanguage.SCALA)
    return frozenset(languages)


def _detected_build_system(paths: frozenset[str]) -> JvmBuildSystem | None:
    has_gradle = paths >= _GRADLE_KOTLIN_INDICATORS
    has_sbt = paths >= _SBT_INDICATORS
    if has_gradle == has_sbt:
        return None
    return JvmBuildSystem.GRADLE_KOTLIN_DSL if has_gradle else JvmBuildSystem.SBT


def _configuration_conflicts(
    paths: frozenset[str],
    text_by_path: Mapping[str, str],
) -> tuple[str, ...]:
    conflicts: set[str] = set()
    if paths & _MAVEN_INDICATORS:
        conflicts.add("Maven projects are recognized but outside the Sprint 09 validated scope")
    if paths & _GRADLE_GROOVY_INDICATORS:
        conflicts.add("Gradle Groovy DSL is outside the Sprint 09 validated scope")
    if paths >= _GRADLE_KOTLIN_INDICATORS and paths >= _SBT_INDICATORS:
        conflicts.add("multiple JVM build systems require a human decision")
    if any(PurePosixPath(path).name in _ANDROID_PATH_NAMES for path in paths):
        conflicts.add("Android project indicators are outside the JVM-only Sprint 09 scope")

    combined = "\n".join(
        text_by_path.get(path, "")
        for path in ("build.gradle.kts", "settings.gradle.kts", "build.sbt")
    )
    if any(marker in combined for marker in _ANDROID_MARKERS):
        conflicts.add("Android Gradle plugins are outside the JVM-only Sprint 09 scope")
    if any(marker in combined for marker in _KOTLIN_MULTIPLATFORM_MARKERS):
        conflicts.add("Kotlin Multiplatform is outside the Sprint 09 validated scope")
    settings = text_by_path.get("settings.gradle.kts", "")
    if re.search(r"\binclude(?:Build)?\s*\(", settings):
        conflicts.add("multi-module Gradle projects are outside the validated scope")
    build_sbt = text_by_path.get("build.sbt", "")
    if ".aggregate(" in build_sbt or ".dependsOn(" in build_sbt:
        conflicts.add("multi-project sbt builds are outside the validated scope")
    return tuple(sorted(conflicts))


def _expected_build_system(language: JvmImplementationLanguage) -> JvmBuildSystem:
    if language is JvmImplementationLanguage.SCALA:
        return JvmBuildSystem.SBT
    return JvmBuildSystem.GRADLE_KOTLIN_DSL


def _candidate(
    language: JvmImplementationLanguage,
    build_system: JvmBuildSystem,
    paths: frozenset[str],
) -> JvmDetectionCandidate:
    target = {
        JvmImplementationLanguage.JAVA: ExecutionTarget.JVM_JAVA,
        JvmImplementationLanguage.KOTLIN: ExecutionTarget.JVM_KOTLIN,
        JvmImplementationLanguage.SCALA: ExecutionTarget.JVM_SCALA,
    }[language]
    selection = selection_for(target)
    indicators = [f"{language.value.lower()} source files are present"]
    if build_system is JvmBuildSystem.GRADLE_KOTLIN_DSL:
        indicators.extend(sorted(_GRADLE_KOTLIN_INDICATORS & paths))
        score = 95
    else:
        indicators.extend(sorted(_SBT_INDICATORS & paths))
        score = 92
    return JvmDetectionCandidate(
        selection=selection,
        match_score=score,
        positive_indicators=tuple(sorted(indicators)),
    )


def _validate_relative_path(path: str) -> None:
    if (
        not path
        or path != path.strip()
        or "\\" in path
        or path.startswith("/")
        or PurePosixPath(path).is_absolute()
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        raise ValueError("JVM source path must be a normalized relative POSIX path")


def _require_canonical_paths(paths: tuple[str, ...]) -> None:
    if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
        raise ValueError("JVM detection paths must be canonical and unique")
    for path in paths:
        _validate_relative_path(path)


def _require_canonical_text(values: tuple[str, ...], *, label: str) -> None:
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError(f"JVM detection {label} must be canonical and unique")
    if any(not value or value != " ".join(value.split()) for value in values):
        raise ValueError(f"JVM detection {label} must contain normalized values")
