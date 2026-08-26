"""FastAPI boundary for execution profiles, sandbox evidence, and Gate 7."""

from __future__ import annotations

from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.clarification import HumanGateEventResponse, HumanGateResponse
from orchestwin.identity.domain import UserAccount
from orchestwin.sandbox.command_plans import CommandNetworkMode
from orchestwin.sandbox.container_runtime import ContainerImageReference
from orchestwin.sandbox.execution_policy import SandboxResourceLimits
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionProfileMetadata,
    ExecutionProfileReference,
)
from orchestwin.sandbox.run_persistence import PersistedProjectSandboxRun
from orchestwin.workflow.gates import HumanGate, HumanGateAction, HumanGateEvent
from orchestwin.workflow.high_impact import (
    HighImpactExecutionRequest,
    HighImpactOperationKind,
    HighImpactOperationReference,
)
from orchestwin.workflow.high_impact_gate import (
    HighImpactApprovalReadiness,
    HighImpactGateDecisionResult,
    HighImpactGateDecisionStatus,
    HighImpactGateSubmissionResult,
    HighImpactGateSubmissionStatus,
    HighImpactReadinessResult,
    HighImpactRequestCreateResult,
    HighImpactRequestCreateStatus,
)
from orchestwin.workflow.high_impact_persistence import PersistedHighImpactOperation


class ExecutionQueryApiService(Protocol):
    """Owner-scoped execution-profile and sandbox evidence queries."""

    async def profiles(self) -> tuple[ExecutionProfileMetadata, ...]: ...

    async def profile(
        self,
        *,
        profile_id: str,
        profile_version: str | None,
    ) -> ExecutionProfileMetadata | None: ...

    async def sandbox_history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[PersistedProjectSandboxRun, ...]: ...

    async def sandbox_run(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
    ) -> PersistedProjectSandboxRun | None: ...


class HighImpactApprovalApiService(Protocol):
    """Gate 7 use cases exposed through structured HTTP commands."""

    async def create_request(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        request: HighImpactExecutionRequest,
    ) -> HighImpactRequestCreateResult: ...

    async def submit_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        expected_reference: HighImpactOperationReference,
    ) -> HighImpactGateSubmissionResult: ...

    async def decide_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        expected_reference: HighImpactOperationReference,
        action: HumanGateAction,
        reason: str | None = None,
    ) -> HighImpactGateDecisionResult: ...

    async def current_operation(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> PersistedHighImpactOperation | None: ...

    async def history(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[PersistedHighImpactOperation, ...]: ...

    async def current_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> HumanGate | None: ...

    async def gate_events(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ) -> tuple[HumanGateEvent, ...]: ...

    async def readiness(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> HighImpactReadinessResult: ...


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SnapshotResponse(ApiModel):
    snapshot: dict[str, JsonValue]


class SnapshotListResponse(ApiModel):
    items: tuple[dict[str, JsonValue], ...]


class SandboxLogsResponse(ApiModel):
    run_id: UUID
    logs: tuple[dict[str, JsonValue], ...]


class ProfileReferenceRequest(ApiModel):
    profile_id: str
    profile_version: str
    content_hash: str

    def to_domain(self) -> ExecutionProfileReference:
        return ExecutionProfileReference(
            profile_id=self.profile_id,
            profile_version=self.profile_version,
            content_hash=self.content_hash,
        )


class ResourceLimitsRequest(ApiModel):
    cpu_count: float = Field(gt=0)
    memory_mib: int = Field(gt=0)
    pids_limit: int = Field(gt=0)
    writable_tmpfs_mib: int = Field(gt=0)

    def to_domain(self) -> SandboxResourceLimits:
        return SandboxResourceLimits(
            cpu_count=self.cpu_count,
            memory_mib=self.memory_mib,
            pids_limit=self.pids_limit,
            writable_tmpfs_mib=self.writable_tmpfs_mib,
        )


class HighImpactOperationRequestBody(ApiModel):
    operation_kind: HighImpactOperationKind
    summary: str
    profile_reference: ProfileReferenceRequest
    capability_status: ExecutionCapabilityStatus
    command_plan_id: str | None = None
    command_plan_content_hash: str | None = None
    image_reference: str | None = None
    network_mode: CommandNetworkMode = CommandNetworkMode.DISABLED
    secret_reference_ids: tuple[str, ...] = ()
    resources: ResourceLimitsRequest
    destructive_workspace_paths: tuple[str, ...] = ()
    requests_privileged_container: bool = False
    requests_docker_socket_mount: bool = False
    requests_host_filesystem_mount: bool = False
    requests_arbitrary_host_command: bool = False

    def to_domain(self, *, project_id: UUID) -> HighImpactExecutionRequest:
        return HighImpactExecutionRequest(
            project_id=project_id,
            operation_kind=self.operation_kind,
            summary=self.summary,
            profile_reference=self.profile_reference.to_domain(),
            capability_status=self.capability_status,
            command_plan_id=self.command_plan_id,
            command_plan_content_hash=self.command_plan_content_hash,
            image_reference=(
                None
                if self.image_reference is None
                else ContainerImageReference(self.image_reference)
            ),
            network_mode=self.network_mode,
            secret_reference_ids=tuple(sorted(set(self.secret_reference_ids))),
            resources=self.resources.to_domain(),
            destructive_workspace_paths=tuple(
                sorted(
                    set(self.destructive_workspace_paths),
                    key=lambda value: (value.casefold(), value),
                )
            ),
            requests_privileged_container=self.requests_privileged_container,
            requests_docker_socket_mount=self.requests_docker_socket_mount,
            requests_host_filesystem_mount=self.requests_host_filesystem_mount,
            requests_arbitrary_host_command=self.requests_arbitrary_host_command,
        )


class HighImpactExpectedReferenceBody(ApiModel):
    version_number: int = Field(gt=0)
    content_hash: str


class HighImpactDecisionBody(HighImpactExpectedReferenceBody):
    action: HumanGateAction
    reason: str | None = None


class HighImpactOperationResponse(ApiModel):
    status: str
    operation: dict[str, JsonValue]
    gate: HumanGateResponse | None = None
    event: HumanGateEventResponse | None = None


class HighImpactReadinessResponse(ApiModel):
    status: HighImpactApprovalReadiness
    operation: dict[str, JsonValue] | None
    gate: HumanGateResponse | None


def execution_query_service_dependency(request: Request) -> ExecutionQueryApiService:
    service = getattr(request.app.state, "execution_query_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "EXECUTION_QUERY_SERVICE_UNAVAILABLE"},
        )
    return service


def high_impact_service_dependency(request: Request) -> HighImpactApprovalApiService:
    service = getattr(request.app.state, "high_impact_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "HIGH_IMPACT_SERVICE_UNAVAILABLE"},
        )
    return service


def create_execution_router() -> APIRouter:
    router = APIRouter(tags=["execution"])

    @router.get(
        "/execution-profiles",
        response_model=SnapshotListResponse,
        operation_id="listExecutionProfiles",
    )
    async def list_profiles(
        service: Annotated[ExecutionQueryApiService, Depends(execution_query_service_dependency)],
    ) -> SnapshotListResponse:
        profiles = await service.profiles()
        return SnapshotListResponse(
            items=tuple(_json_snapshot(profile.to_snapshot()) for profile in profiles)
        )

    @router.get(
        "/execution-profiles/{profile_id}",
        response_model=SnapshotResponse,
        operation_id="getExecutionProfile",
    )
    async def get_profile(
        profile_id: str,
        service: Annotated[ExecutionQueryApiService, Depends(execution_query_service_dependency)],
        profile_version: Annotated[str | None, Query()] = None,
    ) -> SnapshotResponse:
        profile = await service.profile(
            profile_id=profile_id,
            profile_version=profile_version,
        )
        if profile is None:
            raise _not_found("EXECUTION_PROFILE_NOT_FOUND")
        return SnapshotResponse(snapshot=_json_snapshot(profile.to_snapshot()))

    @router.get(
        "/projects/{project_id}/sandbox-runs",
        response_model=SnapshotListResponse,
        operation_id="listProjectSandboxRuns",
    )
    async def list_sandbox_runs(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[ExecutionQueryApiService, Depends(execution_query_service_dependency)],
    ) -> SnapshotListResponse:
        runs = await service.sandbox_history(
            owner_user_id=user.id,
            project_id=project_id,
        )
        return SnapshotListResponse(items=tuple(_json_snapshot(run.to_snapshot()) for run in runs))

    @router.get(
        "/sandbox-runs/{run_id}",
        response_model=SnapshotResponse,
        operation_id="getSandboxRun",
    )
    async def get_sandbox_run(
        run_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[ExecutionQueryApiService, Depends(execution_query_service_dependency)],
    ) -> SnapshotResponse:
        run = await service.sandbox_run(owner_user_id=user.id, run_id=run_id)
        if run is None:
            raise _not_found("SANDBOX_RUN_NOT_FOUND")
        return SnapshotResponse(snapshot=_json_snapshot(run.to_snapshot()))

    @router.get(
        "/sandbox-runs/{run_id}/logs",
        response_model=SandboxLogsResponse,
        operation_id="getSandboxRunLogs",
    )
    async def get_sandbox_logs(
        run_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[ExecutionQueryApiService, Depends(execution_query_service_dependency)],
    ) -> SandboxLogsResponse:
        run = await service.sandbox_run(owner_user_id=user.id, run_id=run_id)
        if run is None:
            raise _not_found("SANDBOX_RUN_NOT_FOUND")
        logs = tuple(
            {
                "command_id": result.command_id,
                "stdout": result.stdout_log,
                "stderr": result.stderr_log,
            }
            for result in run.command_results
        )
        return SandboxLogsResponse(
            run_id=run_id,
            logs=tuple(_json_snapshot(log) for log in logs),
        )

    @router.post(
        "/projects/{project_id}/high-impact-operations",
        response_model=HighImpactOperationResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createHighImpactOperation",
    )
    async def create_high_impact_operation(
        project_id: UUID,
        body: HighImpactOperationRequestBody,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            HighImpactApprovalApiService,
            Depends(high_impact_service_dependency),
        ],
    ) -> HighImpactOperationResponse:
        result = await service.create_request(
            project_id=project_id,
            owner_user_id=user.id,
            request=body.to_domain(project_id=project_id),
        )
        if result.operation is None:
            code = (
                "HIGH_IMPACT_PROJECT_NOT_FOUND"
                if result.status is HighImpactRequestCreateStatus.PROJECT_NOT_FOUND
                else "HIGH_IMPACT_VERSION_CONFLICT"
            )
            raise _operation_error(result.status.value, code)
        return HighImpactOperationResponse(
            status=result.status.value,
            operation=_json_snapshot(result.operation.to_snapshot()),
        )

    @router.get(
        "/projects/{project_id}/high-impact-operations",
        response_model=SnapshotListResponse,
        operation_id="listHighImpactOperations",
    )
    async def list_high_impact_operations(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            HighImpactApprovalApiService,
            Depends(high_impact_service_dependency),
        ],
    ) -> SnapshotListResponse:
        operations = await service.history(
            project_id=project_id,
            owner_user_id=user.id,
        )
        return SnapshotListResponse(
            items=tuple(_json_snapshot(item.to_snapshot()) for item in operations)
        )

    @router.get(
        "/projects/{project_id}/high-impact-operations/current",
        response_model=SnapshotResponse,
        operation_id="getCurrentHighImpactOperation",
    )
    async def get_current_high_impact_operation(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            HighImpactApprovalApiService,
            Depends(high_impact_service_dependency),
        ],
    ) -> SnapshotResponse:
        operation = await service.current_operation(
            project_id=project_id,
            owner_user_id=user.id,
        )
        if operation is None:
            raise _not_found("HIGH_IMPACT_OPERATION_NOT_FOUND")
        return SnapshotResponse(snapshot=_json_snapshot(operation.to_snapshot()))

    @router.post(
        "/projects/{project_id}/high-impact-operations/{request_id}/gate/submit",
        response_model=HighImpactOperationResponse,
        operation_id="submitHighImpactGate",
    )
    async def submit_high_impact_gate(
        project_id: UUID,
        request_id: UUID,
        body: HighImpactExpectedReferenceBody,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            HighImpactApprovalApiService,
            Depends(high_impact_service_dependency),
        ],
    ) -> HighImpactOperationResponse:
        expected = HighImpactOperationReference(
            request_id=request_id,
            project_id=project_id,
            version_number=body.version_number,
            content_hash=body.content_hash,
        )
        result = await service.submit_gate(
            project_id=project_id,
            owner_user_id=user.id,
            expected_reference=expected,
        )
        return _submission_response(result)

    @router.post(
        "/projects/{project_id}/high-impact-operations/{request_id}/gate/decision",
        response_model=HighImpactOperationResponse,
        operation_id="decideHighImpactGate",
    )
    async def decide_high_impact_gate(
        project_id: UUID,
        request_id: UUID,
        body: HighImpactDecisionBody,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            HighImpactApprovalApiService,
            Depends(high_impact_service_dependency),
        ],
    ) -> HighImpactOperationResponse:
        expected = HighImpactOperationReference(
            request_id=request_id,
            project_id=project_id,
            version_number=body.version_number,
            content_hash=body.content_hash,
        )
        result = await service.decide_gate(
            project_id=project_id,
            owner_user_id=user.id,
            expected_reference=expected,
            action=body.action,
            reason=body.reason,
        )
        return _decision_response(result)

    @router.get(
        "/projects/{project_id}/high-impact-operations/{request_id}/gate",
        response_model=HighImpactReadinessResponse,
        operation_id="getHighImpactGate",
    )
    async def get_high_impact_gate(
        project_id: UUID,
        request_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            HighImpactApprovalApiService,
            Depends(high_impact_service_dependency),
        ],
    ) -> HighImpactReadinessResponse:
        readiness = await service.readiness(
            project_id=project_id,
            owner_user_id=user.id,
        )
        operation = readiness.operation
        if operation is None or operation.version.id != request_id:
            raise _not_found("HIGH_IMPACT_OPERATION_NOT_FOUND")
        return HighImpactReadinessResponse(
            status=readiness.status,
            operation=_json_snapshot(operation.to_snapshot()),
            gate=(
                None if readiness.gate is None else HumanGateResponse.from_domain(readiness.gate)
            ),
        )

    @router.get(
        "/projects/{project_id}/high-impact-operations/{request_id}/gate/events",
        response_model=tuple[HumanGateEventResponse, ...],
        operation_id="listHighImpactGateEvents",
    )
    async def list_high_impact_gate_events(
        project_id: UUID,
        request_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            HighImpactApprovalApiService,
            Depends(high_impact_service_dependency),
        ],
    ) -> tuple[HumanGateEventResponse, ...]:
        operation = await service.current_operation(
            project_id=project_id,
            owner_user_id=user.id,
        )
        gate = await service.current_gate(
            project_id=project_id,
            owner_user_id=user.id,
        )
        if operation is None or operation.version.id != request_id or gate is None:
            raise _not_found("HIGH_IMPACT_GATE_NOT_FOUND")
        events = await service.gate_events(
            project_id=project_id,
            owner_user_id=user.id,
            gate_id=gate.id,
        )
        return tuple(HumanGateEventResponse.from_domain(event) for event in events)

    return router


def _submission_response(result: HighImpactGateSubmissionResult) -> HighImpactOperationResponse:
    if result.operation is None:
        raise _operation_error(result.status.value, "HIGH_IMPACT_OPERATION_NOT_FOUND")
    if result.status not in {
        HighImpactGateSubmissionStatus.SUBMITTED,
        HighImpactGateSubmissionStatus.ALREADY_PENDING,
        HighImpactGateSubmissionStatus.ALREADY_APPROVED,
    }:
        raise _operation_error(result.status.value, "HIGH_IMPACT_GATE_SUBMISSION_REJECTED")
    return HighImpactOperationResponse(
        status=result.status.value,
        operation=_json_snapshot(result.operation.to_snapshot()),
        gate=None if result.gate is None else HumanGateResponse.from_domain(result.gate),
        event=(None if result.event is None else HumanGateEventResponse.from_domain(result.event)),
    )


def _decision_response(result: HighImpactGateDecisionResult) -> HighImpactOperationResponse:
    if result.operation is None:
        raise _operation_error(result.status.value, "HIGH_IMPACT_OPERATION_NOT_FOUND")
    if result.status not in {
        HighImpactGateDecisionStatus.APPLIED,
        HighImpactGateDecisionStatus.NO_CHANGE,
    }:
        raise _operation_error(result.status.value, "HIGH_IMPACT_GATE_DECISION_REJECTED")
    return HighImpactOperationResponse(
        status=result.status.value,
        operation=_json_snapshot(result.operation.to_snapshot()),
        gate=None if result.gate is None else HumanGateResponse.from_domain(result.gate),
        event=(None if result.event is None else HumanGateEventResponse.from_domain(result.event)),
    )


def _operation_error(operation_status: str, code: str) -> HTTPException:
    not_found = operation_status in {
        HighImpactRequestCreateStatus.PROJECT_NOT_FOUND.value,
        HighImpactGateSubmissionStatus.REQUEST_NOT_FOUND.value,
        HighImpactGateDecisionStatus.REQUEST_NOT_FOUND.value,
        HighImpactGateDecisionStatus.GATE_NOT_FOUND.value,
    }
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND if not_found else status.HTTP_409_CONFLICT,
        detail={"code": code, "status": operation_status},
    )


def _not_found(code: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": code})


def _json_snapshot(value: dict[str, object]) -> dict[str, JsonValue]:
    return value  # type: ignore[return-value]
