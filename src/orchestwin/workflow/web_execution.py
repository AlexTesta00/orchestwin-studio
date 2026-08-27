"""Governed Web profile execution, failure stopping, and evidence persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from orchestwin.artifacts.web_sources import WebSourceRevision
from orchestwin.sandbox.command_plans import CommandNetworkMode
from orchestwin.sandbox.execution_profiles import ExecutionCapabilityStatus
from orchestwin.web_execution.attempt_persistence import (
    WebExecutionAttemptAppendStatus,
    WebExecutionAttemptRepository,
)
from orchestwin.web_execution.attempts import (
    WebExecutionAttempt,
    WebExecutionAttemptTrigger,
)
from orchestwin.web_execution.browser_evidence import WebBrowserRouteSpec
from orchestwin.web_execution.detection import WebDetectionSnapshot
from orchestwin.web_execution.lockfiles import WebDependencyLockReport
from orchestwin.web_execution.plans import (
    WebExecutionPhase,
    WebPhaseExecutionKind,
    WebPhasePlan,
)
from orchestwin.web_execution.profile_contracts import (
    WebProfileContract,
    WebProfileRunnerSet,
)
from orchestwin.web_execution.profile_registry import WebExecutionProfileRegistry
from orchestwin.web_execution.reports import (
    WebExecutionReport,
    WebPhaseResult,
    WebPhaseResultStatus,
    create_web_no_op_phase_result,
)
from orchestwin.web_execution.targets import WebTargetSelection


class WebExecutionPurpose(StrEnum):
    """Separate profile validation from owner-facing capability claims."""

    OWNER_PROJECT = "OWNER_PROJECT"
    PROFILE_VALIDATION = "PROFILE_VALIDATION"


class WebExecutionAuthorizationKind(StrEnum):
    """Exact authority used for one governed execution request."""

    GATE_7 = "GATE_7"
    PROFILE_VALIDATION = "PROFILE_VALIDATION"


class WebExecutionServiceStatus(StrEnum):
    """Typed application outcomes without false execution success."""

    RECORDED = "RECORDED"
    PROFILE_NOT_FOUND = "PROFILE_NOT_FOUND"
    PROFILE_INVALID = "PROFILE_INVALID"
    CAPABILITY_BLOCKED = "CAPABILITY_BLOCKED"
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"
    AUTHORIZATION_MISMATCH = "AUTHORIZATION_MISMATCH"
    RERUN_INVALID = "RERUN_INVALID"
    PERSISTENCE_CONFLICT = "PERSISTENCE_CONFLICT"


@dataclass(frozen=True, slots=True)
class WebExecutionAuthorization:
    """Approval bound to the exact execution-sensitive tuple."""

    authorization_id: UUID
    kind: WebExecutionAuthorizationKind
    project_id: UUID
    source_revision_content_hash: str
    profile_validation_content_hash: str
    execution_plan_content_hash: str
    policy_content_hash: str
    execution_runner_image_digest: str
    browser_runner_image_digest: str | None
    authorized_by_user_id: UUID

    def __post_init__(self) -> None:
        for value, label in (
            (self.source_revision_content_hash, "authorization source revision hash"),
            (self.profile_validation_content_hash, "authorization profile validation hash"),
            (self.execution_plan_content_hash, "authorization execution plan hash"),
            (self.policy_content_hash, "authorization policy hash"),
            (self.execution_runner_image_digest, "authorization execution runner hash"),
        ):
            _validate_sha256(value, label=label)
        if self.browser_runner_image_digest is not None:
            _validate_sha256(
                self.browser_runner_image_digest,
                label="authorization browser runner hash",
            )

    def matches(
        self,
        *,
        request: WebExecutionRequest,
        contract: WebProfileContract,
    ) -> bool:
        expected_kind = (
            WebExecutionAuthorizationKind.PROFILE_VALIDATION
            if request.purpose is WebExecutionPurpose.PROFILE_VALIDATION
            else WebExecutionAuthorizationKind.GATE_7
        )
        return (
            self.kind is expected_kind
            and self.project_id == request.project_id
            and self.source_revision_content_hash == request.source_revision.content_hash
            and self.profile_validation_content_hash == contract.validation.content_hash
            and self.execution_plan_content_hash == contract.execution_plan.content_hash
            and self.policy_content_hash == request.policy_content_hash
            and self.execution_runner_image_digest == request.runners.execution_runner_image_digest
            and self.browser_runner_image_digest == request.runners.browser_runner_image_digest
            and self.authorized_by_user_id == request.owner_user_id
        )


@dataclass(frozen=True, slots=True)
class WebExecutionRequest:
    """Complete application request without arbitrary command input."""

    project_id: UUID
    owner_user_id: UUID
    source_revision: WebSourceRevision
    snapshot: WebDetectionSnapshot
    selection: WebTargetSelection
    lock_report: WebDependencyLockReport
    profile_id: str
    profile_version: str
    runners: WebProfileRunnerSet
    policy_content_hash: str
    purpose: WebExecutionPurpose
    trigger: WebExecutionAttemptTrigger
    authorization: WebExecutionAuthorization | None
    rerun_phases: tuple[WebExecutionPhase, ...] | None = None
    declared_routes: tuple[WebBrowserRouteSpec, ...] = ()

    def __post_init__(self) -> None:
        if self.project_id != self.source_revision.project_id:
            raise ValueError("Web execution request and source revision projects differ")
        if self.owner_user_id != self.source_revision.created_by_user_id:
            raise ValueError("Web execution request owner differs from source revision creator")
        if self.selection != self.source_revision.target_selection:
            raise ValueError("Web execution selection differs from source revision")
        _validate_sha256(self.policy_content_hash, label="Web execution policy hash")
        if self.rerun_phases is not None:
            order = {phase: index for index, phase in enumerate(WebExecutionPhase)}
            if not self.rerun_phases:
                raise ValueError("Web rerun phase selection must not be empty")
            if self.rerun_phases != tuple(sorted(self.rerun_phases, key=order.__getitem__)) or len(
                self.rerun_phases
            ) != len(set(self.rerun_phases)):
                raise ValueError("Web rerun phases must be canonical and unique")


@dataclass(frozen=True, slots=True)
class WebExecutionServiceResult:
    """Application result carrying an attempt only after successful persistence."""

    status: WebExecutionServiceStatus
    attempt: WebExecutionAttempt | None
    message: str

    def __post_init__(self) -> None:
        if not self.message or self.message != " ".join(self.message.split()):
            raise ValueError("Web execution service message must be normalized")
        if (self.status is WebExecutionServiceStatus.RECORDED) != (self.attempt is not None):
            raise ValueError("Web execution service result shape is inconsistent")


class WebPhaseExecutionPort(Protocol):
    """Execute one validated phase through sandbox or controlled adapters."""

    async def execute(
        self,
        phase_plan: WebPhasePlan,
        *,
        contract: WebProfileContract,
    ) -> WebPhaseResult: ...


class WebExecutionClock(Protocol):
    def now(self) -> datetime: ...


class WebExecutionIdProvider(Protocol):
    def new_id(self) -> UUID: ...


class LocalGovernedWebExecutionService:
    """Orchestrate one exact profile run and preserve every phase result."""

    def __init__(
        self,
        *,
        registry: WebExecutionProfileRegistry,
        attempts: WebExecutionAttemptRepository,
        phase_executor: WebPhaseExecutionPort,
        clock: WebExecutionClock,
        ids: WebExecutionIdProvider,
    ) -> None:
        self._registry = registry
        self._attempts = attempts
        self._phase_executor = phase_executor
        self._clock = clock
        self._ids = ids

    async def execute(self, request: WebExecutionRequest) -> WebExecutionServiceResult:
        profile = self._registry.find(request.profile_id, request.profile_version)
        if profile is None:
            return _failed(
                WebExecutionServiceStatus.PROFILE_NOT_FOUND,
                "Requested Web execution profile was not found.",
            )
        validation = profile.validate(
            request.snapshot,
            selection=request.selection,
            lock_report=request.lock_report,
        )
        if not validation.is_ready:
            return _failed(
                WebExecutionServiceStatus.PROFILE_INVALID,
                "Web project is outside the selected profile validation contract.",
            )
        contract = profile.create_contract(
            request.snapshot,
            selection=request.selection,
            lock_report=request.lock_report,
            source_revision_content_hash=request.source_revision.content_hash,
            source_tree_hash=request.source_revision.source_tree_hash,
            runners=request.runners,
            declared_routes=request.declared_routes,
        )
        if (
            request.purpose is WebExecutionPurpose.OWNER_PROJECT
            and profile.scope.capability_status is not ExecutionCapabilityStatus.VALIDATED_LEVEL_D
        ):
            return _failed(
                WebExecutionServiceStatus.CAPABILITY_BLOCKED,
                "Owner project execution remains blocked until this profile has Level D evidence.",
            )
        authorization_required = (
            request.purpose is WebExecutionPurpose.PROFILE_VALIDATION
            or _uses_controlled_network(contract)
        )
        if authorization_required and request.authorization is None:
            return _failed(
                WebExecutionServiceStatus.AUTHORIZATION_REQUIRED,
                "Exact execution authorization is required for this request.",
            )
        if request.authorization is not None and not request.authorization.matches(
            request=request,
            contract=contract,
        ):
            return _failed(
                WebExecutionServiceStatus.AUTHORIZATION_MISMATCH,
                "Execution authorization targets another source, plan, policy, or runner.",
            )

        current = await self._attempts.current(project_id=request.project_id)
        rerun_issue = _rerun_issue(request, current=current)
        if rerun_issue is not None:
            return _failed(WebExecutionServiceStatus.RERUN_INVALID, rerun_issue)
        phases_to_execute = (
            tuple(WebExecutionPhase) if request.rerun_phases is None else request.rerun_phases
        )
        started_at = self._clock.now()
        results: list[WebPhaseResult] = []
        executed_phases: list[WebExecutionPhase] = []
        failed = False
        previous_results = (
            {}
            if current is None
            else {result.phase: result for result in current.report.phase_results}
        )
        for phase_plan in contract.execution_plan.phases:
            phase = phase_plan.phase
            if failed:
                results.append(_not_run_result(phase, "A previous Web phase failed."))
                continue
            if phase not in phases_to_execute:
                previous = previous_results.get(phase)
                if previous is None:
                    return _failed(
                        WebExecutionServiceStatus.RERUN_INVALID,
                        "Rerun cannot reuse a phase without previous evidence.",
                    )
                results.append(previous)
                continue
            if phase_plan.execution_kind is WebPhaseExecutionKind.NO_OP:
                results.append(create_web_no_op_phase_result(phase_plan))
                continue
            result = await self._phase_executor.execute(
                phase_plan,
                contract=contract,
            )
            if result.phase is not phase:
                raise ValueError("Web phase executor returned evidence for another phase")
            results.append(result)
            executed_phases.append(phase)
            failed = result.is_failure

        report = WebExecutionReport(
            source_revision_content_hash=request.source_revision.content_hash,
            source_tree_hash=request.source_revision.source_tree_hash,
            profile_id=contract.validation.profile_id,
            profile_version=contract.validation.profile_version,
            runner_image_digest=request.runners.execution_runner_image_digest,
            policy_content_hash=request.policy_content_hash,
            phase_results=tuple(results),
        )
        completed_at = self._clock.now()
        attempt = WebExecutionAttempt(
            id=self._ids.new_id(),
            project_id=request.project_id,
            created_by_user_id=request.owner_user_id,
            attempt_number=1 if current is None else current.attempt_number + 1,
            previous_attempt_id=None if current is None else current.id,
            source_revision=request.source_revision.reference,
            profile_validation_content_hash=contract.validation.content_hash,
            execution_plan_content_hash=contract.execution_plan.content_hash,
            trigger=request.trigger,
            executed_phases=tuple(executed_phases),
            report=report,
            started_at=started_at,
            completed_at=completed_at,
        )
        append_result = await self._attempts.append(attempt)
        if append_result.status not in {
            WebExecutionAttemptAppendStatus.APPENDED,
            WebExecutionAttemptAppendStatus.ALREADY_PRESENT,
        }:
            return _failed(
                WebExecutionServiceStatus.PERSISTENCE_CONFLICT,
                "Web execution attempt could not be appended consistently.",
            )
        assert append_result.attempt is not None
        return WebExecutionServiceResult(
            status=WebExecutionServiceStatus.RECORDED,
            attempt=append_result.attempt,
            message="Web execution attempt and terminal evidence were recorded.",
        )


def _uses_controlled_network(contract: WebProfileContract) -> bool:
    return any(
        command.network_mode is CommandNetworkMode.CONTROLLED
        for phase in contract.execution_plan.phases
        for plan in phase.command_plans
        for command in plan.commands
    )


def _rerun_issue(
    request: WebExecutionRequest,
    *,
    current: WebExecutionAttempt | None,
) -> str | None:
    if request.rerun_phases is None:
        if current is not None:
            return "A later execution attempt must declare its rerun phase scope."
        return None
    if current is None:
        return "A rerun requires previous execution evidence."
    if request.trigger not in {
        WebExecutionAttemptTrigger.REPAIR_RERUN,
        WebExecutionAttemptTrigger.MANUAL_RERUN,
    }:
        return "Rerun phase scope requires a rerun trigger."
    if request.trigger is WebExecutionAttemptTrigger.MANUAL_RERUN:
        if request.source_revision.reference != current.source_revision:
            return "Manual rerun must use the same source revision."
    elif not (
        request.source_revision.version_number == current.source_revision.version_number + 1
        and request.source_revision.based_on == current.source_revision
        and WebExecutionPhase.VALIDATE in request.rerun_phases
    ):
        return "Repair rerun requires the next source revision and validation phase."
    return None


def _not_run_result(phase: WebExecutionPhase, message: str) -> WebPhaseResult:
    return WebPhaseResult(
        phase=phase,
        status=WebPhaseResultStatus.NOT_RUN,
        command_plan_hashes=(),
        started_at=None,
        completed_at=None,
        exit_codes=(),
        stdout_refs=(),
        stderr_refs=(),
        artifact_refs=(),
        findings=(),
        failure_category=None,
        failure_code=None,
        normalized_summary=message,
    )


def _failed(status: WebExecutionServiceStatus, message: str) -> WebExecutionServiceResult:
    return WebExecutionServiceResult(status=status, attempt=None, message=message)


def _validate_sha256(value: str, *, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} must be lowercase SHA-256")
