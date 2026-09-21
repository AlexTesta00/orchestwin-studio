"""Dependency boundary checks; actual cache population needs the Docker fixture run."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_FIXTURES = Path(__file__).parents[2] / "fixtures" / "jvm_execution"
_GRADLE_FIXTURES = ("jvm-java-greeting", "jvm-kotlin-calculator")
_INIT_SCRIPT = (
    Path(__file__).parents[4] / "infra" / "jvm-runners" / "resolve-dependencies.gradle.kts"
)


def _read(fixture: str, path: str) -> str:
    return (_FIXTURES / fixture / path).read_text(encoding="utf-8")


def test_resolver_is_runner_owned_and_never_regenerates_dependency_trust() -> None:
    script = _INIT_SCRIPT.read_text(encoding="utf-8")

    assert 'tasks.register("orchestwinResolveDependencies")' in script
    assert "it.isCanBeResolved" in script
    assert "configuration.resolve()" in script
    assert all(
        unwanted not in script
        for unwanted in (
            "lenient",
            "catch",
            "runCatching",
            "dependsOn",
            "--write-verification-metadata",
            "--dependency-verification=off",
        )
    )
    for fixture in _GRADLE_FIXTURES:
        assert "orchestwinResolveDependencies" not in _read(fixture, "build.gradle.kts")


@pytest.mark.parametrize("fixture", _GRADLE_FIXTURES)
def test_fixture_uses_only_settings_owned_maven_central_repositories(fixture: str) -> None:
    settings = _read(fixture, "settings.gradle.kts")
    build = _read(fixture, "build.gradle.kts")

    assert settings.startswith("pluginManagement {")
    assert "dependencyResolutionManagement {" in settings
    assert "repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)" in settings
    repositories = re.findall(r"repositories\s*\{([^{}]*)\}", settings)
    assert [repository.strip() for repository in repositories] == [
        "mavenCentral()",
        "mavenCentral()",
    ]
    assert re.search(r"\brepositories\s*\{", build) is None
    assert all(
        unwanted not in settings + build
        for unwanted in ("gradlePluginPortal", "mavenLocal", "jcenter", "repo1.maven.org")
    )


@pytest.mark.parametrize("fixture", _GRADLE_FIXTURES)
def test_fixture_pins_the_junit_platform_runtime_needed_by_gradle_nine(fixture: str) -> None:
    build = _read(fixture, "build.gradle.kts")

    assert 'testImplementation("org.junit.jupiter:junit-jupiter:5.11.4")' in build
    assert 'testRuntimeOnly("org.junit.platform:junit-platform-launcher:1.11.4")' in build
    assert "useJUnitPlatform()" in build
    assert ":latest" not in build and ":+" not in build and "SNAPSHOT" not in build


def test_kotlin_plugin_and_junit_adapter_match_the_pinned_baseline() -> None:
    build = _read("jvm-kotlin-calculator", "build.gradle.kts")
    settings = _read("jvm-kotlin-calculator", "settings.gradle.kts")

    assert 'kotlin("jvm") version "2.4.10"' in build
    assert "jvmToolchain(21)" in build
    assert 'testImplementation(kotlin("test-junit5"))' in build
    assert 'testImplementation(kotlin("test"))' not in build
    assert 'requested.id.id == "org.jetbrains.kotlin.jvm"' in settings
    assert 'useModule("org.jetbrains.kotlin:kotlin-gradle-plugin:${requested.version}")' in settings
