"""Tests for the structurally executable but not-yet-promoted WEB_STATIC profile."""

from __future__ import annotations

import hashlib

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
from orchestwin.web_execution.profile_contracts import (
    WebProfileIssueCode,
    WebProfileRunnerSet,
    WebProfileValidationStatus,
)
from orchestwin.web_execution.static_profile import WebStaticExecutionProfile


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


def static_inputs(files: dict[str, str]):
    source = snapshot(files)
    detection = detect_web_project(source)
    assert detection.selected is not None
    selection = detection.selected.selection
    locks = validate_web_dependency_locks(source, selection=selection)
    return source, selection, locks


def test_static_profile_is_structurally_ready_but_remains_design_only() -> None:
    source, selection, locks = static_inputs(
        {
            "assets/site.css": "body { font-family: sans-serif; }",
            "index.html": "<!doctype html><title>Ready</title>",
            "site.js": "document.body.dataset.ready = 'true';",
        }
    )
    profile = WebStaticExecutionProfile()

    validation = profile.validate(source, selection=selection, lock_report=locks)

    assert validation.status is WebProfileValidationStatus.READY_FOR_VALIDATION
    assert validation.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
    assert validation.selection.target is ExecutionTarget.WEB_STATIC


def test_static_profile_creates_health_browser_and_phase_contracts() -> None:
    source, selection, locks = static_inputs({"index.html": "<!doctype html><title>Ready</title>"})
    profile = WebStaticExecutionProfile()

    contract = profile.create_contract(
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

    assert contract.execution_plan.profile_id == "web.static"
    assert contract.health_checks[0].port == 4173
    assert contract.browser_evidence_request is not None
    assert contract.browser_evidence_request.routes[0].path == "/"
    assert len(contract.content_hash) == 64


def test_static_profile_rejects_framework_and_compiled_language_indicators() -> None:
    source = snapshot(
        {
            "index.html": "<!doctype html>",
            "src/main.ts": "export {};",
        }
    )
    profile = WebStaticExecutionProfile()
    selection = profile.scope.language_configurations[0]
    from orchestwin.web_execution.targets import WebTargetSelection

    target_selection = WebTargetSelection(
        target=ExecutionTarget.WEB_STATIC,
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
        WebProfileIssueCode.UNSUPPORTED_PROJECT,
    }
