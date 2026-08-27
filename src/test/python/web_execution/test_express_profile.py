"""Tests for the Node.js Express JavaScript/TypeScript execution profile."""

from __future__ import annotations

import hashlib
import json

import pytest

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
from orchestwin.web_execution.browser_evidence import WebBrowserRouteSpec
from orchestwin.web_execution.detection import (
    create_web_detection_snapshot,
    detect_web_project,
)
from orchestwin.web_execution.express_profile import WebNodeExpressExecutionProfile
from orchestwin.web_execution.lockfiles import validate_web_dependency_locks
from orchestwin.web_execution.profile_contracts import (
    WebProfileIssueCode,
    WebProfileRunnerSet,
    WebProfileValidationStatus,
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


def package_json(*, typescript: bool, include_start: bool = True) -> str:
    scripts = {"test": "vitest"}
    if include_start:
        scripts["start"] = "node dist/server.js" if typescript else "node server.js"
    if typescript:
        scripts["build"] = "tsc"
    dev_dependencies = {"vitest": "3.0.0"}
    if typescript:
        dev_dependencies["typescript"] = "5.8.0"
    return json.dumps(
        {
            "dependencies": {"express": "5.0.0"},
            "devDependencies": dev_dependencies,
            "scripts": scripts,
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


def test_express_javascript_and_typescript_variants_are_structurally_ready() -> None:
    javascript = profile_inputs(
        {
            "package-lock.json": package_lock(),
            "package.json": package_json(typescript=False),
            "server.js": "import express from 'express';",
        }
    )
    typescript = profile_inputs(
        {
            "package-lock.json": package_lock(),
            "package.json": package_json(typescript=True),
            "src/server.ts": "import express from 'express';",
            "tsconfig.json": "{}",
        }
    )
    profile = WebNodeExpressExecutionProfile()

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
        js_validation.selection.language_configuration.backend
        is WebImplementationLanguage.JAVASCRIPT
    )
    assert (
        ts_validation.selection.language_configuration.backend
        is WebImplementationLanguage.TYPESCRIPT
    )
    assert ts_validation.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C


def test_express_profile_creates_api_health_without_browser_evidence() -> None:
    source, selection, locks = profile_inputs(
        {
            "package-lock.json": package_lock(),
            "package.json": package_json(typescript=False),
            "server.js": "import express from 'express';",
        }
    )

    contract = WebNodeExpressExecutionProfile().create_contract(
        source,
        selection=selection,
        lock_report=locks,
        source_revision_content_hash="b" * 64,
        source_tree_hash="c" * 64,
        runners=WebProfileRunnerSet(
            execution_runner_image_digest="d" * 64,
            browser_runner_image_digest=None,
        ),
    )

    assert contract.execution_plan.profile_id == "web.node-express"
    assert contract.health_checks[0].path == "/health"
    assert contract.browser_evidence_request is None

    with pytest.raises(ValueError, match="does not accept browser routes"):
        WebNodeExpressExecutionProfile().create_contract(
            source,
            selection=selection,
            lock_report=locks,
            source_revision_content_hash="b" * 64,
            source_tree_hash="c" * 64,
            runners=WebProfileRunnerSet(
                execution_runner_image_digest="d" * 64,
                browser_runner_image_digest=None,
            ),
            declared_routes=(WebBrowserRouteSpec(route_id="root", path="/"),),
        )


def test_express_profile_reports_missing_start_script() -> None:
    source, selection, locks = profile_inputs(
        {
            "package-lock.json": package_lock(),
            "package.json": package_json(typescript=False, include_start=False),
            "server.js": "import express from 'express';",
        }
    )

    validation = WebNodeExpressExecutionProfile().validate(
        source,
        selection=selection,
        lock_report=locks,
    )

    assert validation.status is WebProfileValidationStatus.INVALID
    assert WebProfileIssueCode.REQUIRED_SCRIPT_MISSING in {
        issue.code for issue in validation.issues
    }
