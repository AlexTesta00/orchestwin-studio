"""Capability-honest Java, Kotlin, and Scala target validation scopes."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionTarget,
)

_VERSION_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_JVM_TARGETS: Final = frozenset(
    {
        ExecutionTarget.JVM_JAVA,
        ExecutionTarget.JVM_KOTLIN,
        ExecutionTarget.JVM_SCALA,
    }
)


class JvmImplementationLanguage(StrEnum):
    """Languages explicitly included in the Sprint 09 JVM boundary."""

    JAVA = "JAVA"
    KOTLIN = "KOTLIN"
    SCALA = "SCALA"


class JvmBuildSystem(StrEnum):
    """Build systems admitted by the initial validated project shapes."""

    GRADLE_KOTLIN_DSL = "GRADLE_KOTLIN_DSL"
    SBT = "SBT"


class JvmProjectLayout(StrEnum):
    """Project layouts included in the initial JVM scope."""

    SINGLE_MODULE = "SINGLE_MODULE"


class JvmRuntimeKind(StrEnum):
    """Runtime family used by all Sprint 09 profiles."""

    JVM = "JVM"


@dataclass(frozen=True, slots=True)
class JvmValidationScope:
    """Versioned claim boundary for one public JVM execution target."""

    target: ExecutionTarget
    profile_id: str
    profile_version: str
    capability_status: ExecutionCapabilityStatus
    language: JvmImplementationLanguage
    language_version: str
    build_system: JvmBuildSystem
    layout: JvmProjectLayout
    runtime_kind: JvmRuntimeKind
    jdk_major: int
    required_indicators: tuple[str, ...]
    excluded_configurations: tuple[str, ...]
    validation_evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.target not in _JVM_TARGETS:
            raise ValueError("JVM validation scope requires an approved JVM target")
        if not self.profile_id or self.profile_id != self.profile_id.strip():
            raise ValueError("JVM validation scope profile ID must be normalized")
        if _VERSION_PATTERN.fullmatch(self.profile_version) is None:
            raise ValueError("JVM validation scope profile version must be normalized")
        if _VERSION_PATTERN.fullmatch(self.language_version) is None:
            raise ValueError("JVM language version must be normalized")
        if isinstance(self.jdk_major, bool) or self.jdk_major < 8:
            raise ValueError("JVM validation scope requires a supported JDK major")
        _require_canonical_text(self.required_indicators, label="required indicators")
        if not self.required_indicators:
            raise ValueError("JVM validation scope requires structural indicators")
        _require_canonical_text(
            self.excluded_configurations,
            label="excluded configurations",
        )
        _require_canonical_text(
            self.validation_evidence_refs,
            label="validation evidence references",
        )
        _validate_target_shape(self)
        if self.capability_status is ExecutionCapabilityStatus.VALIDATED_LEVEL_D:
            if not self.validation_evidence_refs:
                raise ValueError("validated JVM scope requires recorded evidence")
        elif self.validation_evidence_refs:
            raise ValueError("non-validated JVM scope must not claim validation evidence")

    @property
    def content_hash(self) -> str:
        """Hash the complete capability claim independently from object identity."""
        return hashlib.sha256(_canonical_json(self._content_snapshot())).hexdigest()

    def to_snapshot(self) -> dict[str, object]:
        """Return canonical scope metadata including its integrity hash."""
        return {**self._content_snapshot(), "content_hash": self.content_hash}

    def _content_snapshot(self) -> dict[str, object]:
        return {
            "target": self.target.value,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "capability_status": self.capability_status.value,
            "language": self.language.value,
            "language_version": self.language_version,
            "build_system": self.build_system.value,
            "layout": self.layout.value,
            "runtime_kind": self.runtime_kind.value,
            "jdk_major": self.jdk_major,
            "required_indicators": list(self.required_indicators),
            "excluded_configurations": list(self.excluded_configurations),
            "validation_evidence_refs": list(self.validation_evidence_refs),
        }


@dataclass(frozen=True, slots=True)
class JvmTargetSelection:
    """Exact target and toolchain shape selected for one source snapshot."""

    target: ExecutionTarget
    language: JvmImplementationLanguage
    build_system: JvmBuildSystem
    layout: JvmProjectLayout
    jdk_major: int

    def __post_init__(self) -> None:
        if self.target not in _JVM_TARGETS:
            raise ValueError("JVM target selection requires an approved JVM target")
        if isinstance(self.jdk_major, bool) or self.jdk_major < 8:
            raise ValueError("JVM target selection requires a supported JDK major")
        _validate_selection_shape(self)

    def validate_against(self, scope: JvmValidationScope) -> None:
        """Raise when a selection exceeds one versioned validation boundary."""
        if self.target is not scope.target:
            raise ValueError("JVM target selection does not match the validation scope")
        if self.language is not scope.language:
            raise ValueError("JVM language is outside the validation scope")
        if self.build_system is not scope.build_system:
            raise ValueError("JVM build system is outside the validation scope")
        if self.layout is not scope.layout:
            raise ValueError("JVM project layout is outside the validation scope")
        if self.jdk_major != scope.jdk_major:
            raise ValueError("JVM JDK major is outside the validation scope")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "target": self.target.value,
            "language": self.language.value,
            "build_system": self.build_system.value,
            "layout": self.layout.value,
            "jdk_major": self.jdk_major,
        }


_COMMON_EXCLUSIONS: Final = (
    "android",
    "gradle-groovy-dsl",
    "javafx",
    "kotlin-multiplatform",
    "maven",
    "mixed-language-project",
    "multi-module-build",
    "scala-2",
    "scala-js",
    "scala-native",
    "spring-boot",
)


def create_sprint09_jvm_validation_scopes() -> Mapping[ExecutionTarget, JvmValidationScope]:
    """Return the three owner-approved JVM targets as honest Level C claims."""
    scopes = {
        ExecutionTarget.JVM_JAVA: JvmValidationScope(
            target=ExecutionTarget.JVM_JAVA,
            profile_id="jvm.java-gradle",
            profile_version="1.0.0",
            capability_status=ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C,
            language=JvmImplementationLanguage.JAVA,
            language_version="21",
            build_system=JvmBuildSystem.GRADLE_KOTLIN_DSL,
            layout=JvmProjectLayout.SINGLE_MODULE,
            runtime_kind=JvmRuntimeKind.JVM,
            jdk_major=21,
            required_indicators=(
                "build.gradle.kts",
                "gradle/wrapper/gradle-wrapper.properties",
                "settings.gradle.kts",
            ),
            excluded_configurations=_COMMON_EXCLUSIONS,
        ),
        ExecutionTarget.JVM_KOTLIN: JvmValidationScope(
            target=ExecutionTarget.JVM_KOTLIN,
            profile_id="jvm.kotlin-gradle",
            profile_version="1.0.0",
            capability_status=ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C,
            language=JvmImplementationLanguage.KOTLIN,
            language_version="2.4.10",
            build_system=JvmBuildSystem.GRADLE_KOTLIN_DSL,
            layout=JvmProjectLayout.SINGLE_MODULE,
            runtime_kind=JvmRuntimeKind.JVM,
            jdk_major=21,
            required_indicators=(
                "build.gradle.kts",
                "gradle/wrapper/gradle-wrapper.properties",
                "settings.gradle.kts",
            ),
            excluded_configurations=_COMMON_EXCLUSIONS,
        ),
        ExecutionTarget.JVM_SCALA: JvmValidationScope(
            target=ExecutionTarget.JVM_SCALA,
            profile_id="jvm.scala-sbt",
            profile_version="1.0.0",
            capability_status=ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C,
            language=JvmImplementationLanguage.SCALA,
            language_version="3.3.8",
            build_system=JvmBuildSystem.SBT,
            layout=JvmProjectLayout.SINGLE_MODULE,
            runtime_kind=JvmRuntimeKind.JVM,
            jdk_major=21,
            required_indicators=(
                "build.sbt",
                "project/build.properties",
            ),
            excluded_configurations=_COMMON_EXCLUSIONS,
        ),
    }
    return MappingProxyType(scopes)


def promote_jvm_validation_scope(
    scope: JvmValidationScope,
    *,
    validation_evidence_refs: tuple[str, ...],
) -> JvmValidationScope:
    """Promote one exact baseline only from canonical durable evidence references."""
    if scope.capability_status is not ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C:
        raise ValueError("only a design-only baseline JVM scope can be promoted")
    _require_canonical_text(
        validation_evidence_refs,
        label="validation evidence references",
    )
    if not validation_evidence_refs:
        raise ValueError("JVM scope promotion requires durable evidence references")
    return replace(
        scope,
        capability_status=ExecutionCapabilityStatus.VALIDATED_LEVEL_D,
        validation_evidence_refs=validation_evidence_refs,
    )


def jvm_scope_for(target: ExecutionTarget) -> JvmValidationScope:
    """Resolve one exact Sprint 09 scope or reject non-JVM targets."""
    try:
        return _SPRINT09_JVM_SCOPES[target]
    except KeyError as error:
        raise ValueError("target is outside the Sprint 09 JVM scope") from error


def selection_for(target: ExecutionTarget) -> JvmTargetSelection:
    """Create the canonical target selection declared by one scope."""
    scope = jvm_scope_for(target)
    return JvmTargetSelection(
        target=scope.target,
        language=scope.language,
        build_system=scope.build_system,
        layout=scope.layout,
        jdk_major=scope.jdk_major,
    )


def _validate_target_shape(scope: JvmValidationScope) -> None:
    expected = {
        ExecutionTarget.JVM_JAVA: (
            JvmImplementationLanguage.JAVA,
            JvmBuildSystem.GRADLE_KOTLIN_DSL,
        ),
        ExecutionTarget.JVM_KOTLIN: (
            JvmImplementationLanguage.KOTLIN,
            JvmBuildSystem.GRADLE_KOTLIN_DSL,
        ),
        ExecutionTarget.JVM_SCALA: (
            JvmImplementationLanguage.SCALA,
            JvmBuildSystem.SBT,
        ),
    }[scope.target]
    if (scope.language, scope.build_system) != expected:
        raise ValueError("JVM target, language, and build system are inconsistent")
    if scope.layout is not JvmProjectLayout.SINGLE_MODULE:
        raise ValueError("Sprint 09 validates only single-module JVM projects")
    if scope.runtime_kind is not JvmRuntimeKind.JVM:
        raise ValueError("Sprint 09 targets require the JVM runtime")


def _validate_selection_shape(selection: JvmTargetSelection) -> None:
    scope = jvm_scope_for(selection.target)
    selection.validate_against(scope)


def _require_canonical_text(values: tuple[str, ...], *, label: str) -> None:
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError(f"JVM {label} must be canonical and unique")
    if any(not value or value != " ".join(value.split()) for value in values):
        raise ValueError(f"JVM {label} must contain normalized values")


def _canonical_json(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


_SPRINT09_JVM_SCOPES: Final = create_sprint09_jvm_validation_scopes()
