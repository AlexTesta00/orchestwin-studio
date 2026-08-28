"""Owner-scoped API contracts for JVM source, execution, and repair state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from orchestwin.api.auth import current_user_dependency
from orchestwin.artifacts.jvm_change_sets import JvmSourceChangeOperation
from orchestwin.artifacts.jvm_sources import JvmSourceProvenanceKind
from orchestwin.identity.domain import UserAccount
from orchestwin.jvm_execution.attempts import JvmExecutionAttemptTrigger
from orchestwin.jvm_execution.plans import JvmExecutionPhase
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.workflow.jvm_execution import JvmExecutionPurpose


class JvmApiCommandStatus(StrEnum):
    """Stable JVM command outcomes translated into HTTP status codes."""

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
class JvmSourcePlanFileCommand:
    normalized_path: str
    content: str
    media_type: str


@dataclass(frozen=True, slots=True)
class JvmSourceProvenanceCommand:
    kind: JvmSourceProvenanceKind
    reference_id: str
    version_number: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class JvmSourceRevisionCreateCommand:
    target: ExecutionTarget
    rationale: str
    files: tuple[JvmSourcePlanFileCommand, ...]
    provenance_references: tuple[JvmSourceProvenanceCommand, ...]


@dataclass(frozen=True, slots=True)
class JvmExecutionStartCommand:
    source_revision_id: UUID
    profile_id: str
    profile_version: str
    policy_content_hash: str
    runner_image_digest: str
    purpose: JvmExecutionPurpose
    trigger: JvmExecutionAttemptTrigger
    authorization_id: UUID | None
    rerun_phases: tuple[JvmExecutionPhase, ...] | None


@dataclass(frozen=True, slots=True)
class JvmRepairChangeCommand:
    operation: JvmSourceChangeOperation
    normalized_path: str
    content: str | None
    media_type: str | None


@dataclass(frozen=True, slots=True)
class JvmRepairProposalCreateCommand:
    base_revision_content_hash: str
    failure_signature: str
    changes: tuple[JvmRepairChangeCommand, ...]
    rationale: str


@dataclass(frozen=True, slots=True)
class JvmRepairProposalApplyCommand:
    base_revision_content_hash: str
    proposal_content_hash: str
    approval_id: UUID | None


@dataclass(frozen=True, slots=True)
class JvmApiCommandResult:
    status: JvmApiCommandStatus
    snapshot: dict[str, JsonValue] | None
    message: str

    def __post_init__(self) -> None:
        if not self.message or self.message != " ".join(self.message.split()):
            raise ValueError("JVM API command message must be normalized")
        success = self.status in {
            JvmApiCommandStatus.SOURCE_REVISION_CREATED,
            JvmApiCommandStatus.EXECUTION_RECORDED,
            JvmApiCommandStatus.REPAIR_PROPOSED,
            JvmApiCommandStatus.REPAIR_APPLIED,
        }
        if success != (self.snapshot is not None):
            raise ValueError("JVM API command result shape is inconsistent")


class JvmExecutionApiService(Protocol):
    """Application port preserving owner/project scope and typed inputs."""

    async def profiles(
        self,
        *,
        owner_user_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]: ...

    async def create_source_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        command: JvmSourceRevisionCreateCommand,
    ) -> JvmApiCommandResult: ...

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
        command: JvmExecutionStartCommand,
    ) -> JvmApiCommandResult: ...

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
        command: JvmRepairProposalCreateCommand,
    ) -> JvmApiCommandResult: ...

    async def apply_repair_proposal(
        self,
        *,
        owner_user_id: UUID,
        execution_id: UUID,
        proposal_id: UUID,
        command: JvmRepairProposalApplyCommand,
    ) -> JvmApiCommandResult: ...


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JvmSourcePlanFileBody(ApiModel):
    normalized_path: str = Field(min_length=1, max_length=240)
    content: str
    media_type: str = Field(min_length=3, max_length=127)


class JvmSourceProvenanceBody(ApiModel):
    kind: JvmSourceProvenanceKind
    reference_id: str = Field(min_length=1, max_length=240)
    version_number: int = Field(gt=0)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class CreateJvmSourceRevisionBody(ApiModel):
    target: ExecutionTarget
    rationale: str = Field(min_length=1, max_length=1_000)
    files: tuple[JvmSourcePlanFileBody, ...] = Field(min_length=1, max_length=1_000)
    provenance_references: tuple[JvmSourceProvenanceBody, ...] = Field(
        min_length=1,
        max_length=64,
    )

    @model_validator(mode="after")
    def require_jvm_target(self) -> CreateJvmSourceRevisionBody:
        if self.target not in {
            ExecutionTarget.JVM_JAVA,
            ExecutionTarget.JVM_KOTLIN,
            ExecutionTarget.JVM_SCALA,
        }:
            raise ValueError("source revision requires a JVM-only target")
        return self

    def to_command(self) -> JvmSourceRevisionCreateCommand:
        return JvmSourceRevisionCreateCommand(
            target=self.target,
            rationale=self.rationale,
            files=tuple(
                JvmSourcePlanFileCommand(
                    normalized_path=item.normalized_path,
                    content=item.content,
                    media_type=item.media_type,
                )
                for item in self.files
            ),
            provenance_references=tuple(
                JvmSourceProvenanceCommand(
                    kind=item.kind,
                    reference_id=item.reference_id,
                    version_number=item.version_number,
                    content_hash=item.content_hash,
                )
                for item in self.provenance_references
            ),
        )


class StartJvmExecutionBody(ApiModel):
    source_revision_id: UUID
    profile_id: str = Field(min_length=1, max_length=128)
    profile_version: str = Field(min_length=1, max_length=64)
    policy_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    runner_image_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    purpose: JvmExecutionPurpose
    trigger: JvmExecutionAttemptTrigger
    authorization_id: UUID | None = None
    rerun_phases: tuple[JvmExecutionPhase, ...] | None = None

    def to_command(self) -> JvmExecutionStartCommand:
        return JvmExecutionStartCommand(
            source_revision_id=self.source_revision_id,
            profile_id=self.profile_id,
            profile_version=self.profile_version,
            policy_content_hash=self.policy_content_hash,
            runner_image_digest=self.runner_image_digest,
            purpose=self.purpose,
            trigger=self.trigger,
            authorization_id=self.authorization_id,
            rerun_phases=self.rerun_phases,
        )


class JvmRepairChangeBody(ApiModel):
    operation: JvmSourceChangeOperation
    normalized_path: str = Field(min_length=1, max_length=240)
    content: str | None = None
    media_type: str | None = Field(default=None, min_length=3, max_length=127)

    @model_validator(mode="after")
    def validate_operation_shape(self) -> JvmRepairChangeBody:
        if self.operation is JvmSourceChangeOperation.DELETE:
            if self.content is not None or self.media_type is not None:
                raise ValueError("DELETE must not carry replacement content")
        elif self.content is None or self.media_type is None:
            raise ValueError("ADD and REPLACE require content and media type")
        return self


class CreateJvmRepairProposalBody(ApiModel):
    base_revision_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    failure_signature: str = Field(pattern=r"^[0-9a-f]{64}$")
    changes: tuple[JvmRepairChangeBody, ...] = Field(min_length=1, max_length=128)
    rationale: str = Field(min_length=1, max_length=1_000)

    def to_command(self) -> JvmRepairProposalCreateCommand:
        return JvmRepairProposalCreateCommand(
            base_revision_content_hash=self.base_revision_content_hash,
            failure_signature=self.failure_signature,
            changes=tuple(
                JvmRepairChangeCommand(
                    operation=item.operation,
                    normalized_path=item.normalized_path,
                    content=item.content,
                    media_type=item.media_type,
                )
                for item in self.changes
            ),
            rationale=self.rationale,
        )


class ApplyJvmRepairProposalBody(ApiModel):
    base_revision_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposal_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_id: UUID | None = None

    def to_command(self) -> JvmRepairProposalApplyCommand:
        return JvmRepairProposalApplyCommand(
            base_revision_content_hash=self.base_revision_content_hash,
            proposal_content_hash=self.proposal_content_hash,
            approval_id=self.approval_id,
        )


class SnapshotResponse(ApiModel):
    snapshot: dict[str, JsonValue]


class SnapshotListResponse(ApiModel):
    items: tuple[dict[str, JsonValue], ...]


class JvmCommandResponse(ApiModel):
    status: JvmApiCommandStatus
    snapshot: dict[str, JsonValue]
    message: str


def jvm_execution_api_service_dependency(request: Request) -> JvmExecutionApiService:
    service = getattr(request.app.state, "jvm_execution_api_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "JVM_EXECUTION_API_SERVICE_UNAVAILABLE"},
        )
    return service


def create_jvm_execution_router() -> APIRouter:
    router = APIRouter(tags=["jvm-execution"])

    @router.get(
        "/jvm-execution-profiles",
        response_model=SnapshotListResponse,
        operation_id="listJvmExecutionProfiles",
    )
    async def list_profiles(
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            JvmExecutionApiService,
            Depends(jvm_execution_api_service_dependency),
        ],
    ) -> SnapshotListResponse:
        return SnapshotListResponse(items=await service.profiles(owner_user_id=user.id))

    @router.post(
        "/projects/{project_id}/jvm-source-revisions",
        response_model=JvmCommandResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createJvmSourceRevision",
    )
    async def create_source_revision(
        project_id: UUID,
        body: CreateJvmSourceRevisionBody,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            JvmExecutionApiService,
            Depends(jvm_execution_api_service_dependency),
        ],
    ) -> JvmCommandResponse:
        return _command_response(
            await service.create_source_revision(
                owner_user_id=user.id,
                project_id=project_id,
                command=body.to_command(),
            )
        )

    @router.get(
        "/projects/{project_id}/jvm-source-revisions",
        response_model=SnapshotListResponse,
        operation_id="listJvmSourceRevisions",
    )
    async def list_source_revisions(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            JvmExecutionApiService,
            Depends(jvm_execution_api_service_dependency),
        ],
    ) -> SnapshotListResponse:
        return SnapshotListResponse(
            items=await service.source_revision_history(
                owner_user_id=user.id,
                project_id=project_id,
            )
        )

    @router.get(
        "/projects/{project_id}/jvm-source-revisions/{revision_id}",
        response_model=SnapshotResponse,
        operation_id="getJvmSourceRevision",
    )
    async def get_source_revision(
        project_id: UUID,
        revision_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            JvmExecutionApiService,
            Depends(jvm_execution_api_service_dependency),
        ],
    ) -> SnapshotResponse:
        return SnapshotResponse(
            snapshot=_required_snapshot(
                await service.source_revision(
                    owner_user_id=user.id,
                    project_id=project_id,
                    revision_id=revision_id,
                )
            )
        )

    @router.post(
        "/projects/{project_id}/jvm-executions",
        response_model=JvmCommandResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="startJvmExecution",
    )
    async def start_execution(
        project_id: UUID,
        body: StartJvmExecutionBody,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            JvmExecutionApiService,
            Depends(jvm_execution_api_service_dependency),
        ],
    ) -> JvmCommandResponse:
        return _command_response(
            await service.start_execution(
                owner_user_id=user.id,
                project_id=project_id,
                command=body.to_command(),
            )
        )

    @router.get(
        "/projects/{project_id}/jvm-executions",
        response_model=SnapshotListResponse,
        operation_id="listJvmExecutions",
    )
    async def list_executions(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            JvmExecutionApiService,
            Depends(jvm_execution_api_service_dependency),
        ],
    ) -> SnapshotListResponse:
        return SnapshotListResponse(
            items=await service.execution_history(
                owner_user_id=user.id,
                project_id=project_id,
            )
        )

    @router.get(
        "/jvm-executions/{execution_id}",
        response_model=SnapshotResponse,
        operation_id="getJvmExecution",
    )
    async def get_execution(
        execution_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            JvmExecutionApiService,
            Depends(jvm_execution_api_service_dependency),
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
        "/jvm-executions/{execution_id}/report",
        response_model=SnapshotResponse,
        operation_id="getJvmExecutionReport",
    )
    async def get_execution_report(
        execution_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            JvmExecutionApiService,
            Depends(jvm_execution_api_service_dependency),
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
        "/jvm-executions/{execution_id}/repair-proposals",
        response_model=SnapshotListResponse,
        operation_id="listJvmRepairProposals",
    )
    async def list_repair_proposals(
        execution_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            JvmExecutionApiService,
            Depends(jvm_execution_api_service_dependency),
        ],
    ) -> SnapshotListResponse:
        return SnapshotListResponse(
            items=await service.repair_proposals(
                owner_user_id=user.id,
                execution_id=execution_id,
            )
        )

    @router.post(
        "/jvm-executions/{execution_id}/repair-proposals",
        response_model=JvmCommandResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createJvmRepairProposal",
    )
    async def create_repair_proposal(
        execution_id: UUID,
        body: CreateJvmRepairProposalBody,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            JvmExecutionApiService,
            Depends(jvm_execution_api_service_dependency),
        ],
    ) -> JvmCommandResponse:
        return _command_response(
            await service.create_repair_proposal(
                owner_user_id=user.id,
                execution_id=execution_id,
                command=body.to_command(),
            )
        )

    @router.post(
        "/jvm-executions/{execution_id}/repair-proposals/{proposal_id}/apply",
        response_model=JvmCommandResponse,
        operation_id="applyJvmRepairProposal",
    )
    async def apply_repair_proposal(
        execution_id: UUID,
        proposal_id: UUID,
        body: ApplyJvmRepairProposalBody,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            JvmExecutionApiService,
            Depends(jvm_execution_api_service_dependency),
        ],
    ) -> JvmCommandResponse:
        return _command_response(
            await service.apply_repair_proposal(
                owner_user_id=user.id,
                execution_id=execution_id,
                proposal_id=proposal_id,
                command=body.to_command(),
            )
        )

    return router


def _required_snapshot(snapshot: dict[str, JsonValue] | None) -> dict[str, JsonValue]:
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "JVM_EXECUTION_RESOURCE_NOT_FOUND"},
        )
    return snapshot


def _command_response(result: JvmApiCommandResult) -> JvmCommandResponse:
    if result.snapshot is not None:
        return JvmCommandResponse(
            status=result.status,
            snapshot=result.snapshot,
            message=result.message,
        )
    status_code = {
        JvmApiCommandStatus.NOT_FOUND: status.HTTP_404_NOT_FOUND,
        JvmApiCommandStatus.INVALID: status.HTTP_422_UNPROCESSABLE_CONTENT,
        JvmApiCommandStatus.CONFLICT: status.HTTP_409_CONFLICT,
        JvmApiCommandStatus.APPROVAL_REQUIRED: status.HTTP_409_CONFLICT,
        JvmApiCommandStatus.CAPABILITY_BLOCKED: status.HTTP_409_CONFLICT,
    }.get(result.status, status.HTTP_409_CONFLICT)
    raise HTTPException(
        status_code=status_code,
        detail={"status": result.status.value, "message": result.message},
    )
