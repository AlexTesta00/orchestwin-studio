"""Sprint 09 acceptance journeys for governed JVM failure, repair, and rerun."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from orchestwin.artifacts.jvm_change_sets import (
    JvmSourceChange,
    JvmSourceChangeOperation,
    create_jvm_source_change_set,
)
from orchestwin.artifacts.jvm_source_persistence import (
    InMemoryJvmSourceRevisionRepository,
    JvmSourceRevisionAppendStatus,
)
from orchestwin.artifacts.jvm_source_plans import (
    FileSystemJvmSourceContentStore,
    JvmSourceMaterializationStatus,
    JvmSourcePlanFile,
    create_jvm_source_plan,
    materialize_jvm_source_plan,
)
from orchestwin.artifacts.jvm_sources import (
    JvmSourceProvenanceKind,
    JvmSourceProvenanceReference,
    JvmSourceRevision,
)
from orchestwin.jvm_execution.attempt_persistence import (
    InMemoryJvmExecutionAttemptRepository,
    jvm_execution_attempt_from_record,
    jvm_execution_attempt_to_record,
)
from orchestwin.jvm_execution.attempts import JvmExecutionAttemptTrigger
from orchestwin.jvm_execution.detection import JvmDetectionSnapshot, JvmTextFile
from orchestwin.jvm_execution.evidence import (
    JvmEvidenceReference,
    JvmExecutionReportStatus,
    JvmFailureCategory,
    JvmNormalizedFinding,
    JvmPhaseResult,
    JvmPhaseResultStatus,
)
from orchestwin.jvm_execution.gradle_runner import create_gradle_jvm_runner_contract
from orchestwin.jvm_execution.plans import JvmExecutionPhase, JvmPhasePlan
from orchestwin.jvm_execution.policy import (
    JvmRepository,
    JvmToolchainDeclaration,
    policy_for,
)
from orchestwin.jvm_execution.profile_contracts import JvmProfileContract
from orchestwin.jvm_execution.profile_registry import create_sprint09_jvm_profile_registry
from orchestwin.jvm_execution.targets import selection_for
from orchestwin.sandbox.container_runtime import ContainerImageReference
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.workflow.jvm_execution import (
    JvmExecutionAuthorization,
    JvmExecutionAuthorizationKind,
    JvmExecutionPurpose,
    JvmExecutionRequest,
    JvmExecutionServiceStatus,
    LocalGovernedJvmExecutionService,
)
from orchestwin.workflow.jvm_repair import (
    JvmRepairApplicationStatus,
    JvmRepairPolicy,
    JvmRepairProposal,
    apply_jvm_repair_revision,
)

PROJECT_ID = UUID("92000000-0000-4000-8000-000000000001")
OWNER_ID = UUID("92000000-0000-4000-8000-000000000002")
SOURCE_PLAN_ID = UUID("92000000-0000-4000-8000-000000000003")
SOURCE_REVISION_ID = UUID("92000000-0000-4000-8000-000000000004")
CHANGE_SET_ID = UUID("92000000-0000-4000-8000-000000000005")
REPAIR_PROPOSAL_ID = UUID("92000000-0000-4000-8000-000000000006")
REPAIRED_REVISION_ID = UUID("92000000-0000-4000-8000-000000000007")
BASE_TIME = datetime(2026, 8, 28, 20, 0, tzinfo=UTC)
RUNNER = create_gradle_jvm_runner_contract(
    ContainerImageReference("orchestwin/jvm-gradle-runner@sha256:" + "d" * 64)
)


class SequenceClock:
    """Deterministic application clock for ordered execution attempts."""

    def __init__(self) -> None:
        self._calls = 0

    def now(self) -> datetime:
        value = BASE_TIME + timedelta(seconds=self._calls)
        self._calls += 1
        return value


class SequenceIds:
    """Deterministic UUID source for persisted execution attempts."""

    def __init__(self) -> None:
        self._next = 100

    def new_id(self) -> UUID:
        value = UUID(f"92000000-0000-4000-8000-{self._next:012d}")
        self._next += 1
        return value


class RepairJourneyPhaseExecutor:
    """Fail the first Kotlin test phase, then return deterministic evidence."""

    def __init__(self) -> None:
        self._test_failures_remaining = 1
        self.calls: list[JvmExecutionPhase] = []

    async def execute(
        self,
        phase_plan: JvmPhasePlan,
        *,
        contract: JvmProfileContract,
    ) -> JvmPhaseResult:
        del contract
        phase = phase_plan.phase
        self.calls.append(phase)
        observed_at = BASE_TIME + timedelta(seconds=len(self.calls))
        if phase is JvmExecutionPhase.TEST and self._test_failures_remaining:
            self._test_failures_remaining -= 1
            return JvmPhaseResult(
                phase=phase,
                status=JvmPhaseResultStatus.FAILED,
                command_plan_hash=phase_plan.command_plan.content_hash,
                started_at=observed_at,
                completed_at=observed_at + timedelta(seconds=1),
                exit_codes=(1,),
                stdout_refs=(),
                stderr_refs=(
                    evidence_reference(
                        storage_key="sha256/11/" + "1" * 64,
                        digest="1" * 64,
                        media_type="text/plain",
                    ),
                ),
                artifact_refs=(),
                findings=(
                    JvmNormalizedFinding(
                        code="KOTLIN_UNRESOLVED_REFERENCE",
                        message="The calculator references missingOperand.",
                        source_tool="gradle-kotlin-test",
                        location="src/main/kotlin/example/Calculator.kt",
                    ),
                ),
                failure_category=JvmFailureCategory.TEST,
                failure_code="KOTLIN_UNRESOLVED_REFERENCE",
                normalized_summary=(
                    "Kotlin test compilation failed: unresolved reference missingOperand."
                ),
            )

        artifacts: tuple[JvmEvidenceReference, ...] = ()
        findings: tuple[JvmNormalizedFinding, ...] = ()
        if phase in {JvmExecutionPhase.BUILD, JvmExecutionPhase.COLLECT_ARTIFACTS}:
            artifacts = (
                evidence_reference(
                    storage_key="sha256/22/" + "2" * 64,
                    digest="2" * 64,
                    media_type="application/java-archive",
                ),
            )
        if phase is JvmExecutionPhase.TEST:
            findings = (
                JvmNormalizedFinding(
                    code="JUNIT_ALL_PASSED",
                    message="All deterministic Kotlin/JVM tests passed.",
                    source_tool="junit-platform",
                    location="build/test-results/test",
                ),
            )
        return JvmPhaseResult(
            phase=phase,
            status=JvmPhaseResultStatus.PASSED,
            command_plan_hash=phase_plan.command_plan.content_hash,
            started_at=observed_at,
            completed_at=observed_at + timedelta(seconds=1),
            exit_codes=(0,),
            stdout_refs=(),
            stderr_refs=(),
            artifact_refs=artifacts,
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
) -> JvmEvidenceReference:
    return JvmEvidenceReference(
        storage_key=storage_key,
        sha256_digest=digest,
        size_bytes=16,
        media_type=media_type,
    )


def source_provenance() -> JvmSourceProvenanceReference:
    return JvmSourceProvenanceReference(
        kind=JvmSourceProvenanceKind.SOURCE_PLAN,
        reference_id="source-plan:sprint-09-journey",
        version_number=1,
        content_hash="a" * 64,
    )


def source_plan_files() -> tuple[JvmSourcePlanFile, ...]:
    return (
        JvmSourcePlanFile(
            normalized_path="build.gradle.kts",
            content=(
                'plugins { application; kotlin("jvm") version "2.4.10" }\n'
                "repositories { mavenCentral() }\n"
                'application { mainClass.set("example.MainKt") }\n'
            ),
            media_type="text/x-gradle",
        ),
        JvmSourcePlanFile(
            normalized_path="gradle/wrapper/gradle-wrapper.properties",
            content=(
                "distributionUrl=https\\://services.gradle.org/distributions/gradle-9.5.0-bin.zip\n"
            ),
            media_type="text/plain",
        ),
        JvmSourcePlanFile(
            normalized_path="settings.gradle.kts",
            content='rootProject.name = "journey"\n',
            media_type="text/x-gradle",
        ),
        JvmSourcePlanFile(
            normalized_path="src/main/kotlin/example/Calculator.kt",
            content=(
                "package example\n\n"
                "object Calculator {\n"
                "    fun add(left: Int, right: Int): Int = left + missingOperand\n"
                "}\n"
            ),
            media_type="text/x-kotlin",
        ),
        JvmSourcePlanFile(
            normalized_path="src/main/kotlin/example/Main.kt",
            content=("package example\n\nfun main() = println(Calculator.add(2, 3))\n"),
            media_type="text/x-kotlin",
        ),
        JvmSourcePlanFile(
            normalized_path="src/test/kotlin/example/CalculatorTest.kt",
            content=(
                "package example\n\nclass CalculatorTest { /* deterministic contract fixture */ }\n"
            ),
            media_type="text/x-kotlin",
        ),
    )


def snapshot_for_revision(
    revision: JvmSourceRevision,
    *,
    content_store: FileSystemJvmSourceContentStore,
) -> JvmDetectionSnapshot:
    """Reconstruct deterministic detection input from immutable source metadata."""
    text_files: list[JvmTextFile] = []
    for file in revision.files:
        content = content_store.read(file.storage_key)
        assert content is not None
        try:
            decoded = content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        text_files.append(
            JvmTextFile(
                normalized_path=file.normalized_path,
                content=decoded,
                sha256_digest=file.sha256_digest,
            )
        )
    inventory_projection = "\n".join(
        f"{file.normalized_path}:{file.sha256_digest}" for file in revision.files
    )
    return JvmDetectionSnapshot(
        inventory_content_hash=hashlib.sha256(inventory_projection.encode("utf-8")).hexdigest(),
        included_paths=tuple(file.normalized_path for file in revision.files),
        text_files=tuple(text_files),
    )


def toolchain_declaration() -> JvmToolchainDeclaration:
    policy = policy_for(ExecutionTarget.JVM_KOTLIN)
    return JvmToolchainDeclaration(
        selection=policy.selection,
        jdk_major=policy.selection.jdk_major,
        build_tool_version=policy.build_tool_version,
        language_version=policy.language_version,
        launcher_files_present=True,
        launcher_integrity_verified=True,
        dependency_verification_enabled=policy.require_dependency_verification,
        repositories=(JvmRepository.MAVEN_CENTRAL,),
        plugins=policy.allowed_plugins,
        network_disabled_after_setup=True,
    )


def execution_request(
    revision: JvmSourceRevision,
    *,
    snapshot: JvmDetectionSnapshot,
    trigger: JvmExecutionAttemptTrigger,
    rerun_phases: tuple[JvmExecutionPhase, ...] | None,
) -> JvmExecutionRequest:
    return JvmExecutionRequest(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        source_revision=revision.reference,
        snapshot=snapshot,
        declaration=toolchain_declaration(),
        profile_id="jvm.kotlin-gradle",
        profile_version="1.0.0",
        runner=RUNNER,
        policy_content_hash=RUNNER.execution_policy.content_hash,
        purpose=JvmExecutionPurpose.PROFILE_VALIDATION,
        trigger=trigger,
        authorization=None,
        rerun_phases=rerun_phases,
    )


def authorize(
    request: JvmExecutionRequest,
    *,
    authorization_id: UUID,
) -> JvmExecutionRequest:
    registry = create_sprint09_jvm_profile_registry()
    profile = registry.find(request.profile_id, request.profile_version)
    assert profile is not None
    contract = profile.create_contract(
        request.snapshot,
        request.declaration,
        source_revision=request.source_revision,
        runner=request.runner,
    )
    return replace(
        request,
        authorization=JvmExecutionAuthorization(
            authorization_id=authorization_id,
            kind=JvmExecutionAuthorizationKind.PROFILE_VALIDATION,
            project_id=request.project_id,
            source_revision_content_hash=request.source_revision.content_hash,
            profile_validation_content_hash=contract.validation.content_hash,
            execution_plan_content_hash=contract.execution_plan.content_hash,
            runner_image_digest=contract.runner.image.digest,
            policy_content_hash=request.policy_content_hash,
            authorized_by_user_id=request.owner_user_id,
        ),
    )


async def governed_repair_journey(tmp_path: Path) -> None:
    """Run source materialization, failure, repair, authorization, and rerun."""
    content_store = FileSystemJvmSourceContentStore(tmp_path / "objects")
    source_plan = create_jvm_source_plan(
        plan_id=SOURCE_PLAN_ID,
        project_id=PROJECT_ID,
        created_by_user_id=OWNER_ID,
        target_selection=selection_for(ExecutionTarget.JVM_KOTLIN),
        files=source_plan_files(),
        rationale="Materialize the approved deterministic Sprint 09 Kotlin journey fixture.",
        provenance_references=(source_provenance(),),
        created_at=BASE_TIME,
    )
    materialized = materialize_jvm_source_plan(
        source_plan,
        revision_id=SOURCE_REVISION_ID,
        workspace_path=(tmp_path / "workspace").resolve(),
        content_store=content_store,
        created_at=BASE_TIME,
    )
    assert materialized.status is JvmSourceMaterializationStatus.MATERIALIZED
    assert materialized.revision is not None
    base_revision = materialized.revision

    revisions = InMemoryJvmSourceRevisionRepository(
        owner_user_id=OWNER_ID,
        project_ids=frozenset({PROJECT_ID}),
    )
    attempts = InMemoryJvmExecutionAttemptRepository(
        owner_user_id=OWNER_ID,
        project_ids=frozenset({PROJECT_ID}),
    )
    assert (await revisions.append(base_revision)).status is (
        JvmSourceRevisionAppendStatus.APPENDED
    )
    executor = RepairJourneyPhaseExecutor()
    service = LocalGovernedJvmExecutionService(
        registry=create_sprint09_jvm_profile_registry(),
        attempts=attempts,
        phase_executor=executor,
        clock=SequenceClock(),
        ids=SequenceIds(),
    )

    initial_snapshot = snapshot_for_revision(base_revision, content_store=content_store)
    initial_request = authorize(
        execution_request(
            base_revision,
            snapshot=initial_snapshot,
            trigger=JvmExecutionAttemptTrigger.PROFILE_VALIDATION,
            rerun_phases=None,
        ),
        authorization_id=UUID("92000000-0000-4000-8000-000000000010"),
    )
    initial = await service.execute(initial_request)
    assert initial.status is JvmExecutionServiceStatus.RECORDED
    assert initial.attempt is not None
    assert initial.attempt.report.status is JvmExecutionReportStatus.FAILED
    assert len(initial.attempt.report.failure_signatures) == 1
    failure_signature = initial.attempt.report.failure_signatures[0]

    corrected = (
        b"package example\n\n"
        b"object Calculator {\n"
        b"    fun add(left: Int, right: Int): Int = left + right\n"
        b"}\n"
    )
    stored = content_store.store(
        normalized_path="src/main/kotlin/example/Calculator.kt",
        content=corrected,
        media_type="text/x-kotlin",
    )
    repair = JvmRepairProposal(
        id=REPAIR_PROPOSAL_ID,
        project_id=PROJECT_ID,
        created_by_user_id=OWNER_ID,
        base_revision=base_revision.reference,
        failure_signature=failure_signature,
        change_set=create_jvm_source_change_set(
            change_set_id=CHANGE_SET_ID,
            project_id=PROJECT_ID,
            base_revision=base_revision.reference,
            changes=(
                JvmSourceChange(
                    normalized_path=stored.normalized_path,
                    operation=JvmSourceChangeOperation.REPLACE,
                    content_sha256=stored.sha256_digest,
                    size_bytes=stored.size_bytes,
                    storage_key=stored.storage_key,
                    media_type=stored.media_type,
                ),
            ),
            rationale="Replace the unresolved Kotlin operand identified by the test phase.",
            provenance_references=("failure-signature:kotlin-calculator",),
        ),
        attempt_number=1,
        identical_failure_occurrences=1,
        provenance_references=(
            JvmSourceProvenanceReference(
                kind=JvmSourceProvenanceKind.FAILURE_SIGNATURE,
                reference_id="failure-signature:kotlin-calculator",
                version_number=1,
                content_hash=failure_signature.signature,
            ),
        ),
        created_at=BASE_TIME + timedelta(minutes=1),
    )
    applied = apply_jvm_repair_revision(
        repair,
        base_revision=base_revision,
        revision_id=REPAIRED_REVISION_ID,
        created_by_user_id=OWNER_ID,
        created_at=BASE_TIME + timedelta(minutes=2),
        content_store=content_store,
    )
    assert applied.status is JvmRepairApplicationStatus.APPLIED
    assert applied.revision is not None
    repaired_revision = applied.revision
    assert (await revisions.append(repaired_revision)).status is (
        JvmSourceRevisionAppendStatus.APPENDED
    )

    repaired_snapshot = snapshot_for_revision(repaired_revision, content_store=content_store)
    repair_request = execution_request(
        repaired_revision,
        snapshot=repaired_snapshot,
        trigger=JvmExecutionAttemptTrigger.REPAIR_RERUN,
        rerun_phases=applied.required_rerun_phases,
    )
    stale = await service.execute(
        replace(repair_request, authorization=initial_request.authorization)
    )
    assert stale.status is JvmExecutionServiceStatus.AUTHORIZATION_MISMATCH

    authorized_repair = authorize(
        repair_request,
        authorization_id=UUID("92000000-0000-4000-8000-000000000011"),
    )
    rerun = await service.execute(authorized_repair)
    assert rerun.status is JvmExecutionServiceStatus.RECORDED
    assert rerun.attempt is not None
    assert rerun.attempt.attempt_number == 2
    assert rerun.attempt.previous_attempt_id == initial.attempt.id
    assert rerun.attempt.source_revision == repaired_revision.reference
    assert rerun.attempt.report.status is JvmExecutionReportStatus.PASSED

    test_result = next(
        result
        for result in rerun.attempt.report.phase_results
        if result.phase is JvmExecutionPhase.TEST
    )
    artifact_result = next(
        result
        for result in rerun.attempt.report.phase_results
        if result.phase is JvmExecutionPhase.COLLECT_ARTIFACTS
    )
    assert test_result.findings[0].source_tool == "junit-platform"
    assert artifact_result.artifact_refs[0].media_type == "application/java-archive"

    persisted_record = jvm_execution_attempt_to_record(rerun.attempt)
    assert jvm_execution_attempt_from_record(persisted_record) == rerun.attempt
    assert persisted_record["attempt_number"] == 2
    assert persisted_record["previous_attempt_id"] == initial.attempt.id

    revision_history = await revisions.history(project_id=PROJECT_ID)
    attempt_history = await attempts.history(project_id=PROJECT_ID)
    assert revision_history == (base_revision, repaired_revision)
    assert attempt_history == (initial.attempt, rerun.attempt)
    assert repaired_revision.based_on == base_revision.reference
    assert repaired_revision.related_failure_signature == failure_signature.signature
    assert JvmExecutionPhase.VALIDATE in applied.required_rerun_phases
    assert JvmExecutionPhase.SETUP not in applied.required_rerun_phases
    assert executor.calls.count(JvmExecutionPhase.SETUP) == 1


def test_governed_jvm_generation_repair_and_persisted_rerun_journey(
    tmp_path: Path,
) -> None:
    """Verify the complete deterministic Sprint 09 Kotlin acceptance path."""
    asyncio.run(governed_repair_journey(tmp_path))


def test_repeated_jvm_failure_signature_pauses_before_revision(tmp_path: Path) -> None:
    """Verify the bounded loop pauses rather than creating an extra revision."""
    content_store = FileSystemJvmSourceContentStore(tmp_path / "objects")
    plan = create_jvm_source_plan(
        plan_id=SOURCE_PLAN_ID,
        project_id=PROJECT_ID,
        created_by_user_id=OWNER_ID,
        target_selection=selection_for(ExecutionTarget.JVM_KOTLIN),
        files=source_plan_files(),
        rationale="Materialize the deterministic repeated-failure fixture.",
        provenance_references=(source_provenance(),),
        created_at=BASE_TIME,
    )
    materialized = materialize_jvm_source_plan(
        plan,
        revision_id=SOURCE_REVISION_ID,
        workspace_path=(tmp_path / "workspace").resolve(),
        content_store=content_store,
        created_at=BASE_TIME,
    )
    assert materialized.revision is not None
    base = materialized.revision
    bundle_snapshot = snapshot_for_revision(base, content_store=content_store)
    request = execution_request(
        base,
        snapshot=bundle_snapshot,
        trigger=JvmExecutionAttemptTrigger.PROFILE_VALIDATION,
        rerun_phases=None,
    )
    profile = create_sprint09_jvm_profile_registry().find(
        request.profile_id,
        request.profile_version,
    )
    assert profile is not None
    contract = profile.create_contract(
        request.snapshot,
        request.declaration,
        source_revision=request.source_revision,
        runner=request.runner,
    )
    failed_phase = JvmPhaseResult(
        phase=JvmExecutionPhase.TEST,
        status=JvmPhaseResultStatus.FAILED,
        command_plan_hash=contract.execution_plan.phase(
            JvmExecutionPhase.TEST
        ).command_plan.content_hash,
        started_at=BASE_TIME,
        completed_at=BASE_TIME + timedelta(seconds=1),
        exit_codes=(1,),
        stdout_refs=(),
        stderr_refs=(
            evidence_reference(
                storage_key="sha256/33/" + "3" * 64,
                digest="3" * 64,
                media_type="text/plain",
            ),
        ),
        artifact_refs=(),
        findings=(),
        failure_category=JvmFailureCategory.TEST,
        failure_code="KOTLIN_UNRESOLVED_REFERENCE",
        normalized_summary="Kotlin unresolved reference missingOperand.",
    )
    from orchestwin.jvm_execution.evidence import failure_signature_for

    signature = failure_signature_for(failed_phase)
    assert signature is not None
    corrected = content_store.store(
        normalized_path="src/main/kotlin/example/Calculator.kt",
        content=b"package example\nobject Calculator\n",
        media_type="text/x-kotlin",
    )
    proposal = JvmRepairProposal(
        id=REPAIR_PROPOSAL_ID,
        project_id=PROJECT_ID,
        created_by_user_id=OWNER_ID,
        base_revision=base.reference,
        failure_signature=signature,
        change_set=create_jvm_source_change_set(
            change_set_id=CHANGE_SET_ID,
            project_id=PROJECT_ID,
            base_revision=base.reference,
            changes=(
                JvmSourceChange(
                    normalized_path=corrected.normalized_path,
                    operation=JvmSourceChangeOperation.REPLACE,
                    content_sha256=corrected.sha256_digest,
                    size_bytes=corrected.size_bytes,
                    storage_key=corrected.storage_key,
                    media_type=corrected.media_type,
                ),
            ),
            rationale="Attempt a bounded repair after a repeated failure.",
            provenance_references=("failure-signature:repeated",),
        ),
        attempt_number=3,
        identical_failure_occurrences=3,
        provenance_references=(
            JvmSourceProvenanceReference(
                kind=JvmSourceProvenanceKind.FAILURE_SIGNATURE,
                reference_id="failure-signature:repeated",
                version_number=1,
                content_hash=signature.signature,
            ),
        ),
        created_at=BASE_TIME + timedelta(minutes=1),
    )

    paused = apply_jvm_repair_revision(
        proposal,
        base_revision=base,
        revision_id=REPAIRED_REVISION_ID,
        created_by_user_id=OWNER_ID,
        created_at=BASE_TIME + timedelta(minutes=2),
        content_store=content_store,
        policy=JvmRepairPolicy(
            maximum_attempts_per_failure_signature=5,
            maximum_identical_failure_occurrences=2,
        ),
    )

    assert paused.status is JvmRepairApplicationStatus.PAUSED_NEEDS_HUMAN
    assert paused.revision is None
    assert paused.required_rerun_phases == ()
    assert "human review" in (paused.failure_message or "").casefold()
