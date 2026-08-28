"""Tests for governed JVM execution, authorization, and bounded reruns."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from orchestwin.artifacts.jvm_sources import JvmSourceRevisionReference
from orchestwin.jvm_execution.attempt_persistence import (
    InMemoryJvmExecutionAttemptRepository,
)
from orchestwin.jvm_execution.attempts import JvmExecutionAttemptTrigger
from orchestwin.jvm_execution.evidence import (
    JvmEvidenceReference,
    JvmFailureCategory,
    JvmPhaseResult,
    JvmPhaseResultStatus,
)
from orchestwin.jvm_execution.plans import JvmExecutionPhase, JvmPhasePlan
from orchestwin.jvm_execution.profile_contracts import JvmProfileContract
from orchestwin.jvm_execution.profile_registry import (
    create_sprint09_jvm_profile_registry,
)
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.workflow.jvm_execution import (
    JvmExecutionAuthorization,
    JvmExecutionAuthorizationKind,
    JvmExecutionPurpose,
    JvmExecutionRequest,
    JvmExecutionServiceStatus,
    LocalGovernedJvmExecutionService,
)

from .profile_support import (
    declaration_for,
    runner_for,
    snapshot_for,
    source_revision_reference,
)

OWNER_ID = UUID("44444444-4444-4444-8444-444444444445")
START = datetime(2026, 8, 28, 19, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self._value = START

    def now(self) -> datetime:
        value = self._value
        self._value += timedelta(seconds=2)
        return value


class Ids:
    def __init__(self) -> None:
        self._next = 1

    def new_id(self) -> UUID:
        value = UUID(f"44444444-4444-4444-8444-{self._next:012d}")
        self._next += 1
        return value


class Executor:
    def __init__(self, *, fail_once_at: JvmExecutionPhase | None = None) -> None:
        self.fail_once_at = fail_once_at
        self.calls: list[JvmExecutionPhase] = []

    async def execute(
        self,
        phase_plan: JvmPhasePlan,
        *,
        contract: JvmProfileContract,
    ) -> JvmPhaseResult:
        assert contract.execution_plan.phase(phase_plan.phase) == phase_plan
        self.calls.append(phase_plan.phase)
        failed = self.fail_once_at is phase_plan.phase
        if failed:
            self.fail_once_at = None
        evidence = JvmEvidenceReference(
            storage_key="sha256/aa/" + "a" * 64,
            sha256_digest="a" * 64,
            size_bytes=9,
            media_type="text/plain",
        )
        return JvmPhaseResult(
            phase=phase_plan.phase,
            status=(JvmPhaseResultStatus.FAILED if failed else JvmPhaseResultStatus.PASSED),
            command_plan_hash=phase_plan.command_plan.content_hash,
            started_at=START,
            completed_at=START + timedelta(seconds=1),
            exit_codes=((1,) if failed else (0,)),
            stdout_refs=(),
            stderr_refs=((evidence,) if failed else ()),
            artifact_refs=(),
            findings=(),
            failure_category=(JvmFailureCategory.BUILD if failed else None),
            failure_code=("JVM_BUILD_FAILED" if failed else None),
            normalized_summary=("JVM build failed." if failed else "JVM phase completed."),
        )


def base_request(
    *,
    purpose: JvmExecutionPurpose = JvmExecutionPurpose.PROFILE_VALIDATION,
    trigger: JvmExecutionAttemptTrigger = JvmExecutionAttemptTrigger.PROFILE_VALIDATION,
    source: JvmSourceRevisionReference | None = None,
    rerun_phases: tuple[JvmExecutionPhase, ...] | None = None,
) -> JvmExecutionRequest:
    target = ExecutionTarget.JVM_KOTLIN
    runner = runner_for(target)
    return JvmExecutionRequest(
        project_id=source_revision_reference().project_id,
        owner_user_id=OWNER_ID,
        source_revision=source or source_revision_reference(),
        snapshot=snapshot_for(target),
        declaration=declaration_for(target),
        profile_id="jvm.kotlin-gradle",
        profile_version="1.0.0",
        runner=runner,
        policy_content_hash=runner.execution_policy.content_hash,
        purpose=purpose,
        trigger=trigger,
        authorization=None,
        rerun_phases=rerun_phases,
    )


def authorized(request: JvmExecutionRequest) -> JvmExecutionRequest:
    registry = create_sprint09_jvm_profile_registry()
    profile = registry.find(request.profile_id, request.profile_version)
    assert profile is not None
    contract = profile.create_contract(
        request.snapshot,
        request.declaration,
        source_revision=request.source_revision,
        runner=request.runner,
    )
    authorization = JvmExecutionAuthorization(
        authorization_id=UUID("44444444-4444-4444-8444-444444444499"),
        kind=(
            JvmExecutionAuthorizationKind.PROFILE_VALIDATION
            if request.purpose is JvmExecutionPurpose.PROFILE_VALIDATION
            else JvmExecutionAuthorizationKind.GATE_7
        ),
        project_id=request.project_id,
        source_revision_content_hash=request.source_revision.content_hash,
        profile_validation_content_hash=contract.validation.content_hash,
        execution_plan_content_hash=contract.execution_plan.content_hash,
        runner_image_digest=contract.runner.image.digest,
        policy_content_hash=request.policy_content_hash,
        authorized_by_user_id=request.owner_user_id,
    )
    return replace(request, authorization=authorization)


def service(executor: Executor):
    request = base_request()
    attempts = InMemoryJvmExecutionAttemptRepository(
        owner_user_id=OWNER_ID,
        project_ids=frozenset({request.project_id}),
    )
    return (
        LocalGovernedJvmExecutionService(
            registry=create_sprint09_jvm_profile_registry(),
            attempts=attempts,
            phase_executor=executor,
            clock=Clock(),
            ids=Ids(),
        ),
        attempts,
    )


def test_profile_validation_requires_exact_authorization() -> None:
    async def scenario() -> None:
        app, _ = service(Executor())
        request = base_request()

        missing = await app.execute(request)
        approved = authorized(request)
        assert approved.authorization is not None
        mismatched = await app.execute(
            replace(
                approved,
                authorization=replace(
                    approved.authorization,
                    source_revision_content_hash="0" * 64,
                ),
            )
        )

        assert missing.status is JvmExecutionServiceStatus.AUTHORIZATION_REQUIRED
        assert mismatched.status is JvmExecutionServiceStatus.AUTHORIZATION_MISMATCH

    asyncio.run(scenario())


def test_owner_execution_is_blocked_while_profile_remains_level_c() -> None:
    async def scenario() -> None:
        app, _ = service(Executor())
        request = authorized(base_request(purpose=JvmExecutionPurpose.OWNER_PROJECT))

        result = await app.execute(request)

        assert result.status is JvmExecutionServiceStatus.CAPABILITY_BLOCKED

    asyncio.run(scenario())


def test_complete_profile_validation_attempt_is_recorded() -> None:
    async def scenario() -> None:
        executor = Executor()
        app, attempts = service(executor)

        result = await app.execute(authorized(base_request()))

        assert result.status is JvmExecutionServiceStatus.RECORDED
        assert result.attempt is not None
        assert result.attempt.attempt_number == 1
        assert result.attempt.executed_phases == tuple(JvmExecutionPhase)
        assert executor.calls == list(JvmExecutionPhase)
        assert await attempts.current(project_id=result.attempt.project_id) == result.attempt

    asyncio.run(scenario())


def test_failure_stops_later_phases_but_persists_complete_report() -> None:
    async def scenario() -> None:
        executor = Executor(fail_once_at=JvmExecutionPhase.BUILD)
        app, _ = service(executor)

        result = await app.execute(authorized(base_request()))

        assert result.status is JvmExecutionServiceStatus.RECORDED
        assert result.attempt is not None
        statuses = {item.phase: item.status for item in result.attempt.report.phase_results}
        assert statuses[JvmExecutionPhase.BUILD] is JvmPhaseResultStatus.FAILED
        assert statuses[JvmExecutionPhase.TEST] is JvmPhaseResultStatus.NOT_RUN
        assert statuses[JvmExecutionPhase.RUN] is JvmPhaseResultStatus.NOT_RUN
        assert executor.calls[-1] is JvmExecutionPhase.BUILD

    asyncio.run(scenario())


def test_repair_rerun_reuses_setup_and_executes_bounded_phases() -> None:
    async def scenario() -> None:
        executor = Executor(fail_once_at=JvmExecutionPhase.BUILD)
        app, attempts = service(executor)
        first = await app.execute(authorized(base_request()))
        assert first.attempt is not None
        repaired_source = JvmSourceRevisionReference(
            revision_id=UUID("44444444-4444-4444-8444-444444444433"),
            project_id=first.attempt.project_id,
            version_number=2,
            content_hash="1" * 64,
            source_tree_hash="2" * 64,
        )
        phases = (
            JvmExecutionPhase.VALIDATE,
            JvmExecutionPhase.STATIC_CHECKS,
            JvmExecutionPhase.BUILD,
            JvmExecutionPhase.TEST,
            JvmExecutionPhase.RUN,
            JvmExecutionPhase.COLLECT_ARTIFACTS,
        )
        repair_request = authorized(
            base_request(
                trigger=JvmExecutionAttemptTrigger.REPAIR_RERUN,
                source=repaired_source,
                rerun_phases=phases,
            )
        )
        executor.calls.clear()

        second = await app.execute(repair_request)

        assert second.status is JvmExecutionServiceStatus.RECORDED
        assert second.attempt is not None
        assert second.attempt.attempt_number == 2
        assert second.attempt.previous_attempt_id == first.attempt.id
        assert second.attempt.executed_phases == phases
        assert JvmExecutionPhase.SETUP not in executor.calls
        assert executor.calls == list(phases)
        assert len(await attempts.history(project_id=first.attempt.project_id)) == 2

    asyncio.run(scenario())


def test_rerun_without_previous_attempt_is_rejected() -> None:
    async def scenario() -> None:
        app, _ = service(Executor())
        request = authorized(
            base_request(
                trigger=JvmExecutionAttemptTrigger.MANUAL_RERUN,
                rerun_phases=(JvmExecutionPhase.TEST,),
            )
        )

        result = await app.execute(request)

        assert result.status is JvmExecutionServiceStatus.RERUN_INVALID

    asyncio.run(scenario())
