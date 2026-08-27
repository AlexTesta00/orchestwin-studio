"""Owner-scoped API contracts for typed Web source, execution, and repair state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from orchestwin.api.auth import current_user_dependency
from orchestwin.artifacts.web_change_sets import WebSourceChangeOperation
from orchestwin.artifacts.web_sources import WebSourceProvenanceKind
from orchestwin.identity.domain import UserAccount
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.web_execution.attempts import WebExecutionAttemptTrigger
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.targets import (
    WebImplementationLanguage,
    WebProjectLayout,
)
from orchestwin.workflow.web_execution import WebExecutionPurpose


class WebApiCommandStatus(StrEnum):
    """Stable command outcomes translated into HTTP status codes."""

    SOURCE_REVISION_CREATED = "SOURCE_REVISION_CREATED"
    EXECUTION_RECORDED = "EXECUTION_RECORDED"
    REPAIR_PROPOSED = "REPAIR_PROPOSED"
    REPAIR_APPLIED = "REPAIR_APPLIED"
    NOT_FOUND = "NOT_FOUND"
    INVALID = "INVALID"
    CONFLICT = "CONFLICT"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    CAPABILITY_BLOCKED = "CAPABILITY_BLOCKED"


@dataclass(frozen=True, slots=True)
class WebSourcePlanFileCommand:
    normalized_path: str
    content: str
    media_type: str


@dataclass(frozen=True, slots=True)
class WebSourceProvenanceCommand:
    kind: WebSourceProvenanceKind
    reference_id: str
    version_number: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class WebSourceRevisionCreateCommand:
    frontend_language: WebImplementationLanguage | None
    backend_language: WebImplementationLanguage | None
    target: ExecutionTarget
    layout: WebProjectLayout
    rationale: str
    files: tuple[WebSourcePlanFileCommand, ...]
    provenance_references: tuple[WebSourceProvenanceCommand, ...]


@dataclass(frozen=True, slots=True)
class WebBrowserRouteCommand:
    route_id: str
    path: str


@dataclass(frozen=True, slots=True)
class WebExecutionStartCommand:
    source_revision_id: UUID
    profile_id: str
    profile_version: str
    policy_content_hash: str
    execution_runner_image_digest: str
    browser_runner_image_digest: str | None
    purpose: WebExecutionPurpose
    trigger: WebExecutionAttemptTrigger
    authorization_id: UUID | None
    rerun_phases: tuple[WebExecutionPhase, ...] | None
    declared_routes: tuple[WebBrowserRouteCommand, ...]


@dataclass(frozen=True, slots=True)
class WebRepairChangeCommand:
    operation: WebSourceChangeOperation
    normalized_path: str
    content: str | None
    media_type: str | None


@dataclass(frozen=True, slots=True)
class WebRepairProposalCreateCommand:
    base_revision_content_hash: str
    failure_signature_digest: str
    changes: tuple[WebRepairChangeCommand, ...]
    rationale: str


@dataclass(frozen=True, slots=True)
class WebRepairProposalApplyCommand:
    base_revision_content_hash: str
    proposal_content_hash: str
    approval_id: UUID | None


@dataclass(frozen=True, slots=True)
class WebApiCommandResult:
    status: WebApiCommandStatus
    snapshot: dict[str, JsonValue] | None
    message: str

    def __post_init__(self) -> None:
        if not self.message or self.message != " ".join(self.message.split()):
            raise ValueError("Web API command message must be normalized")
        success = self.status in {
            WebApiCommandStatus.SOURCE_REVISION_CREATED,
            WebApiCommandStatus.EXECUTION_RECORDED,
            WebApiCommandStatus.REPAIR_PROPOSED,
            WebApiCommandStatus.REPAIR_APPLIED,
        }
        if success != (self.snapshot is not None):
            raise ValueError("Web API command result shape is inconsistent")


class WebExecutionApiService(Protocol):
    """Application port preserving owner/project scope and typed command inputs."""

    async def create_source_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        command: WebSourceRevisionCreateCommand,
    ) -> WebApiCommandResult: ...

    async def source_revision_history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]: ...

    async def source_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        revision_id: UUID,
    ) -> dict[str, JsonValue] | None: ...

    async def start_execution(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        command: WebExecutionStartCommand,
    ) -> WebApiCommandResult: ...

    async def execution_history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]: ...

    async def execution(
        self,
        *,
        owner_user_id: UUID,
        execution_id: UUID,
    ) -> dict[str, JsonValue] | None: ...

    async def execution_report(
        self,
        *,
        owner_user_id: UUID,
        execution_id: UUID,
    ) -> dict[str, JsonValue] | None: ...

    async def browser_evidence(
        self,
        *,
        owner_user_id: UUID,
        execution_id: UUID,
    ) -> dict[str, JsonValue] | None: ...

    async def repair_proposals(
        self,
        *,
        owner_user_id: UUID,
        execution_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]: ...

    async def create_repair_proposal(
        self,
        *,
        owner_user_id: UUID,
        execution_id: UUID,
        command: WebRepairProposalCreateCommand,
    ) -> WebApiCommandResult: ...

    async def apply_repair_proposal(
        self,
        *,
        owner_user_id: UUID,
        execution_id: UUID,
        proposal_id: UUID,
        command: WebRepairProposalApplyCommand,
    ) -> WebApiCommandResult: ...


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WebLanguageConfigurationBody(ApiModel):
    frontend: WebImplementationLanguage | None = None
    backend: WebImplementationLanguage | None = None


class WebTargetSelectionBody(ApiModel):
    target: ExecutionTarget
    language_configuration: WebLanguageConfigurationBody
    layout: WebProjectLayout


class WebSourcePlanFileBody(ApiModel):
    normalized_path: str = Field(min_length=1, max_length=240)
    content: str
    media_type: str = Field(min_length=3, max_length=127)


class WebSourceProvenanceBody(ApiModel):
    kind: WebSourceProvenanceKind
    reference_id: str = Field(min_length=1, max_length=240)
    version_number: int = Field(gt=0)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class CreateWebSourceRevisionBody(ApiModel):
    target_selection: WebTargetSelectionBody
    rationale: str = Field(min_length=1, max_length=1_000)
    files: tuple[WebSourcePlanFileBody, ...] = Field(min_length=1, max_length=1_000)
    provenance_references: tuple[WebSourceProvenanceBody, ...] = Field(
        min_length=1,
        max_length=64,
    )

    def to_command(self) -> WebSourceRevisionCreateCommand:
        configuration = self.target_selection.language_configuration
        return WebSourceRevisionCreateCommand(
            frontend_language=configuration.frontend,
            backend_language=configuration.backend,
            target=self.target_selection.target,
            layout=self.target_selection.layout,
            rationale=self.rationale,
            files=tuple(
                WebSourcePlanFileCommand(
                    normalized_path=item.normalized_path,
                    content=item.content,
                    media_type=item.media_type,
                )
                for item in self.files
            ),
            provenance_references=tuple(
                WebSourceProvenanceCommand(
                    kind=item.kind,
                    reference_id=item.reference_id,
                    version_number=item.version_number,
                    content_hash=item.content_hash,
                )
                for item in self.provenance_references
            ),
        )


class WebRunnerSetBody(ApiModel):
    execution_runner_image_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    browser_runner_image_digest: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )


class WebBrowserRouteBody(ApiModel):
    route_id: str = Field(min_length=1, max_length=128)
    path: str = Field(min_length=1, max_length=240)


class StartWebExecutionBody(ApiModel):
    source_revision_id: UUID
    profile_id: str = Field(min_length=1, max_length=128)
    profile_version: str = Field(min_length=1, max_length=64)
    policy_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    runners: WebRunnerSetBody
    purpose: WebExecutionPurpose
    trigger: WebExecutionAttemptTrigger
    authorization_id: UUID | None = None
    rerun_phases: tuple[WebExecutionPhase, ...] | None = None
    declared_routes: tuple[WebBrowserRouteBody, ...] = Field(default=(), max_length=5)

    def to_command(self) -> WebExecutionStartCommand:
        return WebExecutionStartCommand(
            source_revision_id=self.source_revision_id,
            profile_id=self.profile_id,
            profile_version=self.profile_version,
            policy_content_hash=self.policy_content_hash,
            execution_runner_image_digest=self.runners.execution_runner_image_digest,
            browser_runner_image_digest=self.runners.browser_runner_image_digest,
            purpose=self.purpose,
            trigger=self.trigger,
            authorization_id=self.authorization_id,
            rerun_phases=self.rerun_phases,
            declared_routes=tuple(
                WebBrowserRouteCommand(route_id=item.route_id, path=item.path)
                for item in self.declared_routes
            ),
        )


class WebRepairChangeBody(ApiModel):
    operation: WebSourceChangeOperation
    normalized_path: str = Field(min_length=1, max_length=240)
    content: str | None = None
    media_type: str | None = Field(default=None, min_length=3, max_length=127)

    @model_validator(mode="after")
    def validate_content_shape(self) -> WebRepairChangeBody:
        if self.operation is WebSourceChangeOperation.DELETE:
            if self.content is not None or self.media_type is not None:
                raise ValueError("delete repair changes must not contain file content")
        elif self.content is None or self.media_type is None:
            raise ValueError("add and replace repair changes require content and media type")
        return self


class CreateWebRepairProposalBody(ApiModel):
    base_revision_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    failure_signature_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    changes: tuple[WebRepairChangeBody, ...] = Field(min_length=1, max_length=128)
    rationale: str = Field(min_length=1, max_length=1_000)

    def to_command(self) -> WebRepairProposalCreateCommand:
        return WebRepairProposalCreateCommand(
            base_revision_content_hash=self.base_revision_content_hash,
            failure_signature_digest=self.failure_signature_digest,
            changes=tuple(
                WebRepairChangeCommand(
                    operation=item.operation,
                    normalized_path=item.normalized_path,
                    content=item.content,
                    media_type=item.media_type,
                )
                for item in self.changes
            ),
            rationale=self.rationale,
        )


class ApplyWebRepairProposalBody(ApiModel):
    base_revision_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposal_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_id: UUID | None = None

    def to_command(self) -> WebRepairProposalApplyCommand:
        return WebRepairProposalApplyCommand(
            base_revision_content_hash=self.base_revision_content_hash,
            proposal_content_hash=self.proposal_content_hash,
            approval_id=self.approval_id,
        )


class SnapshotResponse(ApiModel):
    snapshot: dict[str, JsonValue]


class SnapshotListResponse(ApiModel):
    items: tuple[dict[str, JsonValue], ...]


class WebCommandResponse(ApiModel):
    status: WebApiCommandStatus
    snapshot: dict[str, JsonValue]
    message: str


def web_execution_api_service_dependency(request: Request) -> WebExecutionApiService:
    service = getattr(request.app.state, "web_execution_api_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "WEB_EXECUTION_API_SERVICE_UNAVAILABLE"},
        )
    return service


def create_web_execution_router() -> APIRouter:
    router = APIRouter(tags=["web-execution"])

    @router.post(
        "/projects/{project_id}/web-source-revisions",
        response_model=WebCommandResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createWebSourceRevision",
    )
    async def create_source_revision(
        project_id: UUID,
        body: CreateWebSourceRevisionBody,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            WebExecutionApiService,
            Depends(web_execution_api_service_dependency),
        ],
    ) -> WebCommandResponse:
        return _command_response(
            await service.create_source_revision(
                owner_user_id=user.id,
                project_id=project_id,
                command=body.to_command(),
            )
        )

    @router.get(
        "/projects/{project_id}/web-source-revisions",
        response_model=SnapshotListResponse,
        operation_id="listWebSourceRevisions",
    )
    async def list_source_revisions(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            WebExecutionApiService,
            Depends(web_execution_api_service_dependency),
        ],
    ) -> SnapshotListResponse:
        return SnapshotListResponse(
            items=await service.source_revision_history(
                owner_user_id=user.id,
                project_id=project_id,
            )
        )

    @router.get(
        "/projects/{project_id}/web-source-revisions/{revision_id}",
        response_model=SnapshotResponse,
        operation_id="getWebSourceRevision",
    )
    async def get_source_revision(
        project_id: UUID,
        revision_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            WebExecutionApiService,
            Depends(web_execution_api_service_dependency),
        ],
    ) -> SnapshotResponse:
        snapshot = await service.source_revision(
            owner_user_id=user.id,
            project_id=project_id,
            revision_id=revision_id,
        )
        return SnapshotResponse(snapshot=_required_snapshot(snapshot))

    @router.post(
        "/projects/{project_id}/web-executions",
        response_model=WebCommandResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="startWebExecution",
    )
    async def start_execution(
        project_id: UUID,
        body: StartWebExecutionBody,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            WebExecutionApiService,
            Depends(web_execution_api_service_dependency),
        ],
    ) -> WebCommandResponse:
        return _command_response(
            await service.start_execution(
                owner_user_id=user.id,
                project_id=project_id,
                command=body.to_command(),
            )
        )

    @router.get(
        "/projects/{project_id}/web-executions",
        response_model=SnapshotListResponse,
        operation_id="listWebExecutions",
    )
    async def list_executions(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            WebExecutionApiService,
            Depends(web_execution_api_service_dependency),
        ],
    ) -> SnapshotListResponse:
        return SnapshotListResponse(
            items=await service.execution_history(
                owner_user_id=user.id,
                project_id=project_id,
            )
        )

    @router.get(
        "/web-executions/{execution_id}",
        response_model=SnapshotResponse,
        operation_id="getWebExecution",
    )
    async def get_execution(
        execution_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            WebExecutionApiService,
            Depends(web_execution_api_service_dependency),
        ],
    ) -> SnapshotResponse:
        return SnapshotResponse(
            snapshot=_required_snapshot(
                await service.execution(
                    owner_user_id=user.id,
                    execution_id=execution_id,
                )
            )
        )

    @router.get(
        "/web-executions/{execution_id}/report",
        response_model=SnapshotResponse,
        operation_id="getWebExecutionReport",
    )
    async def get_execution_report(
        execution_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            WebExecutionApiService,
            Depends(web_execution_api_service_dependency),
        ],
    ) -> SnapshotResponse:
        return SnapshotResponse(
            snapshot=_required_snapshot(
                await service.execution_report(
                    owner_user_id=user.id,
                    execution_id=execution_id,
                )
            )
        )

    @router.get(
        "/web-executions/{execution_id}/browser-evidence",
        response_model=SnapshotResponse,
        operation_id="getWebBrowserEvidence",
    )
    async def get_browser_evidence(
        execution_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            WebExecutionApiService,
            Depends(web_execution_api_service_dependency),
        ],
    ) -> SnapshotResponse:
        return SnapshotResponse(
            snapshot=_required_snapshot(
                await service.browser_evidence(
                    owner_user_id=user.id,
                    execution_id=execution_id,
                )
            )
        )

    @router.get(
        "/web-executions/{execution_id}/repair-proposals",
        response_model=SnapshotListResponse,
        operation_id="listWebRepairProposals",
    )
    async def list_repair_proposals(
        execution_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            WebExecutionApiService,
            Depends(web_execution_api_service_dependency),
        ],
    ) -> SnapshotListResponse:
        return SnapshotListResponse(
            items=await service.repair_proposals(
                owner_user_id=user.id,
                execution_id=execution_id,
            )
        )

    @router.post(
        "/web-executions/{execution_id}/repair-proposals",
        response_model=WebCommandResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createWebRepairProposal",
    )
    async def create_repair_proposal(
        execution_id: UUID,
        body: CreateWebRepairProposalBody,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            WebExecutionApiService,
            Depends(web_execution_api_service_dependency),
        ],
    ) -> WebCommandResponse:
        return _command_response(
            await service.create_repair_proposal(
                owner_user_id=user.id,
                execution_id=execution_id,
                command=body.to_command(),
            )
        )

    @router.post(
        "/web-executions/{execution_id}/repair-proposals/{proposal_id}/apply",
        response_model=WebCommandResponse,
        operation_id="applyWebRepairProposal",
    )
    async def apply_repair_proposal(
        execution_id: UUID,
        proposal_id: UUID,
        body: ApplyWebRepairProposalBody,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            WebExecutionApiService,
            Depends(web_execution_api_service_dependency),
        ],
    ) -> WebCommandResponse:
        return _command_response(
            await service.apply_repair_proposal(
                owner_user_id=user.id,
                execution_id=execution_id,
                proposal_id=proposal_id,
                command=body.to_command(),
            )
        )

    return router


def _required_snapshot(
    snapshot: dict[str, JsonValue] | None,
) -> dict[str, JsonValue]:
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "WEB_EXECUTION_RESOURCE_NOT_FOUND"},
        )
    return snapshot


def _command_response(result: WebApiCommandResult) -> WebCommandResponse:
    if result.snapshot is not None:
        return WebCommandResponse(
            status=result.status,
            snapshot=result.snapshot,
            message=result.message,
        )
    status_code = {
        WebApiCommandStatus.NOT_FOUND: status.HTTP_404_NOT_FOUND,
        WebApiCommandStatus.INVALID: status.HTTP_422_UNPROCESSABLE_CONTENT,
        WebApiCommandStatus.CONFLICT: status.HTTP_409_CONFLICT,
        WebApiCommandStatus.APPROVAL_REQUIRED: status.HTTP_409_CONFLICT,
        WebApiCommandStatus.CAPABILITY_BLOCKED: status.HTTP_409_CONFLICT,
    }.get(result.status, status.HTTP_409_CONFLICT)
    raise HTTPException(
        status_code=status_code,
        detail={"status": result.status.value, "message": result.message},
    )
