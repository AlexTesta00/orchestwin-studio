"""Tests for the amended web, JVM, and Android built-in profile descriptors."""

from __future__ import annotations

from orchestwin.sandbox.archive_policy import (
    SourceArchiveEntryDisposition,
    SourceArchiveEntryKind,
)
from orchestwin.sandbox.builtin_execution_profiles import (
    create_builtin_execution_profile_registry,
)
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionProfilePhase,
    ExecutionProfileProjectIssueCode,
    ExecutionProfileProjectValidationStatus,
    ExecutionTarget,
)
from orchestwin.sandbox.source_inventory import (
    SourceInventoryClassification,
    SourceInventoryEntry,
    SourceTreeInventory,
)

_DIGEST = "a" * 64


def _inventory(*paths: str) -> SourceTreeInventory:
    entries = tuple(
        sorted(
            (
                SourceInventoryEntry(
                    normalized_path=path,
                    kind=SourceArchiveEntryKind.FILE,
                    classification=SourceInventoryClassification.SOURCE,
                    size_bytes=1,
                    sha256_digest=_DIGEST,
                    disposition=SourceArchiveEntryDisposition.INCLUDE,
                    disposition_reason=None,
                )
                for path in paths
            ),
            key=lambda entry: (entry.normalized_path.casefold(), entry.normalized_path),
        )
    )
    return SourceTreeInventory(archive_sha256="b" * 64, entries=entries)


def _profile(profile_id: str):
    registry = create_builtin_execution_profile_registry()
    profile = registry.find(profile_id, "1.0.0")
    assert profile is not None
    return profile


def test_builtin_registry_contains_the_approved_amended_stack_families() -> None:
    """Register web, JVM, and Android targets without reintroducing Flutter implicitly."""
    registry = create_builtin_execution_profile_registry()

    assert tuple(profile.metadata.profile_id for profile in registry.profiles) == (
        "ANDROID_JAVA",
        "ANDROID_KOTLIN",
        "JVM_JAVA",
        "JVM_KOTLIN",
        "JVM_SCALA",
        "WEB_NODE_EXPRESS",
        "WEB_PHP",
        "WEB_STATIC",
        "WEB_VUE",
        "WEB_VUE_NODE",
    )
    assert all(
        profile.metadata.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
        for profile in registry.profiles
    )
    assert all(profile.metadata.validation_evidence_refs == () for profile in registry.profiles)
    assert ExecutionTarget.CUSTOM_DECLARATIVE not in {
        target for profile in registry.profiles for target in profile.metadata.supported_targets
    }


def test_static_web_profile_detects_html_css_and_javascript_without_level_d() -> None:
    """Recognize a static site while preserving the design-only capability boundary."""
    inventory = _inventory("index.html", "assets/site.css", "assets/site.js")
    profile = _profile("WEB_STATIC")

    detection = profile.detect(inventory)
    validation = profile.validate_project(inventory)

    assert detection.confidence == 100
    assert detection.conflicting_indicators == ()
    assert detection.requires_human_decision is False
    assert validation.status is ExecutionProfileProjectValidationStatus.DESIGN_ONLY
    assert validation.issues[0].code is (ExecutionProfileProjectIssueCode.DESIGN_ONLY_CAPABILITY)
    assert profile.create_plan(ExecutionProfilePhase.BUILD, inventory) is None


def test_vue_node_composition_wins_structurally_but_single_profiles_show_conflicts() -> None:
    """Expose full-stack evidence instead of silently choosing Vue or Express alone."""
    inventory = _inventory(
        "package.json",
        "vite.config.ts",
        "frontend/src/App.vue",
        "backend/src/server.ts",
    )
    full_stack = _profile("WEB_VUE_NODE").detect(inventory)
    vue = _profile("WEB_VUE").detect(inventory)
    node = _profile("WEB_NODE_EXPRESS").detect(inventory)

    assert full_stack.confidence == 100
    assert full_stack.conflicting_indicators == ()
    assert full_stack.requires_human_decision is False
    assert vue.conflicting_indicators == ("conflict.node.server.entry",)
    assert node.conflicting_indicators == ("conflict.vue.source",)
    assert vue.requires_human_decision is True
    assert node.requires_human_decision is True


def test_android_kotlin_is_distinguished_from_plain_jvm_kotlin() -> None:
    """Treat AndroidManifest as a conflict for JVM-only selection."""
    inventory = _inventory(
        "app/src/main/AndroidManifest.xml",
        "app/src/main/java/example/MainActivity.kt",
        "app/build.gradle.kts",
    )
    android = _profile("ANDROID_KOTLIN").detect(inventory)
    jvm = _profile("JVM_KOTLIN").detect(inventory)

    assert android.confidence == 100
    assert android.detected_targets == (ExecutionTarget.ANDROID_KOTLIN,)
    assert jvm.conflicting_indicators == ("conflict.android.manifest",)
    assert jvm.requires_human_decision is True


def test_scala_and_php_targets_are_first_class_profile_candidates() -> None:
    """Preserve the owner-approved scope extension beyond TypeScript and Kotlin."""
    scala_inventory = _inventory("build.sbt", "src/main/scala/example/Main.scala")
    php_inventory = _inventory("composer.json", "public/index.php", "public/site.css")

    scala = _profile("JVM_SCALA").detect(scala_inventory)
    php = _profile("WEB_PHP").detect(php_inventory)

    assert scala.confidence == 100
    assert scala.detected_targets == (ExecutionTarget.JVM_SCALA,)
    assert php.confidence == 100
    assert php.detected_targets == (ExecutionTarget.WEB_PHP,)


def test_missing_required_indicators_make_project_validation_invalid() -> None:
    """Do not select a profile from a language extension without its project structure."""
    inventory = _inventory("src/main/java/example/Main.java")
    profile = _profile("JVM_JAVA")

    detection = profile.detect(inventory)
    validation = profile.validate_project(inventory)

    assert detection.confidence == 55
    assert detection.requires_human_decision is True
    assert validation.status is ExecutionProfileProjectValidationStatus.INVALID
    assert validation.issues[0].code is (
        ExecutionProfileProjectIssueCode.MISSING_REQUIRED_INDICATOR
    )
    assert validation.issues[0].path == "jvm.build"
