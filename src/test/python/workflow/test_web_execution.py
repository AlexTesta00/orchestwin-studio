"""Tests for governed Web execution and bounded rerun orchestration."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.artifacts.web_sources import (
    WebSourceFileEntry,
    WebSourceOrigin,
    WebSourceProvenanceKind,
    WebSourceProvenanceReference,
    create_web_source_revision,
)
from orchestwin.sandbox.archive_policy import (
    SourceArchiveEntryDisposition,
    SourceArchiveEntryKind,
)
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.sandbox.source_inventory import (
    SourceInventoryClassification,
    SourceInventoryEntry,
    SourceTreeInventory,
)
from orchestwin.web_execution.attempt_persistence import (
    InMemoryWebExecutionAttemptRepository,
)
from orchestwin.web_execution.attempts import WebExecutionAttemptTrigger
from orchestwin.web_execution.detection import (
    create_web_detection_snapshot,
    detect_web_project,
)
from orchestwin.web_execution.lockfiles import validate_web_dependency_locks
from orchestwin.web_execution.plans import WebExecutionPhase, WebPhasePlan
from orchestwin.web_execution.profile_contracts import (
    WebProfileContract,
    WebProfileRunnerSet,
)
from orchestwin.web_execution.profile_registry import (
    create_sprint08_web_profile_registry,
)
from orchestwin.web_execution.reports import (
    WebEvidenceReference,
    WebExecutionReportStatus,
    WebFailureCategory,
    WebPhaseResult,
    WebPhaseResultStatus,
)
from orchestwin.web_execution.targets import (
    WebImplementationLanguage,
    WebLanguageConfiguration,
    WebProjectLayout,
)
from orchestwin.workflow.web_execution import (
    LocalGovernedWebExecutionService,
    WebExecutionAuthorization,
    WebExecutionAuthorizationKind,
    WebExecutionPurpose,
    WebExecutionRequest,
    WebExecutionServiceStatus,
)

PROJECT_ID = UUID("40000000-0000-4000-8000-000000000001")
OWNER_ID = UUID("40000000-0000-4000-8000-000000000002")
SOURCE_ID = UUID("40000000-0000-4000-8000-000000000003")
BASE_TIME = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


class SequenceClock:
    def __init__(self) -> None:
        self._calls = 0

    def now(self) -> datetime:
        value = BASE_TIME + timedelta(seconds=self._calls)
        self._calls += 1
        return value


class SequenceIds:
    def __init__(self) -> None:
        self._next = 10

    def new_id(self) -> UUID:
        value = UUID(f"40000000-0000-4000-8000-{self._next:012d}")
        self._next += 1
        return value


class FakePhaseExecutor:
    def __init__(self, *, failure_phase: WebExecutionPhase | None = None) -> None:
        self.failure_phase = failure_phase
        self.calls: list[WebExecutionPhase] = []

    async def execute(
        self,
        phase_plan: WebPhasePlan,
        *,
        contract: WebProfileContract,
    ) -> WebPhaseResult:
        del contract
        phase = phase_plan.phase
        self.calls.append(phase)
        hashes = tuple(sorted(plan.content_hash for plan in phase_plan.command_plans))
        if phase is self.failure_phase:
            evidence = WebEvidenceReference(
                storage_key="sha256/aa/" + "a" * 64,
                sha256_digest="a" * 64,
                size_bytes=8,
                media_type="text/plain",
            )
            return WebPhaseResult(
                phase=phase,
                status=WebPhaseResultStatus.FAILED,
                command_plan_hashes=hashes,
                started_at=BASE_TIME,
                completed_at=BASE_TIME + timedelta(seconds=1),
                exit_codes=(1,),
                stdout_refs=(),
                stderr_refs=(evidence,),
                artifact_refs=(),
                findings=(),
                failure_category=WebFailureCategory.TEST,
                failure_code="TEST_FAILED",
                normalized_summary="deterministic test failed",
            )
        return WebPhaseResult(
            phase=phase,
            status=WebPhaseResultStatus.PASSED,
            command_plan_hashes=hashes,
            started_at=BASE_TIME,
            completed_at=BASE_TIME + timedelta(seconds=1),
            exit_codes=(0,),
            stdout_refs=(),
            stderr_refs=(),
            artifact_refs=(),
            findings=(),
            failure_category=None,
            failure_code=None,
            normalized_summary=f"{phase.value} completed successfully.",
        )


def static_inputs():
    files = {"index.html": "<!doctype html><title>Ready</title>"}
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
    inventory = SourceTreeInventory(archive_sha256="9" * 64, entries=entries)
    snapshot = create_web_detection_snapshot(inventory, text_content_by_path=files)
    detection = detect_web_project(snapshot)
    assert detection.selected is not None
    selection = detection.selected.selection
    locks = validate_web_dependency_locks(snapshot, selection=selection)
    digest = entries[0].sha256_digest
    assert digest is not None
    source = create_web_source_revision(
        revision_id=SOURCE_ID,
        project_id=PROJECT_ID,
        created_by_user_id=OWNER_ID,
        version_number=1,
        based_on=None,
        target=ExecutionTarget.WEB_STATIC,
        language_configuration=WebLanguageConfiguration(
            frontend=WebImplementationLanguage.STATIC_ASSETS,
            backend=None,
        ),
        layout=WebProjectLayout.SINGLE_ROOT,
        origin=WebSourceOrigin.DETERMINISTIC_FIXTURE,
        files=(
            WebSourceFileEntry(
                normalized_path="index.html",
                sha256_digest=digest,
                size_bytes=entries[0].size_bytes,
                storage_key=f"sha256/{digest[:2]}/{digest}",
                media_type="text/html",
            ),
        ),
        provenance_references=(
            WebSourceProvenanceReference(
                kind=WebSourceProvenanceKind.SOURCE_PLAN,
                reference_id="source-plan:fixture",
                version_number=1,
                content_hash="8" * 64,
            ),
        ),
        created_at=BASE_TIME,
    )
    return snapshot, selection, locks, source


def request(*, purpose: WebExecutionPurpose) -> WebExecutionRequest:
    snapshot, selection, locks, source = static_inputs()
    return WebExecutionRequest(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        source_revision=source,
        snapshot=snapshot,
        selection=selection,
        lock_report=locks,
        profile_id="web.static",
        profile_version="1.0.0",
        runners=WebProfileRunnerSet(
            execution_runner_image_digest="6" * 64,
            browser_runner_image_digest="7" * 64,
        ),
        policy_content_hash="5" * 64,
        purpose=purpose,
        trigger=(
            WebExecutionAttemptTrigger.PROFILE_VALIDATION
            if purpose is WebExecutionPurpose.PROFILE_VALIDATION
            else WebExecutionAttemptTrigger.INITIAL
        ),
        authorization=None,
    )


def authorize(candidate: WebExecutionRequest) -> WebExecutionRequest:
    registry = create_sprint08_web_profile_registry()
    profile = registry.find(candidate.profile_id, candidate.profile_version)
    assert profile is not None
    contract = profile.create_contract(
        candidate.snapshot,
        selection=candidate.selection,
        lock_report=candidate.lock_report,
        source_revision_content_hash=candidate.source_revision.content_hash,
        source_tree_hash=candidate.source_revision.source_tree_hash,
        runners=candidate.runners,
        declared_routes=candidate.declared_routes,
    )
    authorization = WebExecutionAuthorization(
        authorization_id=UUID("40000000-0000-4000-8000-000000000004"),
        kind=(
            WebExecutionAuthorizationKind.PROFILE_VALIDATION
            if candidate.purpose is WebExecutionPurpose.PROFILE_VALIDATION
            else WebExecutionAuthorizationKind.GATE_7
        ),
        project_id=PROJECT_ID,
        source_revision_content_hash=candidate.source_revision.content_hash,
        profile_validation_content_hash=contract.validation.content_hash,
        execution_plan_content_hash=contract.execution_plan.content_hash,
        policy_content_hash=candidate.policy_content_hash,
        execution_runner_image_digest=candidate.runners.execution_runner_image_digest,
        browser_runner_image_digest=candidate.runners.browser_runner_image_digest,
        authorized_by_user_id=OWNER_ID,
    )
    return replace(candidate, authorization=authorization)


def service(executor: FakePhaseExecutor, *, lifecycle=None, binding=None):
    repository = InMemoryWebExecutionAttemptRepository(
        owner_user_id=OWNER_ID,
        project_ids=frozenset({PROJECT_ID}),
    )
    return (
        LocalGovernedWebExecutionService(
            registry=create_sprint08_web_profile_registry(),
            attempts=repository,
            phase_executor=executor,
            clock=SequenceClock(),
            ids=SequenceIds(),
            phase_lifecycle=lifecycle,
            phase_attempt_binding=binding,
        ),
        repository,
    )


def test_attempt_identity_is_bound_after_authorization_and_before_first_phase() -> None:
    class BoundExecutor(FakePhaseExecutor):
        attempt_id = None

        def bind_attempt(self, attempt_id):
            assert not self.calls
            self.attempt_id = attempt_id

        async def execute(self, phase_plan, *, contract):
            assert self.attempt_id is not None
            return await super().execute(phase_plan, contract=contract)

    executor = BoundExecutor()
    application, _ = service(executor, binding=executor)
    candidate = request(purpose=WebExecutionPurpose.PROFILE_VALIDATION)
    blocked = asyncio.run(application.execute(candidate))
    assert blocked.status is WebExecutionServiceStatus.AUTHORIZATION_REQUIRED
    assert executor.attempt_id is None
    recorded = asyncio.run(application.execute(authorize(candidate)))
    assert recorded.attempt.id == executor.attempt_id


def test_owner_execution_is_blocked_while_profile_remains_level_c() -> None:
    executor = FakePhaseExecutor()
    application, _repository = service(executor)

    import asyncio

    result = asyncio.run(application.execute(request(purpose=WebExecutionPurpose.OWNER_PROJECT)))

    assert result.status is WebExecutionServiceStatus.CAPABILITY_BLOCKED
    assert executor.calls == []


def test_profile_validation_requires_exact_authorization_and_records_attempt() -> None:
    executor = FakePhaseExecutor()
    application, repository = service(executor)
    candidate = request(purpose=WebExecutionPurpose.PROFILE_VALIDATION)

    import asyncio

    blocked = asyncio.run(application.execute(candidate))
    recorded = asyncio.run(application.execute(authorize(candidate)))

    assert blocked.status is WebExecutionServiceStatus.AUTHORIZATION_REQUIRED
    assert recorded.status is WebExecutionServiceStatus.RECORDED
    assert recorded.attempt is not None
    assert recorded.attempt.trigger is WebExecutionAttemptTrigger.PROFILE_VALIDATION
    assert asyncio.run(repository.current(project_id=PROJECT_ID)) == recorded.attempt


def test_failed_phase_stops_later_work_and_preserves_complete_report() -> None:
    executor = FakePhaseExecutor(failure_phase=WebExecutionPhase.TEST)
    application, _repository = service(executor)

    import asyncio

    result = asyncio.run(
        application.execute(authorize(request(purpose=WebExecutionPurpose.PROFILE_VALIDATION)))
    )

    assert result.status is WebExecutionServiceStatus.RECORDED
    assert result.attempt is not None
    results = {item.phase: item for item in result.attempt.report.phase_results}
    assert results[WebExecutionPhase.TEST].status is WebPhaseResultStatus.FAILED
    assert results[WebExecutionPhase.RUN].status is WebPhaseResultStatus.NOT_RUN
    assert WebExecutionPhase.RUN not in executor.calls


def test_authorization_is_invalidated_by_policy_change() -> None:
    executor = FakePhaseExecutor()
    application, _repository = service(executor)
    approved = authorize(request(purpose=WebExecutionPurpose.PROFILE_VALIDATION))
    changed = replace(approved, policy_content_hash="4" * 64)

    import asyncio

    result = asyncio.run(application.execute(changed))

    assert result.status is WebExecutionServiceStatus.AUTHORIZATION_MISMATCH
    assert executor.calls == []


def test_manual_rerun_executes_only_requested_phases_and_reuses_prior_evidence() -> None:
    executor = FakePhaseExecutor()
    application, _repository = service(executor)
    initial = authorize(request(purpose=WebExecutionPurpose.PROFILE_VALIDATION))

    import asyncio

    first = asyncio.run(application.execute(initial))
    executor.calls.clear()
    rerun = replace(
        initial,
        trigger=WebExecutionAttemptTrigger.MANUAL_RERUN,
        rerun_phases=(
            WebExecutionPhase.TEST,
            WebExecutionPhase.RUN,
            WebExecutionPhase.HEALTH_CHECK,
            WebExecutionPhase.BROWSER_EVIDENCE,
            WebExecutionPhase.COLLECT_ARTIFACTS,
        ),
    )
    second = asyncio.run(application.execute(rerun))

    assert first.status is WebExecutionServiceStatus.RECORDED
    assert second.status is WebExecutionServiceStatus.RECORDED
    assert second.attempt is not None
    assert second.attempt.attempt_number == 2
    assert tuple(executor.calls) == rerun.rerun_phases


def finalization_result(*, failed=False):
    evidence = WebEvidenceReference(
        storage_key="sha256/bb/" + "b" * 64,
        sha256_digest="b" * 64,
        size_bytes=8,
        media_type="text/plain",
    )
    return WebPhaseResult(
        phase=WebExecutionPhase.COLLECT_ARTIFACTS,
        status=WebPhaseResultStatus.RUNTIME_ERROR if failed else WebPhaseResultStatus.PASSED,
        command_plan_hashes=(),
        started_at=BASE_TIME,
        completed_at=BASE_TIME + timedelta(seconds=1),
        exit_codes=(1,) if failed else (0,),
        stdout_refs=(evidence,),
        stderr_refs=(),
        artifact_refs=(),
        findings=(),
        failure_category=WebFailureCategory.ARTIFACT_COLLECTION if failed else None,
        failure_code="CLEANUP_NOT_CONFIRMED" if failed else None,
        normalized_summary="Final resource cleanup failed."
        if failed
        else "Final resource cleanup confirmed.",
    )


class FakeLifecycle:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0
        self.completed = False

    async def finalize(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        self.completed = True
        return self.result


@pytest.mark.parametrize("cleanup_failed", [False, True])
def test_lifecycle_result_is_recorded_only_after_finalization(monkeypatch, cleanup_failed) -> None:
    lifecycle = FakeLifecycle(finalization_result(failed=cleanup_failed))
    application, repository = service(FakePhaseExecutor(), lifecycle=lifecycle)
    original_append = repository.append

    async def append(attempt):
        assert lifecycle.completed
        assert attempt.report.phase_results[-1] == lifecycle.result
        return await original_append(attempt)

    monkeypatch.setattr(repository, "append", append)
    result = asyncio.run(
        application.execute(authorize(request(purpose=WebExecutionPurpose.PROFILE_VALIDATION)))
    )

    assert lifecycle.calls == 1
    assert result.attempt is not None
    assert result.attempt.report.status is (
        WebExecutionReportStatus.FAILED if cleanup_failed else WebExecutionReportStatus.PASSED
    )
    assert result.attempt.executed_phases.count(WebExecutionPhase.COLLECT_ARTIFACTS) == 1


def test_failed_early_phase_still_records_actual_finalization() -> None:
    lifecycle = FakeLifecycle(finalization_result())
    executor = FakePhaseExecutor(failure_phase=WebExecutionPhase.TEST)
    application, _repository = service(executor, lifecycle=lifecycle)

    result = asyncio.run(
        application.execute(authorize(request(purpose=WebExecutionPurpose.PROFILE_VALIDATION)))
    )

    assert lifecycle.completed
    assert result.attempt is not None
    assert result.attempt.report.status is WebExecutionReportStatus.FAILED
    assert result.attempt.report.phase_results[-1] == lifecycle.result
    assert result.attempt.executed_phases[-1] is WebExecutionPhase.COLLECT_ARTIFACTS
    assert WebExecutionPhase.RUN not in executor.calls
    assert WebExecutionPhase.COLLECT_ARTIFACTS not in executor.calls


def test_successful_cleanup_does_not_erase_existing_collection_failure() -> None:
    lifecycle = FakeLifecycle(finalization_result())
    application, _repository = service(
        FakePhaseExecutor(failure_phase=WebExecutionPhase.COLLECT_ARTIFACTS),
        lifecycle=lifecycle,
    )
    result = asyncio.run(
        application.execute(authorize(request(purpose=WebExecutionPurpose.PROFILE_VALIDATION)))
    )
    assert result.attempt is not None
    collection = result.attempt.report.phase_results[-1]
    assert collection.status is WebPhaseResultStatus.FAILED
    assert collection.failure_code == "TEST_FAILED"
    assert collection.stdout_refs == lifecycle.result.stdout_refs
    assert len(collection.stderr_refs) == 1
    assert result.attempt.report.status is WebExecutionReportStatus.FAILED


def test_lifecycle_without_executed_cleanup_preserves_existing_result() -> None:
    lifecycle = FakeLifecycle()
    application, _repository = service(FakePhaseExecutor(), lifecycle=lifecycle)
    result = asyncio.run(
        application.execute(authorize(request(purpose=WebExecutionPurpose.PROFILE_VALIDATION)))
    )
    assert lifecycle.completed
    assert result.attempt is not None
    assert (
        result.attempt.report.phase_results[-1].normalized_summary
        == "COLLECT_ARTIFACTS completed successfully."
    )


def test_lifecycle_cannot_replace_evidence_for_another_phase() -> None:
    lifecycle = FakeLifecycle(replace(finalization_result(), phase=WebExecutionPhase.TEST))
    application, repository = service(FakePhaseExecutor(), lifecycle=lifecycle)
    with pytest.raises(ValueError, match="artifact collection evidence"):
        asyncio.run(
            application.execute(authorize(request(purpose=WebExecutionPurpose.PROFILE_VALIDATION)))
        )
    assert asyncio.run(repository.current(project_id=PROJECT_ID)) is None


@pytest.mark.parametrize("error", [RuntimeError("runtime failed"), asyncio.CancelledError()])
def test_executor_exception_finalizes_without_appending(error) -> None:
    class RaisingExecutor(FakePhaseExecutor):
        async def execute(self, phase_plan, *, contract):
            raise error

    lifecycle = FakeLifecycle(finalization_result())
    application, repository = service(RaisingExecutor(), lifecycle=lifecycle)

    with pytest.raises(type(error)):
        asyncio.run(
            application.execute(authorize(request(purpose=WebExecutionPurpose.PROFILE_VALIDATION)))
        )

    assert lifecycle.calls == 1
    assert lifecycle.completed
    assert asyncio.run(repository.current(project_id=PROJECT_ID)) is None


def test_lifecycle_exception_prevents_persistence() -> None:
    lifecycle = FakeLifecycle(error=RuntimeError("cleanup failed"))
    application, repository = service(FakePhaseExecutor(), lifecycle=lifecycle)
    with pytest.raises(RuntimeError, match="cleanup failed"):
        asyncio.run(
            application.execute(authorize(request(purpose=WebExecutionPurpose.PROFILE_VALIDATION)))
        )
    assert asyncio.run(repository.current(project_id=PROJECT_ID)) is None


def test_cancellation_waits_for_finalization_and_never_appends() -> None:
    async def scenario():
        cleanup_started = asyncio.Event()
        cleanup_release = asyncio.Event()

        class WaitingLifecycle(FakeLifecycle):
            async def finalize(self):
                self.calls += 1
                cleanup_started.set()
                await cleanup_release.wait()
                self.completed = True
                return self.result

        lifecycle = WaitingLifecycle(finalization_result())
        application, repository = service(FakePhaseExecutor(), lifecycle=lifecycle)
        task = asyncio.create_task(
            application.execute(authorize(request(purpose=WebExecutionPurpose.PROFILE_VALIDATION)))
        )
        await asyncio.wait_for(cleanup_started.wait(), timeout=2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert not lifecycle.completed
        assert await repository.current(project_id=PROJECT_ID) is None
        cleanup_release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
        assert lifecycle.completed
        assert lifecycle.calls == 1
        assert await repository.current(project_id=PROJECT_ID) is None

    asyncio.run(scenario())


def test_authorization_failure_does_not_start_lifecycle() -> None:
    lifecycle = FakeLifecycle(finalization_result())
    application, _repository = service(FakePhaseExecutor(), lifecycle=lifecycle)
    result = asyncio.run(
        application.execute(request(purpose=WebExecutionPurpose.PROFILE_VALIDATION))
    )
    assert result.status is WebExecutionServiceStatus.AUTHORIZATION_REQUIRED
    assert lifecycle.calls == 0
