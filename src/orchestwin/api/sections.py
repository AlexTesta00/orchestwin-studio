from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Final, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from orchestwin.agents.realignment_service import TeamRealignmentFailure, TeamRealignmentService
from orchestwin.agents.team_gate import LocalAgentTeamApprovalService
from orchestwin.api.auth import current_user_dependency
from orchestwin.api.twin_learning import TwinLearningApplication
from orchestwin.identity.domain import UserAccount
from orchestwin.models.proposal_evidence_persistence import SqlAlchemyProposalEvidenceStore
from orchestwin.models.real_runtime import RealModelRuntime
from orchestwin.persistence import DatabaseRuntime
from orchestwin.projects.design_realignment_service import (
    DesignRealignmentFailure,
    DesignRealignmentService,
)
from orchestwin.projects.progress import ProjectStage
from orchestwin.projects.requirements_realignment_service import (
    RequirementsRealignmentFailure,
    RequirementsRealignmentService,
)
from orchestwin.projects.sections import (
    ProjectSections,
    Section,
    SectionAlignment,
    SectionBlock,
    SectionReason,
    SectionState,
)
from orchestwin.projects.sections_service import (
    PROJECT_NOT_FOUND,
    SectionGate,
    SectionOutcome,
    SectionsAlignment,
    SectionsAlignmentStatus,
    SectionsFailure,
    SectionsService,
    SectionStep,
    SectionUpdate,
    SqlAlchemySectionReads,
)
from orchestwin.twins.realignment_service import (
    UserModelingRealignmentFailure,
    UserModelingRealignmentService,
)
from orchestwin.twins.runtime import UserModelingServices
from orchestwin.workflow.gates import HumanGateAction

SECTIONS_API_PREFIX: Final = "/projects/{project_id}/sections"
_NOT_FOUND_CODES: Final = frozenset({PROJECT_NOT_FOUND})


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SectionPayload(ApiModel):
    key: ProjectStage
    state: SectionState
    version_number: int | None
    reasons: tuple[SectionReason, ...]
    blocked: SectionBlock | None
    codes: tuple[str, ...]
    affected_codes: dict[str, tuple[str, ...]] = Field(
        default_factory=dict, exclude_if=lambda value: not value
    )

    @classmethod
    def from_domain(cls, section: Section) -> SectionPayload:
        return cls(
            key=section.key,
            state=section.state,
            version_number=section.version_number,
            reasons=section.reasons,
            blocked=section.blocked,
            codes=section.codes,
            affected_codes=dict(section.affected_codes),
        )


class SectionAlignmentPayload(ApiModel):
    available: bool
    sections: tuple[ProjectStage, ...]
    uncovered_codes: tuple[str, ...]

    @classmethod
    def from_domain(cls, alignment: SectionAlignment) -> SectionAlignmentPayload:
        return cls(
            available=alignment.available,
            sections=alignment.sections,
            uncovered_codes=alignment.uncovered_codes,
        )


class ProjectSectionsPayload(ApiModel):
    first_pass_complete: bool
    sections: tuple[SectionPayload, ...]
    alignment: SectionAlignmentPayload
    workflow_inputs: dict | None = Field(default=None, exclude_if=lambda value: value is None)

    @classmethod
    def from_domain(cls, sections: ProjectSections) -> ProjectSectionsPayload:
        return cls(
            first_pass_complete=sections.first_pass_complete,
            sections=tuple(SectionPayload.from_domain(section) for section in sections.sections),
            alignment=SectionAlignmentPayload.from_domain(sections.alignment),
        )


class SectionUpdatePayload(ApiModel):
    key: ProjectStage
    outcome: SectionOutcome
    issue: str | None
    version_number: int | None
    codes: tuple[str, ...]

    @classmethod
    def from_domain(cls, update: SectionUpdate) -> SectionUpdatePayload:
        return cls(
            key=update.key,
            outcome=update.outcome,
            issue=update.issue,
            version_number=update.version_number,
            codes=update.codes,
        )


class SectionsAlignmentPayload(ApiModel):
    status: SectionsAlignmentStatus
    results: tuple[SectionUpdatePayload, ...]
    sections: ProjectSectionsPayload

    @classmethod
    def from_domain(cls, alignment: SectionsAlignment) -> SectionsAlignmentPayload:
        return cls(
            status=alignment.status,
            results=tuple(SectionUpdatePayload.from_domain(item) for item in alignment.results),
            sections=ProjectSectionsPayload.from_domain(alignment.sections),
        )


@dataclass(frozen=True, slots=True)
class TwinLearningSources:
    database_runtime: DatabaseRuntime
    user_modeling_services: UserModelingServices
    real_model_runtime: RealModelRuntime | None = None
    proposal_evidence_store: SqlAlchemyProposalEvidenceStore | None = None


class TwinLearningOverview(Protocol):
    async def overview(self, *, owner_user_id: UUID, project_id: UUID) -> dict[str, object]: ...


class TwinLearningProbe:
    def __init__(self, application: TwinLearningOverview) -> None:
        self._application = application

    async def learned(self, *, owner_user_id: UUID, project_id: UUID) -> bool:
        overview = await self._application.overview(
            owner_user_id=owner_user_id, project_id=project_id
        )
        available = overview["update_available"] is True
        return any(
            entry["pending_update"] is not None
            or (available and any(entry["new_material"].values()))
            for entry in overview["twins"]
        )


class TeamSectionGate:
    def __init__(self, service: LocalAgentTeamApprovalService) -> None:
        self._service = service

    async def current_gate(self, *, project_id: UUID, owner_user_id: UUID):
        return await self._service.current_gate(project_id=project_id, owner_user_id=owner_user_id)

    async def submit(self, *, project_id: UUID, owner_user_id: UUID):
        return await self._service.submit_gate(project_id=project_id, owner_user_id=owner_user_id)

    async def decide(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        action: HumanGateAction,
        reason: str | None = None,
    ):
        return await self._service.decide_gate(
            project_id=project_id, owner_user_id=owner_user_id, action=action, reason=reason
        )


def build_sections_service(
    *,
    database_runtime: DatabaseRuntime,
    user_modeling_services: UserModelingServices,
    user_modeling_realignment_service: UserModelingRealignmentService,
    requirements_realignment_service: RequirementsRealignmentService,
    requirements_gate_service: SectionGate,
    design_realignment_service: DesignRealignmentService,
    design_gate_service: SectionGate,
    real_model_runtime: RealModelRuntime | None = None,
    proposal_evidence_store: SqlAlchemyProposalEvidenceStore | None = None,
    team_realignment_service: TeamRealignmentService | None = None,
    agent_team_service: LocalAgentTeamApprovalService | None = None,
) -> SectionsService:
    return SectionsService(
        reads=SqlAlchemySectionReads(database_runtime.session_factory),
        team=None
        if team_realignment_service is None or agent_team_service is None
        else SectionStep(
            realignment=team_realignment_service,
            gate=TeamSectionGate(agent_team_service),
            failure=TeamRealignmentFailure,
        ),
        user_twins=SectionStep(
            realignment=user_modeling_realignment_service,
            gate=user_modeling_services.gates,
            failure=UserModelingRealignmentFailure,
        ),
        requirements=SectionStep(
            realignment=requirements_realignment_service,
            gate=requirements_gate_service,
            failure=RequirementsRealignmentFailure,
        ),
        design=SectionStep(
            realignment=design_realignment_service,
            gate=design_gate_service,
            failure=DesignRealignmentFailure,
        ),
        design_alignment=design_realignment_service,
        twin_learning=TwinLearningProbe(
            TwinLearningApplication(
                TwinLearningSources(
                    database_runtime=database_runtime,
                    user_modeling_services=user_modeling_services,
                    real_model_runtime=real_model_runtime,
                    proposal_evidence_store=proposal_evidence_store,
                )
            )
        ),
    )


def sections_service_dependency(request: Request) -> SectionsService:
    service = getattr(request.app.state, "sections_service", None)

    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "SECTIONS_SERVICE_UNAVAILABLE"},
        )

    return service


def sections_failure(error: SectionsFailure) -> HTTPException:
    status_code = (
        status.HTTP_404_NOT_FOUND if error.code in _NOT_FOUND_CODES else status.HTTP_409_CONFLICT
    )
    return HTTPException(status_code=status_code, detail={"code": error.code})


def create_sections_router() -> APIRouter:
    router = APIRouter(prefix=SECTIONS_API_PREFIX, tags=["projects"])

    @router.get(
        "",
        response_model=ProjectSectionsPayload,
        operation_id="getProjectSections",
    )
    async def sections_endpoint(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[SectionsService, Depends(sections_service_dependency)],
    ) -> ProjectSectionsPayload:
        try:
            sections = await service.current(owner_user_id=user.id, project_id=project_id)
        except SectionsFailure as error:
            raise sections_failure(error) from error

        result = ProjectSectionsPayload.from_domain(sections)
        inputs_service = getattr(request.app.state, "workflow_inputs_service", None)
        if inputs_service is not None:
            records = await inputs_service.records(owner_user_id=user.id, project_id=project_id)
            if records and (records["decisions"] or records["prototypes"]):
                result.workflow_inputs = records
        return result

    @router.post(
        "/alignment",
        response_model=SectionsAlignmentPayload,
        operation_id="alignProjectSections",
    )
    async def alignment_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[SectionsService, Depends(sections_service_dependency)],
    ) -> SectionsAlignmentPayload:
        try:
            alignment = await service.align(owner_user_id=user.id, project_id=project_id)
        except SectionsFailure as error:
            raise sections_failure(error) from error

        return SectionsAlignmentPayload.from_domain(alignment)

    return router


__all__ = [
    "SECTIONS_API_PREFIX",
    "ProjectSectionsPayload",
    "SectionAlignmentPayload",
    "SectionPayload",
    "SectionUpdatePayload",
    "SectionsAlignmentPayload",
    "TeamSectionGate",
    "TwinLearningOverview",
    "TwinLearningProbe",
    "TwinLearningSources",
    "build_sections_service",
    "create_sections_router",
    "sections_failure",
    "sections_service_dependency",
]
