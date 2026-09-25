from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.design import DesignGenerationPayload
from orchestwin.artifacts.design_evaluation import (
    DesignEvaluationError,
    DesignEvaluationRun,
    compare_design_evaluations,
    create_design_evaluation_run,
    evaluation_bundle,
    evaluation_document,
)
from orchestwin.artifacts.design_evaluation_persistence import (
    DesignEvaluationWriteStatus,
    SqlAlchemyDesignEvaluationRepository,
)
from orchestwin.evaluation.artifact_content import prepare_artifact_content
from orchestwin.evaluation.evaluator import EvaluationUserTwinProfile, UserTwinEvaluationRequest
from orchestwin.identity.domain import UserAccount
from orchestwin.twins.persistence.repositories import SqlAlchemyUserTwinVersionRepository

DESIGN_LOOP_API_PREFIX = "/projects/{project_id}/design"


class DesignEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    design_version_id: UUID
    design_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    locale: str = Field(default="it-IT", min_length=2, max_length=20)


class DesignLoopApplication:
    def __init__(self, runtime):
        self.runtime = runtime

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

    async def evaluate(self, *, owner_user_id, project_id, body) -> DesignEvaluationRun:
        version = await self._current(owner_user_id, project_id)
        if (version.id, version.content_hash) != (body.design_version_id, body.design_content_hash):
            raise HTTPException(409, detail={"code": "DESIGN_CONTEXT_CHANGED"})
        evaluator_runtime = getattr(self.runtime, "final_evaluator_runtime", None)
        if evaluator_runtime is None:
            raise HTTPException(503, detail={"code": "DESIGN_EVALUATOR_NOT_CONFIGURED"})
        try:
            document = evaluation_document(version, language=body.locale.split("-")[0])
        except DesignEvaluationError as error:
            raise HTTPException(409, detail={"code": error.code}) from error
        twins = await self._twins(owner_user_id, project_id, version)
        started_at = datetime.now(UTC)
        run_id = uuid4()
        bundle = evaluation_bundle(version, document, locale=body.locale, created_at=started_at)
        responses = []
        for twin in twins:
            request = UserTwinEvaluationRequest(
                evaluation_run_id=run_id,
                project_id=project_id,
                workflow_run_id=version.id,
                artifact_bundle=bundle,
                twin=EvaluationUserTwinProfile.from_version(twin),
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
        return run

    async def runs(self, *, owner_user_id, project_id) -> tuple[DesignEvaluationRun, ...]:
        sessions = self._sessions()
        async with sessions() as session:
            return await SqlAlchemyDesignEvaluationRepository(
                session, owner_user_id=owner_user_id
            ).list(project_id=project_id)

    async def comparison(self, *, owner_user_id, project_id):
        runs = await self.runs(owner_user_id=owner_user_id, project_id=project_id)
        if len(runs) < 2:
            raise HTTPException(404, detail={"code": "DESIGN_EVALUATION_COMPARISON_UNAVAILABLE"})
        head, base = runs[0], runs[1]
        return compare_design_evaluations(base, head)

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
        run = await DesignLoopApplication(request.app.state.application_runtime).evaluate(
            owner_user_id=user.id, project_id=project_id, body=body
        )
        return run.to_snapshot()

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

    @router.post("/regenerations", status_code=201)
    async def regenerate(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        result = await DesignLoopApplication(request.app.state.application_runtime).regenerate(
            owner_user_id=user.id, project_id=project_id
        )
        return DesignGenerationPayload.from_domain(result)

    return router


__all__ = [
    "DESIGN_LOOP_API_PREFIX",
    "DesignEvaluationRequest",
    "DesignLoopApplication",
    "create_design_loop_router",
]
