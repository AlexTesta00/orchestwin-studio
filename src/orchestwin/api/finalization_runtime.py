from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.agents.persistence.repositories import SqlAlchemyTeamProposalVersionRepository
from orchestwin.api.artifacts import ArtifactGraphQueryService, CrossStageArtifactGraphPayload
from orchestwin.api.finalization import (
    CreateFinalExportCommand,
    DecideFinalApprovalCommand,
    FinalExportDownload,
    FinalizationApiCommandResult,
    FinalizationApiStatus,
    SubmitFinalReviewCommand,
)
from orchestwin.api.synthetic_evaluation import evaluation_run_payload, synthetic_finding_payload
from orchestwin.artifacts.architecture_persistence import SqlAlchemyArchitecturePackageRepository
from orchestwin.artifacts.design_persistence import SqlAlchemyDesignPackageRepository
from orchestwin.artifacts.export_archive import (
    BuiltFinalExportArchive,
    assemble_final_export_archive,
    complete_workflow_after_export,
)
from orchestwin.artifacts.export_manifest import (
    ExportArtifactCategory,
    FinalExportEntry,
    FinalExportOmission,
    create_final_export_manifest,
)
from orchestwin.artifacts.export_persistence import (
    ExportBundlePersistenceConflict,
    SqlAlchemyExportBundleRepository,
    StoredExportBundle,
)
from orchestwin.artifacts.web_source_persistence import SqlAlchemyWebSourceRevisionRepository
from orchestwin.artifacts.workspace_files import read_regular_file
from orchestwin.evaluation.aggregation import aggregate_synthetic_evaluation
from orchestwin.evaluation.persistence import SqlAlchemySyntheticEvaluationRepository
from orchestwin.evaluation.run_restore import synthetic_evaluation_run_from_snapshot
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.persistence.briefs import SqlAlchemyProjectBriefRepository
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.projects.requirements_persistence import (
    SqlAlchemyRequirementsSpecificationRepository,
)
from orchestwin.projects.requirements_primitives import canonical_json
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionProfileReference,
)
from orchestwin.twins.persistence.repositories import SqlAlchemyUserModelingSnapshotRepository
from orchestwin.web_execution.attempt_persistence import SqlAlchemyWebExecutionAttemptRepository
from orchestwin.web_execution.reports import WebExecutionReportStatus
from orchestwin.workflow.checkpoints import create_workflow_checkpoint
from orchestwin.workflow.final_approval import (
    FinalApprovalError,
    FinalApprovalIssueCode,
    decide_final_output_gate,
    enter_final_approval_stage,
    resume_after_final_output_approval,
    submit_final_review_for_approval,
)
from orchestwin.workflow.final_review import (
    AcceptedFinalLimitation,
    FinalReviewAssessment,
    FinalReviewCheck,
    FinalReviewCheckKind,
    FinalReviewCheckStatus,
    create_final_review_assessment,
)
from orchestwin.workflow.final_review_persistence import SqlAlchemyFinalReviewRepository
from orchestwin.workflow.gates import (
    HumanGate,
    HumanGateAction,
    HumanGateEventKind,
    HumanGateStatus,
    HumanGateTransitionStatus,
    HumanGateType,
)
from orchestwin.workflow.persistence.repositories import SqlAlchemyHumanGateRepository
from orchestwin.workflow.routing import (
    WorkflowTransitionStatus,
    advance_workflow_run,
    resume_after_human_gate,
    start_workflow_run,
)
from orchestwin.workflow.run_persistence import (
    SqlAlchemyWorkflowRunRepository,
    WorkflowRunStoreStatus,
)
from orchestwin.workflow.runs import (
    WorkflowArtifactReference,
    WorkflowCapabilityState,
    WorkflowRun,
    WorkflowStage,
    create_workflow_run,
)

FINALIZATION_RUN_NAMESPACE = UUID("6f1d3c4a-8e2b-4f7a-9c1d-2b5e7a9c4d10")
LIMITATION_ID = "LIMIT-SYNTHETIC-FEEDBACK"
LIMITATION_SUMMARY = (
    "User Twin opinions and every model proposal are hypotheses; owner approval is not"
    " empirical validation with real users."
)
LIMITATION_RATIONALE = (
    "No empirical user validation was recorded in this project; the sandbox observed only"
    " automated tests, browser checks and accessibility audits."
)
STAGE_GATE_TYPES = (
    HumanGateType.PROJECT_BRIEF,
    HumanGateType.AGENT_TEAM,
    HumanGateType.USER_MODELING,
    HumanGateType.REQUIREMENTS,
    HumanGateType.DESIGN,
    HumanGateType.ARCHITECTURE,
    HumanGateType.FINAL_OUTPUT,
)
TEST_SUFFIXES = (".test.js", ".test.cjs", ".test.mjs")
JSON_MEDIA_TYPE = "application/json"


@dataclass(frozen=True, slots=True)
class _ProjectState:
    project: ProjectRecord
    brief: Any
    team: Any
    twins: Any
    requirements: Any
    design: Any
    architecture: Any
    source: Any
    attempt: Any
    evaluation: Any = None

    @property
    def execution_passed(self) -> bool:
        return (
            self.attempt is not None
            and self.attempt.report.status is WebExecutionReportStatus.PASSED
        )

    @property
    def findings_count(self) -> int:
        if self.attempt is None:
            return 0
        return sum(len(phase.findings) for phase in self.attempt.report.phase_results)


def _now() -> datetime:
    return datetime.now(UTC)


def _later(*moments: datetime | None) -> datetime:
    return max(moment for moment in (_now(), *moments) if moment is not None)


def _json_bytes(value: object) -> bytes:
    return canonical_json(_plain(value)).encode("utf-8")


def _plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _plain(asdict(value))
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_plain(item) for item in value), key=str)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (UUID, datetime)):
        return str(value) if isinstance(value, UUID) else value.isoformat()
    return value


def _content_hash(version: Any, data: bytes) -> str:
    digest = getattr(version, "content_hash", None)
    return digest if isinstance(digest, str) else hashlib.sha256(data).hexdigest()


def _result(
    status: FinalizationApiStatus, snapshot: dict | None, message: str
) -> FinalizationApiCommandResult:
    return FinalizationApiCommandResult(status, snapshot, message)


def _run_id(project_id: UUID) -> UUID:
    return uuid5(FINALIZATION_RUN_NAMESPACE, str(project_id))


def _approval_snapshot(gate: HumanGate, approval_event_id: UUID | None) -> dict[str, Any]:
    return {
        "gate_id": str(gate.id),
        "review_id": str(gate.artifact.artifact_id),
        "review_version": gate.artifact.version,
        "review_hash": gate.artifact.content_hash,
        "status": gate.status.value,
        "updated_at": gate.updated_at.isoformat(),
        "approval_event_id": None if approval_event_id is None else str(approval_event_id),
    }


def _check(
    kind: FinalReviewCheckKind,
    satisfied: bool | None,
    summary: str,
    evidence: tuple[str, ...] = (),
    *,
    blocking: bool = True,
) -> FinalReviewCheck:
    if satisfied is None:
        status = FinalReviewCheckStatus.NOT_APPLICABLE
    else:
        status = (
            FinalReviewCheckStatus.SATISFIED if satisfied else FinalReviewCheckStatus.NOT_SATISFIED
        )
    return FinalReviewCheck(
        check_id="FRC-" + kind.value,
        kind=kind,
        status=status,
        summary=summary,
        evidence_refs=tuple(sorted(set(evidence))),
        blocking=blocking and satisfied is not None,
    )


def _definition_of_done_present(requirements: Any) -> bool:
    if requirements is None:
        return False
    specification = requirements.to_snapshot().get("specification", {})
    return bool(specification.get("definition_of_done"))


def _checks(state: _ProjectState) -> tuple[FinalReviewCheck, ...]:
    attempt_ref = () if state.attempt is None else (f"execution:{state.attempt.id}",)
    profile_ref = (
        ()
        if state.attempt is None
        else (f"profile:{state.attempt.report.profile_id}@{state.attempt.report.profile_version}",)
    )
    checks = (
        _check(
            FinalReviewCheckKind.DEFINITION_OF_DONE,
            _definition_of_done_present(state.requirements),
            "The approved requirements declare a definition of done.",
            () if state.requirements is None else (f"requirements:{state.requirements.id}",),
        ),
        _check(
            FinalReviewCheckKind.REQUIREMENTS,
            state.requirements is not None,
            "An approved requirements specification exists.",
            () if state.requirements is None else (f"requirements:{state.requirements.id}",),
        ),
        _check(
            FinalReviewCheckKind.TRACEABILITY,
            state.source is not None
            and state.architecture is not None
            and bool(state.source.provenance_references),
            "The generated sources declare their provenance up to the approved architecture.",
            () if state.source is None else (f"web_source:{state.source.id}",),
        ),
        _check(
            FinalReviewCheckKind.EXECUTION_EVIDENCE,
            state.execution_passed,
            "The latest sandbox execution passed every phase.",
            attempt_ref,
        ),
        _check(
            FinalReviewCheckKind.DETERMINISTIC_FINDINGS,
            state.execution_passed and state.findings_count == 0,
            "The latest sandbox execution reported no deterministic findings.",
            attempt_ref,
        ),
        _check(
            FinalReviewCheckKind.SYNTHETIC_EVALUATION,
            None if state.evaluation is None else True,
            "No synthetic evaluation run was executed for this project."
            if state.evaluation is None
            else (
                f"The User Twins evaluated the executed prototype: {state.evaluation.finding_count} "
                f"simulated findings from {state.evaluation.response_count} twins, recorded as hypotheses."
            ),
            () if state.evaluation is None else (f"evaluation-run:{state.evaluation.id}",),
            blocking=False,
        ),
        _check(
            FinalReviewCheckKind.CAPABILITY,
            state.attempt is not None,
            "The execution profile that produced the evidence is recorded.",
            profile_ref,
        ),
        _check(
            FinalReviewCheckKind.HUMAN_VALIDATION,
            None,
            "No empirical validation with real users was recorded.",
            blocking=False,
        ),
        FinalReviewCheck(
            check_id="FRC-" + FinalReviewCheckKind.LIMITATIONS.value,
            kind=FinalReviewCheckKind.LIMITATIONS,
            status=FinalReviewCheckStatus.ACCEPTED_LIMITATION,
            summary="Synthetic feedback remains a hypothesis and is declared as a limitation.",
            evidence_refs=(f"limitation:{LIMITATION_ID}",),
            blocking=False,
        ),
        _check(
            FinalReviewCheckKind.EXPORT_READINESS,
            all(
                item is not None
                for item in (
                    state.brief,
                    state.requirements,
                    state.design,
                    state.architecture,
                    state.source,
                )
            ),
            "Brief, requirements, design, architecture and sources are available for export.",
        ),
    )
    return tuple(sorted(checks, key=lambda item: item.sort_key))


def _limitations() -> tuple[AcceptedFinalLimitation, ...]:
    return (AcceptedFinalLimitation(LIMITATION_ID, LIMITATION_SUMMARY, LIMITATION_RATIONALE),)


def _references(state: _ProjectState) -> tuple[WorkflowArtifactReference, ...]:
    references = []
    for artifact_type, version in (
        ("project_brief", state.brief),
        ("team_proposal", state.team),
        ("user_modeling", state.twins),
        ("requirements", state.requirements),
        ("design", state.design),
        ("architecture", state.architecture),
        ("web_source", state.source),
    ):
        if version is None:
            continue
        references.append(
            WorkflowArtifactReference(
                artifact_type=artifact_type,
                artifact_id=version.id,
                version_number=version.version_number,
                content_hash=_content_hash(version, _json_bytes(_snapshot(version))),
            )
        )
    return tuple(sorted(references, key=lambda item: item.sort_key))


def _snapshot(version: Any) -> dict[str, Any]:
    if hasattr(version, "to_snapshot"):
        return version.to_snapshot()
    return _plain(version)


def _capability(state: _ProjectState) -> WorkflowCapabilityState:
    if state.attempt is None:
        return WorkflowCapabilityState()
    report = state.attempt.report
    return WorkflowCapabilityState(
        selected_profile=ExecutionProfileReference(
            profile_id=report.profile_id,
            profile_version=report.profile_version,
            content_hash=state.attempt.profile_validation_content_hash,
        ),
        capability_status=ExecutionCapabilityStatus.VALIDATED_LEVEL_D,
    )


def _semantic_key(review: FinalReviewAssessment) -> tuple:
    return (
        tuple(check.to_snapshot().items() for check in review.checks),
        tuple(item.to_snapshot().items() for item in review.artifact_references),
        review.latest_execution_attempt_id,
        review.capability_status,
    )


class SqlAlchemyFinalizationApiService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        content_root: Path,
        export_root: Path,
        artifact_graph_query_service: ArtifactGraphQueryService | None = None,
    ) -> None:
        self._sessions = session_factory
        self._content_root = Path(content_root)
        self._export_root = Path(export_root)
        self._graphs = artifact_graph_query_service

    async def evaluation_run(self, *, owner_user_id: UUID, evaluation_run_id: UUID):
        async with self._sessions() as session:
            stored = await SqlAlchemySyntheticEvaluationRepository(
                session, owner_user_id=owner_user_id
            ).get_owned(run_id=evaluation_run_id)
        return None if stored is None else evaluation_run_payload(stored)

    async def evaluation_findings(self, *, owner_user_id: UUID, evaluation_run_id: UUID):
        async with self._sessions() as session:
            repository = SqlAlchemySyntheticEvaluationRepository(
                session, owner_user_id=owner_user_id
            )
            if await repository.get_owned(run_id=evaluation_run_id) is None:
                return None
            findings = await repository.list_findings(run_id=evaluation_run_id)
        return tuple(synthetic_finding_payload(item) for item in findings)

    async def evaluation_aggregation(self, *, owner_user_id: UUID, evaluation_run_id: UUID):
        async with self._sessions() as session:
            snapshot = await SqlAlchemySyntheticEvaluationRepository(
                session, owner_user_id=owner_user_id
            ).get_owned_snapshot(run_id=evaluation_run_id)
        if snapshot is None:
            return None
        run = synthetic_evaluation_run_from_snapshot(snapshot)
        return aggregate_synthetic_evaluation(run).to_snapshot()

    async def workflow_run_for(self, *, owner_user_id: UUID, project_id: UUID):
        async with self._sessions() as session, session.begin():
            state = await self._state(session, owner_user_id=owner_user_id, project_id=project_id)
            if state is None:
                return None
            return await self._run(session, state, owner_user_id=owner_user_id)

    async def final_reviews(self, *, owner_user_id: UUID, project_id: UUID):
        async with self._sessions() as session, session.begin():
            state = await self._state(session, owner_user_id=owner_user_id, project_id=project_id)
            if state is None:
                return ()
            run = await self._run(session, state, owner_user_id=owner_user_id)
            if run is None:
                return ()
            reviews = SqlAlchemyFinalReviewRepository(session)
            existing = list(
                await reviews.list_for_run_owned(
                    workflow_run_id=run.id, owner_user_id=owner_user_id
                )
            )
            existing.sort(key=lambda item: item.version_number)
            previous = existing[-1] if existing else None
            candidate = create_final_review_assessment(
                run,
                checks=_checks(state),
                accepted_limitations=_limitations(),
                previous_review=previous,
                created_at=_later(
                    run.updated_at, None if previous is None else previous.created_at
                ),
            )
            if previous is None or _semantic_key(previous) != _semantic_key(candidate):
                await reviews.append(candidate)
                existing.append(candidate)
            return tuple(review.to_snapshot() for review in existing)

    async def submit_final_review(self, *, owner_user_id: UUID, command: SubmitFinalReviewCommand):
        async with self._sessions() as session, session.begin():
            reviews = SqlAlchemyFinalReviewRepository(session)
            review = await reviews.get_owned(
                review_id=command.review_id, owner_user_id=owner_user_id
            )
            if review is None:
                return _result(FinalizationApiStatus.NOT_FOUND, None, "Final review not found.")
            if (
                review.version_number != command.expected_version
                or review.content_hash != command.expected_content_hash
            ):
                return _result(
                    FinalizationApiStatus.STALE_REVIEW,
                    review.to_snapshot(),
                    "The final review changed since it was read.",
                )
            gates = SqlAlchemyHumanGateRepository(session)
            current = await gates.get_latest_owned_for_update(
                project_id=review.project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.FINAL_OUTPUT,
            )
            if (
                current is not None
                and current.artifact.artifact_id == review.id
                and current.status in {HumanGateStatus.PENDING_APPROVAL, HumanGateStatus.APPROVED}
            ):
                return _result(
                    FinalizationApiStatus.ALREADY_PRESENT,
                    _approval_snapshot(current, None),
                    "The final review was already submitted.",
                )
            runs = SqlAlchemyWorkflowRunRepository(session, owner_user_id=owner_user_id)
            run = await runs.get_owned(run_id=review.workflow_run_id)
            if run is None:
                return _result(FinalizationApiStatus.NOT_FOUND, None, "Finalization run not found.")
            occurred_at = _later(run.updated_at, review.created_at)
            try:
                submitted = submit_final_review_for_approval(
                    review,
                    gate_id=command.gate_id,
                    event_id=command.event_id,
                    occurred_at=occurred_at,
                )
                waiting = enter_final_approval_stage(
                    run, gate=submitted.gate, occurred_at=occurred_at
                )
            except FinalApprovalError as error:
                status = (
                    FinalizationApiStatus.REVIEW_NOT_READY
                    if error.code is FinalApprovalIssueCode.REVIEW_NOT_READY
                    else FinalizationApiStatus.ILLEGAL_STATE
                )
                return _result(status, review.to_snapshot(), str(error))
            await gates.add_with_event(gate=submitted.gate, event=submitted.transition.event)
            if await self._checkpoint(runs, run, waiting, occurred_at) is None:
                return _result(
                    FinalizationApiStatus.STATE_CONFLICT,
                    _approval_snapshot(submitted.gate, None),
                    "Finalization run changed concurrently.",
                )
            return _result(
                FinalizationApiStatus.APPLIED,
                _approval_snapshot(submitted.gate, None),
                "Final review submitted for owner approval.",
            )

    async def decide_final_approval(
        self, *, owner_user_id: UUID, command: DecideFinalApprovalCommand
    ):
        async with self._sessions() as session, session.begin():
            reviews = SqlAlchemyFinalReviewRepository(session)
            review = await reviews.get_owned(
                review_id=command.expected_review_id, owner_user_id=owner_user_id
            )
            if review is None:
                return _result(FinalizationApiStatus.NOT_FOUND, None, "Final review not found.")
            if (
                review.version_number != command.expected_review_version
                or review.content_hash != command.expected_review_hash
            ):
                return _result(
                    FinalizationApiStatus.STALE_REVIEW,
                    review.to_snapshot(),
                    "The final review changed since it was read.",
                )
            gates = SqlAlchemyHumanGateRepository(session)
            gate = await gates.get_latest_owned_for_update(
                project_id=review.project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.FINAL_OUTPUT,
            )
            if gate is None or gate.id != command.gate_id:
                return _result(
                    FinalizationApiStatus.NOT_FOUND, None, "Final approval gate not found."
                )
            runs = SqlAlchemyWorkflowRunRepository(session, owner_user_id=owner_user_id)
            run = await runs.get_owned(run_id=review.workflow_run_id)
            if run is None:
                return _result(FinalizationApiStatus.NOT_FOUND, None, "Finalization run not found.")
            occurred_at = _later(run.updated_at, gate.updated_at)
            try:
                transition = decide_final_output_gate(
                    gate,
                    current_review=review,
                    action=command.action,
                    actor_user_id=owner_user_id,
                    occurred_at=occurred_at,
                    reason=command.reason,
                    event_id=command.event_id,
                )
            except FinalApprovalError as error:
                return _result(
                    FinalizationApiStatus.ILLEGAL_STATE, _approval_snapshot(gate, None), str(error)
                )
            if transition.status is HumanGateTransitionStatus.NO_CHANGE:
                return _result(
                    FinalizationApiStatus.ALREADY_PRESENT,
                    _approval_snapshot(gate, None),
                    "The final approval gate is already in the requested state.",
                )
            if (
                transition.status is not HumanGateTransitionStatus.APPLIED
                or transition.event is None
            ):
                return _result(
                    FinalizationApiStatus.ILLEGAL_STATE,
                    _approval_snapshot(gate, None),
                    "The requested decision is not allowed in the current gate state.",
                )
            updated = await gates.save_transition(
                previous_gate=gate, updated_gate=transition.gate, event=transition.event
            )
            if command.action is HumanGateAction.APPROVE:
                try:
                    resume_after_final_output_approval(run, gate=updated, occurred_at=occurred_at)
                except FinalApprovalError as error:
                    return _result(
                        FinalizationApiStatus.ILLEGAL_STATE,
                        _approval_snapshot(updated, None),
                        str(error),
                    )
                resumed = resume_after_human_gate(run, occurred_at=occurred_at)
                persisted = (
                    None
                    if resumed.status is not WorkflowTransitionStatus.APPLIED
                    else await self._checkpoint(runs, run, resumed.run, occurred_at)
                )
                if persisted is None:
                    return _result(
                        FinalizationApiStatus.STATE_CONFLICT,
                        _approval_snapshot(updated, None),
                        "Finalization run changed concurrently.",
                    )
                export = advance_workflow_run(
                    persisted, next_stage=WorkflowStage.EXPORT, occurred_at=occurred_at
                )
                if export.status is not WorkflowTransitionStatus.APPLIED or (
                    await self._checkpoint(runs, persisted, export.run, occurred_at) is None
                ):
                    return _result(
                        FinalizationApiStatus.STATE_CONFLICT,
                        _approval_snapshot(updated, None),
                        "Finalization run changed concurrently.",
                    )
            approval_event = (
                transition.event.id if updated.status is HumanGateStatus.APPROVED else None
            )
            return _result(
                FinalizationApiStatus.APPLIED,
                _approval_snapshot(updated, approval_event),
                "Final approval decision applied.",
            )

    async def create_export(
        self, *, owner_user_id: UUID, project_id: UUID, command: CreateFinalExportCommand
    ):
        async with self._sessions() as session, session.begin():
            exports = SqlAlchemyExportBundleRepository(session)
            existing = await exports.get_owned(
                export_id=command.export_id, owner_user_id=owner_user_id
            )
            if existing is not None:
                return _result(
                    FinalizationApiStatus.ALREADY_PRESENT,
                    existing.to_snapshot(),
                    "Final export already exists.",
                )
            reviews = SqlAlchemyFinalReviewRepository(session)
            review = await reviews.get_owned(
                review_id=command.final_review_id, owner_user_id=owner_user_id
            )
            if review is None or review.project_id != project_id:
                return _result(FinalizationApiStatus.NOT_FOUND, None, "Final review not found.")
            if (
                review.version_number != command.expected_review_version
                or review.content_hash != command.expected_review_hash
            ):
                return _result(
                    FinalizationApiStatus.STALE_REVIEW,
                    review.to_snapshot(),
                    "The final review changed since it was read.",
                )
            gates = SqlAlchemyHumanGateRepository(session)
            gate = await gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.FINAL_OUTPUT,
            )
            if gate is None or gate.id != command.final_approval_gate_id:
                return _result(
                    FinalizationApiStatus.NOT_FOUND, None, "Final approval gate not found."
                )
            if gate.status is not HumanGateStatus.APPROVED:
                return _result(
                    FinalizationApiStatus.ILLEGAL_STATE,
                    _approval_snapshot(gate, None),
                    "The final approval gate is not approved.",
                )
            events = await gates.list_events_owned(
                project_id=project_id, owner_user_id=owner_user_id, gate_id=gate.id
            )
            approval = next(
                (
                    event
                    for event in events
                    if event.kind is HumanGateEventKind.APPROVE
                    and event.id == command.final_approval_event_id
                ),
                None,
            )
            if approval is None:
                return _result(
                    FinalizationApiStatus.ILLEGAL_STATE,
                    _approval_snapshot(gate, None),
                    "The approval event does not belong to the final approval gate.",
                )
            state = await self._state(session, owner_user_id=owner_user_id, project_id=project_id)
            if state is None:
                return _result(FinalizationApiStatus.NOT_FOUND, None, "Project not found.")
            runs = SqlAlchemyWorkflowRunRepository(session, owner_user_id=owner_user_id)
            run = await runs.get_owned(run_id=review.workflow_run_id)
            if run is None:
                return _result(FinalizationApiStatus.NOT_FOUND, None, "Finalization run not found.")
            occurred_at = _later(run.updated_at, gate.updated_at)
            try:
                entries, omissions, contents = await self._entries(
                    session,
                    owner_user_id=owner_user_id,
                    project_id=project_id,
                    state=state,
                    review=review,
                )
                manifest = create_final_export_manifest(
                    review,
                    approved_gate=gate,
                    approval_event_id=approval.id,
                    entries=entries,
                    omissions=omissions,
                    manifest_id=uuid4(),
                    created_at=occurred_at,
                )
                archive = assemble_final_export_archive(
                    manifest,
                    content_by_path=contents,
                    archive_id=command.export_id,
                    created_at=occurred_at,
                )
                completed = complete_workflow_after_export(
                    run, archive=archive, occurred_at=occurred_at
                )
            except (FinalApprovalError, ValueError, OSError) as error:
                return _result(
                    FinalizationApiStatus.ILLEGAL_STATE,
                    _approval_snapshot(gate, approval.id),
                    _message(error),
                )
            storage_ref = self._store(archive)
            stored = StoredExportBundle.from_archive(archive, storage_ref=storage_ref)
            try:
                await exports.append(stored)
            except ExportBundlePersistenceConflict:
                return _result(
                    FinalizationApiStatus.STATE_CONFLICT,
                    _approval_snapshot(gate, approval.id),
                    "Final export conflicts with an existing one.",
                )
            if await self._checkpoint(runs, run, completed, occurred_at) is None:
                return _result(
                    FinalizationApiStatus.STATE_CONFLICT,
                    _approval_snapshot(gate, approval.id),
                    "Finalization run changed concurrently.",
                )
            return _result(
                FinalizationApiStatus.CREATED,
                {**stored.to_snapshot(), "manifest": manifest.to_snapshot()},
                "Final export created.",
            )

    async def export(self, *, owner_user_id: UUID, export_id: UUID):
        async with self._sessions() as session:
            stored = await SqlAlchemyExportBundleRepository(session).get_owned(
                export_id=export_id, owner_user_id=owner_user_id
            )
            return None if stored is None else stored.to_snapshot()

    async def download_export(self, *, owner_user_id: UUID, export_id: UUID):
        async with self._sessions() as session:
            stored = await SqlAlchemyExportBundleRepository(session).get_owned(
                export_id=export_id, owner_user_id=owner_user_id
            )
        if stored is None:
            return None
        content = read_regular_file(
            self._export_root / stored.storage_ref, maximum_bytes=stored.archive_size_bytes
        )
        if hashlib.sha256(content).hexdigest() != stored.archive_hash:
            return None
        return FinalExportDownload(
            filename=f"orchestwin-export-{export_id}.zip",
            content=content,
            content_hash=stored.archive_hash,
        )

    async def _state(self, session, *, owner_user_id: UUID, project_id: UUID):
        project = await session.scalar(
            select(ProjectRecord).where(
                ProjectRecord.id == project_id,
                ProjectRecord.owner_user_id == owner_user_id,
                ProjectRecord.archived_at.is_(None),
            )
        )
        if project is None:
            return None
        briefs = await SqlAlchemyProjectBriefRepository(session).list_owned_versions(
            project_id=project_id, owner_user_id=owner_user_id
        )
        teams = await SqlAlchemyTeamProposalVersionRepository(session).list_owned_versions(
            project_id=project_id, owner_user_id=owner_user_id
        )
        return _ProjectState(
            project=project,
            brief=briefs[-1] if briefs else None,
            team=teams[-1] if teams else None,
            twins=await SqlAlchemyUserModelingSnapshotRepository(
                session, owner_user_id=owner_user_id
            ).current(project_id=project_id),
            requirements=await SqlAlchemyRequirementsSpecificationRepository(
                session, owner_user_id=owner_user_id
            ).current(project_id=project_id),
            design=await SqlAlchemyDesignPackageRepository(
                session, owner_user_id=owner_user_id
            ).current(project_id=project_id),
            architecture=await SqlAlchemyArchitecturePackageRepository(
                session, owner_user_id=owner_user_id
            ).current(project_id=project_id),
            source=await SqlAlchemyWebSourceRevisionRepository(
                session, owner_user_id=owner_user_id
            ).current(project_id=project_id),
            attempt=await SqlAlchemyWebExecutionAttemptRepository(
                session, owner_user_id=owner_user_id
            ).current(project_id=project_id),
            evaluation=await SqlAlchemySyntheticEvaluationRepository(
                session, owner_user_id=owner_user_id
            ).latest_owned(project_id=project_id),
        )

    async def _run(self, session, state: _ProjectState, *, owner_user_id: UUID):
        runs = SqlAlchemyWorkflowRunRepository(session, owner_user_id=owner_user_id)
        run_id = _run_id(state.project.id)
        run = await runs.get_owned(run_id=run_id)
        references = _references(state)
        attempt_id = None if state.attempt is None else state.attempt.id
        source_id = None if state.source is None else state.source.id
        capability = _capability(state)
        if run is None:
            if not state.execution_passed:
                return None
            now = _now()
            draft = create_workflow_run(
                project_id=state.project.id,
                owner_user_id=owner_user_id,
                project_mode=ProjectMode(state.project.mode),
                run_id=run_id,
                created_at=now,
            )
            running = start_workflow_run(draft, occurred_at=now).run
            prepared = replace(
                running,
                current_stage=WorkflowStage.FINAL_REVIEW,
                artifact_references=references,
                latest_source_revision_id=source_id,
                latest_execution_attempt_id=attempt_id,
                capability_state=capability,
                updated_at=now,
            )
            created = await runs.create(draft)
            if created.status is not WorkflowRunStoreStatus.CREATED:
                return None
            creation = create_workflow_checkpoint(prepared, created_at=now)
            saved = await runs.save_checkpoint(previous_run=draft, creation=creation)
            return saved.run
        if run.current_stage is not WorkflowStage.FINAL_REVIEW:
            return run
        if (
            run.artifact_references == references
            and run.latest_execution_attempt_id == attempt_id
            and run.latest_source_revision_id == source_id
            and run.capability_state == capability
        ):
            return run
        now = _later(run.updated_at)
        updated = replace(
            run,
            artifact_references=references,
            latest_source_revision_id=source_id,
            latest_execution_attempt_id=attempt_id,
            capability_state=capability,
            state_version=run.state_version + 1,
            updated_at=now,
        )
        persisted = await self._checkpoint(runs, run, updated, now)
        return run if persisted is None else persisted

    async def _checkpoint(
        self, runs, previous: WorkflowRun, updated: WorkflowRun, moment: datetime
    ):
        checkpoints = await runs.list_checkpoints(run_id=previous.id)
        latest = checkpoints[-1] if checkpoints else None
        creation = create_workflow_checkpoint(
            updated, created_at=_later(moment, updated.updated_at), previous_checkpoint=latest
        )
        saved = await runs.save_checkpoint(previous_run=previous, creation=creation)
        return saved.run if saved.status is WorkflowRunStoreStatus.UPDATED else None

    async def _entries(
        self, session, *, owner_user_id: UUID, project_id: UUID, state: _ProjectState, review
    ):
        entries: list[FinalExportEntry] = []
        omissions: list[FinalExportOmission] = []
        contents: dict[str, bytes] = {}

        def add(
            path, category, artifact_id, version, data, media_type=JSON_MEDIA_TYPE, digest=None
        ):
            entries.append(
                FinalExportEntry(
                    path=path,
                    category=category,
                    artifact_id=artifact_id,
                    artifact_version=version,
                    content_hash=digest or hashlib.sha256(data).hexdigest(),
                    media_type=media_type,
                    size_bytes=len(data),
                    required=True,
                )
            )
            contents[path] = data

        def add_json(path, category, version):
            add(path, category, version.id, version.version_number, _json_bytes(_snapshot(version)))

        for path, category, version in (
            ("project/brief.json", ExportArtifactCategory.PROJECT_BRIEF, state.brief),
            ("project/team.json", ExportArtifactCategory.TEAM_SELECTION, state.team),
            ("project/user-twins.json", ExportArtifactCategory.USER_TWIN, state.twins),
            (
                "specification/requirements.json",
                ExportArtifactCategory.REQUIREMENTS,
                state.requirements,
            ),
            ("design/design.json", ExportArtifactCategory.DESIGN, state.design),
            (
                "architecture/architecture.json",
                ExportArtifactCategory.ARCHITECTURE,
                state.architecture,
            ),
        ):
            if version is None:
                omissions.append(FinalExportOmission(category, "The artifact was not produced."))
            else:
                add_json(path, category, version)
        if state.architecture is None:
            omissions.append(
                FinalExportOmission(
                    ExportArtifactCategory.TEST_PLAN, "The artifact was not produced."
                )
            )
        else:
            test_plan = state.architecture.to_snapshot().get("package", {}).get("test_plan")
            add(
                "architecture/test-plan.json",
                ExportArtifactCategory.TEST_PLAN,
                state.architecture.id,
                state.architecture.version_number,
                _json_bytes(test_plan),
            )
        omissions.append(
            FinalExportOmission(
                ExportArtifactCategory.PERSONA, "Personas are part of the user twin snapshot."
            )
        )
        if state.source is None:
            omissions.append(
                FinalExportOmission(ExportArtifactCategory.SOURCE, "The artifact was not produced.")
            )
            omissions.append(
                FinalExportOmission(ExportArtifactCategory.TESTS, "The artifact was not produced.")
            )
        else:
            for file in state.source.files:
                entry = file.to_snapshot()
                data = read_regular_file(
                    self._content_root / entry["storage_key"], maximum_bytes=entry["size_bytes"]
                )
                category = (
                    ExportArtifactCategory.TESTS
                    if entry["normalized_path"].endswith(TEST_SUFFIXES)
                    else ExportArtifactCategory.SOURCE
                )
                add(
                    "sources/" + entry["normalized_path"],
                    category,
                    state.source.id,
                    state.source.version_number,
                    data,
                    entry["media_type"],
                    entry["sha256_digest"],
                )
            add(
                "setup/run.json",
                ExportArtifactCategory.SETUP_AND_RUN,
                state.source.id,
                state.source.version_number,
                _json_bytes(
                    {
                        "open": "sources/index.html",
                        "tests": ["node --test sources/app.test.cjs"],
                        "target": state.source.target_selection.to_snapshot(),
                    }
                ),
            )
        if state.attempt is None:
            omissions.append(
                FinalExportOmission(
                    ExportArtifactCategory.EXECUTION_EVIDENCE, "No sandbox execution was recorded."
                )
            )
        else:
            add(
                "evidence/execution-attempt.json",
                ExportArtifactCategory.EXECUTION_EVIDENCE,
                state.attempt.id,
                state.attempt.attempt_number,
                _json_bytes(state.attempt.to_snapshot()),
            )
        omissions.append(
            FinalExportOmission(
                ExportArtifactCategory.SYNTHETIC_EVALUATION,
                "No synthetic evaluation run was executed.",
                LIMITATION_ID,
            )
        )
        add(
            "decisions/human-gates.json",
            ExportArtifactCategory.HUMAN_DECISIONS,
            project_id,
            1,
            _json_bytes(
                await self._decisions(session, owner_user_id=owner_user_id, project_id=project_id)
            ),
        )
        graph = None
        if self._graphs is not None:
            graph = await self._graphs.current(owner_user_id=owner_user_id, project_id=project_id)
        if graph is None:
            omissions.append(
                FinalExportOmission(
                    ExportArtifactCategory.TRACEABILITY,
                    "No cross-stage artifact graph is available.",
                )
            )
        else:
            add(
                "traceability/artifact-graph.json",
                ExportArtifactCategory.TRACEABILITY,
                project_id,
                1,
                _json_bytes(
                    CrossStageArtifactGraphPayload.from_domain(graph).model_dump(mode="json")
                ),
            )
        add(
            "reports/limitations.json",
            ExportArtifactCategory.LIMITATIONS,
            review.id,
            review.version_number,
            _json_bytes([item.to_snapshot() for item in review.accepted_limitations]),
        )
        add(
            "reports/final-review.json",
            ExportArtifactCategory.FINAL_REVIEW,
            review.id,
            review.version_number,
            _json_bytes(review.to_snapshot()),
        )
        return tuple(entries), tuple(omissions), contents

    async def _decisions(self, session, *, owner_user_id: UUID, project_id: UUID):
        gates = SqlAlchemyHumanGateRepository(session)
        decisions = []
        for gate_type in STAGE_GATE_TYPES:
            gate = await gates.get_latest_owned_for_update(
                project_id=project_id, owner_user_id=owner_user_id, gate_type=gate_type
            )
            if gate is None:
                continue
            events = await gates.list_events_owned(
                project_id=project_id, owner_user_id=owner_user_id, gate_id=gate.id
            )
            decisions.append({"gate": _plain(gate), "events": [_plain(event) for event in events]})
        return decisions

    def _store(self, archive: BuiltFinalExportArchive) -> str:
        storage_ref = f"sha256/{archive.archive_hash[:2]}/{archive.archive_hash}.zip"
        target = self._export_root / storage_ref
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            return storage_ref
        temporary = target.with_name(target.name + f".{os.getpid()}.tmp")
        temporary.write_bytes(archive.archive_bytes)
        os.replace(temporary, target)
        return storage_ref


def _message(error: Exception) -> str:
    text = " ".join(str(error).split())
    return text or error.__class__.__name__
