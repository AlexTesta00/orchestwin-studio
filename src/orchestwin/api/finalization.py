"""Owner-scoped API resources for evaluation, Gate 8, and final exports."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from orchestwin.api.auth import current_user_dependency
from orchestwin.identity.domain import UserAccount
from orchestwin.workflow.gates import HumanGateAction


class FinalizationApiStatus(StrEnum):
    """Stable command outcomes at the finalization HTTP boundary."""

    CREATED = "CREATED"
    APPLIED = "APPLIED"
    ALREADY_PRESENT = "ALREADY_PRESENT"
    NOT_FOUND = "NOT_FOUND"
    STATE_CONFLICT = "STATE_CONFLICT"
    REVIEW_NOT_READY = "REVIEW_NOT_READY"
    STALE_REVIEW = "STALE_REVIEW"
    ILLEGAL_STATE = "ILLEGAL_STATE"


@dataclass(frozen=True, slots=True)
class FinalizationApiCommandResult:
    """Typed owner-safe command result containing no hidden model reasoning."""

    status: FinalizationApiStatus
    snapshot: dict[str, JsonValue] | None
    message: str

    def __post_init__(self) -> None:
        if not self.message or self.message != " ".join(self.message.split()):
            raise ValueError("finalization API message must be normalized")
        visible = self.status is not FinalizationApiStatus.NOT_FOUND
        if visible != (self.snapshot is not None):
            raise ValueError("finalization API command result shape is inconsistent")


@dataclass(frozen=True, slots=True)
class SubmitFinalReviewCommand:
    review_id: UUID
    expected_version: int
    expected_content_hash: str
    gate_id: UUID
    event_id: UUID
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class DecideFinalApprovalCommand:
    gate_id: UUID
    action: HumanGateAction
    expected_review_id: UUID
    expected_review_version: int
    expected_review_hash: str
    event_id: UUID
    occurred_at: datetime
    reason: str | None


@dataclass(frozen=True, slots=True)
class CreateFinalExportCommand:
    export_id: UUID
    final_review_id: UUID
    expected_review_version: int
    expected_review_hash: str
    final_approval_gate_id: UUID
    final_approval_event_id: UUID
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class FinalExportDownload:
    """Validated archive bytes and safe response metadata."""

    filename: str
    content: bytes
    content_hash: str

    def __post_init__(self) -> None:
        if (
            not self.filename.endswith(".zip")
            or len(self.filename) > 128
            or any(character in self.filename for character in ("/", "\\", '"', "\r", "\n"))
        ):
            raise ValueError("final export download filename is unsafe")
        if not self.content:
            raise ValueError("final export download content must not be empty")
        if len(self.content_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.content_hash
        ):
            raise ValueError("final export download hash must be lowercase SHA-256")
        if hashlib.sha256(self.content).hexdigest() != self.content_hash:
            raise ValueError("final export download hash does not match its content")


class FinalizationApiService(Protocol):
    """Application port preserving owner scope and exact-version commands."""

    async def evaluation_run(
        self,
        *,
        owner_user_id: UUID,
        evaluation_run_id: UUID,
    ) -> dict[str, JsonValue] | None: ...

    async def evaluation_findings(
        self,
        *,
        owner_user_id: UUID,
        evaluation_run_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...] | None: ...

    async def evaluation_aggregation(
        self,
        *,
        owner_user_id: UUID,
        evaluation_run_id: UUID,
    ) -> dict[str, JsonValue] | None: ...

    async def final_reviews(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]: ...

    async def submit_final_review(
        self,
        *,
        owner_user_id: UUID,
        command: SubmitFinalReviewCommand,
    ) -> FinalizationApiCommandResult: ...

    async def decide_final_approval(
        self,
        *,
        owner_user_id: UUID,
        command: DecideFinalApprovalCommand,
    ) -> FinalizationApiCommandResult: ...

    async def create_export(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        command: CreateFinalExportCommand,
    ) -> FinalizationApiCommandResult: ...

    async def export(
        self,
        *,
        owner_user_id: UUID,
        export_id: UUID,
    ) -> dict[str, JsonValue] | None: ...

    async def download_export(
        self,
        *,
        owner_user_id: UUID,
        export_id: UUID,
    ) -> FinalExportDownload | None: ...


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SubmitFinalReviewBody(ApiModel):
    expected_version: int = Field(gt=0)
    expected_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    gate_id: UUID
    event_id: UUID
    occurred_at: datetime

    def to_command(self, review_id: UUID) -> SubmitFinalReviewCommand:
        return SubmitFinalReviewCommand(
            review_id=review_id,
            expected_version=self.expected_version,
            expected_content_hash=self.expected_content_hash,
            gate_id=self.gate_id,
            event_id=self.event_id,
            occurred_at=self.occurred_at,
        )


class FinalApprovalDecisionBody(ApiModel):
    action: HumanGateAction
    expected_review_id: UUID
    expected_review_version: int = Field(gt=0)
    expected_review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_id: UUID
    occurred_at: datetime
    reason: str | None = Field(default=None, min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def validate_final_action(self) -> FinalApprovalDecisionBody:
        if self.action not in {
            HumanGateAction.APPROVE,
            HumanGateAction.REJECT,
            HumanGateAction.REQUEST_REVISION,
            HumanGateAction.PAUSE,
            HumanGateAction.CANCEL,
        }:
            raise ValueError("unsupported Gate 8 decision action")
        if (
            self.action
            in {
                HumanGateAction.REJECT,
                HumanGateAction.REQUEST_REVISION,
            }
            and self.reason is None
        ):
            raise ValueError("reject and revision decisions require a reason")
        return self

    def to_command(self, gate_id: UUID) -> DecideFinalApprovalCommand:
        return DecideFinalApprovalCommand(
            gate_id=gate_id,
            action=self.action,
            expected_review_id=self.expected_review_id,
            expected_review_version=self.expected_review_version,
            expected_review_hash=self.expected_review_hash,
            event_id=self.event_id,
            occurred_at=self.occurred_at,
            reason=self.reason,
        )


class CreateFinalExportBody(ApiModel):
    export_id: UUID
    final_review_id: UUID
    expected_review_version: int = Field(gt=0)
    expected_review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    final_approval_gate_id: UUID
    final_approval_event_id: UUID
    occurred_at: datetime

    def to_command(self) -> CreateFinalExportCommand:
        return CreateFinalExportCommand(
            export_id=self.export_id,
            final_review_id=self.final_review_id,
            expected_review_version=self.expected_review_version,
            expected_review_hash=self.expected_review_hash,
            final_approval_gate_id=self.final_approval_gate_id,
            final_approval_event_id=self.final_approval_event_id,
            occurred_at=self.occurred_at,
        )


class SnapshotResponse(ApiModel):
    snapshot: dict[str, JsonValue]


class SnapshotListResponse(ApiModel):
    items: tuple[dict[str, JsonValue], ...]


class FinalizationCommandResponse(ApiModel):
    status: FinalizationApiStatus
    snapshot: dict[str, JsonValue]
    message: str


def finalization_api_service_dependency(request: Request) -> FinalizationApiService:
    service = getattr(request.app.state, "finalization_api_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "FINALIZATION_API_SERVICE_UNAVAILABLE"},
        )
    return service


def create_finalization_router() -> APIRouter:
    """Create authenticated synthetic-evaluation, Gate 8, and export routes."""
    router = APIRouter(tags=["finalization"])

    @router.get(
        "/evaluation-runs/{evaluation_run_id}",
        response_model=SnapshotResponse,
        operation_id="getSyntheticEvaluationRun",
    )
    async def get_evaluation_run(
        evaluation_run_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[FinalizationApiService, Depends(finalization_api_service_dependency)],
    ) -> SnapshotResponse:
        return SnapshotResponse(
            snapshot=_required_snapshot(
                await service.evaluation_run(
                    owner_user_id=user.id,
                    evaluation_run_id=evaluation_run_id,
                ),
                code="EVALUATION_RUN_NOT_FOUND",
            )
        )

    @router.get(
        "/evaluation-runs/{evaluation_run_id}/findings",
        response_model=SnapshotListResponse,
        operation_id="listSyntheticEvaluationFindings",
    )
    async def list_evaluation_findings(
        evaluation_run_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[FinalizationApiService, Depends(finalization_api_service_dependency)],
    ) -> SnapshotListResponse:
        findings = await service.evaluation_findings(
            owner_user_id=user.id,
            evaluation_run_id=evaluation_run_id,
        )
        if findings is None:
            raise _not_found("EVALUATION_RUN_NOT_FOUND")
        return SnapshotListResponse(items=findings)

    @router.get(
        "/evaluation-runs/{evaluation_run_id}/aggregation",
        response_model=SnapshotResponse,
        operation_id="getSyntheticEvaluationAggregation",
    )
    async def get_evaluation_aggregation(
        evaluation_run_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[FinalizationApiService, Depends(finalization_api_service_dependency)],
    ) -> SnapshotResponse:
        return SnapshotResponse(
            snapshot=_required_snapshot(
                await service.evaluation_aggregation(
                    owner_user_id=user.id,
                    evaluation_run_id=evaluation_run_id,
                ),
                code="EVALUATION_AGGREGATION_NOT_FOUND",
            )
        )

    @router.get(
        "/projects/{project_id}/final-reviews",
        response_model=SnapshotListResponse,
        operation_id="listFinalReviews",
    )
    async def list_final_reviews(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[FinalizationApiService, Depends(finalization_api_service_dependency)],
    ) -> SnapshotListResponse:
        return SnapshotListResponse(
            items=await service.final_reviews(
                owner_user_id=user.id,
                project_id=project_id,
            )
        )

    @router.post(
        "/final-reviews/{review_id}/submit",
        response_model=FinalizationCommandResponse,
        operation_id="submitFinalReviewForApproval",
    )
    async def submit_final_review(
        review_id: UUID,
        body: SubmitFinalReviewBody,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[FinalizationApiService, Depends(finalization_api_service_dependency)],
    ) -> FinalizationCommandResponse:
        return _command_response(
            await service.submit_final_review(
                owner_user_id=user.id,
                command=body.to_command(review_id),
            )
        )

    @router.post(
        "/final-approval-requests/{gate_id}/decisions",
        response_model=FinalizationCommandResponse,
        operation_id="decideFinalOutputApproval",
    )
    async def decide_final_approval(
        gate_id: UUID,
        body: FinalApprovalDecisionBody,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[FinalizationApiService, Depends(finalization_api_service_dependency)],
    ) -> FinalizationCommandResponse:
        return _command_response(
            await service.decide_final_approval(
                owner_user_id=user.id,
                command=body.to_command(gate_id),
            )
        )

    @router.post(
        "/projects/{project_id}/exports",
        response_model=FinalizationCommandResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createFinalExport",
    )
    async def create_export(
        project_id: UUID,
        body: CreateFinalExportBody,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[FinalizationApiService, Depends(finalization_api_service_dependency)],
    ) -> FinalizationCommandResponse:
        return _command_response(
            await service.create_export(
                owner_user_id=user.id,
                project_id=project_id,
                command=body.to_command(),
            )
        )

    @router.get(
        "/exports/{export_id}",
        response_model=SnapshotResponse,
        operation_id="getFinalExport",
    )
    async def get_export(
        export_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[FinalizationApiService, Depends(finalization_api_service_dependency)],
    ) -> SnapshotResponse:
        return SnapshotResponse(
            snapshot=_required_snapshot(
                await service.export(owner_user_id=user.id, export_id=export_id),
                code="FINAL_EXPORT_NOT_FOUND",
            )
        )

    @router.get(
        "/exports/{export_id}/download",
        response_class=Response,
        operation_id="downloadFinalExport",
        responses={200: {"content": {"application/zip": {}}}},
    )
    async def download_export(
        export_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[FinalizationApiService, Depends(finalization_api_service_dependency)],
    ) -> Response:
        download = await service.download_export(
            owner_user_id=user.id,
            export_id=export_id,
        )
        if download is None:
            raise _not_found("FINAL_EXPORT_NOT_FOUND")
        return Response(
            content=download.content,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{download.filename}"',
                "ETag": f'"sha256:{download.content_hash}"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    return router


def _required_snapshot(
    snapshot: dict[str, JsonValue] | None,
    *,
    code: str,
) -> dict[str, JsonValue]:
    if snapshot is None:
        raise _not_found(code)
    return snapshot


def _not_found(code: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": code},
    )


def _command_response(result: FinalizationApiCommandResult) -> FinalizationCommandResponse:
    if result.snapshot is not None and result.status in {
        FinalizationApiStatus.CREATED,
        FinalizationApiStatus.APPLIED,
        FinalizationApiStatus.ALREADY_PRESENT,
    }:
        return FinalizationCommandResponse(
            status=result.status,
            snapshot=result.snapshot,
            message=result.message,
        )
    if result.status is FinalizationApiStatus.NOT_FOUND:
        raise _not_found("FINALIZATION_RESOURCE_NOT_FOUND")
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"status": result.status.value, "message": result.message},
    )
