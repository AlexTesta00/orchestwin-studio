"""Tests for deterministic npm and Composer lockfile policies."""

from __future__ import annotations

import hashlib
import json

from orchestwin.sandbox.archive_policy import (
    SourceArchiveEntryDisposition,
    SourceArchiveEntryKind,
)
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.sandbox.source_inventory import (
    SourceInventoryClassification,
    SourceInventoryEntry,
    SourceTreeInventory,
)
from orchestwin.web_execution.detection import create_web_detection_snapshot
from orchestwin.web_execution.lockfiles import (
    WebLockfileIssueCode,
    WebLockfileValidationStatus,
    validate_web_dependency_locks,
)
from orchestwin.web_execution.targets import (
    WebImplementationLanguage,
    WebLanguageConfiguration,
    WebProjectLayout,
    WebTargetSelection,
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


def selection(target: ExecutionTarget) -> WebTargetSelection:
    if target is ExecutionTarget.WEB_PHP:
        language = WebLanguageConfiguration(
            frontend=None,
            backend=WebImplementationLanguage.PHP,
        )
    elif target is ExecutionTarget.WEB_VUE_NODE:
        language = WebLanguageConfiguration(
            frontend=WebImplementationLanguage.TYPESCRIPT,
            backend=WebImplementationLanguage.TYPESCRIPT,
        )
    else:
        language = WebLanguageConfiguration(
            frontend=WebImplementationLanguage.TYPESCRIPT,
            backend=None,
        )
    return WebTargetSelection(
        target=target,
        language_configuration=language,
        layout=(
            WebProjectLayout.FRONTEND_BACKEND
            if target is ExecutionTarget.WEB_VUE_NODE
            else WebProjectLayout.SINGLE_ROOT
        ),
    )


def npm_files(root: str = ".") -> dict[str, str]:
    prefix = "" if root == "." else f"{root}/"
    return {
        f"{prefix}package.json": json.dumps({"name": "fixture"}),
        f"{prefix}package-lock.json": json.dumps(
            {"name": "fixture", "lockfileVersion": 3, "packages": {"": {}}}
        ),
    }


def test_npm_requires_one_supported_package_lock() -> None:
    files = npm_files()
    report = validate_web_dependency_locks(
        snapshot(files),
        selection=selection(ExecutionTarget.WEB_VUE),
    )

    assert report.is_valid
    assert report.roots[0].status is WebLockfileValidationStatus.VALID
    assert report.roots[0].lockfile_path == "package-lock.json"


def test_npm_rejects_missing_or_competing_lockfiles() -> None:
    files = {"package.json": json.dumps({"name": "fixture"}), "yarn.lock": "lock"}
    report = validate_web_dependency_locks(
        snapshot(files),
        selection=selection(ExecutionTarget.WEB_VUE),
    )

    assert not report.is_valid
    assert {issue.code for issue in report.roots[0].issues} == {
        WebLockfileIssueCode.LOCKFILE_MISSING,
        WebLockfileIssueCode.CONFLICTING_PACKAGE_MANAGER,
    }


def test_composed_project_validates_frontend_and_backend_independently() -> None:
    files = {**npm_files("frontend"), **npm_files("backend")}
    report = validate_web_dependency_locks(
        snapshot(files),
        selection=selection(ExecutionTarget.WEB_VUE_NODE),
    )

    assert report.is_valid
    assert tuple(root.root for root in report.roots) == ("backend", "frontend")


def test_composer_requires_locked_packages_and_disables_scripts_and_plugins() -> None:
    valid_files = {
        "composer.json": json.dumps(
            {"require": {"php": ">=8.4"}, "config": {"allow-plugins": False}}
        ),
        "composer.lock": json.dumps({"content-hash": "abc", "packages": [], "packages-dev": []}),
        "public/index.php": "<?php echo 'ready';",
    }
    valid = validate_web_dependency_locks(
        snapshot(valid_files),
        selection=selection(ExecutionTarget.WEB_PHP),
    )
    invalid_files = {
        **valid_files,
        "composer.json": json.dumps(
            {
                "scripts": {"post-install-cmd": "unsafe"},
                "config": {"allow-plugins": {"vendor/plugin": True}},
            }
        ),
    }
    invalid = validate_web_dependency_locks(
        snapshot(invalid_files),
        selection=selection(ExecutionTarget.WEB_PHP),
    )

    assert valid.is_valid
    assert {issue.code for issue in invalid.roots[0].issues} == {
        WebLockfileIssueCode.COMPOSER_SCRIPTS_ENABLED,
        WebLockfileIssueCode.COMPOSER_PLUGINS_ENABLED,
    }
