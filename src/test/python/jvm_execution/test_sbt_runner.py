"""Tests for the constrained sbt JVM runner contract."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from orchestwin.jvm_execution.plans import (
    JvmExecutionPhase,
    JvmExecutionPlanBundle,
    create_jvm_execution_plan_bundle,
)
from orchestwin.jvm_execution.sbt_runner import create_sbt_jvm_runner_contract
from orchestwin.jvm_execution.targets import selection_for
from orchestwin.sandbox.container_runtime import (
    ContainerEnvironmentVariable,
    ContainerImageReference,
)
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionTarget,
)

_IMAGE = ContainerImageReference("orchestwin/jvm-sbt-runner@sha256:" + "b" * 64)
_RUN_ID = UUID("22222222-2222-4222-8222-222222222222")


def _plan(target: ExecutionTarget = ExecutionTarget.JVM_SCALA):
    return create_jvm_execution_plan_bundle(selection_for(target))


def test_sbt_runner_creates_controlled_setup_and_offline_requests(
    tmp_path: Path,
) -> None:
    contract = create_sbt_jvm_runner_contract(_IMAGE)
    plan = _plan()
    environment = (
        ContainerEnvironmentVariable(key="JAVA_HOME", value="/opt/java", is_secret=False),
        ContainerEnvironmentVariable(
            key="SBT_OPTS",
            value="-Dsbt.supershell=false",
            is_secret=False,
        ),
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
    assert all(request.plan.commands[0].executable == "sbt" for request in requests.values())
    assert all(request.policy_report.is_accepted for request in requests.values())
    assert contract.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C


def test_sbt_runner_rejects_gradle_targets_and_tampered_tasks(tmp_path: Path) -> None:
    contract = create_sbt_jvm_runner_contract(_IMAGE)

    for target in (ExecutionTarget.JVM_JAVA, ExecutionTarget.JVM_KOTLIN):
        with pytest.raises(ValueError, match="build-system family"):
            contract.create_request(
                run_id=_RUN_ID,
                execution_plan=_plan(target),
                phase=JvmExecutionPhase.BUILD,
                workspace_path=tmp_path,
            )

    plan = _plan()
    tests = plan.phase(JvmExecutionPhase.TEST)
    command = tests.command_plan.commands[0]
    tampered_command = replace(command, arguments=("-batch", "-no-colors", "test;clean"))
    tampered_phase = replace(
        tests,
        command_plan=replace(tests.command_plan, commands=(tampered_command,)),
    )
    tampered = JvmExecutionPlanBundle(
        target_selection=plan.target_selection,
        phases=tuple(
            tampered_phase if phase.phase is JvmExecutionPhase.TEST else phase
            for phase in plan.phases
        ),
    )

    with pytest.raises(ValueError, match="canonical execution plan"):
        contract.create_request(
            run_id=_RUN_ID,
            execution_plan=tampered,
            phase=JvmExecutionPhase.TEST,
            workspace_path=tmp_path,
        )


def test_sbt_runner_rejects_gradle_environment_keys(tmp_path: Path) -> None:
    contract = create_sbt_jvm_runner_contract(_IMAGE)

    with pytest.raises(ValueError, match="outside its contract"):
        contract.create_request(
            run_id=_RUN_ID,
            execution_plan=_plan(),
            phase=JvmExecutionPhase.TEST,
            workspace_path=tmp_path,
            environment_variables=(
                ContainerEnvironmentVariable(
                    key="GRADLE_USER_HOME",
                    value="/tmp/gradle-home",
                    is_secret=False,
                ),
            ),
        )


def test_sbt_runner_requires_its_digest_pinned_repository() -> None:
    with pytest.raises(ValueError, match="repository identity"):
        create_sbt_jvm_runner_contract(ContainerImageReference("example/other@sha256:" + "c" * 64))
    with pytest.raises(ValueError, match="pinned by a lowercase SHA-256 digest"):
        ContainerImageReference("orchestwin/jvm-sbt-runner:latest")


def test_sbt_runner_snapshot_is_bound_to_one_executable() -> None:
    contract = create_sbt_jvm_runner_contract(_IMAGE)
    snapshot = contract.to_safe_snapshot()

    assert snapshot["runner_id"] == "jvm.sbt"
    assert snapshot["build_system"] == "SBT"
    assert snapshot["execution_kind"] == "SBT"
    assert contract.execution_policy.allowed_executables == frozenset({"sbt"})
    assert contract.validation_evidence_refs == ()
