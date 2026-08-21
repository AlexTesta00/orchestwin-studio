"""FastAPI boundary for cross-stage artifact traceability and export."""

from __future__ import annotations

from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict

from orchestwin.api.auth import current_user_dependency
from orchestwin.artifacts.references import ArtifactKind, VersionedArtifactReference
from orchestwin.artifacts.traceability import (
    ArtifactGraphLink,
    ArtifactGraphLinkKind,
    ArtifactGraphNode,
    ArtifactGraphNodeKind,
    ArtifactGraphReference,
    ArtifactGraphStage,
    CrossStageArtifactGraph,
)
from orchestwin.identity.domain import UserAccount
from orchestwin.projects.requirements_primitives import canonical_json

ARTIFACT_GRAPH_API_PREFIX = "/projects/{project_id}/artifacts"


class ArtifactGraphQueryService(Protocol):
    """Owner-scoped graph query required by the HTTP adapter."""

    async def current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> CrossStageArtifactGraph | None:
        """Return the graph derived from current immutable artifact versions."""


class ApiModel(BaseModel):
    """Strict base model for artifact graph API contracts."""

    model_config = ConfigDict(extra="forbid")


class VersionedArtifactReferencePayload(ApiModel):
    """Exact identity, version, and hash of one governed stage root."""

    kind: ArtifactKind
    artifact_id: UUID
    version_number: int
    content_hash: str

    @classmethod
    def from_domain(
        cls,
        reference: VersionedArtifactReference,
    ) -> VersionedArtifactReferencePayload:
        """Map one exact domain reference."""
        return cls(
            kind=reference.kind,
            artifact_id=reference.artifact_id,
            version_number=reference.version_number,
            content_hash=reference.content_hash,
        )


class ArtifactGraphReferencePayload(ApiModel):
    """Stable graph node reference with optional exact version metadata."""

    kind: ArtifactGraphNodeKind
    artifact_id: UUID
    version_number: int | None
    content_hash: str | None

    @classmethod
    def from_domain(
        cls,
        reference: ArtifactGraphReference,
    ) -> ArtifactGraphReferencePayload:
        """Map one graph reference."""
        return cls(
            kind=reference.kind,
            artifact_id=reference.artifact_id,
            version_number=reference.version_number,
            content_hash=reference.content_hash,
        )


class ArtifactGraphNodePayload(ApiModel):
    """One inspectable artifact graph node."""

    reference: ArtifactGraphReferencePayload
    stage: ArtifactGraphStage
    display_code: str
    title: str

    @classmethod
    def from_domain(cls, node: ArtifactGraphNode) -> ArtifactGraphNodePayload:
        """Map one graph node."""
        return cls(
            reference=ArtifactGraphReferencePayload.from_domain(node.reference),
            stage=node.stage,
            display_code=node.display_code,
            title=node.title,
        )


class ArtifactGraphLinkPayload(ApiModel):
    """One semantic relationship between artifact graph nodes."""

    kind: ArtifactGraphLinkKind
    source: ArtifactGraphReferencePayload
    target: ArtifactGraphReferencePayload

    @classmethod
    def from_domain(cls, link: ArtifactGraphLink) -> ArtifactGraphLinkPayload:
        """Map one graph relationship."""
        return cls(
            kind=link.kind,
            source=ArtifactGraphReferencePayload.from_domain(link.source),
            target=ArtifactGraphReferencePayload.from_domain(link.target),
        )


class CrossStageArtifactGraphPayload(ApiModel):
    """Export-ready traceability graph for the current governed workflow state."""

    schema_version: int
    project_id: UUID
    requirements_reference: VersionedArtifactReferencePayload
    design_reference: VersionedArtifactReferencePayload | None
    architecture_reference: VersionedArtifactReferencePayload | None
    nodes: tuple[ArtifactGraphNodePayload, ...]
    links: tuple[ArtifactGraphLinkPayload, ...]
    stage_counts: dict[ArtifactGraphStage, int]
    content_hash: str

    @classmethod
    def from_domain(
        cls,
        graph: CrossStageArtifactGraph,
    ) -> CrossStageArtifactGraphPayload:
        """Map one canonical domain graph and its derived summary."""
        return cls(
            schema_version=1,
            project_id=graph.project_id,
            requirements_reference=VersionedArtifactReferencePayload.from_domain(
                graph.requirements_reference
            ),
            design_reference=(
                None
                if graph.design_reference is None
                else VersionedArtifactReferencePayload.from_domain(graph.design_reference)
            ),
            architecture_reference=(
                None
                if graph.architecture_reference is None
                else VersionedArtifactReferencePayload.from_domain(graph.architecture_reference)
            ),
            nodes=tuple(ArtifactGraphNodePayload.from_domain(node) for node in graph.nodes),
            links=tuple(ArtifactGraphLinkPayload.from_domain(link) for link in graph.links),
            stage_counts={
                stage.value: sum(node.stage is stage for node in graph.nodes)
                for stage in ArtifactGraphStage
            },
            content_hash=graph.content_hash,
        )


def artifact_graph_query_service_dependency(
    request: Request,
) -> ArtifactGraphQueryService:
    """Resolve the application-scoped artifact graph query service."""
    service = getattr(request.app.state, "artifact_graph_query_service", None)

    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "ARTIFACT_GRAPH_SERVICE_UNAVAILABLE"},
        )

    return service


def create_artifact_graph_router() -> APIRouter:
    """Create the owner-scoped artifact traceability router."""
    router = APIRouter(prefix=ARTIFACT_GRAPH_API_PREFIX, tags=["artifacts"])

    @router.get(
        "/graph",
        response_model=CrossStageArtifactGraphPayload,
        operation_id="getCurrentArtifactGraph",
    )
    async def current_graph_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            ArtifactGraphQueryService,
            Depends(artifact_graph_query_service_dependency),
        ],
    ) -> CrossStageArtifactGraphPayload:
        graph = await service.current(
            owner_user_id=user.id,
            project_id=project_id,
        )

        if graph is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "ARTIFACT_GRAPH_NOT_FOUND"},
            )

        return CrossStageArtifactGraphPayload.from_domain(graph)

    @router.get(
        "/graph/export",
        response_class=Response,
        operation_id="exportCurrentArtifactGraph",
    )
    async def export_graph_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            ArtifactGraphQueryService,
            Depends(artifact_graph_query_service_dependency),
        ],
    ) -> Response:
        graph = await service.current(
            owner_user_id=user.id,
            project_id=project_id,
        )

        if graph is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "ARTIFACT_GRAPH_NOT_FOUND"},
            )

        payload = CrossStageArtifactGraphPayload.from_domain(graph)
        filename = f"orchestwin-{project_id}-artifact-graph.json"

        return Response(
            content=canonical_json(payload.model_dump(mode="json")),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Content-SHA256": graph.content_hash,
            },
        )

    return router


__all__ = [
    "ARTIFACT_GRAPH_API_PREFIX",
    "ArtifactGraphQueryService",
    "CrossStageArtifactGraphPayload",
    "create_artifact_graph_router",
]
