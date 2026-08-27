"""Tests for governed Web execution and bounded rerun orchestration."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

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


def service(executor: FakePhaseExecutor):
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
        ),
        repository,
    )


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
