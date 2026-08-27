"""Tests for deterministic multi-stack Web project detection."""

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
from orchestwin.web_execution.detection import (
    WebDetectionStatus,
    create_web_detection_snapshot,
    detect_web_project,
)
from orchestwin.web_execution.targets import WebImplementationLanguage


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


def package(*dependencies: str, dev_dependencies: tuple[str, ...] = ()) -> str:
    return json.dumps(
        {
            "dependencies": {name: "1.0.0" for name in dependencies},
            "devDependencies": {name: "1.0.0" for name in dev_dependencies},
        }
    )


def test_detects_static_project_without_framework_guessing() -> None:
    result = detect_web_project(
        snapshot(
            {
                "assets/site.css": "body {}",
                "index.html": "<!doctype html>",
                "site.js": "console.log('ready')",
            }
        )
    )

    assert result.status is WebDetectionStatus.SELECTED
    assert result.selected is not None
    assert result.selected.selection.target is ExecutionTarget.WEB_STATIC


def test_detects_vue_typescript_from_manifest_and_structure() -> None:
    result = detect_web_project(
        snapshot(
            {
                "package.json": package("vue", dev_dependencies=("typescript", "vite")),
                "package-lock.json": "{}",
                "src/App.vue": '<script setup lang="ts"></script>',
                "src/main.ts": "export {}",
                "tsconfig.json": "{}",
                "vite.config.ts": "export default {}",
            }
        )
    )

    assert result.status is WebDetectionStatus.SELECTED
    assert result.selected is not None
    assert result.selected.selection.target is ExecutionTarget.WEB_VUE
    assert (
        result.selected.selection.language_configuration.frontend
        is WebImplementationLanguage.TYPESCRIPT
    )


def test_detects_express_javascript_without_browser_assumption() -> None:
    result = detect_web_project(
        snapshot(
            {
                "package.json": package("express"),
                "package-lock.json": "{}",
                "src/server.js": "export const app = {};",
            }
        )
    )

    assert result.status is WebDetectionStatus.SELECTED
    assert result.selected is not None
    assert result.selected.selection.target is ExecutionTarget.WEB_NODE_EXPRESS
    assert (
        result.selected.selection.language_configuration.backend
        is WebImplementationLanguage.JAVASCRIPT
    )


def test_detects_composed_typescript_only_for_matching_pair() -> None:
    result = detect_web_project(
        snapshot(
            {
                "backend/package.json": package("express", dev_dependencies=("typescript",)),
                "backend/package-lock.json": "{}",
                "backend/src/server.ts": "export {}",
                "backend/tsconfig.json": "{}",
                "frontend/package.json": package("vue", dev_dependencies=("typescript", "vite")),
                "frontend/package-lock.json": "{}",
                "frontend/src/App.vue": '<script setup lang="ts"></script>',
                "frontend/src/main.ts": "export {}",
                "frontend/tsconfig.json": "{}",
            }
        )
    )

    assert result.status is WebDetectionStatus.SELECTED
    assert result.selected is not None
    assert result.selected.selection.target is ExecutionTarget.WEB_VUE_NODE


def test_mixed_composed_language_pair_does_not_receive_a_candidate() -> None:
    result = detect_web_project(
        snapshot(
            {
                "backend/package.json": package("express"),
                "backend/package-lock.json": "{}",
                "backend/src/server.js": "export {}",
                "frontend/package.json": package("vue", dev_dependencies=("typescript", "vite")),
                "frontend/package-lock.json": "{}",
                "frontend/src/main.ts": "export {}",
                "frontend/tsconfig.json": "{}",
            }
        )
    )

    assert result.status is WebDetectionStatus.UNSUPPORTED
    assert result.candidates == ()


def test_detects_framework_free_php_public_root() -> None:
    result = detect_web_project(
        snapshot(
            {
                "composer.json": json.dumps({"require": {"php": ">=8.4"}}),
                "composer.lock": "{}",
                "public/index.php": "<?php echo 'ready';",
            }
        )
    )

    assert result.status is WebDetectionStatus.SELECTED
    assert result.selected is not None
    assert result.selected.selection.target is ExecutionTarget.WEB_PHP


def test_conflicting_framework_and_package_manager_require_human_decision() -> None:
    result = detect_web_project(
        snapshot(
            {
                "package.json": package("react", "vue", dev_dependencies=("vite",)),
                "src/App.vue": "<template />",
                "yarn.lock": "lockfile",
            }
        )
    )

    assert result.status is WebDetectionStatus.HUMAN_DECISION_REQUIRED
    assert result.selected is None
    assert result.conflicting_indicators == (
        "package.json declares unsupported framework react",
        "unsupported package-manager lockfile yarn.lock",
    )
