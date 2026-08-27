"""Tests for composed Vue plus Express profile behavior and profile registry."""

from __future__ import annotations

import hashlib
import json

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
from orchestwin.web_execution.vue_node_profile import WebVueNodeExecutionProfile


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


def package_lock() -> str:
    return json.dumps({"lockfileVersion": 3, "packages": {"": {}}})


def frontend_manifest(*, typescript: bool) -> str:
    dev_dependencies = {"vitest": "3.0.0"}
    if typescript:
        dev_dependencies["typescript"] = "5.8.0"
    return json.dumps(
        {
            "dependencies": {"vite": "6.0.0", "vue": "3.5.0"},
            "devDependencies": dev_dependencies,
            "scripts": {
                "build": "vite build",
                "preview": "vite preview",
                "test": "vitest",
            },
        }
    )


def backend_manifest(*, typescript: bool) -> str:
    scripts = {
        "start": "node dist/server.js" if typescript else "node server.js",
        "test": "vitest",
    }
    dev_dependencies = {"vitest": "3.0.0"}
    if typescript:
        scripts["build"] = "tsc"
        dev_dependencies["typescript"] = "5.8.0"
    return json.dumps(
        {
            "dependencies": {"express": "5.0.0"},
            "devDependencies": dev_dependencies,
            "scripts": scripts,
        }
    )


def composed_files(*, typescript: bool) -> dict[str, str]:
    extension = "ts" if typescript else "js"
    vue_script = '<script setup lang="ts"></script>' if typescript else "<script setup></script>"
    files = {
        "backend/package-lock.json": package_lock(),
        "backend/package.json": backend_manifest(typescript=typescript),
        f"backend/src/server.{extension}": "import express from 'express';",
        "frontend/package-lock.json": package_lock(),
        "frontend/package.json": frontend_manifest(typescript=typescript),
        "frontend/src/App.vue": vue_script,
        f"frontend/src/main.{extension}": "import './App.vue';",
    }
    if typescript:
        files["backend/tsconfig.json"] = "{}"
        files["frontend/tsconfig.json"] = "{}"
    return files


def profile_inputs(*, typescript: bool):
    source = snapshot(composed_files(typescript=typescript))
    detection = detect_web_project(source)
    assert detection.selected is not None
    selection = detection.selected.selection
    locks = validate_web_dependency_locks(source, selection=selection)
    return source, selection, locks


def test_composed_profile_validates_matching_javascript_and_typescript_roots() -> None:
    javascript = profile_inputs(typescript=False)
    typescript = profile_inputs(typescript=True)
    profile = WebVueNodeExecutionProfile()

    js_validation = profile.validate(
        javascript[0],
        selection=javascript[1],
        lock_report=javascript[2],
    )
    ts_validation = profile.validate(
        typescript[0],
        selection=typescript[1],
        lock_report=typescript[2],
    )

    assert js_validation.is_ready
    assert ts_validation.is_ready
    assert (
        js_validation.selection.language_configuration.frontend
        is WebImplementationLanguage.JAVASCRIPT
    )
    assert (
        ts_validation.selection.language_configuration.backend
        is WebImplementationLanguage.TYPESCRIPT
    )


def test_composed_contract_keeps_frontend_and_backend_runtime_evidence_separate() -> None:
    source, selection, locks = profile_inputs(typescript=True)

    contract = WebVueNodeExecutionProfile().create_contract(
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

    assert tuple(check.check_id for check in contract.health_checks) == (
        "vue-node.backend",
        "vue-node.frontend",
    )
    assert contract.browser_evidence_request is not None
    run_phase = contract.execution_plan.phase(WebExecutionPhase.RUN)
    assert len(run_phase.command_plans) == 2
    assert {plan.commands[0].working_directory for plan in run_phase.command_plans} == {
        "backend",
        "frontend",
    }


def test_registry_contains_one_honest_profile_for_each_sprint08_target() -> None:
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
    assert registry.for_target(ExecutionTarget.WEB_VUE_NODE) is not None
    assert registry.find("web.vue-node", "1.0.0") is not None
    assert len(registry.content_hash) == 64
