"""Tests for immutable shell-free command plan values."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from orchestwin.sandbox.command_plans import (
    CommandNetworkMode,
    CommandPlan,
    SecretReference,
    StructuredCommand,
)


def _command(**overrides: object) -> StructuredCommand:
    values: dict[str, object] = {
        "command_id": "tests.unit",
        "executable": "python",
        "arguments": ("-m", "pytest", "-q"),
        "working_directory": ".",
        "allowed_environment_keys": frozenset({"CI", "PYTHONUNBUFFERED"}),
        "secret_references": frozenset(),
        "timeout_seconds": 120,
        "network_mode": CommandNetworkMode.DISABLED,
        "expected_exit_codes": frozenset({0}),
        "output_parser_id": "pytest.v1",
        "artifact_patterns": frozenset({"reports/**/*.xml"}),
    }
    values.update(overrides)
    return StructuredCommand(**values)  # type: ignore[arg-type]


def _plan(command: StructuredCommand | None = None) -> CommandPlan:
    return CommandPlan(
        plan_id="web.tests",
        profile_id="web.vue",
        profile_version="1.0.0",
        commands=(command or _command(),),
    )


def test_structured_command_preserves_an_argument_vector_without_a_shell_string() -> None:
    """Keep executable and arguments separate at the public command boundary."""
    command = _command(
        executable="npm",
        arguments=("run", "test", "--", "--runInBand"),
    )

    snapshot = command.to_snapshot()

    assert snapshot["executable"] == "npm"
    assert snapshot["arguments"] == ["run", "test", "--", "--runInBand"]
    assert "shell" not in snapshot
    assert "command" not in snapshot


def test_plan_hash_is_canonical_for_unordered_metadata() -> None:
    """Make equivalent environment, exit-code, and artifact sets hash identically."""
    first = _plan(
        _command(
            allowed_environment_keys=frozenset({"CI", "LANG"}),
            expected_exit_codes=frozenset({0, 2}),
            artifact_patterns=frozenset({"coverage/**", "reports/*.xml"}),
        )
    )
    second = _plan(
        _command(
            allowed_environment_keys=frozenset({"LANG", "CI"}),
            expected_exit_codes=frozenset({2, 0}),
            artifact_patterns=frozenset({"reports/*.xml", "coverage/**"}),
        )
    )

    assert first.content_hash == second.content_hash
    assert first.to_snapshot()["content_hash"] == first.content_hash
    assert len(first.content_hash) == 64


def test_plan_hash_changes_when_process_arguments_change() -> None:
    """Bind approvals and evidence to the exact tokenized invocation."""
    original = _plan(_command(arguments=("-m", "pytest")))
    changed = _plan(_command(arguments=("-m", "pytest", "-q")))

    assert original.content_hash != changed.content_hash


def test_command_values_and_plans_are_immutable() -> None:
    """Prevent policy-reviewed commands from changing in place."""
    command = _command()
    plan = _plan(command)

    with pytest.raises(FrozenInstanceError):
        command.timeout_seconds = 1  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        plan.commands = ()  # type: ignore[misc]


def test_command_rejects_paths_that_can_leave_the_workspace() -> None:
    """Reject absolute, parent-traversing, and host-specific working directories."""
    for working_directory in ("../outside", "/etc", "C:/temp", "src\\tests"):
        with pytest.raises(ValueError, match="working directory"):
            _command(working_directory=working_directory)


def test_command_rejects_control_separators_and_invalid_environment_keys() -> None:
    """Keep values safe for direct process invocation and environment construction."""
    with pytest.raises(ValueError, match="control separators"):
        _command(arguments=("test", "value\nnext-command"))

    with pytest.raises(ValueError, match="portable identifiers"):
        _command(allowed_environment_keys=frozenset({"INVALID-KEY"}))


def test_secret_references_declare_only_external_ids_and_allowed_destinations() -> None:
    """Reference secrets without embedding values or undeclared environment keys."""
    reference = SecretReference(
        reference_id="npm.registry.token",
        environment_key="NPM_TOKEN",
    )
    command = _command(
        allowed_environment_keys=frozenset({"CI", "NPM_TOKEN"}),
        secret_references=frozenset({reference}),
    )

    assert command.to_snapshot()["secret_references"] == [
        {
            "reference_id": "npm.registry.token",
            "environment_key": "NPM_TOKEN",
        }
    ]

    with pytest.raises(ValueError, match="must be declared"):
        replace(
            command,
            allowed_environment_keys=frozenset({"CI"}),
        )


def test_plan_rejects_duplicate_command_ids_and_invalid_exit_codes() -> None:
    """Keep command evidence addressable and process outcomes portable."""
    command = _command()

    with pytest.raises(ValueError, match="command IDs must be unique"):
        CommandPlan(
            plan_id="duplicate.plan",
            profile_id="web.vue",
            profile_version="1",
            commands=(command, command),
        )

    with pytest.raises(ValueError, match="zero to 255"):
        _command(expected_exit_codes=frozenset({256}))


def test_plan_reports_the_sequential_timeout_budget() -> None:
    """Expose the worst-case duration used by the later policy boundary."""
    plan = CommandPlan(
        plan_id="web.quality",
        profile_id="web.vue",
        profile_version="1",
        commands=(
            _command(command_id="quality.lint", timeout_seconds=30),
            _command(command_id="quality.test", timeout_seconds=90),
        ),
    )

    assert plan.total_timeout_seconds == 120
    assert plan.command_by_id("quality.test") is plan.commands[1]
    assert plan.command_by_id("missing") is None


def test_profile_identifiers_support_the_approved_uppercase_catalog_style() -> None:
    """Allow stable profile IDs such as WEB_VUE without weakening plan hashing."""
    plan = CommandPlan(
        plan_id="web.tests",
        profile_id="WEB_VUE",
        profile_version="1.0.0",
        commands=(_command(),),
    )

    assert plan.profile_id == "WEB_VUE"
    assert plan.to_snapshot()["profile_id"] == "WEB_VUE"
