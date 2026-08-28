"""Tests for the constrained Gradle JVM runner contract."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from orchestwin.jvm_execution.gradle_runner import create_gradle_jvm_runner_contract
from orchestwin.jvm_execution.plans import (
    JvmExecutionPhase,
    JvmExecutionPlanBundle,
    create_jvm_execution_plan_bundle,
)
from orchestwin.jvm_execution.targets import selection_for
from orchestwin.sandbox.container_runtime import (
    ContainerEnvironmentVariable,
    ContainerImageReference,
)
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionTarget,
)

_IMAGE = ContainerImageReference("orchestwin/jvm-gradle-runner@sha256:" + "a" * 64)
_RUN_ID = UUID("11111111-1111-4111-8111-111111111111")


def _plan(target: ExecutionTarget = ExecutionTarget.JVM_KOTLIN):
    return create_jvm_execution_plan_bundle(selection_for(target))


def test_gradle_runner_creates_policy_bound_requests_for_every_phase(
    tmp_path: Path,
) -> None:
    contract = create_gradle_jvm_runner_contract(_IMAGE)
    plan = _plan()
    environment = (
        ContainerEnvironmentVariable(
            key="GRADLE_USER_HOME",
            value="/tmp/gradle-home",
            is_secret=False,
        ),
        ContainerEnvironmentVariable(key="JAVA_HOME", value="/opt/java", is_secret=False),
    )

    requests = {
        phase: contract.create_request(
            run_id=_RUN_ID,
            execution_plan=plan,
            phase=phase,
            workspace_path=tmp_path,
            environment_variables=environment,
        )
        for phase in JvmExecutionPhase
    }

    assert requests[JvmExecutionPhase.SETUP].plan.commands[0].network_mode.value == "CONTROLLED"
    assert all(
        request.plan.commands[0].network_mode.value == "DISABLED"
        for phase, request in requests.items()
        if phase is not JvmExecutionPhase.SETUP
    )
    assert all(request.policy_report.is_accepted for request in requests.values())
    assert all(request.image == _IMAGE for request in requests.values())
    assert contract.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C


def test_gradle_runner_rejects_scala_and_tampered_commands(tmp_path: Path) -> None:
    contract = create_gradle_jvm_runner_contract(_IMAGE)

    with pytest.raises(ValueError, match="build-system family"):
        contract.create_request(
            run_id=_RUN_ID,
            execution_plan=_plan(ExecutionTarget.JVM_SCALA),
            phase=JvmExecutionPhase.BUILD,
            workspace_path=tmp_path,
        )

    plan = _plan(ExecutionTarget.JVM_JAVA)
    build = plan.phase(JvmExecutionPhase.BUILD)
    command = build.command_plan.commands[0]
    tampered_command = replace(command, arguments=("assemble", ";", "rm", "-rf"))
    tampered_phase = replace(
        build,
        command_plan=replace(build.command_plan, commands=(tampered_command,)),
    )
    tampered = JvmExecutionPlanBundle(
        target_selection=plan.target_selection,
        phases=tuple(
            tampered_phase if phase.phase is JvmExecutionPhase.BUILD else phase
            for phase in plan.phases
        ),
    )

    with pytest.raises(ValueError, match="canonical execution plan"):
        contract.create_request(
            run_id=_RUN_ID,
            execution_plan=tampered,
            phase=JvmExecutionPhase.BUILD,
            workspace_path=tmp_path,
        )


def test_gradle_runner_rejects_noncanonical_or_unapproved_environment(
    tmp_path: Path,
) -> None:
    contract = create_gradle_jvm_runner_contract(_IMAGE)
    plan = _plan(ExecutionTarget.JVM_JAVA)
    reversed_environment = (
        ContainerEnvironmentVariable(key="JAVA_HOME", value="/opt/java", is_secret=False),
        ContainerEnvironmentVariable(key="HOME", value="/tmp", is_secret=False),
    )

    with pytest.raises(ValueError, match="canonical key order"):
        contract.create_request(
            run_id=_RUN_ID,
            execution_plan=plan,
            phase=JvmExecutionPhase.TEST,
            workspace_path=tmp_path,
            environment_variables=reversed_environment,
        )

    with pytest.raises(ValueError, match="outside its contract"):
        contract.create_request(
            run_id=_RUN_ID,
            execution_plan=plan,
            phase=JvmExecutionPhase.TEST,
            workspace_path=tmp_path,
            environment_variables=(
                ContainerEnvironmentVariable(
                    key="SBT_OPTS",
                    value="-Dsbt.supershell=false",
                    is_secret=False,
                ),
            ),
        )


def test_gradle_runner_requires_its_digest_pinned_repository() -> None:
    with pytest.raises(ValueError, match="repository identity"):
        create_gradle_jvm_runner_contract(
            ContainerImageReference("example/other@sha256:" + "b" * 64)
        )
    with pytest.raises(ValueError, match="pinned by a lowercase SHA-256 digest"):
        ContainerImageReference("orchestwin/jvm-gradle-runner:latest")


def test_gradle_runner_snapshot_exposes_no_host_workspace() -> None:
    snapshot = create_gradle_jvm_runner_contract(_IMAGE).to_safe_snapshot()

    assert snapshot["runner_id"] == "jvm.gradle"
    assert snapshot["image_reference"] == _IMAGE.value
    assert snapshot["capability_status"] == "DESIGN_ONLY_LEVEL_C"
    assert "workspace" not in str(snapshot).casefold()
