"""Tests for the framework-free PHP and Composer execution profile."""

from __future__ import annotations

import hashlib
import json

from orchestwin.sandbox.archive_policy import (
    SourceArchiveEntryDisposition,
    SourceArchiveEntryKind,
)
from orchestwin.sandbox.execution_profiles import ExecutionCapabilityStatus
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
from orchestwin.web_execution.php_profile import WebPhpExecutionProfile
from orchestwin.web_execution.profile_contracts import (
    WebProfileIssueCode,
    WebProfileRunnerSet,
    WebProfileValidationStatus,
)


def snapshot(files: dict[str, str]):
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
    inventory = SourceTreeInventory(archive_sha256="a" * 64, entries=entries)
    return create_web_detection_snapshot(inventory, text_content_by_path=files)


def composer_json(*, framework: str | None = None) -> str:
    requirements = {"php": ">=8.4"}
    if framework is not None:
        requirements[framework] = "*"
    return json.dumps(
        {
            "require": requirements,
            "require-dev": {"phpunit/phpunit": "^12"},
            "config": {"allow-plugins": False},
        }
    )


def composer_lock() -> str:
    return json.dumps(
        {
            "content-hash": "fixture",
            "packages": [],
            "packages-dev": [],
        }
    )


def profile_inputs(files: dict[str, str]):
    source = snapshot(files)
    detection = detect_web_project(source)
    assert detection.selected is not None
    selection = detection.selected.selection
    locks = validate_web_dependency_locks(source, selection=selection)
    return source, selection, locks


def test_framework_free_php_profile_is_structurally_ready() -> None:
    source, selection, locks = profile_inputs(
        {
            "composer.json": composer_json(),
            "composer.lock": composer_lock(),
            "public/index.php": "<?php echo 'ready';",
            "tests/HomeTest.php": "<?php final class HomeTest {}",
        }
    )

    validation = WebPhpExecutionProfile().validate(
        source,
        selection=selection,
        lock_report=locks,
    )

    assert validation.is_ready
    assert validation.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C


def test_php_profile_creates_local_health_and_browser_contracts() -> None:
    source, selection, locks = profile_inputs(
        {
            "composer.json": composer_json(),
            "composer.lock": composer_lock(),
            "public/index.php": "<?php echo 'ready';",
        }
    )

    contract = WebPhpExecutionProfile().create_contract(
        source,
        selection=selection,
        lock_report=locks,
        source_revision_content_hash="b" * 64,
        source_tree_hash="c" * 64,
        runners=WebProfileRunnerSet(
            execution_runner_image_digest="d" * 64,
            browser_runner_image_digest="e" * 64,
        ),
    )

    assert contract.execution_plan.profile_id == "web.php"
    assert contract.health_checks[0].port == 8080
    assert contract.browser_evidence_request is not None
    assert contract.browser_evidence_request.base_url == "http://127.0.0.1:8080"


def test_php_profile_rejects_framework_dependencies() -> None:
    source = snapshot(
        {
            "composer.json": composer_json(framework="laravel/framework"),
            "composer.lock": composer_lock(),
            "public/index.php": "<?php echo 'ready';",
        }
    )
    profile = WebPhpExecutionProfile()
    from orchestwin.web_execution.targets import WebTargetSelection

    target_selection = WebTargetSelection(
        target=profile.scope.target,
        language_configuration=profile.scope.language_configurations[0],
        layout=profile.scope.layout,
    )
    locks = validate_web_dependency_locks(source, selection=target_selection)

    validation = profile.validate(
        source,
        selection=target_selection,
        lock_report=locks,
    )

    assert validation.status is WebProfileValidationStatus.INVALID
    assert {issue.code for issue in validation.issues} >= {
        WebProfileIssueCode.DETECTION_NOT_SELECTED,
        WebProfileIssueCode.FORBIDDEN_DEPENDENCY,
    }
