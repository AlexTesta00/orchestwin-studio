from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict

from orchestwin.api.auth import current_user_dependency
from orchestwin.identity.domain import UserAccount
from orchestwin.knowledge.diagram_service import (
    DiagramSourceVersion,
    ProjectDiagrams,
    ProjectDiagramService,
)
from orchestwin.knowledge.diagrams import MERMAID_VERSION, Diagram, DiagramKind, DiagramStage

DIAGRAMS_API_PREFIX = "/projects/{project_id}"


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DiagramSourceVersionPayload(ApiModel):
    version_id: UUID
    version_number: int
    content_hash: str

    @classmethod
    def from_domain(cls, version: DiagramSourceVersion) -> DiagramSourceVersionPayload:
        return cls(
            version_id=version.version_id,
            version_number=version.version_number,
            content_hash=version.content_hash,
        )


class DiagramPayload(ApiModel):
    key: str
    stage: DiagramStage
    kind: DiagramKind
    subject: str | None
    title: str
    description: str
    path: str
    source: str

    @classmethod
    def from_domain(cls, diagram: Diagram) -> DiagramPayload:
        return cls(
            key=diagram.key,
            stage=diagram.stage,
            kind=diagram.kind,
            subject=diagram.subject,
            title=diagram.title,
            description=diagram.description,
            path=diagram.path,
            source=diagram.source,
        )


class ProjectDiagramsPayload(ApiModel):
    project_id: UUID
    locale: str
    mermaid_version: str
    system_name: str
    requirements: DiagramSourceVersionPayload
    design: DiagramSourceVersionPayload | None
    diagrams: tuple[DiagramPayload, ...]

    @classmethod
    def from_domain(cls, result: ProjectDiagrams) -> ProjectDiagramsPayload:
        return cls(
            project_id=result.project_id,
            locale=result.locale,
            mermaid_version=MERMAID_VERSION,
            system_name=result.system_name,
            requirements=DiagramSourceVersionPayload.from_domain(result.requirements),
            design=(
                None
                if result.design is None
                else DiagramSourceVersionPayload.from_domain(result.design)
            ),
            diagrams=tuple(DiagramPayload.from_domain(item) for item in result.diagrams),
        )


def project_diagram_service_dependency(request: Request) -> ProjectDiagramService:
    service = getattr(request.app.state, "project_diagram_service", None)

    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DIAGRAM_SERVICE_UNAVAILABLE"},
        )

    return service


def create_diagram_router() -> APIRouter:
    router = APIRouter(prefix=DIAGRAMS_API_PREFIX, tags=["artifacts"])

    @router.get(
        "/diagrams",
        response_model=ProjectDiagramsPayload,
        operation_id="getProjectDiagrams",
    )
    async def project_diagrams_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            ProjectDiagramService,
            Depends(project_diagram_service_dependency),
        ],
        locale: Annotated[Literal["en", "it"], Query()] = "en",
    ) -> ProjectDiagramsPayload:
        result = await service.current(
            owner_user_id=user.id,
            project_id=project_id,
            locale=locale,
        )

        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "DIAGRAMS_NOT_FOUND"},
            )

        return ProjectDiagramsPayload.from_domain(result)

    return router


__all__ = [
    "DIAGRAMS_API_PREFIX",
    "DiagramPayload",
    "ProjectDiagramsPayload",
    "create_diagram_router",
    "project_diagram_service_dependency",
]
