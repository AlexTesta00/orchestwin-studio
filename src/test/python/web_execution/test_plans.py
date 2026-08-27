"""Tests for shell-free Web phase command planning."""

from __future__ import annotations

import hashlib
import json

import pytest

from orchestwin.sandbox.archive_policy import (
    SourceArchiveEntryDisposition,
    SourceArchiveEntryKind,
)
from orchestwin.sandbox.command_plans import CommandNetworkMode
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.sandbox.source_inventory import (
    SourceInventoryClassification,
    SourceInventoryEntry,
    SourceTreeInventory,
)
from orchestwin.web_execution.detection import create_web_detection_snapshot
from orchestwin.web_execution.lockfiles import validate_web_dependency_locks
from orchestwin.web_execution.plans import (
    WebExecutionPhase,
    WebPhaseExecutionKind,
    create_structured_web_phase_plans,
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
    inventory = SourceTreeInventory(
        archive_sha256="a" * 64,
        entries=entries,
    )
    return create_web_detection_snapshot(
        inventory,
        text_content_by_path=files,
    )


def selection(
    target: ExecutionTarget,
    *,
    language: WebImplementationLanguage,
) -> WebTargetSelection:
    if target is ExecutionTarget.WEB_VUE_NODE:
        configuration = WebLanguageConfiguration(
            frontend=language,
            backend=language,
        )
        layout = WebProjectLayout.FRONTEND_BACKEND
    elif target is ExecutionTarget.WEB_NODE_EXPRESS:
        configuration = WebLanguageConfiguration(
            frontend=None,
            backend=language,
        )
        layout = WebProjectLayout.SINGLE_ROOT
    elif target is ExecutionTarget.WEB_PHP:
        configuration = WebLanguageConfiguration(
            frontend=None,
            backend=WebImplementationLanguage.PHP,
        )
        layout = WebProjectLayout.SINGLE_ROOT
    else:
        configuration = WebLanguageConfiguration(
            frontend=language,
            backend=None,
        )
        layout = WebProjectLayout.SINGLE_ROOT

    return WebTargetSelection(
        target=target,
        language_configuration=configuration,
        layout=layout,
    )


def npm_files(root: str = ".") -> dict[str, str]:
    prefix = "" if root == "." else f"{root}/"
    return {
        f"{prefix}package.json": json.dumps({"name": "fixture"}),
        f"{prefix}package-lock.json": json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {"": {}},
            }
        ),
    }


def test_bundle_contains_every_phase_and_marks_static_no_ops_explicitly() -> None:
    source = snapshot({"index.html": "<!doctype html>"})
    chosen = selection(
        ExecutionTarget.WEB_STATIC,
        language=WebImplementationLanguage.STATIC_ASSETS,
    )
    locks = validate_web_dependency_locks(
        source,
        selection=chosen,
    )

    bundle = create_structured_web_phase_plans(
        source,
        selection=chosen,
        lock_report=locks,
    )

    assert tuple(phase.phase for phase in bundle.phases) == tuple(WebExecutionPhase)
    assert bundle.phase(WebExecutionPhase.SETUP).execution_kind is WebPhaseExecutionKind.NO_OP
    assert bundle.phase(WebExecutionPhase.BUILD).execution_kind is WebPhaseExecutionKind.NO_OP

    run_plan = bundle.phase(WebExecutionPhase.RUN).command_plans[0]

    assert run_plan.commands[0].executable == "node"
    assert "static-server.mjs" in run_plan.commands[0].arguments[0]


def test_vue_setup_is_the_only_controlled_network_phase() -> None:
    files = {
        **npm_files(),
        "src/main.ts": "export {}",
        "tsconfig.json": "{}",
    }
    source = snapshot(files)
    chosen = selection(
        ExecutionTarget.WEB_VUE,
        language=WebImplementationLanguage.TYPESCRIPT,
    )
    locks = validate_web_dependency_locks(
        source,
        selection=chosen,
    )

    bundle = create_structured_web_phase_plans(
        source,
        selection=chosen,
        lock_report=locks,
    )

    setup_commands = bundle.phase(WebExecutionPhase.SETUP).command_plans[0].commands

    later_commands = tuple(
        command
        for phase in bundle.phases[2:]
        for plan in phase.command_plans
        for command in plan.commands
    )

    assert {command.network_mode for command in setup_commands} == {CommandNetworkMode.CONTROLLED}
    assert all(command.network_mode is CommandNetworkMode.DISABLED for command in later_commands)
    assert any(
        command.executable == "npx"
        for command in bundle.phase(WebExecutionPhase.STATIC_CHECK).command_plans[0].commands
    )


def test_composed_runtime_uses_two_independent_structured_process_plans() -> None:
    files = {
        **npm_files("frontend"),
        **npm_files("backend"),
    }
    source = snapshot(files)
    chosen = selection(
        ExecutionTarget.WEB_VUE_NODE,
        language=WebImplementationLanguage.TYPESCRIPT,
    )
    locks = validate_web_dependency_locks(
        source,
        selection=chosen,
    )

    bundle = create_structured_web_phase_plans(
        source,
        selection=chosen,
        lock_report=locks,
    )
    run_phase = bundle.phase(WebExecutionPhase.RUN)

    assert run_phase.execution_kind is WebPhaseExecutionKind.COMMAND_PLANS
    assert len(run_phase.command_plans) == 2
    assert {plan.commands[0].working_directory for plan in run_phase.command_plans} == {
        "backend",
        "frontend",
    }


def test_php_setup_disables_composer_plugins_and_scripts() -> None:
    files = {
        "composer.json": json.dumps(
            {
                "config": {
                    "allow-plugins": False,
                }
            }
        ),
        "composer.lock": json.dumps(
            {
                "content-hash": "abc",
                "packages": [],
                "packages-dev": [],
            }
        ),
        "public/index.php": "<?php echo 'ready';",
    }
    source = snapshot(files)
    chosen = selection(
        ExecutionTarget.WEB_PHP,
        language=WebImplementationLanguage.PHP,
    )
    locks = validate_web_dependency_locks(
        source,
        selection=chosen,
    )

    bundle = create_structured_web_phase_plans(
        source,
        selection=chosen,
        lock_report=locks,
    )
    setup = bundle.phase(WebExecutionPhase.SETUP).command_plans[0].commands[0]

    assert setup.executable == "composer"
    assert "--no-scripts" in setup.arguments
    assert "--no-plugins" in setup.arguments


def test_invalid_lock_report_blocks_plan_creation() -> None:
    source = snapshot({"package.json": "{}"})
    chosen = selection(
        ExecutionTarget.WEB_VUE,
        language=WebImplementationLanguage.JAVASCRIPT,
    )
    locks = validate_web_dependency_locks(
        source,
        selection=chosen,
    )

    with pytest.raises(
        ValueError,
        match="valid dependency lock report",
    ):
        create_structured_web_phase_plans(
            source,
            selection=chosen,
            lock_report=locks,
        )
