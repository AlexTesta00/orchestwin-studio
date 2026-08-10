"""HTTP contracts for projects and immutable Project Brief versions."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from orchestwin.api.auth import (
    current_user_dependency,
)
from orchestwin.identity.domain import UserAccount
from orchestwin.projects.application import (
    ProjectApplicationService,
)
from orchestwin.projects.briefs import (
    BriefField,
    ProjectBrief,
    ProjectBriefVersion,
    create_project_brief,
)
from orchestwin.projects.domain import (
    Project,
    ProjectMode,
)
from orchestwin.projects.repository import (
    BriefVersionCreationStatus,
)


class ProjectCreateRequest(BaseModel):
    """Create an owner-scoped project."""

    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(
        min_length=1,
        max_length=120,
    )
    mode: ProjectMode


class ProjectUpdateRequest(BaseModel):
    """Rename an active project."""

    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(
        min_length=1,
        max_length=120,
    )


class ProjectResponse(BaseModel):
    """Safe project representation."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    display_name: str
    mode: ProjectMode
    current_brief_version: int
    is_archived: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(
        cls,
        project: Project,
    ) -> ProjectResponse:
        """Map a project aggregate into an API response."""
        return cls(
            id=project.id,
            display_name=project.display_name,
            mode=project.mode,
            current_brief_version=(project.current_brief_version),
            is_archived=project.is_archived,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )


class ProjectBriefRequest(BaseModel):
    """Structured partial Project Brief request."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    problem: str | None = None
    goals: list[str] | None = None
    target_users: list[str] | None = None
    domain: str | None = None
    technical_constraints: list[str] | None = None
    temporal_constraints: str | None = None
    budget: str | None = None
    functional_requirements: list[str] | None = None
    non_functional_requirements: list[str] | None = None
    risks: list[str] | None = None
    stakeholders: list[str] | None = None
    available_artifacts: list[str] | None = None
    definition_of_done: list[str] | None = None
    unknown_fields: set[BriefField] = Field(default_factory=set)

    @model_validator(mode="after")
    def validate_unknown_fields(
        self,
    ) -> ProjectBriefRequest:
        """Reject explicit values also marked UNKNOWN."""
        for field in self.unknown_fields:
            value = getattr(
                self,
                field.value,
            )

            if value not in (None, "", []):
                raise ValueError(f"{field.value} cannot be provided and UNKNOWN")

        return self

    def to_domain(self) -> ProjectBrief:
        """Create the normalized immutable domain value."""
        return create_project_brief(
            name=self.name,
            description=self.description,
            problem=self.problem,
            goals=self.goals,
            target_users=self.target_users,
            domain=self.domain,
            technical_constraints=(self.technical_constraints),
            temporal_constraints=(self.temporal_constraints),
            budget=self.budget,
            functional_requirements=(self.functional_requirements),
            non_functional_requirements=(self.non_functional_requirements),
            risks=self.risks,
            stakeholders=self.stakeholders,
            available_artifacts=(self.available_artifacts),
            definition_of_done=(self.definition_of_done),
            unknown_fields=self.unknown_fields,
        )


class ProjectBriefResponse(BaseModel):
    """Structured brief plus its epistemic field states."""

    model_config = ConfigDict(frozen=True)

    name: str | None
    description: str | None
    problem: str | None
    goals: tuple[str, ...] | None
    target_users: tuple[str, ...] | None
    domain: str | None
    technical_constraints: tuple[str, ...] | None
    temporal_constraints: str | None
    budget: str | None
    functional_requirements: tuple[str, ...] | None
    non_functional_requirements: tuple[str, ...] | None
    risks: tuple[str, ...] | None
    stakeholders: tuple[str, ...] | None
    available_artifacts: tuple[str, ...] | None
    definition_of_done: tuple[str, ...] | None
    provided_fields: tuple[BriefField, ...]
    unknown_fields: tuple[BriefField, ...]
    missing_fields: tuple[BriefField, ...]

    @classmethod
    def from_domain(
        cls,
        brief: ProjectBrief,
    ) -> ProjectBriefResponse:
        """Map the complete brief state into the API contract."""
        return cls(
            name=brief.name,
            description=brief.description,
            problem=brief.problem,
            goals=brief.goals,
            target_users=brief.target_users,
            domain=brief.domain,
            technical_constraints=(brief.technical_constraints),
            temporal_constraints=(brief.temporal_constraints),
            budget=brief.budget,
            functional_requirements=(brief.functional_requirements),
            non_functional_requirements=(brief.non_functional_requirements),
            risks=brief.risks,
            stakeholders=brief.stakeholders,
            available_artifacts=(brief.available_artifacts),
            definition_of_done=(brief.definition_of_done),
            provided_fields=tuple(
                sorted(
                    brief.provided_fields,
                    key=lambda field: field.value,
                )
            ),
            unknown_fields=tuple(
                sorted(
                    brief.unknown_fields,
                    key=lambda field: field.value,
                )
            ),
            missing_fields=tuple(
                sorted(
                    brief.missing_fields,
                    key=lambda field: field.value,
                )
            ),
        )


class ProjectBriefVersionResponse(BaseModel):
    """Metadata and content of one immutable brief version."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    version_number: int
    schema_version: int
    content_hash: str
    created_by_user_id: UUID
    created_at: datetime
    brief: ProjectBriefResponse

    @classmethod
    def from_domain(
        cls,
        version: ProjectBriefVersion,
    ) -> ProjectBriefVersionResponse:
        """Map a domain version into the API contract."""
        return cls(
            id=version.id,
            project_id=version.project_id,
            version_number=(version.version_number),
            schema_version=(version.schema_version),
            content_hash=version.content_hash,
            created_by_user_id=(version.created_by_user_id),
            created_at=version.created_at,
            brief=ProjectBriefResponse.from_domain(version.brief),
        )


def project_service_dependency(
    request: Request,
) -> ProjectApplicationService:
    """Return the configured project application service."""
    service = getattr(
        request.app.state,
        "project_service",
        None,
    )

    if service is None:
        raise HTTPException(
            status_code=(status.HTTP_503_SERVICE_UNAVAILABLE),
            detail="project_service_unavailable",
        )

    return service


def project_not_found() -> HTTPException:
    """Return one non-disclosing project lookup error."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="project_not_found",
    )


def create_project_router() -> APIRouter:
    """Create owner-scoped project and brief routes."""
    router = APIRouter(
        prefix="/projects",
        tags=["projects"],
    )

    @router.post(
        "",
        response_model=ProjectResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createProject",
    )
    async def create_project_endpoint(
        payload: ProjectCreateRequest,
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            ProjectApplicationService,
            Depends(project_service_dependency),
        ],
    ) -> ProjectResponse:
        try:
            project = await service.create(
                owner_user_id=user.id,
                display_name=payload.display_name,
                mode=payload.mode,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=(status.HTTP_422_UNPROCESSABLE_CONTENT),
                detail="invalid_project",
            ) from error

        return ProjectResponse.from_domain(project)

    @router.get(
        "",
        response_model=list[ProjectResponse],
        operation_id="listProjects",
    )
    async def list_projects_endpoint(
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            ProjectApplicationService,
            Depends(project_service_dependency),
        ],
    ) -> list[ProjectResponse]:
        projects = await service.list_active(owner_user_id=user.id)

        return [ProjectResponse.from_domain(project) for project in projects]

    @router.get(
        "/{project_id}",
        response_model=ProjectResponse,
        operation_id="getProject",
    )
    async def get_project_endpoint(
        project_id: UUID,
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            ProjectApplicationService,
            Depends(project_service_dependency),
        ],
    ) -> ProjectResponse:
        project = await service.get(
            project_id=project_id,
            owner_user_id=user.id,
        )

        if project is None:
            raise project_not_found()

        return ProjectResponse.from_domain(project)

    @router.patch(
        "/{project_id}",
        response_model=ProjectResponse,
        operation_id="renameProject",
    )
    async def rename_project_endpoint(
        project_id: UUID,
        payload: ProjectUpdateRequest,
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            ProjectApplicationService,
            Depends(project_service_dependency),
        ],
    ) -> ProjectResponse:
        try:
            project = await service.rename(
                project_id=project_id,
                owner_user_id=user.id,
                display_name=payload.display_name,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=(status.HTTP_422_UNPROCESSABLE_CONTENT),
                detail="invalid_project",
            ) from error

        if project is None:
            raise project_not_found()

        return ProjectResponse.from_domain(project)

    @router.delete(
        "/{project_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        operation_id="archiveProject",
    )
    async def archive_project_endpoint(
        project_id: UUID,
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            ProjectApplicationService,
            Depends(project_service_dependency),
        ],
    ) -> None:
        project = await service.archive(
            project_id=project_id,
            owner_user_id=user.id,
        )

        if project is None:
            raise project_not_found()

    @router.post(
        "/{project_id}/brief-versions",
        response_model=ProjectBriefVersionResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createProjectBriefVersion",
    )
    async def create_brief_version_endpoint(
        project_id: UUID,
        payload: ProjectBriefRequest,
        response: Response,
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            ProjectApplicationService,
            Depends(project_service_dependency),
        ],
    ) -> ProjectBriefVersionResponse:
        try:
            brief = payload.to_domain()
        except ValueError as error:
            raise HTTPException(
                status_code=(status.HTTP_422_UNPROCESSABLE_CONTENT),
                detail="invalid_project_brief",
            ) from error

        result = await service.create_brief_version(
            project_id=project_id,
            owner_user_id=user.id,
            brief=brief,
        )

        if result.status is BriefVersionCreationStatus.PROJECT_NOT_FOUND:
            raise project_not_found()

        if result.version is None:
            raise RuntimeError("brief-version result did not contain a version")

        if not result.created:
            response.status_code = status.HTTP_200_OK

        return ProjectBriefVersionResponse.from_domain(result.version)

    @router.get(
        "/{project_id}/brief-versions/current",
        response_model=ProjectBriefVersionResponse,
        operation_id="getCurrentProjectBriefVersion",
    )
    async def current_brief_endpoint(
        project_id: UUID,
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            ProjectApplicationService,
            Depends(project_service_dependency),
        ],
    ) -> ProjectBriefVersionResponse:
        version = await service.current_brief(
            project_id=project_id,
            owner_user_id=user.id,
        )

        if version is None:
            raise project_not_found()

        return ProjectBriefVersionResponse.from_domain(version)

    @router.get(
        "/{project_id}/brief-versions",
        response_model=list[ProjectBriefVersionResponse],
        operation_id="listProjectBriefVersions",
    )
    async def brief_history_endpoint(
        project_id: UUID,
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            ProjectApplicationService,
            Depends(project_service_dependency),
        ],
    ) -> list[ProjectBriefVersionResponse]:
        project = await service.get(
            project_id=project_id,
            owner_user_id=user.id,
        )

        if project is None:
            raise project_not_found()

        versions = await service.brief_history(
            project_id=project_id,
            owner_user_id=user.id,
        )

        return [ProjectBriefVersionResponse.from_domain(version) for version in versions]

    @router.get(
        "/{project_id}/brief-versions/{version_number}",
        response_model=ProjectBriefVersionResponse,
        operation_id="getProjectBriefVersion",
    )
    async def brief_version_endpoint(
        project_id: UUID,
        version_number: int,
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            ProjectApplicationService,
            Depends(project_service_dependency),
        ],
    ) -> ProjectBriefVersionResponse:
        if version_number < 1:
            raise project_not_found()

        version = await service.brief_version(
            project_id=project_id,
            owner_user_id=user.id,
            version_number=version_number,
        )

        if version is None:
            raise project_not_found()

        return ProjectBriefVersionResponse.from_domain(version)

    return router
