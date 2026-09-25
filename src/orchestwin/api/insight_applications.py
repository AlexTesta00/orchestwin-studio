from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from orchestwin.api.auth import current_user_dependency
from orchestwin.artifacts.design_packages import create_design_concern
from orchestwin.artifacts.design_revision_application import DesignRevisionStatus
from orchestwin.artifacts.design_revisions import DesignRevisionDecision
from orchestwin.identity.domain import UserAccount
from orchestwin.projects.briefs import BriefField
from orchestwin.projects.insight_applications import (
    BRIEF_LIST_TARGETS,
    DEFAULT_BRIEF_FIELD,
    MAX_INSIGHT_TEXT_LENGTH,
    MAX_SOURCE_ID_LENGTH,
    InsightApplication,
    InsightSourceKind,
    InsightTarget,
    create_insight_application,
)
from orchestwin.projects.persistence.insight_applications import (
    InsightApplicationWriteStatus,
    SqlAlchemyInsightApplicationRepository,
)
from orchestwin.projects.requirements import (
    RequirementKind,
    RequirementPriority,
    create_requirement,
)
from orchestwin.projects.requirements_primitives import (
    RequirementSourceKind,
    RequirementSourceReference,
)
from orchestwin.projects.requirements_revision_application import (
    RequirementsRevisionDecision,
    RequirementsRevisionStatus,
)
from orchestwin.projects.requirements_specifications import create_requirements_specification

INSIGHT_APPLICATIONS_API_PREFIX = "/projects/{project_id}/insight-applications"
MAX_REQUIREMENT_TITLE_LENGTH = 120


class InsightApplicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: InsightSourceKind
    source_id: str = Field(min_length=1, max_length=MAX_SOURCE_ID_LENGTH)
    source_twin_id: UUID | None = None
    text: str = Field(min_length=1, max_length=MAX_INSIGHT_TEXT_LENGTH)
    target: InsightTarget
    brief_field: BriefField | None = None
    mitigation: str | None = Field(default=None, max_length=MAX_INSIGHT_TEXT_LENGTH)
    requirement_kind: RequirementKind | None = None


def _title(text: str) -> str:
    words = text.split()
    title = ""
    for word in words:
        candidate = f"{title} {word}".strip()
        if len(candidate) > MAX_REQUIREMENT_TITLE_LENGTH:
            break
        title = candidate
    return title or text[:MAX_REQUIREMENT_TITLE_LENGTH]


def _next_code(prefix: str, codes) -> str:
    numbers = []
    for code in codes:
        suffix = code.rsplit("-", 1)[-1]
        if suffix.isdigit():
            numbers.append(int(suffix))
    return f"{prefix}-{(max(numbers, default=0) + 1):03d}"


class InsightApplicationService:
    def __init__(self, runtime):
        self.runtime = runtime

    def _sessions(self):
        database = getattr(self.runtime, "database_runtime", None)
        if database is None:
            raise HTTPException(503, detail={"code": "DATABASE_UNAVAILABLE"})
        return database.session_factory

    def _service(self, name):
        service = getattr(self.runtime, name, None)
        if service is None:
            raise HTTPException(503, detail={"code": f"{name.upper()}_UNAVAILABLE"})
        return service

    async def _apply_to_brief(self, owner_user_id, project_id, body):
        service = self._service("project_service")
        current = await service.current_brief(project_id=project_id, owner_user_id=owner_user_id)
        if current is None:
            raise HTTPException(404, detail={"code": "PROJECT_BRIEF_NOT_FOUND"})
        field = body.brief_field or DEFAULT_BRIEF_FIELD
        if field not in BRIEF_LIST_TARGETS:
            raise HTTPException(422, detail={"code": "BRIEF_FIELD_NOT_A_LIST"})
        existing = current.brief.value_for(field) or ()
        if not isinstance(existing, tuple):
            raise HTTPException(422, detail={"code": "BRIEF_FIELD_NOT_A_LIST"})
        text = " ".join(body.text.split())
        if text in existing:
            raise HTTPException(409, detail={"code": "INSIGHT_ALREADY_APPLIED"})
        try:
            brief = replace(
                current.brief,
                unknown_fields=current.brief.unknown_fields - {field},
                **{field.value: (*existing, text)},
            )
        except ValueError as error:
            raise HTTPException(422, detail={"code": "INVALID_PROJECT_BRIEF"}) from error
        result = await service.create_brief_version(
            project_id=project_id, owner_user_id=owner_user_id, brief=brief
        )
        version = getattr(result, "version", None)
        if version is None:
            raise HTTPException(409, detail={"code": "BRIEF_VERSION_NOT_CREATED"})
        return version.id, version.version_number, field, None

    async def _apply_to_requirements(self, owner_user_id, project_id, body):
        query = self._service("requirements_query_service")
        revisions = self._service("requirements_revision_service")
        current = await query.current(owner_user_id=owner_user_id, project_id=project_id)
        if current is None:
            raise HTTPException(404, detail={"code": "REQUIREMENTS_NOT_FOUND"})
        specification = current.specification
        text = " ".join(body.text.split())
        if any(item.statement == text for item in specification.requirements):
            raise HTTPException(409, detail={"code": "INSIGHT_ALREADY_APPLIED"})
        code = _next_code("REQ", (item.code for item in specification.requirements))
        twin_references = tuple(
            reference
            for reference in specification.user_twin_references
            if reference.twin_id == body.source_twin_id
        )
        source = RequirementSourceReference(
            kind=RequirementSourceKind.USER_TWIN
            if body.source_twin_id is not None
            else RequirementSourceKind.OWNER_INPUT,
            source_id=str(body.source_twin_id) if body.source_twin_id is not None else "owner",
            locator=f"{body.source_kind.value}:{body.source_id}",
        )
        kind = body.requirement_kind or RequirementKind.FUNCTIONAL
        try:
            requirement = create_requirement(
                requirement_id=uuid4(),
                code=code,
                title=_title(text),
                statement=text,
                kind=kind,
                priority=RequirementPriority.SHOULD,
                sources=(source,),
                user_twin_references=twin_references,
            )
            proposed = create_requirements_specification(
                project_id=specification.project_id,
                project_brief_reference=specification.project_brief_reference,
                agent_team_reference=specification.agent_team_reference,
                user_modeling_reference=specification.user_modeling_reference,
                catalog_version=specification.catalog_version,
                catalog_content_hash=specification.catalog_content_hash,
                user_twin_references=specification.user_twin_references,
                requirements=(*specification.requirements, requirement),
                user_stories=specification.user_stories,
                acceptance_criteria=specification.acceptance_criteria,
                scenarios=specification.scenarios,
                risks=specification.risks,
                definition_of_done=specification.definition_of_done,
            )
        except ValueError as error:
            raise HTTPException(422, detail={"code": "INVALID_REQUIREMENT"}) from error
        proposal = await revisions.propose_revision(
            owner_user_id=owner_user_id,
            project_id=project_id,
            proposed_specification=proposed,
        )
        if proposal.status is not RequirementsRevisionStatus.CREATED or proposal.diff is None:
            raise HTTPException(
                409,
                detail={
                    "code": "REQUIREMENTS_REVISION_REJECTED",
                    "issue": None if proposal.issue is None else proposal.issue.value,
                },
            )
        decision = await revisions.decide_revision(
            owner_user_id=owner_user_id,
            project_id=project_id,
            diff_id=proposal.diff.id,
            decision=RequirementsRevisionDecision.APPROVE,
        )
        if decision.version is None:
            raise HTTPException(
                409,
                detail={
                    "code": "REQUIREMENTS_REVISION_REJECTED",
                    "issue": None if decision.issue is None else decision.issue.value,
                },
            )
        return decision.version.id, decision.version.version_number, None, code

    async def _apply_to_design(self, owner_user_id, project_id, body):
        query = self._service("design_query_service")
        revisions = self._service("design_revision_service")
        current = await query.current(owner_user_id=owner_user_id, project_id=project_id)
        if current is None:
            raise HTTPException(404, detail={"code": "DESIGN_PACKAGE_NOT_FOUND"})
        package = current.package
        text = " ".join(body.text.split())
        if any(item.summary == text for item in package.concerns):
            raise HTTPException(409, detail={"code": "INSIGHT_ALREADY_APPLIED"})
        code = _next_code("DRK", (item.code for item in package.concerns))
        selected = package.owner_selected_alternative_id
        chosen = next(
            (item for item in package.alternatives if item.id == selected),
            package.alternatives[0],
        )
        alternatives = (
            (chosen.id,)
            if selected is not None
            else tuple(item.id for item in package.alternatives)
        )
        mitigation = " ".join((body.mitigation or "").split()) or (
            "Review the chosen design against this observation before approval."
        )
        try:
            concern = create_design_concern(
                concern_id=uuid4(),
                code=code,
                summary=text,
                mitigation=mitigation,
                requirement_ids=chosen.requirement_ids,
                design_alternative_ids=alternatives,
            )
            proposed = replace(package, concerns=(*package.concerns, concern))
        except ValueError as error:
            raise HTTPException(422, detail={"code": "INVALID_DESIGN_CONCERN"}) from error
        proposal = await revisions.propose_revision(
            owner_user_id=owner_user_id, project_id=project_id, proposed_package=proposed
        )
        if proposal.status is not DesignRevisionStatus.CREATED or proposal.diff is None:
            raise HTTPException(
                409,
                detail={
                    "code": "DESIGN_REVISION_REJECTED",
                    "issue": None if proposal.issue is None else proposal.issue.value,
                },
            )
        decision = await revisions.decide_revision(
            owner_user_id=owner_user_id,
            project_id=project_id,
            diff_id=proposal.diff.id,
            decision=DesignRevisionDecision.APPROVE,
        )
        if decision.version is None:
            raise HTTPException(
                409,
                detail={
                    "code": "DESIGN_REVISION_REJECTED",
                    "issue": None if decision.issue is None else decision.issue.value,
                },
            )
        return decision.version.id, decision.version.version_number, None, code

    async def apply(self, *, owner_user_id, project_id, body) -> InsightApplication:
        if body.target is InsightTarget.BRIEF:
            outcome = await self._apply_to_brief(owner_user_id, project_id, body)
        elif body.target is InsightTarget.REQUIREMENTS:
            outcome = await self._apply_to_requirements(owner_user_id, project_id, body)
        else:
            outcome = await self._apply_to_design(owner_user_id, project_id, body)
        version_id, version_number, field, code = outcome
        try:
            application = create_insight_application(
                application_id=uuid4(),
                project_id=project_id,
                owner_user_id=owner_user_id,
                source_kind=body.source_kind,
                source_id=body.source_id,
                source_twin_id=body.source_twin_id,
                text=body.text,
                target=body.target,
                target_field=field,
                target_version_id=version_id,
                target_version_number=version_number,
                target_code=code,
                created_at=datetime.now(UTC),
            )
        except ValueError as error:
            raise HTTPException(422, detail={"code": "INSIGHT_APPLICATION_INVALID"}) from error
        sessions = self._sessions()
        async with sessions() as session, session.begin():
            status = await SqlAlchemyInsightApplicationRepository(
                session, owner_user_id=owner_user_id
            ).create(application)
            if status is not InsightApplicationWriteStatus.WRITTEN:
                raise HTTPException(404, detail={"code": "PROJECT_NOT_FOUND"})
        return application

    async def applications(self, *, owner_user_id, project_id):
        sessions = self._sessions()
        async with sessions() as session:
            return await SqlAlchemyInsightApplicationRepository(
                session, owner_user_id=owner_user_id
            ).list(project_id=project_id)


def create_insight_application_router():
    router = APIRouter(prefix=INSIGHT_APPLICATIONS_API_PREFIX, tags=["design"])

    @router.post("", status_code=201)
    async def apply(
        project_id: UUID,
        body: InsightApplicationRequest,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        application = await InsightApplicationService(request.app.state.application_runtime).apply(
            owner_user_id=user.id, project_id=project_id, body=body
        )
        return application.to_snapshot()

    @router.get("")
    async def applications(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        items = await InsightApplicationService(request.app.state.application_runtime).applications(
            owner_user_id=user.id, project_id=project_id
        )
        return [item.to_snapshot() for item in items]

    return router


__all__ = [
    "INSIGHT_APPLICATIONS_API_PREFIX",
    "InsightApplicationRequest",
    "InsightApplicationService",
    "create_insight_application_router",
]
