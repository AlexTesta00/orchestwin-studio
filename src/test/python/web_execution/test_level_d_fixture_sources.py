"""Real fixture inputs are inspectable sources, never capability evidence themselves."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestwin.web_execution.browser_evidence import WebBrowserRouteSpec
from orchestwin.web_execution.detection import detect_web_project
from orchestwin.web_execution.lockfiles import validate_web_dependency_locks
from orchestwin.web_execution.phase_browser_evidence import WebBrowserInteraction
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.profile_registry import create_sprint08_web_profile_registry
from orchestwin.web_execution.static_browser_jobs import BrowserAction

from .test_profile_fixture_matrix import detection_snapshot

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "web_level_d"


def test_real_fixture_matrix_covers_all_eight_supported_configurations():
    matrix = json.loads((FIXTURE_ROOT / "matrix.json").read_text(encoding="utf-8"))
    assert matrix["schema_version"] == 1
    assert len(matrix["fixtures"]) == 8
    assert len({fixture["id"] for fixture in matrix["fixtures"]}) == 8
    registry = create_sprint08_web_profile_registry()
    expected = {
        (profile.scope.profile_id, configuration.frontend, configuration.backend)
        for profile in registry.profiles
        for configuration in profile.scope.language_configurations
    }
    observed = {
        (fixture["profile_id"], *fixture["language_configuration"].values())
        for fixture in matrix["fixtures"]
    }
    assert observed == expected


@pytest.mark.parametrize(
    "fixture_id",
    ["static", "vue-js", "vue-ts", "express-js", "express-ts", "php", "vue-node-js", "vue-node-ts"],
)
def test_fixture_has_real_locked_dependencies_and_an_exact_repair(fixture_id):
    matrix = json.loads((FIXTURE_ROOT / "matrix.json").read_text(encoding="utf-8"))
    fixture = next(item for item in matrix["fixtures"] if item["id"] == fixture_id)
    root = FIXTURE_ROOT / fixture["source_dir"]
    source = {}
    for path in sorted(root.rglob("*")):
        assert not path.is_symlink() and not path.is_junction()
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            assert not {"node_modules", "vendor", "dist"}.intersection(path.parts)
            content = path.read_bytes()
            assert len(content) <= 1024 * 1024
            source[relative] = content.decode("utf-8")
    assert sum(len(content.encode("utf-8")) for content in source.values()) < 20 * 1024 * 1024
    snapshot = detection_snapshot(source)
    detection = detect_web_project(snapshot)
    assert detection.selected is not None
    selection = detection.selected.selection
    assert selection.target.value == fixture["target"]
    assert selection.language_configuration.to_snapshot() == fixture["language_configuration"]
    assert selection.layout.value == fixture["layout"]
    locks = validate_web_dependency_locks(snapshot, selection=selection)
    assert locks.is_valid
    for path, content in source.items():
        if path.endswith("package.json"):
            package = json.loads(content)
            lock_path = str(Path(path).with_name("package-lock.json")).replace("\\", "/")
            lock = json.loads(source[lock_path])
            assert lock["lockfileVersion"] == 3
            assert len(lock["packages"]) > 2
            assert lock["packages"][""]["name"] == package["name"]
            for category in ("dependencies", "devDependencies"):
                assert lock["packages"][""].get(category, {}) == package.get(category, {})
                for name, version in package.get(category, {}).items():
                    assert lock["packages"][f"node_modules/{name}"]["version"] == version
            for name, dependency in lock["packages"].items():
                if name:
                    assert dependency["resolved"].startswith("https://registry.npmjs.org/")
                    assert dependency["integrity"].startswith("sha512-")
            assert "vitest" in package["scripts"]["test"]
        if path == "composer.json":
            package = json.loads(content)
            lock = json.loads(source["composer.lock"])
            assert len(lock["content-hash"]) == 32
            assert len(lock["packages-dev"]) > 1
            phpunit = next(
                item for item in lock["packages-dev"] if item["name"] == "phpunit/phpunit"
            )
            assert phpunit["version"] == package["require-dev"]["phpunit/phpunit"]
            assert all(item["dist"]["reference"] for item in lock["packages-dev"])
            assert "extends TestCase" in source["tests/CounterTest.php"]
    change, repair = fixture["failure_change"], fixture["repair"]
    assert change["path"] == repair["path"]
    assert source[repair["path"]] == repair["content"]
    assert change["content"] != repair["content"]
    assert WebExecutionPhase(fixture["expected_failure_phase"]) in {
        WebExecutionPhase.TEST,
        WebExecutionPhase.BROWSER_EVIDENCE,
    }
    assert fixture["expected_failure_marker"] == "LEVEL_D_NEGATIVE_CONTROL"
    assert any(
        fixture["expected_failure_marker"] in value
        for value in ([change["content"]] if fixture_id == "static" else source.values())
    )
    for route in fixture["browser_routes"]:
        WebBrowserRouteSpec(**route)
    for interaction in fixture["browser_interactions"]:
        WebBrowserInteraction(
            interaction["route_id"],
            tuple(BrowserAction(**action) for action in interaction["actions"]),
        )
    if fixture_id.startswith("express"):
        assert fixture["browser_routes"] == fixture["browser_interactions"] == []
