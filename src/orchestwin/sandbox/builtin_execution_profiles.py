"""Capability-honest built-in profile descriptors for the approved stack families."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

from orchestwin.sandbox.archive_policy import SourceArchiveEntryKind
from orchestwin.sandbox.command_plans import CommandNetworkMode, CommandPlan
from orchestwin.sandbox.execution_policy import DEFAULT_SANDBOX_RESOURCE_LIMITS
from orchestwin.sandbox.execution_profile_registry import (
    ExecutionProfileRegistry,
    create_execution_profile_registry,
)
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionProfileDetection,
    ExecutionProfileMetadata,
    ExecutionProfileNetworkPolicy,
    ExecutionProfilePhase,
    ExecutionProfileProjectIssue,
    ExecutionProfileProjectIssueCode,
    ExecutionProfileProjectValidation,
    ExecutionProfileProjectValidationStatus,
    ExecutionTarget,
    create_execution_profile_metadata,
)
from orchestwin.sandbox.source_inventory import SourceTreeInventory


class _IndicatorKind(StrEnum):
    FILE_NAME = "FILE_NAME"
    PATH_SUFFIX = "PATH_SUFFIX"
    DIRECTORY_NAME = "DIRECTORY_NAME"


@dataclass(frozen=True, slots=True)
class _IndicatorRule:
    code: str
    kind: _IndicatorKind
    values: tuple[str, ...]
    required: bool
    weight: int

    def __post_init__(self) -> None:
        if not self.code or self.code != self.code.strip():
            raise ValueError("built-in profile indicator code must be normalized")
        if not self.values or self.values != tuple(sorted(set(self.values))):
            raise ValueError("built-in profile indicator values must be canonical")
        if any(
            not value or value != value.casefold() or value != value.strip() or "\\" in value
            for value in self.values
        ):
            raise ValueError("built-in profile indicator values must be lowercase")
        if not isinstance(self.required, bool):
            raise TypeError("built-in profile indicator required marker must be boolean")
        if isinstance(self.weight, bool) or not 1 <= self.weight <= 100:
            raise ValueError("built-in profile indicator weight must be from one to 100")

    def matches(self, inventory: SourceTreeInventory) -> bool:
        values = frozenset(self.values)
        for entry in inventory.included_entries:
            path = PurePosixPath(entry.normalized_path)
            normalized_path = path.as_posix().casefold()
            if self.kind is _IndicatorKind.FILE_NAME:
                if entry.kind is SourceArchiveEntryKind.FILE and path.name.casefold() in values:
                    return True
            elif self.kind is _IndicatorKind.PATH_SUFFIX:
                if entry.kind is SourceArchiveEntryKind.FILE and any(
                    normalized_path.endswith(value) for value in values
                ):
                    return True
            else:
                directory_parts = (
                    path.parts
                    if entry.kind is SourceArchiveEntryKind.DIRECTORY
                    else path.parts[:-1]
                )
                if any(part.casefold() in values for part in directory_parts):
                    return True
        return False


@dataclass(frozen=True, slots=True)
class RuleBasedDesignOnlyProfile:
    """Deterministic detector that intentionally exposes only Level C in Sprint 07."""

    metadata: ExecutionProfileMetadata
    positive_rules: tuple[_IndicatorRule, ...]
    conflicting_rules: tuple[_IndicatorRule, ...]

    def __post_init__(self) -> None:
        if self.metadata.capability_status is not (ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C):
            raise ValueError("built-in Sprint 07 profiles must remain design-only")
        rule_codes = tuple(rule.code for rule in (*self.positive_rules, *self.conflicting_rules))
        if len(rule_codes) != len(set(rule_codes)):
            raise ValueError("built-in profile indicator codes must be unique")
        if tuple(sorted(rule_codes)) != self.metadata.file_indicators:
            raise ValueError("built-in profile metadata must expose every indicator code")

    def detect(self, inventory: SourceTreeInventory) -> ExecutionProfileDetection:
        matched_positive = tuple(
            rule.code for rule in self.positive_rules if rule.matches(inventory)
        )
        matched_conflicts = tuple(
            rule.code for rule in self.conflicting_rules if rule.matches(inventory)
        )
        matched_positive = tuple(sorted(matched_positive))
        matched_conflicts = tuple(sorted(matched_conflicts))

        total_weight = sum(rule.weight for rule in self.positive_rules)
        matched_weight = sum(
            rule.weight for rule in self.positive_rules if rule.code in matched_positive
        )
        confidence = 0 if matched_weight == 0 else round(100 * matched_weight / total_weight)
        if matched_conflicts and confidence:
            confidence = max(1, confidence - min(40, 15 * len(matched_conflicts)))

        missing_required = tuple(
            rule.code
            for rule in self.positive_rules
            if rule.required and rule.code not in matched_positive
        )
        requires_human_decision = bool(missing_required or matched_conflicts)

        return ExecutionProfileDetection(
            profile_reference=self.metadata.reference,
            detected_targets=(self.metadata.supported_targets if confidence else ()),
            confidence=confidence,
            positive_indicators=matched_positive,
            conflicting_indicators=matched_conflicts,
            missing_tools=(),
            requires_human_decision=requires_human_decision,
        )

    def validate_project(
        self,
        inventory: SourceTreeInventory,
    ) -> ExecutionProfileProjectValidation:
        detection = self.detect(inventory)
        issues: list[ExecutionProfileProjectIssue] = []

        matched = frozenset(detection.positive_indicators)
        for rule in self.positive_rules:
            if rule.required and rule.code not in matched:
                issues.append(
                    ExecutionProfileProjectIssue(
                        code=(ExecutionProfileProjectIssueCode.MISSING_REQUIRED_INDICATOR),
                        message="A required project structure indicator is missing.",
                        path=rule.code,
                    )
                )
        for code in detection.conflicting_indicators:
            issues.append(
                ExecutionProfileProjectIssue(
                    code=ExecutionProfileProjectIssueCode.CONFLICTING_INDICATOR,
                    message="A conflicting stack indicator requires human review.",
                    path=code,
                )
            )

        if issues or not detection.is_candidate:
            if not issues:
                issues.append(
                    ExecutionProfileProjectIssue(
                        code=ExecutionProfileProjectIssueCode.UNSUPPORTED_PROJECT,
                        message="The project does not match this execution profile.",
                    )
                )
            status = ExecutionProfileProjectValidationStatus.INVALID
        else:
            issues.append(
                ExecutionProfileProjectIssue(
                    code=ExecutionProfileProjectIssueCode.DESIGN_ONLY_CAPABILITY,
                    message=(
                        "This profile is registered for design guidance but has not "
                        "been validated for automated execution."
                    ),
                )
            )
            status = ExecutionProfileProjectValidationStatus.DESIGN_ONLY

        return ExecutionProfileProjectValidation(
            profile_reference=self.metadata.reference,
            inventory_content_hash=inventory.content_hash,
            status=status,
            issues=tuple(issues),
        )

    def create_plan(
        self,
        phase: ExecutionProfilePhase,
        inventory: SourceTreeInventory,
    ) -> CommandPlan | None:
        return None


_DISABLED_NETWORK_POLICY = ExecutionProfileNetworkPolicy(
    setup=CommandNetworkMode.DISABLED,
    static_checks=CommandNetworkMode.DISABLED,
    build=CommandNetworkMode.DISABLED,
    test=CommandNetworkMode.DISABLED,
    run=CommandNetworkMode.DISABLED,
)


def create_builtin_execution_profiles() -> tuple[RuleBasedDesignOnlyProfile, ...]:
    """Create the complete amended web, JVM, and Android Sprint 07 catalog."""
    return (
        _profile(
            profile_id="ANDROID_JAVA",
            name="Android Java",
            target=ExecutionTarget.ANDROID_JAVA,
            positive_rules=(
                _file("android.manifest", "androidmanifest.xml", weight=35),
                _suffix("java.source", ".java", weight=35),
                _file(
                    "gradle.build",
                    "build.gradle",
                    "build.gradle.kts",
                    weight=30,
                ),
            ),
        ),
        _profile(
            profile_id="ANDROID_KOTLIN",
            name="Android Kotlin",
            target=ExecutionTarget.ANDROID_KOTLIN,
            positive_rules=(
                _file("android.manifest", "androidmanifest.xml", weight=35),
                _suffix("kotlin.source", ".kt", weight=35),
                _file(
                    "gradle.build",
                    "build.gradle",
                    "build.gradle.kts",
                    weight=30,
                ),
            ),
        ),
        _profile(
            profile_id="JVM_JAVA",
            name="JVM Java",
            target=ExecutionTarget.JVM_JAVA,
            positive_rules=(
                _suffix("java.source", ".java", weight=55),
                _file(
                    "jvm.build",
                    "build.gradle",
                    "build.gradle.kts",
                    "pom.xml",
                    weight=45,
                ),
            ),
            conflicting_rules=(
                _file(
                    "conflict.android.manifest",
                    "androidmanifest.xml",
                    required=False,
                    weight=1,
                ),
            ),
        ),
        _profile(
            profile_id="JVM_KOTLIN",
            name="JVM Kotlin",
            target=ExecutionTarget.JVM_KOTLIN,
            positive_rules=(
                _suffix("kotlin.source", ".kt", weight=55),
                _file(
                    "jvm.build",
                    "build.gradle",
                    "build.gradle.kts",
                    "pom.xml",
                    weight=45,
                ),
            ),
            conflicting_rules=(
                _file(
                    "conflict.android.manifest",
                    "androidmanifest.xml",
                    required=False,
                    weight=1,
                ),
            ),
        ),
        _profile(
            profile_id="JVM_SCALA",
            name="JVM Scala",
            target=ExecutionTarget.JVM_SCALA,
            positive_rules=(
                _suffix("scala.source", ".scala", weight=55),
                _file(
                    "scala.build",
                    "build.gradle",
                    "build.gradle.kts",
                    "build.sbt",
                    "pom.xml",
                    weight=45,
                ),
            ),
            conflicting_rules=(
                _file(
                    "conflict.android.manifest",
                    "androidmanifest.xml",
                    required=False,
                    weight=1,
                ),
            ),
        ),
        _profile(
            profile_id="WEB_NODE_EXPRESS",
            name="Node.js and Express web application",
            target=ExecutionTarget.WEB_NODE_EXPRESS,
            positive_rules=(
                _file("node.manifest", "package.json", weight=40),
                _file(
                    "node.server.entry",
                    "app.js",
                    "app.ts",
                    "server.js",
                    "server.ts",
                    weight=40,
                ),
                _suffix(
                    "javascript.typescript.source",
                    ".js",
                    ".mjs",
                    ".ts",
                    required=False,
                    weight=20,
                ),
            ),
            conflicting_rules=(
                _suffix(
                    "conflict.vue.source",
                    ".vue",
                    required=False,
                    weight=1,
                ),
            ),
        ),
        _profile(
            profile_id="WEB_PHP",
            name="PHP web application",
            target=ExecutionTarget.WEB_PHP,
            positive_rules=(
                _suffix("php.source", ".php", weight=70),
                _file(
                    "php.composer",
                    "composer.json",
                    required=False,
                    weight=15,
                ),
                _suffix(
                    "php.web.assets",
                    ".css",
                    ".html",
                    ".js",
                    required=False,
                    weight=15,
                ),
            ),
            conflicting_rules=(
                _suffix(
                    "conflict.vue.source",
                    ".vue",
                    required=False,
                    weight=1,
                ),
            ),
        ),
        _profile(
            profile_id="WEB_STATIC",
            name="Static HTML CSS JavaScript website",
            target=ExecutionTarget.WEB_STATIC,
            positive_rules=(
                _suffix("html.source", ".htm", ".html", weight=70),
                _suffix(
                    "static.assets",
                    ".css",
                    ".js",
                    required=False,
                    weight=30,
                ),
            ),
            conflicting_rules=(
                _suffix(
                    "conflict.php.source",
                    ".php",
                    required=False,
                    weight=1,
                ),
                _suffix(
                    "conflict.vue.source",
                    ".vue",
                    required=False,
                    weight=1,
                ),
            ),
        ),
        _profile(
            profile_id="WEB_VUE",
            name="Vue web application",
            target=ExecutionTarget.WEB_VUE,
            positive_rules=(
                _file("node.manifest", "package.json", weight=35),
                _suffix("vue.source", ".vue", weight=45),
                _file(
                    "vue.vite.config",
                    "vite.config.js",
                    "vite.config.ts",
                    required=False,
                    weight=10,
                ),
                _suffix(
                    "vue.script.source",
                    ".js",
                    ".ts",
                    required=False,
                    weight=10,
                ),
            ),
            conflicting_rules=(
                _file(
                    "conflict.node.server.entry",
                    "app.js",
                    "app.ts",
                    "server.js",
                    "server.ts",
                    required=False,
                    weight=1,
                ),
            ),
        ),
        _profile(
            profile_id="WEB_VUE_NODE",
            name="Vue and Node.js Express full-stack application",
            target=ExecutionTarget.WEB_VUE_NODE,
            positive_rules=(
                _file("node.manifest", "package.json", weight=25),
                _suffix("vue.source", ".vue", weight=35),
                _file(
                    "node.server.entry",
                    "app.js",
                    "app.ts",
                    "server.js",
                    "server.ts",
                    weight=30,
                ),
                _file(
                    "vue.vite.config",
                    "vite.config.js",
                    "vite.config.ts",
                    required=False,
                    weight=10,
                ),
            ),
        ),
    )


def create_builtin_execution_profile_registry() -> ExecutionProfileRegistry:
    """Return the canonical built-in registry used by capability negotiation."""
    return create_execution_profile_registry(create_builtin_execution_profiles())


def _profile(
    *,
    profile_id: str,
    name: str,
    target: ExecutionTarget,
    positive_rules: tuple[_IndicatorRule, ...],
    conflicting_rules: tuple[_IndicatorRule, ...] = (),
) -> RuleBasedDesignOnlyProfile:
    rules = (*positive_rules, *conflicting_rules)
    metadata = create_execution_profile_metadata(
        profile_id=profile_id,
        name=name,
        version="1.0.0",
        capability_status=ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C,
        supported_targets=(target,),
        file_indicators=tuple(rule.code for rule in rules),
        required_runners=(),
        base_images=(),
        network_policy=_DISABLED_NETWORK_POLICY,
        resource_defaults=DEFAULT_SANDBOX_RESOURCE_LIMITS,
        maintainer="OrchesTwin Studio",
        license_notes=(
            "Sprint 07 descriptor only; automated execution requires later profile validation."
        ),
    )
    return RuleBasedDesignOnlyProfile(
        metadata=metadata,
        positive_rules=positive_rules,
        conflicting_rules=conflicting_rules,
    )


def _file(
    code: str,
    *names: str,
    required: bool = True,
    weight: int,
) -> _IndicatorRule:
    return _IndicatorRule(
        code=code,
        kind=_IndicatorKind.FILE_NAME,
        values=tuple(sorted(name.casefold() for name in names)),
        required=required,
        weight=weight,
    )


def _suffix(
    code: str,
    *suffixes: str,
    required: bool = True,
    weight: int,
) -> _IndicatorRule:
    return _IndicatorRule(
        code=code,
        kind=_IndicatorKind.PATH_SUFFIX,
        values=tuple(sorted(suffix.casefold() for suffix in suffixes)),
        required=required,
        weight=weight,
    )
