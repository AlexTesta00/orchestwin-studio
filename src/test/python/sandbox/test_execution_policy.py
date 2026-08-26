"""Tests for deterministic sandbox command and resource policies."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from orchestwin.sandbox.command_plans import (
    CommandNetworkMode,
    CommandPlan,
    SecretReference,
    StructuredCommand,
)
from orchestwin.sandbox.execution_policy import (
    DEFAULT_SANDBOX_EXECUTION_POLICY,
    DEFAULT_SANDBOX_RESOURCE_LIMITS,
    SandboxPolicyIssueCode,
    SandboxPolicyValidationStatus,
    SandboxResourceLimits,
    validate_sandbox_plan,
)


def _command(**overrides: object) -> StructuredCommand:
    values: dict[str, object] = {
        "command_id": "quality.tests",
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


def _plan(*commands: StructuredCommand) -> CommandPlan:
    return CommandPlan(
        plan_id="quality.plan",
        profile_id="web.vue",
        profile_version="1",
        commands=commands or (_command(),),
    )


def _codes(report: object) -> set[SandboxPolicyIssueCode]:
    return {issue.code for issue in report.issues}  # type: ignore[attr-defined]


def test_default_plan_and_resource_limits_are_accepted() -> None:
    """Allow one bounded shell-free command under the least-privilege defaults."""
    plan = _plan()

    report = validate_sandbox_plan(plan)

    assert report.status is SandboxPolicyValidationStatus.ACCEPTED
    assert report.is_accepted
    assert report.policy_content_hash == DEFAULT_SANDBOX_EXECUTION_POLICY.content_hash
    assert report.plan_content_hash == plan.content_hash
    assert report.resources == DEFAULT_SANDBOX_RESOURCE_LIMITS
    assert report.issues == ()


def test_policy_rejects_arbitrary_executables_and_shell_command_bridges() -> None:
    """Prevent a plan from turning into a generic host or container shell."""
    arbitrary = validate_sandbox_plan(_plan(_command(executable="curl")))

    shell_policy = replace(
        DEFAULT_SANDBOX_EXECUTION_POLICY,
        allowed_executables=(
            DEFAULT_SANDBOX_EXECUTION_POLICY.allowed_executables | frozenset({"bash"})
        ),
    )
    shell_bridge = validate_sandbox_plan(
        _plan(
            _command(
                executable="bash",
                arguments=("-c", "python -m pytest && rm -rf /workspace"),
            )
        ),
        policy=shell_policy,
    )

    assert SandboxPolicyIssueCode.EXECUTABLE_NOT_ALLOWED in _codes(arbitrary)
    assert SandboxPolicyIssueCode.SHELL_BRIDGE_FORBIDDEN in _codes(shell_bridge)


def test_policy_rejects_inline_language_evaluators() -> None:
    """Prevent allowlisted interpreters from becoming arbitrary code-string bridges."""
    python_inline = validate_sandbox_plan(
        _plan(_command(executable="python", arguments=("-c", "print('unsafe')")))
    )
    node_inline = validate_sandbox_plan(
        _plan(_command(executable="node", arguments=("--eval", "process.exit(0)")))
    )

    assert SandboxPolicyIssueCode.INLINE_CODE_FORBIDDEN in _codes(python_inline)
    assert SandboxPolicyIssueCode.INLINE_CODE_FORBIDDEN in _codes(node_inline)


def test_policy_rejects_unapproved_environment_secrets_and_network() -> None:
    """Require explicit policy authorization for each side-effecting capability."""
    secret = SecretReference(
        reference_id="npm.registry.token",
        environment_key="NPM_TOKEN",
    )
    command = _command(
        allowed_environment_keys=frozenset({"CI", "CUSTOM_VALUE", "NPM_TOKEN"}),
        secret_references=frozenset({secret}),
        network_mode=CommandNetworkMode.CONTROLLED,
    )

    report = validate_sandbox_plan(_plan(command))

    assert {
        SandboxPolicyIssueCode.ENVIRONMENT_KEY_NOT_ALLOWED,
        SandboxPolicyIssueCode.SECRET_REFERENCE_NOT_ALLOWED,
        SandboxPolicyIssueCode.NETWORK_MODE_NOT_ALLOWED,
    } <= _codes(report)


def test_policy_rejects_command_and_plan_timeout_overruns() -> None:
    """Bound individual invocations and the sequential plan duration."""
    first = _command(command_id="build.first", timeout_seconds=601)
    second = _command(command_id="build.second", timeout_seconds=3000)
    policy = replace(
        DEFAULT_SANDBOX_EXECUTION_POLICY,
        maximum_command_timeout_seconds=3000,
        maximum_plan_timeout_seconds=3600,
    )

    report = validate_sandbox_plan(_plan(first, second), policy=policy)

    assert SandboxPolicyIssueCode.PLAN_TIMEOUT_EXCEEDED in _codes(report)
    assert report.issues[0].command_id is None

    strict_command_report = validate_sandbox_plan(_plan(first))
    assert SandboxPolicyIssueCode.COMMAND_TIMEOUT_EXCEEDED in _codes(strict_command_report)


def test_policy_rejects_protected_working_directories_and_artifact_globs() -> None:
    """Keep commands and artifact collection away from control and host paths."""
    protected_directory = validate_sandbox_plan(_plan(_command(working_directory=".git/hooks")))
    unsafe_artifacts = validate_sandbox_plan(
        _plan(_command(artifact_patterns=frozenset({"../outside/**"})))
    )
    protected_artifacts = validate_sandbox_plan(
        _plan(_command(artifact_patterns=frozenset({".ssh/**"})))
    )

    assert SandboxPolicyIssueCode.WORKING_DIRECTORY_FORBIDDEN in _codes(protected_directory)
    assert SandboxPolicyIssueCode.ARTIFACT_PATTERN_FORBIDDEN in _codes(unsafe_artifacts)
    assert SandboxPolicyIssueCode.ARTIFACT_PATTERN_FORBIDDEN in _codes(protected_artifacts)


def test_policy_rejects_resource_requests_above_the_approved_maxima() -> None:
    """Prevent callers from silently increasing CPU, memory, process, or tmpfs limits."""
    resources = SandboxResourceLimits(
        cpu_count=4.0,
        memory_mib=8192,
        pids_limit=512,
        writable_tmpfs_mib=1024,
    )

    report = validate_sandbox_plan(_plan(), resources=resources)

    assert report.status is SandboxPolicyValidationStatus.REJECTED
    assert SandboxPolicyIssueCode.RESOURCE_LIMIT_EXCEEDED in _codes(report)
    assert report.to_snapshot()["resources"] == resources.to_snapshot()


def test_policy_rejects_excessive_command_or_artifact_counts() -> None:
    """Bound plan breadth and collection work independently of byte limits."""
    commands = tuple(
        _command(command_id=f"quality.step-{index}")
        for index in range(DEFAULT_SANDBOX_EXECUTION_POLICY.maximum_commands + 1)
    )
    command_report = validate_sandbox_plan(_plan(*commands))

    artifact_patterns = frozenset(
        f"reports/{index}.xml"
        for index in range(
            DEFAULT_SANDBOX_EXECUTION_POLICY.maximum_artifact_patterns_per_command + 1
        )
    )
    artifact_report = validate_sandbox_plan(_plan(_command(artifact_patterns=artifact_patterns)))

    assert SandboxPolicyIssueCode.TOO_MANY_COMMANDS in _codes(command_report)
    assert SandboxPolicyIssueCode.TOO_MANY_ARTIFACT_PATTERNS in _codes(artifact_report)


def test_policy_and_resources_are_immutable_and_validate_configuration() -> None:
    """Prevent runtime weakening and reject incoherent policy definitions."""
    with pytest.raises(FrozenInstanceError):
        DEFAULT_SANDBOX_RESOURCE_LIMITS.memory_mib = 8192  # type: ignore[misc]

    with pytest.raises(ValueError, match="must not exceed"):
        replace(
            DEFAULT_SANDBOX_EXECUTION_POLICY,
            maximum_command_timeout_seconds=3601,
        )

    with pytest.raises(ValueError, match="positive"):
        SandboxResourceLimits(
            cpu_count=0,
            memory_mib=4096,
            pids_limit=256,
            writable_tmpfs_mib=512,
        )
