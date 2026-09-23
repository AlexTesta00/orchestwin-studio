from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from orchestwin.api.auth import current_user_dependency
from orchestwin.evaluation.aggregation import aggregate_synthetic_evaluation
from orchestwin.evaluation.application import (
    ApprovedUserTwinEvaluationTarget,
    IndependentUserTwinEvaluationService,
    SyntheticEvaluationError,
)
from orchestwin.evaluation.artifact_content import ContentAddressedArtifactReader
from orchestwin.evaluation.evaluator import EvaluationUserTwinProfile
from orchestwin.evaluation.execution_bundle import (
    artifact_evidence_references,
    execution_bundle,
    execution_scenario,
)
from orchestwin.evaluation.persistence import (
    SqlAlchemySyntheticEvaluationRepository,
    StoredSyntheticEvaluationRun,
    SyntheticEvaluationStoreStatus,
)
from orchestwin.evaluation.proposer_evaluator import ProposerUserTwinEvaluator
from orchestwin.evaluation.validation import EvaluationEvidenceKind, EvaluationEvidenceReference
from orchestwin.identity.domain import UserAccount
from orchestwin.models.proposal_evidence import (
    current_proposal_evidence,
    evidence_application,
    retain_adapter_result,
)
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.projects.persistence.briefs import SqlAlchemyProjectBriefRepository
from orchestwin.twins.user_modeling_gate import user_modeling_approval_state
from orchestwin.twins.user_twins import UserTwinLifecycleStatus

APPROVED_TWIN_STATUSES = frozenset(
    {
        UserTwinLifecycleStatus.OWNER_APPROVED_UT,
        UserTwinLifecycleStatus.EMPIRICALLY_GROUNDED_UT,
        UserTwinLifecycleStatus.EMPIRICALLY_VALIDATED_UT,
    }
)
MAX_EVALUATED_TWINS = 4


class CreateEvaluationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: UUID


class SyntheticEvaluationStatus(StrEnum):
    RECORDED = "SYNTHETIC_EVALUATION_RECORDED"


@dataclass(frozen=True)
class SyntheticEvaluationResult:
    status: SyntheticEvaluationStatus
    run: StoredSyntheticEvaluationRun
    findings: tuple
    aggregation: dict


def evaluation_run_payload(stored):
    return {
        "id": str(stored.id),
        "project_id": str(stored.project_id),
        "workflow_run_id": str(stored.workflow_run_id),
        "owner_user_id": str(stored.owner_user_id),
        "artifact_bundle_id": str(stored.artifact_bundle_id),
        "artifact_bundle_hash": stored.artifact_bundle_hash,
        "evaluator": stored.evaluator.to_snapshot(),
        "status": stored.status.value,
        "response_count": stored.response_count,
        "finding_count": stored.finding_count,
        "started_at": stored.started_at.isoformat(),
        "completed_at": stored.completed_at.isoformat(),
        "content_hash": stored.content_hash,
        "simulated_feedback": True,
    }


def synthetic_finding_payload(finding):
    return {**finding.to_snapshot(), "origin": "MODEL_GENERATED"}


def twin_profile_reference(twin):
    return EvaluationEvidenceReference(
        reference_id=f"user-twin:{twin.twin_id}:v{twin.version_number}",
        kind=EvaluationEvidenceKind.USER_TWIN_PROFILE,
        content_hash=twin.content_hash,
        locator="profile",
    )


def approved_targets(snapshot, gate, artifact_evidence):
    if snapshot is None:
        return ()
    approval = user_modeling_approval_state(version=snapshot, gate=gate)
    effective = {state.twin_version_id: state.effective_status for state in approval.twins}
    targets = []
    for version in snapshot.snapshot.twin_versions:
        status = effective.get(version.id, version.profile.validation_status)
        if status not in APPROVED_TWIN_STATUSES:
            continue
        twin = replace(EvaluationUserTwinProfile.from_version(version), lifecycle_status=status)
        evidence = tuple(
            sorted(
                (twin_profile_reference(twin), *artifact_evidence), key=lambda item: item.sort_key
            )
        )
        targets.append(ApprovedUserTwinEvaluationTarget(twin=twin, evidence=evidence))
        if len(targets) == MAX_EVALUATED_TWINS:
            break
    return tuple(targets)


class SyntheticEvaluationApplication:
    def __init__(self, runtime):
        self.runtime = runtime
        self._proposal_evidence_store = runtime.proposal_evidence_store

    def _sessions(self):
        database = self.runtime.database_runtime
        if database is None:
            raise HTTPException(503, detail={"code": "DATABASE_UNAVAILABLE"})
        return database.session_factory

    async def runs(self, *, owner_user_id, project_id):
        async with self._sessions()() as session:
            stored = await SqlAlchemySyntheticEvaluationRepository(
                session, owner_user_id=owner_user_id
            ).list_owned(project_id=project_id)
        return tuple(evaluation_run_payload(item) for item in stored)

    @evidence_application
    async def create(self, *, owner_user_id, project_id, body):
        sessions = self._sessions()
        read = self.runtime.web_execution_read_api_service
        modeling = self.runtime.user_modeling_services
        finalization = self.runtime.finalization_api_service
        real = self.runtime.real_model_runtime
        root = self.runtime.sandbox_evidence_root
        if read is None or modeling is None or finalization is None or root is None:
            raise HTTPException(503, detail={"code": "SYNTHETIC_EVALUATION_UNAVAILABLE"})
        execution = await read.execution(
            owner_user_id=owner_user_id, execution_id=body.execution_id
        )
        if execution is None or execution["project_id"] != str(project_id):
            raise HTTPException(404, detail={"code": "EXECUTION_NOT_FOUND"})
        if execution["report"]["status"] != "PASSED":
            raise HTTPException(409, detail={"code": "EXECUTION_NOT_PASSED"})
        manifest = await read.browser_evidence(
            owner_user_id=owner_user_id, execution_id=body.execution_id
        )
        screens = ((manifest or {}).get("browser_evidence") or {}).get("screens")
        if not screens:
            raise HTTPException(409, detail={"code": "BROWSER_EVIDENCE_MISSING"})
        workflow_run = await finalization.workflow_run_for(
            owner_user_id=owner_user_id, project_id=project_id
        )
        if workflow_run is None:
            raise HTTPException(409, detail={"code": "WORKFLOW_RUN_UNAVAILABLE"})
        snapshot = await modeling.queries.current_snapshot(
            owner_user_id=owner_user_id, project_id=project_id
        )
        gate = await modeling.gates.current_gate(project_id=project_id, owner_user_id=owner_user_id)
        async with sessions() as session:
            briefs = await SqlAlchemyProjectBriefRepository(session).list_owned_versions(
                project_id=project_id, owner_user_id=owner_user_id
            )
        brief = briefs[-1].brief if briefs else None
        now = datetime.now(UTC)
        try:
            bundle = execution_bundle(
                project_id=project_id,
                workflow_run_id=workflow_run.id,
                execution_id=body.execution_id,
                attempt_number=int(execution["attempt_number"]),
                screens=screens,
                scenario=execution_scenario(
                    execution_id=body.execution_id,
                    name=(brief.name if brief and brief.name else "Executed prototype"),
                    task=(
                        brief.problem if brief and brief.problem else "Use the executed prototype."
                    ),
                    expected_outcomes=tuple(
                        (brief.definition_of_done or ()) or (brief.goals or ()) if brief else ()
                    ),
                ),
                created_at=now,
            )
        except ValueError as error:
            raise HTTPException(409, detail={"code": "BROWSER_EVIDENCE_INVALID"}) from error
        targets = approved_targets(snapshot, gate, artifact_evidence_references(bundle.artifacts))
        if not targets:
            raise HTTPException(409, detail={"code": "NO_APPROVED_USER_TWINS"})
        if real is None or self._proposal_evidence_store is None:
            raise HTTPException(503, detail={"code": "SYNTHETIC_EVALUATION_MODEL_NOT_CONFIGURED"})
        evaluator = ProposerUserTwinEvaluator(
            real.user_modeling.proposal_port.generator,
            read_content=ContentAddressedArtifactReader(root=root),
        )
        service = IndependentUserTwinEvaluationService(
            evaluator, identifier_provider=uuid4, clock=lambda: datetime.now(UTC)
        )
        try:
            run = await service.evaluate(
                owner_user_id=owner_user_id, artifact_bundle=bundle, targets=targets
            )
        except (SyntheticEvaluationError, ValueError) as error:
            await retain_adapter_result(error=error, reason=str(error))
            raise ProposalGenerationError("INVALID_SYNTHETIC_EVALUATION_OUTPUT") from error
        async with sessions() as session, session.begin():
            stored = await SqlAlchemySyntheticEvaluationRepository(
                session, owner_user_id=owner_user_id
            ).append(run)
        if stored.status is not SyntheticEvaluationStoreStatus.CREATED:
            raise HTTPException(409, detail={"code": "EVALUATION_RUN_" + stored.status.value})
        scope = current_proposal_evidence()
        if scope is not None and scope.request is not None:
            await scope.event(
                "ADAPTER_ACCEPTED",
                {
                    "result": run.to_snapshot(),
                    "generated_content_hashes": {"SYNTHETIC_EVALUATION": [run.content_hash]},
                    **(
                        {"related_generations": scope.related_generations}
                        if scope.related_generations
                        else {}
                    ),
                },
            )
        return SyntheticEvaluationResult(
            status=SyntheticEvaluationStatus.RECORDED,
            run=StoredSyntheticEvaluationRun.from_domain(run),
            findings=run.findings,
            aggregation=aggregate_synthetic_evaluation(run).to_snapshot(),
        )


def create_synthetic_evaluation_router():
    router = APIRouter(prefix="/projects/{project_id}/evaluation-runs", tags=["evaluation"])

    @router.get("")
    async def runs(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        items = await SyntheticEvaluationApplication(request.app.state.application_runtime).runs(
            owner_user_id=user.id, project_id=project_id
        )
        return {"items": list(items)}

    @router.post("", status_code=201)
    async def create(
        project_id: UUID,
        body: CreateEvaluationRunRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        result = await SyntheticEvaluationApplication(request.app.state.application_runtime).create(
            owner_user_id=user.id, project_id=project_id, body=body
        )
        return {
            "status": result.status.value,
            "snapshot": evaluation_run_payload(result.run),
            "findings": [synthetic_finding_payload(item) for item in result.findings],
            "aggregation": result.aggregation,
        }

    return router
