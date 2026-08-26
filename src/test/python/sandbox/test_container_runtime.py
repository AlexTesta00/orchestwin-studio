"""Tests for digest-pinned container execution requests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from orchestwin.sandbox.command_plans import (
    CommandNetworkMode,
    CommandPlan,
    SecretReference,
    StructuredCommand,
)
from orchestwin.sandbox.container_runtime import (
    ContainerEnvironmentVariable,
    ContainerExecutionRequest,
    ContainerImageReference,
)
from orchestwin.sandbox.execution_policy import (
    DEFAULT_SANDBOX_EXECUTION_POLICY,
    validate_sandbox_plan,
)

RUN_ID = UUID("00000000-0000-4000-8000-000000007101")
IMAGE = ContainerImageReference("example/web@sha256:" + "d" * 64)


def _command(**overrides: object) -> StructuredCommand:
    values: dict[str, object] = {
        "command_id": "quality.tests",
        "executable": "python",
        "arguments": ("-m", "pytest"),
        "working_directory": ".",
        "allowed_environment_keys": frozenset({"CI"}),
        "secret_references": frozenset(),
        "timeout_seconds": 120,
        "network_mode": CommandNetworkMode.DISABLED,
        "expected_exit_codes": frozenset({0}),
        "output_parser_id": "pytest.v1",
        "artifact_patterns": frozenset({"reports/*.xml"}),
    }
    values.update(overrides)
    return StructuredCommand(**values)  # type: ignore[arg-type]


def _plan(command: StructuredCommand | None = None) -> CommandPlan:
    return CommandPlan(
        plan_id="quality.plan",
        profile_id="web.vue",
        profile_version="1",
        commands=(command or _command(),),
    )


def _request(
    workspace: Path,
    *,
    plan: CommandPlan | None = None,
    environment: tuple[ContainerEnvironmentVariable, ...] = (),
) -> ContainerExecutionRequest:
    resolved_plan = plan or _plan()
    return ContainerExecutionRequest(
        run_id=RUN_ID,
        plan=resolved_plan,
        execution_policy=DEFAULT_SANDBOX_EXECUTION_POLICY,
        policy_report=validate_sandbox_plan(resolved_plan),
        image=IMAGE,
        workspace_path=workspace,
        environment_variables=environment,
    )


def test_container_image_must_be_pinned_by_digest() -> None:
    """Reject mutable tags before a runtime adapter can pull or run them."""
    assert IMAGE.digest == "d" * 64

    for reference in ("example/web:latest", "example/web:1.0", "example/web@sha256:ABC"):
        with pytest.raises(ValueError, match="pinned"):
            ContainerImageReference(reference)


def test_request_is_bound_to_an_accepted_exact_policy_report(tmp_path: Path) -> None:
    """Prevent adapters from receiving rejected or stale command plans."""
    plan = _plan()
    accepted = validate_sandbox_plan(plan)
    request = ContainerExecutionRequest(
        run_id=RUN_ID,
        plan=plan,
        execution_policy=DEFAULT_SANDBOX_EXECUTION_POLICY,
        policy_report=accepted,
        image=IMAGE,
        workspace_path=tmp_path,
        environment_variables=(),
    )

    assert request.resources == accepted.resources

    changed_plan = _plan(_command(arguments=("-m", "pytest", "-q")))
    with pytest.raises(ValueError, match="targets another"):
        ContainerExecutionRequest(
            run_id=RUN_ID,
            plan=changed_plan,
            execution_policy=DEFAULT_SANDBOX_EXECUTION_POLICY,
            policy_report=accepted,
            image=IMAGE,
            workspace_path=tmp_path,
            environment_variables=(),
        )

    rejected_plan = _plan(_command(executable="curl"))
    with pytest.raises(ValueError, match="accepted"):
        ContainerExecutionRequest(
            run_id=RUN_ID,
            plan=rejected_plan,
            execution_policy=DEFAULT_SANDBOX_EXECUTION_POLICY,
            policy_report=validate_sandbox_plan(rejected_plan),
            image=IMAGE,
            workspace_path=tmp_path,
            environment_variables=(),
        )

    forged_report = replace(
        accepted,
        resources=replace(accepted.resources, memory_mib=8192),
    )
    with pytest.raises(ValueError, match="deterministic validation"):
        ContainerExecutionRequest(
            run_id=RUN_ID,
            plan=plan,
            execution_policy=DEFAULT_SANDBOX_EXECUTION_POLICY,
            policy_report=forged_report,
            image=IMAGE,
            workspace_path=tmp_path,
            environment_variables=(),
        )


def test_request_requires_one_absolute_regular_workspace(tmp_path: Path) -> None:
    """Keep the adapter mount boundary explicit and non-symlinked."""
    _request(tmp_path)

    with pytest.raises(ValueError, match="absolute"):
        _request(Path("relative/workspace"))

    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="regular non-symlink"):
        _request(missing)


def test_environment_values_are_filtered_and_never_exposed_in_snapshots(
    tmp_path: Path,
) -> None:
    """Pass only declared keys while redacting values from audit metadata."""
    variable = ContainerEnvironmentVariable(
        key="CI",
        value="true",
        is_secret=False,
    )
    request = _request(tmp_path, environment=(variable,))

    assert request.environment_for(request.plan.commands[0]) == (variable,)
    snapshot = request.to_safe_snapshot()
    assert snapshot["environment"] == [{"key": "CI", "is_secret": False, "value_state": "PRESENT"}]
    assert "true" not in str(snapshot)
    assert "workspace_path" not in snapshot


def test_secret_markers_must_match_approved_plan_references(tmp_path: Path) -> None:
    """Prevent accidental logging or misclassification of resolved secret values."""
    reference = SecretReference(
        reference_id="npm.registry.token",
        environment_key="NPM_TOKEN",
    )
    command = _command(
        allowed_environment_keys=frozenset({"CI", "NPM_TOKEN"}),
        secret_references=frozenset({reference}),
    )
    plan = _plan(command)
    policy = replace(
        DEFAULT_SANDBOX_EXECUTION_POLICY,
        allowed_environment_keys=(
            DEFAULT_SANDBOX_EXECUTION_POLICY.allowed_environment_keys | frozenset({"NPM_TOKEN"})
        ),
        allowed_secret_reference_ids=frozenset({"npm.registry.token"}),
    )
    report = validate_sandbox_plan(plan, policy=policy)
    secret = ContainerEnvironmentVariable(
        key="NPM_TOKEN",
        value="not-visible",
        is_secret=True,
    )

    request = ContainerExecutionRequest(
        run_id=RUN_ID,
        plan=plan,
        execution_policy=policy,
        policy_report=report,
        image=IMAGE,
        workspace_path=tmp_path,
        environment_variables=(secret,),
    )
    assert "not-visible" not in str(request.to_safe_snapshot())

    with pytest.raises(ValueError, match="secret markers"):
        ContainerExecutionRequest(
            run_id=RUN_ID,
            plan=plan,
            execution_policy=policy,
            policy_report=report,
            image=IMAGE,
            workspace_path=tmp_path,
            environment_variables=(replace(secret, is_secret=False),),
        )
