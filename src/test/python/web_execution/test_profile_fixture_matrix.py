"""Contract matrix for every Sprint 08 Web target, failure, and repair fixture."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from orchestwin.sandbox.archive_policy import (
    SourceArchiveEntryDisposition,
    SourceArchiveEntryKind,
)
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionTarget,
)
from orchestwin.sandbox.source_inventory import (
    SourceInventoryClassification,
    SourceInventoryEntry,
    SourceTreeInventory,
)
from orchestwin.web_execution.detection import (
    create_web_detection_snapshot,
    detect_web_project,
)
from orchestwin.web_execution.lockfiles import validate_web_dependency_locks
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.profile_contracts import WebProfileRunnerSet
from orchestwin.web_execution.profile_registry import (
    create_sprint08_web_profile_registry,
)
from orchestwin.web_execution.targets import WebImplementationLanguage

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "web_execution"
MATRIX_PATH = FIXTURE_ROOT / "matrix.json"
EXPECTED_FAILURE_FIXTURES = {
    "artifact-collection-failure",
    "axe-accessibility-finding",
    "browser-navigation-failure",
    "dependency-install-failure",
    "express-integration-test-failure",
    "health-check-failure",
    "javascript-unit-test-failure",
    "missing-lockfile",
    "multiple-lockfiles",
    "network-policy-violation",
    "php-lint-failure",
    "phpunit-failure",
    "runtime-startup-failure",
    "timeout",
    "typescript-compilation-failure",
}
EXPECTED_REPAIR_TARGETS = {
    "WEB_STATIC",
    "WEB_VUE",
    "WEB_NODE_EXPRESS",
    "WEB_PHP",
    "WEB_VUE_NODE",
}


def matrix() -> dict[str, object]:
    payload = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def fixture_files(fixture_id: str) -> dict[str, str]:
    root = FIXTURE_ROOT / fixture_id
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def detection_snapshot(files: dict[str, str]):
    entries = tuple(
        SourceInventoryEntry(
            normalized_path=path,
            kind=SourceArchiveEntryKind.FILE,
            classification=SourceInventoryClassification.SOURCE,
            size_bytes=len(content.encode("utf-8")),
            sha256_digest=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            disposition=SourceArchiveEntryDisposition.INCLUDE,
            disposition_reason=None,
        )
        for path, content in sorted(files.items())
    )
    inventory = SourceTreeInventory(
        archive_sha256=hashlib.sha256(
            "\n".join(f"{path}:{content}" for path, content in sorted(files.items())).encode()
        ).hexdigest(),
        entries=entries,
    )
    return create_web_detection_snapshot(
        inventory,
        text_content_by_path=files,
    )


@pytest.mark.parametrize(
    "fixture",
    matrix()["valid_fixtures"],
    ids=lambda fixture: fixture["id"],
)
def test_every_valid_fixture_creates_one_complete_profile_contract(
    fixture: dict[str, object],
) -> None:
    fixture_id = str(fixture["id"])
    source = detection_snapshot(fixture_files(fixture_id))
    detection = detect_web_project(source)
    assert detection.selected is not None
    assert detection.selected.selection.target.value == fixture["target"]

    registry = create_sprint08_web_profile_registry()
    profile = registry.for_target(detection.selected.selection.target)
    assert profile is not None
    locks = validate_web_dependency_locks(
        source,
        selection=detection.selected.selection,
    )
    validation = profile.validate(
        source,
        selection=detection.selected.selection,
        lock_report=locks,
    )
    contract = profile.create_contract(
        source,
        selection=detection.selected.selection,
        lock_report=locks,
        source_revision_content_hash="a" * 64,
        source_tree_hash="b" * 64,
        runners=WebProfileRunnerSet(
            execution_runner_image_digest="c" * 64,
            browser_runner_image_digest=(
                "d" * 64 if profile.scope.requires_browser_evidence else None
            ),
        ),
    )

    assert locks.is_valid
    assert validation.is_ready
    assert validation.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
    assert tuple(phase.phase for phase in contract.execution_plan.phases) == tuple(
        WebExecutionPhase
    )
    assert (contract.browser_evidence_request is not None) == (
        profile.scope.requires_browser_evidence
    )
    configuration = validation.selection.language_configuration
    assert (None if configuration.frontend is None else configuration.frontend.value) == fixture[
        "frontend"
    ]
    assert (None if configuration.backend is None else configuration.backend.value) == fixture[
        "backend"
    ]


def test_matrix_covers_every_declared_language_variant() -> None:
    valid = matrix()["valid_fixtures"]
    assert isinstance(valid, list)
    configurations = {
        (item["target"], item["frontend"], item["backend"])
        for item in valid
        if isinstance(item, dict)
    }

    assert configurations == {
        ("WEB_STATIC", WebImplementationLanguage.STATIC_ASSETS.value, None),
        ("WEB_VUE", WebImplementationLanguage.JAVASCRIPT.value, None),
        ("WEB_VUE", WebImplementationLanguage.TYPESCRIPT.value, None),
        ("WEB_NODE_EXPRESS", None, WebImplementationLanguage.JAVASCRIPT.value),
        ("WEB_NODE_EXPRESS", None, WebImplementationLanguage.TYPESCRIPT.value),
        ("WEB_PHP", None, WebImplementationLanguage.PHP.value),
        (
            "WEB_VUE_NODE",
            WebImplementationLanguage.JAVASCRIPT.value,
            WebImplementationLanguage.JAVASCRIPT.value,
        ),
        (
            "WEB_VUE_NODE",
            WebImplementationLanguage.TYPESCRIPT.value,
            WebImplementationLanguage.TYPESCRIPT.value,
        ),
    }


def test_failure_fixture_catalog_is_complete_and_inspectable() -> None:
    declared = matrix()["failure_fixtures"]
    assert isinstance(declared, list)
    fixture_ids = {str(item["id"]) for item in declared if isinstance(item, dict)}
    assert fixture_ids == EXPECTED_FAILURE_FIXTURES

    for fixture_id in fixture_ids:
        payload = json.loads(
            (FIXTURE_ROOT / "failures" / fixture_id / "fixture.json").read_text(encoding="utf-8")
        )
        assert payload["fixture_id"] == fixture_id
        assert payload["expected_failure_category"]
        assert payload["claim_boundary"].endswith("not Level D validation evidence by itself.")


def test_repair_catalog_covers_each_public_profile_without_claiming_success() -> None:
    declared = matrix()["repair_fixtures"]
    assert isinstance(declared, list)
    targets = {str(item["target"]) for item in declared if isinstance(item, dict)}
    assert targets == EXPECTED_REPAIR_TARGETS

    for target in targets:
        directory = target.casefold().replace("_", "-")
        payload = json.loads(
            (FIXTURE_ROOT / "repairs" / directory / "fixture.json").read_text(encoding="utf-8")
        )
        assert payload["expected_terminal_status"] == "PASSED"
        assert payload["required_evidence"] == [
            "failure_signature",
            "source_revision_n_plus_1",
            "successful_rerun",
        ]


def test_matrix_does_not_promote_profiles_without_recorded_runs() -> None:
    manifest = matrix()
    assert manifest["capability_status_before_recorded_validation"] == (
        ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C.value
    )
    registry = create_sprint08_web_profile_registry()
    assert {profile.scope.target for profile in registry.profiles} == {
        ExecutionTarget.WEB_STATIC,
        ExecutionTarget.WEB_VUE,
        ExecutionTarget.WEB_NODE_EXPRESS,
        ExecutionTarget.WEB_PHP,
        ExecutionTarget.WEB_VUE_NODE,
    }
    assert all(
        profile.scope.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
        for profile in registry.profiles
    )
