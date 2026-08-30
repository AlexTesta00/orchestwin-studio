"""Deterministic JVM toolchain, dependency, and network policy validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from orchestwin.jvm_execution.targets import (
    JvmBuildSystem,
    JvmTargetSelection,
    jvm_scope_for,
)
from orchestwin.sandbox.execution_profiles import ExecutionTarget


class JvmRepository(StrEnum):
    """Repository identities explicitly admitted during controlled setup."""

    MAVEN_CENTRAL = "MAVEN_CENTRAL"


class JvmToolchainValidationStatus(StrEnum):
    """Outcome of validating one exact source/toolchain declaration."""

    VALID = "VALID"
    INVALID = "INVALID"


class JvmToolchainIssueCode(StrEnum):
    """Stable reasons why a JVM project cannot enter an execution runner."""

    JDK_VERSION_MISMATCH = "JDK_VERSION_MISMATCH"
    BUILD_TOOL_VERSION_MISMATCH = "BUILD_TOOL_VERSION_MISMATCH"
    LANGUAGE_VERSION_MISMATCH = "LANGUAGE_VERSION_MISMATCH"
    LAUNCHER_FILES_MISSING = "LAUNCHER_FILES_MISSING"
    LAUNCHER_INTEGRITY_UNVERIFIED = "LAUNCHER_INTEGRITY_UNVERIFIED"
    DEPENDENCY_VERIFICATION_DISABLED = "DEPENDENCY_VERIFICATION_DISABLED"
    REPOSITORY_NOT_ALLOWED = "REPOSITORY_NOT_ALLOWED"
    PLUGIN_NOT_ALLOWED = "PLUGIN_NOT_ALLOWED"
    NETWORK_POLICY_TOO_PERMISSIVE = "NETWORK_POLICY_TOO_PERMISSIVE"


@dataclass(frozen=True, slots=True)
class JvmToolchainPolicy:
    """Exact profile policy applied before dependency resolution or compilation."""

    selection: JvmTargetSelection
    build_tool_version: str
    language_version: str
    allowed_repositories: tuple[JvmRepository, ...]
    allowed_plugins: tuple[str, ...]
    require_launcher_integrity: bool = True
    require_dependency_verification: bool = True
    require_offline_post_setup: bool = True

    def __post_init__(self) -> None:
        self.selection.validate_against(jvm_scope_for(self.selection.target))
        _validate_text(self.build_tool_version, label="JVM build-tool version")
        _validate_text(self.language_version, label="JVM language version")
        if not self.allowed_repositories:
            raise ValueError("JVM toolchain policy requires at least one repository")
        _require_canonical_enum(self.allowed_repositories, label="JVM repositories")
        _require_canonical_text(self.allowed_plugins, label="JVM plugins")
        markers = (
            self.require_launcher_integrity,
            self.require_dependency_verification,
            self.require_offline_post_setup,
        )
        if any(not isinstance(marker, bool) for marker in markers):
            raise TypeError("JVM policy markers must be booleans")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_snapshot())).hexdigest()

    def to_snapshot(self) -> dict[str, object]:
        return {
            "selection": self.selection.to_snapshot(),
            "build_tool_version": self.build_tool_version,
            "language_version": self.language_version,
            "allowed_repositories": [item.value for item in self.allowed_repositories],
            "allowed_plugins": list(self.allowed_plugins),
            "require_launcher_integrity": self.require_launcher_integrity,
            "require_dependency_verification": self.require_dependency_verification,
            "require_offline_post_setup": self.require_offline_post_setup,
        }


@dataclass(frozen=True, slots=True)
class JvmToolchainDeclaration:
    """Inspectable project/toolchain facts supplied by deterministic parsers."""

    selection: JvmTargetSelection
    jdk_major: int
    build_tool_version: str
    language_version: str
    launcher_files_present: bool
    launcher_integrity_verified: bool
    dependency_verification_enabled: bool
    repositories: tuple[JvmRepository, ...]
    plugins: tuple[str, ...]
    network_disabled_after_setup: bool

    def __post_init__(self) -> None:
        self.selection.validate_against(jvm_scope_for(self.selection.target))
        if isinstance(self.jdk_major, bool) or self.jdk_major < 8:
            raise ValueError("JVM declaration requires a supported JDK major")
        _validate_text(self.build_tool_version, label="JVM build-tool version")
        _validate_text(self.language_version, label="JVM language version")
        _require_canonical_enum(self.repositories, label="JVM repositories")
        _require_canonical_text(self.plugins, label="JVM plugins")
        markers = (
            self.launcher_files_present,
            self.launcher_integrity_verified,
            self.dependency_verification_enabled,
            self.network_disabled_after_setup,
        )
        if any(not isinstance(marker, bool) for marker in markers):
            raise TypeError("JVM declaration policy markers must be booleans")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "selection": self.selection.to_snapshot(),
            "jdk_major": self.jdk_major,
            "build_tool_version": self.build_tool_version,
            "language_version": self.language_version,
            "launcher_files_present": self.launcher_files_present,
            "launcher_integrity_verified": self.launcher_integrity_verified,
            "dependency_verification_enabled": self.dependency_verification_enabled,
            "repositories": [item.value for item in self.repositories],
            "plugins": list(self.plugins),
            "network_disabled_after_setup": self.network_disabled_after_setup,
        }


@dataclass(frozen=True, slots=True, order=True)
class JvmToolchainIssue:
    """One deterministic policy violation suitable for API and audit output."""

    code: JvmToolchainIssueCode
    message: str
    subject: str

    def __post_init__(self) -> None:
        _validate_text(self.message, label="JVM toolchain issue message")
        _validate_text(self.subject, label="JVM toolchain issue subject")

    def to_snapshot(self) -> dict[str, str]:
        return {
            "code": self.code.value,
            "message": self.message,
            "subject": self.subject,
        }


@dataclass(frozen=True, slots=True)
class JvmToolchainValidation:
    """Canonical validation result with no hidden fallback or implicit upgrade."""

    policy_content_hash: str
    status: JvmToolchainValidationStatus
    issues: tuple[JvmToolchainIssue, ...]

    def __post_init__(self) -> None:
        if len(self.policy_content_hash) != 64:
            raise ValueError("JVM policy content hash must be a SHA-256 digest")
        ordered = tuple(sorted(self.issues, key=lambda issue: (issue.code.value, issue.subject)))
        if self.issues != ordered or len(self.issues) != len(set(self.issues)):
            raise ValueError("JVM toolchain issues must be canonical and unique")
        if self.status is JvmToolchainValidationStatus.VALID and self.issues:
            raise ValueError("valid JVM toolchain result must not contain issues")
        if self.status is JvmToolchainValidationStatus.INVALID and not self.issues:
            raise ValueError("invalid JVM toolchain result requires issues")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "policy_content_hash": self.policy_content_hash,
            "status": self.status.value,
            "issues": [issue.to_snapshot() for issue in self.issues],
        }


_GRADLE_VERSION: Final = "9.5.0"
_KOTLIN_VERSION: Final = "2.4.10"
_SCALA_VERSION: Final = "3.3.8"
_SBT_VERSION: Final = "1.12.14"


def policy_for(target: ExecutionTarget) -> JvmToolchainPolicy:
    """Return the immutable Sprint 09 baseline for one JVM target."""
    scope = jvm_scope_for(target)
    if scope.build_system is JvmBuildSystem.GRADLE_KOTLIN_DSL:
        plugins = (
            "application",
            "java" if target is ExecutionTarget.JVM_JAVA else "org.jetbrains.kotlin.jvm",
        )
        return JvmToolchainPolicy(
            selection=JvmTargetSelection(
                target=scope.target,
                language=scope.language,
                build_system=scope.build_system,
                layout=scope.layout,
                jdk_major=scope.jdk_major,
            ),
            build_tool_version=_GRADLE_VERSION,
            language_version=scope.language_version,
            allowed_repositories=(JvmRepository.MAVEN_CENTRAL,),
            allowed_plugins=tuple(sorted(plugins)),
        )
    return JvmToolchainPolicy(
        selection=JvmTargetSelection(
            target=scope.target,
            language=scope.language,
            build_system=scope.build_system,
            layout=scope.layout,
            jdk_major=scope.jdk_major,
        ),
        build_tool_version=_SBT_VERSION,
        language_version=_SCALA_VERSION,
        allowed_repositories=(JvmRepository.MAVEN_CENTRAL,),
        allowed_plugins=(),
        require_dependency_verification=False,
    )


def validate_toolchain(
    policy: JvmToolchainPolicy,
    declaration: JvmToolchainDeclaration,
) -> JvmToolchainValidation:
    """Validate exact project declarations without executing a process."""
    issues: set[JvmToolchainIssue] = set()
    if declaration.selection != policy.selection:
        issues.add(
            JvmToolchainIssue(
                code=JvmToolchainIssueCode.LANGUAGE_VERSION_MISMATCH,
                message="The project selection does not match the selected JVM profile.",
                subject="target-selection",
            )
        )
    if declaration.jdk_major != policy.selection.jdk_major:
        issues.add(
            JvmToolchainIssue(
                code=JvmToolchainIssueCode.JDK_VERSION_MISMATCH,
                message="The declared JDK major is outside the profile baseline.",
                subject="jdk",
            )
        )
    if declaration.build_tool_version != policy.build_tool_version:
        issues.add(
            JvmToolchainIssue(
                code=JvmToolchainIssueCode.BUILD_TOOL_VERSION_MISMATCH,
                message="The declared build-tool version is outside the profile baseline.",
                subject="build-tool",
            )
        )
    if declaration.language_version != policy.language_version:
        issues.add(
            JvmToolchainIssue(
                code=JvmToolchainIssueCode.LANGUAGE_VERSION_MISMATCH,
                message="The declared language version is outside the profile baseline.",
                subject="language",
            )
        )
    if not declaration.launcher_files_present:
        issues.add(
            JvmToolchainIssue(
                code=JvmToolchainIssueCode.LAUNCHER_FILES_MISSING,
                message="The required repository-owned launcher files are missing.",
                subject="launcher",
            )
        )
    if policy.require_launcher_integrity and not declaration.launcher_integrity_verified:
        issues.add(
            JvmToolchainIssue(
                code=JvmToolchainIssueCode.LAUNCHER_INTEGRITY_UNVERIFIED,
                message="The repository-owned launcher integrity was not verified.",
                subject="launcher",
            )
        )
    if policy.require_dependency_verification and not declaration.dependency_verification_enabled:
        issues.add(
            JvmToolchainIssue(
                code=JvmToolchainIssueCode.DEPENDENCY_VERIFICATION_DISABLED,
                message="Dependency verification is required by the selected profile.",
                subject="dependencies",
            )
        )
    for repository in declaration.repositories:
        if repository not in policy.allowed_repositories:
            issues.add(
                JvmToolchainIssue(
                    code=JvmToolchainIssueCode.REPOSITORY_NOT_ALLOWED,
                    message="The project declares a repository outside the allowlist.",
                    subject=repository.value,
                )
            )
    for plugin in declaration.plugins:
        if plugin not in policy.allowed_plugins:
            issues.add(
                JvmToolchainIssue(
                    code=JvmToolchainIssueCode.PLUGIN_NOT_ALLOWED,
                    message="The project declares a plugin outside the profile allowlist.",
                    subject=plugin,
                )
            )
    if policy.require_offline_post_setup and not declaration.network_disabled_after_setup:
        issues.add(
            JvmToolchainIssue(
                code=JvmToolchainIssueCode.NETWORK_POLICY_TOO_PERMISSIVE,
                message="Build, test, and run phases must disable external network access.",
                subject="network",
            )
        )
    canonical = tuple(sorted(issues, key=lambda issue: (issue.code.value, issue.subject)))
    return JvmToolchainValidation(
        policy_content_hash=policy.content_hash,
        status=(
            JvmToolchainValidationStatus.VALID
            if not canonical
            else JvmToolchainValidationStatus.INVALID
        ),
        issues=canonical,
    )


def _validate_text(value: str, *, label: str) -> None:
    if not value or value != " ".join(value.split()):
        raise ValueError(f"{label} must be normalized")


def _require_canonical_text(values: tuple[str, ...], *, label: str) -> None:
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError(f"{label} must be canonical and unique")
    for value in values:
        _validate_text(value, label=label)


def _require_canonical_enum(values: tuple[JvmRepository, ...], *, label: str) -> None:
    if values != tuple(sorted(values, key=lambda value: value.value)) or len(values) != len(
        set(values)
    ):
        raise ValueError(f"{label} must be canonical and unique")


def _canonical_json(value: dict[str, object]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
