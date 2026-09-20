"""Tests for governed JVM execution, authorization, and bounded reruns."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.artifacts.jvm_sources import JvmSourceRevisionReference
from orchestwin.jvm_execution.attempt_persistence import (
    InMemoryJvmExecutionAttemptRepository,
)
from orchestwin.jvm_execution.attempts import JvmExecutionAttemptTrigger
from orchestwin.jvm_execution.evidence import (
    JvmEvidenceReference,
    JvmExecutionReportStatus,
    JvmFailureCategory,
    JvmPhaseResult,
    JvmPhaseResultStatus,
)
from orchestwin.jvm_execution.plans import JvmExecutionPhase, JvmPhasePlan
from orchestwin.jvm_execution.profile_contracts import JvmProfileContract
from orchestwin.jvm_execution.profile_registry import (
    create_sprint09_jvm_profile_registry,
)
from orchestwin.jvm_execution.targets import jvm_scope_for
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
    target: ExecutionTarget = ExecutionTarget.JVM_KOTLIN,
    purpose: JvmExecutionPurpose = JvmExecutionPurpose.PROFILE_VALIDATION,
    trigger: JvmExecutionAttemptTrigger = JvmExecutionAttemptTrigger.PROFILE_VALIDATION,
    source: JvmSourceRevisionReference | None = None,
    rerun_phases: tuple[JvmExecutionPhase, ...] | None = None,
) -> JvmExecutionRequest:
    runner = runner_for(target)
    return JvmExecutionRequest(
        project_id=source_revision_reference().project_id,
        owner_user_id=OWNER_ID,
        source_revision=source or source_revision_reference(),
        snapshot=snapshot_for(target),
        declaration=declaration_for(target),
        profile_id=jvm_scope_for(target).profile_id,
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


def service(executor: Executor, *, lifecycle=None):
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
            lifecycle=lifecycle,
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


class Lifecycle:
    def __init__(self) -> None:
        self.bindings: list[tuple[UUID, JvmProfileContract, tuple[JvmExecutionPhase, ...]]] = []
        self.finalize_calls = 0
        self.completed = False

    def bind_attempt(self, attempt_id, *, contract, phases_to_execute):
        self.bindings.append((attempt_id, contract, phases_to_execute))

    async def finalize(self):
        self.finalize_calls += 1
        self.completed = True


@pytest.mark.parametrize(
    "target", [ExecutionTarget.JVM_JAVA, ExecutionTarget.JVM_KOTLIN, ExecutionTarget.JVM_SCALA]
)
def test_attempt_identity_and_scope_are_bound_before_execution_and_append(monkeypatch, target):
    lifecycle = Lifecycle()

    class BoundExecutor(Executor):
        async def execute(self, phase_plan, *, contract):
            assert len(lifecycle.bindings) == 1
            assert lifecycle.bindings[0][1] == contract
            assert not lifecycle.completed
            return await super().execute(phase_plan, contract=contract)

    app, attempts = service(BoundExecutor(), lifecycle=lifecycle)
    original_append = attempts.append

    async def append(attempt):
        assert lifecycle.completed
        assert lifecycle.finalize_calls == 1
        assert lifecycle.bindings[0][0] == attempt.id
        assert lifecycle.bindings[0][2] == attempt.executed_phases == tuple(JvmExecutionPhase)
        return await original_append(attempt)

    monkeypatch.setattr(attempts, "append", append)
    result = asyncio.run(app.execute(authorized(base_request(target=target))))
    assert result.status is JvmExecutionServiceStatus.RECORDED


@pytest.mark.parametrize(
    "failure_phase",
    [JvmExecutionPhase.SETUP, JvmExecutionPhase.BUILD, JvmExecutionPhase.COLLECT_ARTIFACTS],
)
def test_cleanup_preserves_failed_and_unexecuted_phase_evidence(failure_phase):
    lifecycle = Lifecycle()
    executor = Executor(fail_once_at=failure_phase)
    app, _ = service(executor, lifecycle=lifecycle)
    result = asyncio.run(app.execute(authorized(base_request())))

    assert lifecycle.completed
    assert lifecycle.finalize_calls == 1
    assert result.attempt is not None
    assert result.attempt.report.status is JvmExecutionReportStatus.FAILED
    phases = tuple(JvmExecutionPhase)
    failed_index = phases.index(failure_phase)
    assert result.attempt.executed_phases == phases[: failed_index + 1]
    failed = result.attempt.report.phase_results[failed_index]
    assert failed.failure_code == "JVM_BUILD_FAILED"
    assert failed.stderr_refs
    for phase in result.attempt.report.phase_results[failed_index + 1 :]:
        assert phase.status is JvmPhaseResultStatus.NOT_RUN
        assert phase.started_at is None
        assert phase.completed_at is None
        assert (
            phase.exit_codes == phase.stdout_refs == phase.stderr_refs == phase.artifact_refs == ()
        )


@pytest.mark.parametrize(
    ("change", "expected_status"),
    [
        ({"authorization": None}, JvmExecutionServiceStatus.AUTHORIZATION_REQUIRED),
        ({"owner_user_id": UUID(int=99)}, JvmExecutionServiceStatus.AUTHORIZATION_MISMATCH),
        (
            {"purpose": JvmExecutionPurpose.OWNER_PROJECT},
            JvmExecutionServiceStatus.CAPABILITY_BLOCKED,
        ),
        ({"profile_id": "jvm.unknown"}, JvmExecutionServiceStatus.PROFILE_NOT_FOUND),
        (
            {"snapshot": snapshot_for(ExecutionTarget.JVM_JAVA)},
            JvmExecutionServiceStatus.PROFILE_INVALID,
        ),
        (
            {
                "trigger": JvmExecutionAttemptTrigger.MANUAL_RERUN,
                "rerun_phases": (JvmExecutionPhase.TEST,),
            },
            JvmExecutionServiceStatus.RERUN_INVALID,
        ),
    ],
)
def test_rejected_request_never_binds_executes_or_finalizes(change, expected_status):
    lifecycle = Lifecycle()
    executor = Executor()
    app, attempts = service(executor, lifecycle=lifecycle)
    request = replace(authorized(base_request()), **change)
    result = asyncio.run(app.execute(request))

    assert result.status is expected_status
    assert lifecycle.bindings == executor.calls == []
    assert lifecycle.finalize_calls == 0
    assert asyncio.run(attempts.current(project_id=request.project_id)) is None


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
def test_executor_exception_finalizes_without_persisting_invented_results(error_type):
    lifecycle = Lifecycle()

    class RaisingExecutor(Executor):
        async def execute(self, phase_plan, *, contract):
            if phase_plan.phase is JvmExecutionPhase.BUILD:
                raise error_type("phase interrupted")
            return await super().execute(phase_plan, contract=contract)

    app, attempts = service(RaisingExecutor(), lifecycle=lifecycle)
    request = authorized(base_request())
    with pytest.raises(error_type, match="phase interrupted"):
        asyncio.run(app.execute(request))
    assert lifecycle.completed
    assert lifecycle.finalize_calls == 1
    assert asyncio.run(attempts.current(project_id=request.project_id)) is None


@pytest.mark.parametrize("mismatch", ["phase", "command_plan_hash"])
def test_invalid_executor_evidence_finalizes_without_persistence(mismatch):
    lifecycle = Lifecycle()

    class WrongExecutor(Executor):
        async def execute(self, phase_plan, *, contract):
            result = await super().execute(phase_plan, contract=contract)
            changes = {mismatch: JvmExecutionPhase.TEST if mismatch == "phase" else "0" * 64}
            return replace(result, **changes)

    app, attempts = service(WrongExecutor(), lifecycle=lifecycle)
    request = authorized(base_request())
    with pytest.raises(ValueError, match="evidence for another"):
        asyncio.run(app.execute(request))
    assert lifecycle.completed
    assert lifecycle.finalize_calls == 1
    assert asyncio.run(attempts.current(project_id=request.project_id)) is None


def test_rejected_binding_does_not_finalize_another_attempts_resources():
    class BusyLifecycle(Lifecycle):
        def bind_attempt(self, attempt_id, *, contract, phases_to_execute):
            raise ValueError("adapter already bound to another attempt")

    lifecycle = BusyLifecycle()
    executor = Executor()
    app, attempts = service(executor, lifecycle=lifecycle)
    request = authorized(base_request())
    with pytest.raises(ValueError, match="another attempt"):
        asyncio.run(app.execute(request))
    assert lifecycle.finalize_calls == 0
    assert executor.calls == []
    assert asyncio.run(attempts.current(project_id=request.project_id)) is None


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
def test_unconfirmed_cleanup_prevents_persistence(error_type):
    class RaisingLifecycle(Lifecycle):
        async def finalize(self):
            self.finalize_calls += 1
            raise error_type("cleanup not confirmed")

    lifecycle = RaisingLifecycle()
    app, attempts = service(Executor(), lifecycle=lifecycle)
    request = authorized(base_request())
    with pytest.raises(error_type):
        asyncio.run(app.execute(request))
    assert lifecycle.finalize_calls == 1
    assert asyncio.run(attempts.current(project_id=request.project_id)) is None


@pytest.mark.parametrize("cancel_during_phase", [False, True])
def test_repeated_cancellation_waits_for_cleanup_without_persistence(cancel_during_phase):
    async def scenario():
        phase_started = asyncio.Event()
        cleanup_started = asyncio.Event()
        cleanup_release = asyncio.Event()

        class WaitingExecutor(Executor):
            async def execute(self, phase_plan, *, contract):
                if cancel_during_phase:
                    phase_started.set()
                    await asyncio.Future()
                return await super().execute(phase_plan, contract=contract)

        class WaitingLifecycle(Lifecycle):
            async def finalize(self):
                self.finalize_calls += 1
                cleanup_started.set()
                await cleanup_release.wait()
                self.completed = True

        lifecycle = WaitingLifecycle()
        app, attempts = service(WaitingExecutor(), lifecycle=lifecycle)
        request = authorized(base_request())
        task = asyncio.create_task(app.execute(request))
        if cancel_during_phase:
            await asyncio.wait_for(phase_started.wait(), timeout=2)
            task.cancel()
        await asyncio.wait_for(cleanup_started.wait(), timeout=2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert not lifecycle.completed
        assert await attempts.current(project_id=request.project_id) is None
        cleanup_release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
        assert lifecycle.completed
        assert lifecycle.finalize_calls == 1
        assert await attempts.current(project_id=request.project_id) is None

    asyncio.run(scenario())


@pytest.mark.parametrize("reused_phase", [JvmExecutionPhase.BUILD, JvmExecutionPhase.RUN])
def test_rerun_cannot_reuse_failed_or_unexecuted_evidence(reused_phase):
    async def scenario():
        lifecycle = Lifecycle()
        executor = Executor(fail_once_at=JvmExecutionPhase.BUILD)
        app, attempts = service(executor, lifecycle=lifecycle)
        initial = await app.execute(authorized(base_request()))
        assert initial.attempt is not None
        phases = tuple(phase for phase in JvmExecutionPhase if phase is not reused_phase)
        request = authorized(
            base_request(
                trigger=JvmExecutionAttemptTrigger.MANUAL_RERUN,
                rerun_phases=phases,
            )
        )
        executor.calls.clear()
        result = await app.execute(request)
        assert result.status is JvmExecutionServiceStatus.RERUN_INVALID
        assert executor.calls == []
        assert len(lifecycle.bindings) == lifecycle.finalize_calls == 1
        assert await attempts.history(project_id=request.project_id) == (initial.attempt,)

    asyncio.run(scenario())


def test_rerun_rejects_reused_evidence_for_a_stale_plan_before_binding(monkeypatch):
    async def scenario():
        lifecycle = Lifecycle()
        executor = Executor()
        app, attempts = service(executor, lifecycle=lifecycle)
        initial = await app.execute(authorized(base_request()))
        assert initial.attempt is not None
        stale_results = tuple(
            replace(result, command_plan_hash="0" * 64)
            if result.phase is JvmExecutionPhase.SETUP
            else result
            for result in initial.attempt.report.phase_results
        )
        stale = replace(
            initial.attempt, report=replace(initial.attempt.report, phase_results=stale_results)
        )

        async def current(*, project_id):
            assert project_id == stale.project_id
            return stale

        monkeypatch.setattr(attempts, "current", current)
        request = authorized(
            base_request(
                trigger=JvmExecutionAttemptTrigger.MANUAL_RERUN,
                rerun_phases=tuple(
                    phase for phase in JvmExecutionPhase if phase is not JvmExecutionPhase.SETUP
                ),
            )
        )
        executor.calls.clear()
        result = await app.execute(request)
        assert result.status is JvmExecutionServiceStatus.RERUN_INVALID
        assert executor.calls == []
        assert len(lifecycle.bindings) == lifecycle.finalize_calls == 1
        assert await attempts.history(project_id=request.project_id) == (initial.attempt,)

    asyncio.run(scenario())


@pytest.mark.parametrize("requires_fresh_setup", [False, True])
def test_adapter_receives_exact_rerun_scope_and_can_reject_missing_fresh_setup(
    requires_fresh_setup,
):
    async def scenario():
        class ScopeLifecycle(Lifecycle):
            def bind_attempt(self, attempt_id, *, contract, phases_to_execute):
                if requires_fresh_setup and JvmExecutionPhase.SETUP not in phases_to_execute:
                    raise ValueError("fresh dependency caches require SETUP")
                super().bind_attempt(
                    attempt_id,
                    contract=contract,
                    phases_to_execute=phases_to_execute,
                )

        lifecycle = ScopeLifecycle()
        executor = Executor()
        app, attempts = service(executor, lifecycle=lifecycle)
        initial = await app.execute(authorized(base_request()))
        assert initial.attempt is not None
        phases = (
            JvmExecutionPhase.TEST,
            JvmExecutionPhase.RUN,
            JvmExecutionPhase.COLLECT_ARTIFACTS,
        )
        request = authorized(
            base_request(
                trigger=JvmExecutionAttemptTrigger.MANUAL_RERUN,
                rerun_phases=phases,
            )
        )
        executor.calls.clear()
        if requires_fresh_setup:
            with pytest.raises(ValueError, match="fresh dependency caches require SETUP"):
                await app.execute(request)
            assert executor.calls == []
            assert len(lifecycle.bindings) == lifecycle.finalize_calls == 1
            assert await attempts.history(project_id=request.project_id) == (initial.attempt,)
        else:
            rerun = await app.execute(request)
            assert rerun.attempt is not None
            assert rerun.attempt.executed_phases == tuple(executor.calls) == phases
            assert lifecycle.bindings[1][0] == rerun.attempt.id != initial.attempt.id
            assert lifecycle.bindings[1][2] == phases
            assert lifecycle.finalize_calls == 2
            assert (
                rerun.attempt.report.phase_results[:4] == initial.attempt.report.phase_results[:4]
            )

    asyncio.run(scenario())
