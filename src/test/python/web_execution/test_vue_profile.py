"""Tests for the Vue 3 and Vite JavaScript/TypeScript execution profile."""

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
from orchestwin.web_execution.profile_contracts import (
    WebProfileIssueCode,
    WebProfileRunnerSet,
    WebProfileValidationStatus,
)
from orchestwin.web_execution.targets import WebImplementationLanguage
from orchestwin.web_execution.vue_profile import WebVueExecutionProfile


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


def package_json(*, typescript: bool, include_vue: bool = True) -> str:
    dependencies = {"vite": "6.0.0"}
    if include_vue:
        dependencies["vue"] = "3.5.0"
    dev_dependencies = {"vitest": "3.0.0"}
    if typescript:
        dev_dependencies["typescript"] = "5.8.0"
    return json.dumps(
        {
            "dependencies": dependencies,
            "devDependencies": dev_dependencies,
            "scripts": {
                "build": "vite build",
                "preview": "vite preview",
                "test": "vitest",
            },
        }
    )


def package_lock() -> str:
    return json.dumps({"lockfileVersion": 3, "packages": {"": {}}})


def profile_inputs(files: dict[str, str]):
    source = snapshot(files)
    detection = detect_web_project(source)
    assert detection.selected is not None
    selection = detection.selected.selection
    locks = validate_web_dependency_locks(source, selection=selection)
    return source, selection, locks


def test_vue_javascript_and_typescript_variants_are_first_class() -> None:
    javascript = profile_inputs(
        {
            "package-lock.json": package_lock(),
            "package.json": package_json(typescript=False),
            "src/App.vue": "<template><main>Ready</main></template>",
            "src/main.js": "import './App.vue';",
        }
    )
    typescript = profile_inputs(
        {
            "package-lock.json": package_lock(),
            "package.json": package_json(typescript=True),
            "src/App.vue": '<script setup lang="ts"></script>',
            "src/main.ts": "import './App.vue';",
            "tsconfig.json": "{}",
        }
    )
    profile = WebVueExecutionProfile()

    javascript_validation = profile.validate(
        javascript[0],
        selection=javascript[1],
        lock_report=javascript[2],
    )
    typescript_validation = profile.validate(
        typescript[0],
        selection=typescript[1],
        lock_report=typescript[2],
    )

    assert javascript_validation.is_ready
    assert typescript_validation.is_ready
    assert (
        javascript_validation.selection.language_configuration.frontend
        is WebImplementationLanguage.JAVASCRIPT
    )
    assert (
        typescript_validation.selection.language_configuration.frontend
        is WebImplementationLanguage.TYPESCRIPT
    )
    assert typescript_validation.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C


def test_vue_profile_contract_requires_browser_and_preview_health_evidence() -> None:
    source, selection, locks = profile_inputs(
        {
            "package-lock.json": package_lock(),
            "package.json": package_json(typescript=True),
            "src/App.vue": '<script setup lang="ts"></script>',
            "src/main.ts": "import './App.vue';",
            "tsconfig.json": "{}",
        }
    )

    contract = WebVueExecutionProfile().create_contract(
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

    assert contract.execution_plan.profile_id == "web.vue"
    assert contract.health_checks[0].port == 4173
    assert contract.browser_evidence_request is not None


def test_vue_profile_reports_missing_dependencies_and_command_scripts() -> None:
    source = snapshot(
        {
            "package-lock.json": package_lock(),
            "package.json": json.dumps(
                {
                    "dependencies": {"vite": "6.0.0"},
                    "scripts": {"build": "vite build"},
                }
            ),
            "src/App.vue": "<template><main>Ready</main></template>",
            "src/main.js": "import './App.vue';",
        }
    )
    profile = WebVueExecutionProfile()
    selection = profile.scope.language_configurations[0]
    from orchestwin.web_execution.targets import WebTargetSelection

    target_selection = WebTargetSelection(
        target=profile.scope.target,
        language_configuration=selection,
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
        WebProfileIssueCode.REQUIRED_DEPENDENCY_MISSING,
        WebProfileIssueCode.REQUIRED_SCRIPT_MISSING,
    }
