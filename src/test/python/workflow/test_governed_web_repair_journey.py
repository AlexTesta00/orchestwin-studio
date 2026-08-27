"""Sprint 08 acceptance journey for governed Web generation, repair, and rerun."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from orchestwin.artifacts.web_change_sets import (
    WebSourceChange,
    WebSourceChangeOperation,
    create_web_source_change_set,
)
from orchestwin.artifacts.web_source_persistence import (
    InMemoryWebSourceRevisionRepository,
    WebSourceRevisionAppendStatus,
)
from orchestwin.artifacts.web_source_plans import (
    FileSystemWebSourceContentStore,
    WebSourceMaterializationStatus,
    WebSourcePlanFile,
    create_web_source_plan,
    materialize_web_source_plan,
)
from orchestwin.artifacts.web_sources import (
    WebSourceProvenanceKind,
    WebSourceProvenanceReference,
    WebSourceRevision,
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
    WebDetectionSnapshot,
    create_web_detection_snapshot,
    detect_web_project,
)
from orchestwin.web_execution.lockfiles import validate_web_dependency_locks
from orchestwin.web_execution.plans import WebExecutionPhase, WebPhasePlan
from orchestwin.web_execution.profile_contracts import (
    WebProfileContract,
    WebProfileRunnerSet,
)
from orchestwin.web_execution.profile_registry import create_sprint08_web_profile_registry
from orchestwin.web_execution.reports import (
    WebEvidenceReference,
    WebExecutionReportStatus,
    WebFailureCategory,
    WebNormalizedFinding,
    WebPhaseResult,
    WebPhaseResultStatus,
)
from orchestwin.web_execution.targets import (
    WebImplementationLanguage,
    WebLanguageConfiguration,
    WebProjectLayout,
    WebTargetSelection,
)
from orchestwin.workflow.web_execution import (
    LocalGovernedWebExecutionService,
    WebExecutionAuthorization,
    WebExecutionAuthorizationKind,
    WebExecutionPurpose,
    WebExecutionRequest,
    WebExecutionServiceStatus,
)
from orchestwin.workflow.web_repair import (
    WebRepairApplicationStatus,
    WebRepairProposal,
    apply_web_repair_revision,
)

PROJECT_ID = UUID("50000000-0000-4000-8000-000000000001")
OWNER_ID = UUID("50000000-0000-4000-8000-000000000002")
SOURCE_PLAN_ID = UUID("50000000-0000-4000-8000-000000000003")
SOURCE_REVISION_ID = UUID("50000000-0000-4000-8000-000000000004")
CHANGE_SET_ID = UUID("50000000-0000-4000-8000-000000000005")
REPAIR_PROPOSAL_ID = UUID("50000000-0000-4000-8000-000000000006")
REPAIRED_REVISION_ID = UUID("50000000-0000-4000-8000-000000000007")
BASE_TIME = datetime(2026, 8, 27, 17, 0, tzinfo=UTC)
RUNNERS = WebProfileRunnerSet(
    execution_runner_image_digest="6" * 64,
    browser_runner_image_digest="7" * 64,
)
POLICY_HASH = "5" * 64


class SequenceClock:
    """Deterministic application clock for ordered attempt timestamps."""

    def __init__(self) -> None:
        self._calls = 0

    def now(self) -> datetime:
        value = BASE_TIME + timedelta(seconds=self._calls)
        self._calls += 1
        return value


class SequenceIds:
    """Deterministic UUID source for attempt and authorization identities."""

    def __init__(self) -> None:
        self._next = 100

    def new_id(self) -> UUID:
        value = UUID(f"50000000-0000-4000-8000-{self._next:012d}")
        self._next += 1
        return value


class RepairJourneyPhaseExecutor:
    """Fail the first test phase, then preserve deterministic passing evidence."""

    def __init__(self) -> None:
        self._test_failures_remaining = 1
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
        observed_at = BASE_TIME + timedelta(seconds=len(self.calls))
        plan_hashes = tuple(sorted(plan.content_hash for plan in phase_plan.command_plans))
        if phase is WebExecutionPhase.TEST and self._test_failures_remaining:
            self._test_failures_remaining -= 1
            raw_failure = evidence_reference(
                storage_key="sha256/11/" + "1" * 64,
                digest="1" * 64,
                media_type="text/plain",
            )
            return WebPhaseResult(
                phase=phase,
                status=WebPhaseResultStatus.FAILED,
                command_plan_hashes=plan_hashes,
                started_at=observed_at,
                completed_at=observed_at + timedelta(seconds=1),
                exit_codes=(1,),
                stdout_refs=(),
                stderr_refs=(raw_failure,),
                artifact_refs=(),
                findings=(
                    WebNormalizedFinding(
                        code="READY_STATE_MISSING",
                        message="The generated page does not expose the required ready state.",
                        source_tool="web.static.smoke",
                        location="index.html",
                    ),
                ),
                failure_category=WebFailureCategory.TEST,
                failure_code="STATIC_READY_STATE_MISSING",
                normalized_summary="Expected ready state but received broken state.",
            )

        artifact_refs = ()
        findings = ()
        if phase is WebExecutionPhase.BROWSER_EVIDENCE:
            artifact_refs = (
                evidence_reference(
                    storage_key="sha256/22/" + "2" * 64,
                    digest="2" * 64,
                    media_type="image/png",
                ),
            )
            findings = (
                WebNormalizedFinding(
                    code="AXE_ZERO_VIOLATIONS",
                    message="The controlled route produced no automated axe violations.",
                    source_tool="axe-core",
                    location="route:/",
                ),
            )
        return WebPhaseResult(
            phase=phase,
            status=WebPhaseResultStatus.PASSED,
            command_plan_hashes=plan_hashes,
            started_at=observed_at,
            completed_at=observed_at + timedelta(seconds=1),
            exit_codes=(0,),
            stdout_refs=(),
            stderr_refs=(),
            artifact_refs=artifact_refs,
            findings=findings,
            failure_category=None,
            failure_code=None,
            normalized_summary=f"{phase.value} completed successfully.",
        )


def evidence_reference(
    *,
    storage_key: str,
    digest: str,
    media_type: str,
) -> WebEvidenceReference:
    return WebEvidenceReference(
        storage_key=storage_key,
        sha256_digest=digest,
        size_bytes=16,
        media_type=media_type,
    )


def target_selection() -> WebTargetSelection:
    return WebTargetSelection(
        target=ExecutionTarget.WEB_STATIC,
        language_configuration=WebLanguageConfiguration(
            frontend=WebImplementationLanguage.STATIC_ASSETS,
            backend=None,
        ),
        layout=WebProjectLayout.SINGLE_ROOT,
    )


def provenance() -> WebSourceProvenanceReference:
    return WebSourceProvenanceReference(
        kind=WebSourceProvenanceKind.SOURCE_PLAN,
        reference_id="source-plan:sprint-08-journey",
        version_number=1,
        content_hash="a" * 64,
    )


def snapshot_for_revision(
    revision: WebSourceRevision,
    *,
    content_store: FileSystemWebSourceContentStore,
) -> WebDetectionSnapshot:
    """Reconstruct deterministic detection input from immutable source metadata."""
    text_by_path: dict[str, str] = {}
    entries: list[SourceInventoryEntry] = []
    for file in revision.files:
        content = content_store.read(file.storage_key)
        assert content is not None
        text_by_path[file.normalized_path] = content.decode("utf-8")
        entries.append(
            SourceInventoryEntry(
                normalized_path=file.normalized_path,
                kind=SourceArchiveEntryKind.FILE,
                classification=SourceInventoryClassification.SOURCE,
                size_bytes=file.size_bytes,
                sha256_digest=file.sha256_digest,
                disposition=SourceArchiveEntryDisposition.INCLUDE,
                disposition_reason=None,
            )
        )
    inventory = SourceTreeInventory(
        archive_sha256=revision.content_hash,
        entries=tuple(entries),
    )
    return create_web_detection_snapshot(
        inventory,
        text_content_by_path=text_by_path,
    )


def execution_request(
    revision: WebSourceRevision,
    *,
    snapshot: WebDetectionSnapshot,
    trigger: WebExecutionAttemptTrigger,
    rerun_phases: tuple[WebExecutionPhase, ...] | None,
) -> WebExecutionRequest:
    detection = detect_web_project(snapshot)
    assert detection.selected is not None
    selection = detection.selected.selection
    locks = validate_web_dependency_locks(snapshot, selection=selection)
    return WebExecutionRequest(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        source_revision=revision,
        snapshot=snapshot,
        selection=selection,
        lock_report=locks,
        profile_id="web.static",
        profile_version="1.0.0",
        runners=RUNNERS,
        policy_content_hash=POLICY_HASH,
        purpose=WebExecutionPurpose.PROFILE_VALIDATION,
        trigger=trigger,
        authorization=None,
        rerun_phases=rerun_phases,
    )


def authorize(
    request: WebExecutionRequest,
    *,
    authorization_id: UUID,
) -> WebExecutionRequest:
    registry = create_sprint08_web_profile_registry()
    profile = registry.find(request.profile_id, request.profile_version)
    assert profile is not None
    contract = profile.create_contract(
        request.snapshot,
        selection=request.selection,
        lock_report=request.lock_report,
        source_revision_content_hash=request.source_revision.content_hash,
        source_tree_hash=request.source_revision.source_tree_hash,
        runners=request.runners,
        declared_routes=request.declared_routes,
    )
    return replace(
        request,
        authorization=WebExecutionAuthorization(
            authorization_id=authorization_id,
            kind=WebExecutionAuthorizationKind.PROFILE_VALIDATION,
            project_id=request.project_id,
            source_revision_content_hash=request.source_revision.content_hash,
            profile_validation_content_hash=contract.validation.content_hash,
            execution_plan_content_hash=contract.execution_plan.content_hash,
            policy_content_hash=request.policy_content_hash,
            execution_runner_image_digest=request.runners.execution_runner_image_digest,
            browser_runner_image_digest=request.runners.browser_runner_image_digest,
            authorized_by_user_id=request.owner_user_id,
        ),
    )


async def governed_journey(tmp_path: Path) -> None:
    """Run source materialization, failure, repair, authorization, and rerun."""
    content_store = FileSystemWebSourceContentStore(tmp_path / "objects")
    source_plan = create_web_source_plan(
        plan_id=SOURCE_PLAN_ID,
        project_id=PROJECT_ID,
        created_by_user_id=OWNER_ID,
        target_selection=target_selection(),
        files=(
            WebSourcePlanFile(
                normalized_path="index.html",
                content=(
                    "<!doctype html><title>Journey</title><main data-state='broken'>Broken</main>"
                ),
                media_type="text/html",
            ),
        ),
        rationale="Materialize the approved deterministic Sprint 08 journey fixture.",
        provenance_references=(provenance(),),
        created_at=BASE_TIME,
    )
    materialized = materialize_web_source_plan(
        source_plan,
        revision_id=SOURCE_REVISION_ID,
        workspace_path=tmp_path / "workspace",
        content_store=content_store,
        created_at=BASE_TIME,
    )
    assert materialized.status is WebSourceMaterializationStatus.MATERIALIZED
    assert materialized.revision is not None
    base_revision = materialized.revision

    revisions = InMemoryWebSourceRevisionRepository(
        owner_user_id=OWNER_ID,
        project_ids=frozenset({PROJECT_ID}),
    )
    attempts = InMemoryWebExecutionAttemptRepository(
        owner_user_id=OWNER_ID,
        project_ids=frozenset({PROJECT_ID}),
    )
    assert (await revisions.append(base_revision)).status is (
        WebSourceRevisionAppendStatus.APPENDED
    )
    executor = RepairJourneyPhaseExecutor()
    application = LocalGovernedWebExecutionService(
        registry=create_sprint08_web_profile_registry(),
        attempts=attempts,
        phase_executor=executor,
        clock=SequenceClock(),
        ids=SequenceIds(),
    )

    initial_snapshot = snapshot_for_revision(
        base_revision,
        content_store=content_store,
    )
    initial_request = authorize(
        execution_request(
            base_revision,
            snapshot=initial_snapshot,
            trigger=WebExecutionAttemptTrigger.PROFILE_VALIDATION,
            rerun_phases=None,
        ),
        authorization_id=UUID("50000000-0000-4000-8000-000000000010"),
    )
    initial = await application.execute(initial_request)
    assert initial.status is WebExecutionServiceStatus.RECORDED
    assert initial.attempt is not None
    assert initial.attempt.report.status is WebExecutionReportStatus.FAILED
    signatures = initial.attempt.report.failure_signatures()
    assert len(signatures) == 1
    signature = signatures[0]

    repaired_content = b"<!doctype html><title>Journey</title><main data-state='ready'>Ready</main>"
    stored = content_store.store(
        normalized_path="index.html",
        content=repaired_content,
        media_type="text/html",
    )
    change = WebSourceChange(
        normalized_path="index.html",
        operation=WebSourceChangeOperation.REPLACE,
        content_sha256=stored.sha256_digest,
        size_bytes=stored.size_bytes,
        storage_key=stored.storage_key,
        media_type=stored.media_type,
    )
    repair = WebRepairProposal(
        id=REPAIR_PROPOSAL_ID,
        project_id=PROJECT_ID,
        created_by_user_id=OWNER_ID,
        base_revision=base_revision.reference,
        failure_signature=signature,
        change_set=create_web_source_change_set(
            change_set_id=CHANGE_SET_ID,
            project_id=PROJECT_ID,
            base_revision=base_revision.reference,
            changes=(change,),
            rationale="Replace the broken ready-state marker identified by the test.",
            provenance_references=("failure-signature:ready-state",),
        ),
        attempt_number=1,
        identical_failure_occurrences=1,
        provenance_references=(
            WebSourceProvenanceReference(
                kind=WebSourceProvenanceKind.FAILURE_SIGNATURE,
                reference_id="failure-signature:ready-state",
                version_number=1,
                content_hash=signature.digest,
            ),
        ),
        created_at=BASE_TIME + timedelta(minutes=1),
    )
    applied = apply_web_repair_revision(
        repair,
        base_revision=base_revision,
        revision_id=REPAIRED_REVISION_ID,
        created_by_user_id=OWNER_ID,
        created_at=BASE_TIME + timedelta(minutes=2),
        content_store=content_store,
    )
    assert applied.status is WebRepairApplicationStatus.APPLIED
    assert applied.revision is not None
    repaired_revision = applied.revision
    assert (await revisions.append(repaired_revision)).status is (
        WebSourceRevisionAppendStatus.APPENDED
    )

    repaired_snapshot = snapshot_for_revision(
        repaired_revision,
        content_store=content_store,
    )
    repair_request = execution_request(
        repaired_revision,
        snapshot=repaired_snapshot,
        trigger=WebExecutionAttemptTrigger.REPAIR_RERUN,
        rerun_phases=applied.required_rerun_phases,
    )
    stale_authorization = replace(
        repair_request,
        authorization=initial_request.authorization,
    )
    stale = await application.execute(stale_authorization)
    assert stale.status is WebExecutionServiceStatus.AUTHORIZATION_MISMATCH

    authorized_repair = authorize(
        repair_request,
        authorization_id=UUID("50000000-0000-4000-8000-000000000011"),
    )
    rerun = await application.execute(authorized_repair)
    assert rerun.status is WebExecutionServiceStatus.RECORDED
    assert rerun.attempt is not None
    assert rerun.attempt.attempt_number == 2
    assert rerun.attempt.previous_attempt_id == initial.attempt.id
    assert rerun.attempt.source_revision == repaired_revision.reference
    assert rerun.attempt.report.status is WebExecutionReportStatus.PASSED
    browser_result = next(
        result
        for result in rerun.attempt.report.phase_results
        if result.phase is WebExecutionPhase.BROWSER_EVIDENCE
    )
    assert browser_result.status is WebPhaseResultStatus.PASSED
    assert browser_result.artifact_refs[0].media_type == "image/png"
    assert browser_result.findings[0].source_tool == "axe-core"

    revision_history = await revisions.history(project_id=PROJECT_ID)
    attempt_history = await attempts.history(project_id=PROJECT_ID)
    assert revision_history == (base_revision, repaired_revision)
    assert attempt_history == (initial.attempt, rerun.attempt)
    assert repaired_revision.based_on == base_revision.reference
    assert repaired_revision.related_failure_signature == signature.digest
    assert WebExecutionPhase.VALIDATE in applied.required_rerun_phases
    assert WebExecutionPhase.SETUP not in applied.required_rerun_phases


def test_governed_web_generation_repair_and_rerun_journey(tmp_path: Path) -> None:
    """Verify the complete deterministic Sprint 08 acceptance path."""
    asyncio.run(governed_journey(tmp_path))
