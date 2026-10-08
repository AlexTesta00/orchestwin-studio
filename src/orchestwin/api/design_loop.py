from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Final
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.design import DesignGenerationPayload
from orchestwin.api.generation_jobs import GenerationOperation
from orchestwin.api.generation_requests import generation_request
from orchestwin.artifacts.design_evaluation import (
    DesignEvaluationError,
    DesignEvaluationRun,
    DesignReviewScope,
    compare_design_evaluations,
    create_design_evaluation_run,
    design_review_anchors,
    design_review_scope,
    design_review_view,
    evaluation_bundle,
    evaluation_document,
)
from orchestwin.artifacts.design_evaluation_persistence import (
    DesignEvaluationWriteStatus,
    SqlAlchemyDesignEvaluationRepository,
)
from orchestwin.artifacts.design_finding_validation_persistence import (
    FindingValidationWriteStatus,
    SqlAlchemyFindingValidationRepository,
)
from orchestwin.artifacts.design_finding_validations import (
    FindingDecision,
    FindingValidation,
    dismissed_finding_keys,
    normalize_finding_note,
)
from orchestwin.artifacts.design_static_check import (
    static_check_bundle,
    static_check_document,
    static_check_profile,
    static_check_target,
)
from orchestwin.evaluation.artifact_content import prepare_artifact_content
from orchestwin.evaluation.evaluator import EvaluationUserTwinProfile, UserTwinEvaluationRequest
from orchestwin.evaluation.proposer_evaluator import (
    INVALID_TWIN_REVIEW_OUTPUT,
    ProposerDesignTwinReviewer,
    hosted_twin_review,
    scoped_review,
)
from orchestwin.identity.domain import UserAccount
from orchestwin.models.design_change import ELEMENT_CODE_PATTERN, SCREEN_CODE_PATTERN
from orchestwin.models.proposal_evidence import current_proposal_evidence, evidence_application
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.twins.persistence.repositories import SqlAlchemyUserTwinVersionRepository

DESIGN_LOOP_API_PREFIX = "/projects/{project_id}/design"
TWIN_REVIEW_ATTEMPTS: Final = 2
RETRYABLE_REVIEW_CODES: Final = frozenset(
    {
        INVALID_TWIN_REVIEW_OUTPUT,
        "INVALID_PROVIDER_OUTPUT",
        "INCOMPLETE_OUTPUT",
        "RESPONSE_SCHEMA_ERROR",
    }
)


class DesignEvaluationMode(StrEnum):
    TWIN_REVIEW = "TWIN_REVIEW"
    STATIC_CHECK = "STATIC_CHECK"


class DesignEvaluationStatus(StrEnum):
    RECORDED = "DESIGN_EVALUATION_RECORDED"


class DesignEvaluationScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    screen_code: str = Field(pattern=SCREEN_CODE_PATTERN)
    element_code: str | None = Field(default=None, pattern=ELEMENT_CODE_PATTERN)


class DesignEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    design_version_id: UUID
    design_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    locale: str = Field(default="it-IT", min_length=2, max_length=20)
    mode: DesignEvaluationMode | None = None
    scope: DesignEvaluationScope | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def scope_of_a_twin_review(self) -> DesignEvaluationRequest:
        if self.scope is not None and self.mode is DesignEvaluationMode.STATIC_CHECK:
            raise ValueError("a scope belongs only to the review of the twins")
        return self

    def requested_mode(self) -> DesignEvaluationMode | None:
        if self.mode is None and self.scope is not None:
            return DesignEvaluationMode.TWIN_REVIEW
        return self.mode


class FindingValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    twin_id: UUID
    finding_id: str = Field(pattern=r"^UTF-[0-9]{3,6}$")
    decision: FindingDecision
    note: str | None = None


@dataclass(frozen=True)
class DesignEvaluationResult:
    status: DesignEvaluationStatus
    run: DesignEvaluationRun


class DesignLoopApplication:
    def __init__(self, runtime):
        self.runtime = runtime
        self._proposal_evidence_store = getattr(runtime, "proposal_evidence_store", None)

    def _sessions(self):
        database = getattr(self.runtime, "database_runtime", None)
        if database is None:
            raise HTTPException(503, detail={"code": "DATABASE_UNAVAILABLE"})
        return database.session_factory

    async def _current(self, owner_user_id, project_id):
        query = getattr(self.runtime, "design_query_service", None)
        if query is None:
            raise HTTPException(503, detail={"code": "DESIGN_QUERY_UNAVAILABLE"})
        current = await query.current(owner_user_id=owner_user_id, project_id=project_id)
        if current is None:
            raise HTTPException(404, detail={"code": "DESIGN_PACKAGE_NOT_FOUND"})
        return current

    async def _twins(self, owner_user_id, project_id, version):
        sessions = self._sessions()
        twins = []
        async with sessions() as session:
            repository = SqlAlchemyUserTwinVersionRepository(session, owner_user_id=owner_user_id)
            for reference in version.package.grounding.user_twin_references:
                twin = await repository.get(
                    project_id=project_id,
                    twin_id=reference.twin_id,
                    version_number=reference.version_number,
                )
                if twin is None or twin.content_hash != reference.content_hash:
                    raise HTTPException(409, detail={"code": "USER_TWIN_CONTEXT_CHANGED"})
                twins.append(twin)
        return twins

    def _generator(self):
        real = getattr(self.runtime, "real_model_runtime", None)
        if real is None or self._proposal_evidence_store is None:
            return None
        return real.user_modeling.proposal_port.generator

    def _mode(self, requested):
        generator = self._generator()
        evaluator = getattr(self.runtime, "final_evaluator_runtime", None)
        if requested is DesignEvaluationMode.TWIN_REVIEW or (
            requested is None and generator is not None
        ):
            if generator is None:
                raise HTTPException(503, detail={"code": "DESIGN_REVIEWER_NOT_CONFIGURED"})
            return DesignEvaluationMode.TWIN_REVIEW, generator
        if evaluator is None:
            raise HTTPException(503, detail={"code": "DESIGN_EVALUATOR_NOT_CONFIGURED"})
        return DesignEvaluationMode.STATIC_CHECK, evaluator

    @staticmethod
    async def _retire(code, run_id):
        scope = current_proposal_evidence()
        if scope is None or scope.request is None:
            return
        await scope.event("APPLICATION_RESULT", {"status": code, "evaluation_run_id": str(run_id)})
        scope.retire(role="TWIN_REVIEW", code=code)

    async def _review(self, reviewer, request):
        for attempt in range(1, TWIN_REVIEW_ATTEMPTS + 1):
            try:
                return await reviewer.evaluate(request)
            except ProposalGenerationError as error:
                if attempt == TWIN_REVIEW_ATTEMPTS or error.code not in RETRYABLE_REVIEW_CODES:
                    raise
                await self._retire("TWIN_REVIEW_REJECTED", request.evaluation_run_id)
        raise RuntimeError("twin review attempts are exhausted")

    @staticmethod
    def _scope(version, body) -> DesignReviewScope | None:
        if body.scope is None:
            return None
        try:
            return design_review_scope(
                version, screen_code=body.scope.screen_code, element_code=body.scope.element_code
            )
        except DesignEvaluationError as error:
            raise HTTPException(422, detail={"code": error.code}) from error

    async def _twin_review(
        self, generator, version, twins, bundle, run_id, *, hosted, language, scope=None
    ):
        try:
            reviewer = ProposerDesignTwinReviewer(
                generator,
                design_view=design_review_view(version, hosted=hosted, language=language),
                anchors=design_review_anchors(
                    version, hosted=hosted, language=language, scope=scope
                ),
                scope=scope,
            )
        except DesignEvaluationError as error:
            raise HTTPException(409, detail={"code": error.code}) from error
        responses = []
        for index, twin in enumerate(twins):
            request = UserTwinEvaluationRequest(
                evaluation_run_id=run_id,
                project_id=version.project_id,
                workflow_run_id=version.id,
                artifact_bundle=bundle,
                twin=EvaluationUserTwinProfile.from_version(twin),
                evidence=(),
                requested_at=datetime.now(UTC),
            )
            try:
                responses.append(await self._review(reviewer, request))
            except ValueError as error:
                raise HTTPException(
                    502,
                    detail={"code": "DESIGN_EVALUATION_FAILED", "reason": str(error)[:300]},
                ) from error
            if index < len(twins) - 1:
                await self._retire("TWIN_REVIEWED", run_id)
        return responses

    async def _static_check(
        self, evaluator_runtime, version, twins, bundle, document, target, run_id
    ):
        responses = []
        for twin in twins:
            request = UserTwinEvaluationRequest(
                evaluation_run_id=run_id,
                project_id=version.project_id,
                workflow_run_id=version.id,
                artifact_bundle=bundle,
                twin=static_check_profile(EvaluationUserTwinProfile.from_version(twin), target),
                evidence=(),
                requested_at=datetime.now(UTC),
            )
            try:
                prepared = prepare_artifact_content(
                    request,
                    selected=((document.reference.artifact_id, document.reference.version_number),),
                    read_content=document.read,
                )
                evaluator = evaluator_runtime.create_evaluator(verified_content=prepared.content)
                responses.append(await evaluator.evaluate(prepared.request))
            except HTTPException:
                raise
            except Exception as error:
                raise HTTPException(
                    502,
                    detail={"code": "DESIGN_EVALUATION_FAILED", "reason": str(error)[:300]},
                ) from error
        return responses

    @evidence_application
    async def evaluate(self, *, owner_user_id, project_id, body) -> DesignEvaluationResult:
        version = await self._current(owner_user_id, project_id)
        if (version.id, version.content_hash) != (body.design_version_id, body.design_content_hash):
            raise HTTPException(409, detail={"code": "DESIGN_CONTEXT_CHANGED"})
        mode, engine = self._mode(body.requested_mode())
        started_at = datetime.now(UTC)
        run_id = uuid4()
        language = body.locale.split("-")[0]
        hosted = mode is DesignEvaluationMode.TWIN_REVIEW and hosted_twin_review(engine)
        try:
            if mode is DesignEvaluationMode.TWIN_REVIEW:
                document = evaluation_document(version, language=language, hosted=hosted)
                bundle = evaluation_bundle(
                    version, document, locale=body.locale, created_at=started_at
                )
                target = None
            else:
                target = static_check_target(version, locale=body.locale)
                document = static_check_document(version, target)
                bundle = static_check_bundle(version, document, target, created_at=started_at)
        except DesignEvaluationError as error:
            raise HTTPException(409, detail={"code": error.code}) from error
        scope = self._scope(version, body)
        twins = await self._twins(owner_user_id, project_id, version)
        if mode is DesignEvaluationMode.TWIN_REVIEW:
            responses = await self._twin_review(
                engine,
                version,
                twins,
                bundle,
                run_id,
                hosted=hosted,
                language=language,
                scope=scope,
            )
        else:
            responses = await self._static_check(
                engine, version, twins, bundle, document, target, run_id
            )
        try:
            run = create_design_evaluation_run(
                run_id=run_id,
                owner_user_id=owner_user_id,
                version=version,
                bundle=bundle,
                responses=responses,
                started_at=started_at,
                completed_at=datetime.now(UTC),
            )
        except ValueError as error:
            raise HTTPException(
                502, detail={"code": "DESIGN_EVALUATION_INVALID", "reason": str(error)[:300]}
            ) from error
        refreshed = await self._current(owner_user_id, project_id)
        if (refreshed.id, refreshed.content_hash) != (version.id, version.content_hash):
            raise HTTPException(409, detail={"code": "DESIGN_CONTEXT_CHANGED"})
        sessions = self._sessions()
        async with sessions() as session, session.begin():
            status = await SqlAlchemyDesignEvaluationRepository(
                session, owner_user_id=owner_user_id
            ).create(run)
            if status is not DesignEvaluationWriteStatus.WRITTEN:
                raise HTTPException(409, detail={"code": f"DESIGN_EVALUATION_{status.value}"})
        return DesignEvaluationResult(status=DesignEvaluationStatus.RECORDED, run=run)

    async def runs(self, *, owner_user_id, project_id) -> tuple[DesignEvaluationRun, ...]:
        sessions = self._sessions()
        async with sessions() as session:
            return await SqlAlchemyDesignEvaluationRepository(
                session, owner_user_id=owner_user_id
            ).list(project_id=project_id)

    async def record_validation(
        self, *, owner_user_id, project_id, run_id, body
    ) -> FindingValidation:
        try:
            note = normalize_finding_note(body.note)
        except ValueError as error:
            raise HTTPException(422, detail={"code": "FINDING_NOTE_INVALID"}) from error
        sessions = self._sessions()
        async with sessions() as session, session.begin():
            result = await SqlAlchemyFindingValidationRepository(
                session, owner_user_id=owner_user_id
            ).append(
                project_id=project_id,
                evaluation_run_id=run_id,
                twin_id=body.twin_id,
                finding_id=body.finding_id,
                decision=body.decision,
                note=note,
                decided_at=datetime.now(UTC),
            )
            if result.status is not FindingValidationWriteStatus.WRITTEN:
                raise HTTPException(404, detail={"code": "DESIGN_FINDING_NOT_FOUND"})
        return result.validation

    async def validations(self, *, owner_user_id, project_id) -> tuple[FindingValidation, ...]:
        sessions = self._sessions()
        async with sessions() as session:
            return await SqlAlchemyFindingValidationRepository(
                session, owner_user_id=owner_user_id
            ).current(project_id=project_id)

    async def _dismissed(self, *, owner_user_id, project_id):
        return dismissed_finding_keys(
            await self.validations(owner_user_id=owner_user_id, project_id=project_id)
        )

    async def comparison(self, *, owner_user_id, project_id):
        runs = [
            run
            for run in await self.runs(owner_user_id=owner_user_id, project_id=project_id)
            if not scoped_review(run.evaluator)
        ]
        if not runs:
            raise HTTPException(404, detail={"code": "DESIGN_EVALUATION_COMPARISON_UNAVAILABLE"})
        head = runs[0]
        base = next(
            (
                item
                for item in runs[1:]
                if item.evaluator.evaluator_id == head.evaluator.evaluator_id
            ),
            None,
        )
        if base is None:
            raise HTTPException(404, detail={"code": "DESIGN_EVALUATION_COMPARISON_UNAVAILABLE"})
        dismissed = await self._dismissed(owner_user_id=owner_user_id, project_id=project_id)
        return compare_design_evaluations(base, head, dismissed=dismissed)

    async def regenerate(self, *, owner_user_id, project_id):
        service = getattr(self.runtime, "design_generation_service", None)
        if service is None:
            raise HTTPException(503, detail={"code": "DESIGN_GENERATION_UNAVAILABLE"})
        return await service.regenerate(owner_user_id=owner_user_id, project_id=project_id)


def create_design_loop_router():
    router = APIRouter(prefix=DESIGN_LOOP_API_PREFIX, tags=["design"])

    @router.post("/evaluations", status_code=201)
    async def evaluate(
        project_id: UUID,
        body: DesignEvaluationRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        async def evaluation():
            result = await DesignLoopApplication(request.app.state.application_runtime).evaluate(
                owner_user_id=user.id, project_id=project_id, body=body
            )
            return result.run.to_snapshot()

        return await generation_request(
            request,
            GenerationOperation.DESIGN_EVALUATION,
            evaluation,
            owner_user_id=user.id,
            project_id=project_id,
            body=body,
        )

    @router.get("/evaluations")
    async def runs(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        items = await DesignLoopApplication(request.app.state.application_runtime).runs(
            owner_user_id=user.id, project_id=project_id
        )
        return [run.to_snapshot() for run in items]

    @router.get("/evaluations/comparison")
    async def comparison(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        result = await DesignLoopApplication(request.app.state.application_runtime).comparison(
            owner_user_id=user.id, project_id=project_id
        )
        return result.to_snapshot()

    @router.get("/evaluations/validations")
    async def validations(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        items = await DesignLoopApplication(request.app.state.application_runtime).validations(
            owner_user_id=user.id, project_id=project_id
        )
        return [item.to_snapshot() for item in items]

    @router.post("/evaluations/{run_id}/validations", status_code=201)
    async def record_validation(
        project_id: UUID,
        run_id: UUID,
        body: FindingValidationRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        validation = await DesignLoopApplication(
            request.app.state.application_runtime
        ).record_validation(owner_user_id=user.id, project_id=project_id, run_id=run_id, body=body)
        return validation.to_snapshot()

    @router.post("/regenerations", status_code=201)
    async def regenerate(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        async def regeneration():
            result = await DesignLoopApplication(request.app.state.application_runtime).regenerate(
                owner_user_id=user.id, project_id=project_id
            )
            return DesignGenerationPayload.from_domain(result)

        return await generation_request(
            request,
            GenerationOperation.DESIGN_REGENERATION,
            regeneration,
            owner_user_id=user.id,
            project_id=project_id,
        )

    return router


__all__ = [
    "DESIGN_LOOP_API_PREFIX",
    "DesignEvaluationMode",
    "DesignEvaluationRequest",
    "DesignEvaluationResult",
    "DesignEvaluationScope",
    "DesignEvaluationStatus",
    "DesignLoopApplication",
    "FindingValidationRequest",
    "create_design_loop_router",
]
