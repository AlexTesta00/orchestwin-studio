"""Governed JVM execution orchestration, authorization, and bounded reruns."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from orchestwin.artifacts.jvm_sources import JvmSourceRevisionReference
from orchestwin.jvm_execution.attempt_persistence import (
    JvmExecutionAttemptAppendStatus,
    JvmExecutionAttemptRepository,
)
from orchestwin.jvm_execution.attempts import (
    JvmExecutionAttempt,
    JvmExecutionAttemptTrigger,
)
from orchestwin.jvm_execution.detection import JvmDetectionSnapshot
from orchestwin.jvm_execution.evidence import (
    JvmPhaseResult,
    JvmPhaseResultStatus,
    create_jvm_execution_report,
)
from orchestwin.jvm_execution.plans import JvmExecutionPhase, JvmPhasePlan
from orchestwin.jvm_execution.policy import JvmToolchainDeclaration
from orchestwin.jvm_execution.profile_contracts import JvmProfileContract
from orchestwin.jvm_execution.profile_registry import JvmExecutionProfileRegistry
from orchestwin.jvm_execution.runner_contracts import JvmContainerRunnerContract
from orchestwin.sandbox.execution_profiles import ExecutionCapabilityStatus


class JvmExecutionPurpose(StrEnum):
    """Why a JVM profile is being executed."""

    PROFILE_VALIDATION = "PROFILE_VALIDATION"
    OWNER_PROJECT = "OWNER_PROJECT"


class JvmExecutionAuthorizationKind(StrEnum):
    """Human authorization boundary for one exact execution contract."""

    PROFILE_VALIDATION = "PROFILE_VALIDATION"
    GATE_7 = "GATE_7"


class JvmExecutionServiceStatus(StrEnum):
    """Typed JVM execution service outcomes."""

    RECORDED = "RECORDED"
    PROFILE_NOT_FOUND = "PROFILE_NOT_FOUND"
    PROFILE_INVALID = "PROFILE_INVALID"
    CAPABILITY_BLOCKED = "CAPABILITY_BLOCKED"
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"
    AUTHORIZATION_MISMATCH = "AUTHORIZATION_MISMATCH"
    RERUN_INVALID = "RERUN_INVALID"
    PERSISTENCE_CONFLICT = "PERSISTENCE_CONFLICT"


@dataclass(frozen=True, slots=True)
class JvmExecutionAuthorization:
    """Approval bound to source, profile, plan, runner, policy, and owner."""

    authorization_id: UUID
    kind: JvmExecutionAuthorizationKind
    project_id: UUID
    source_revision_content_hash: str
    profile_validation_content_hash: str
    execution_plan_content_hash: str
    runner_image_digest: str
    policy_content_hash: str
    authorized_by_user_id: UUID

    def __post_init__(self) -> None:
        for value, label in (
            (self.source_revision_content_hash, "JVM authorization source hash"),
            (self.profile_validation_content_hash, "JVM authorization profile hash"),
            (self.execution_plan_content_hash, "JVM authorization plan hash"),
            (self.runner_image_digest, "JVM authorization runner hash"),
            (self.policy_content_hash, "JVM authorization policy hash"),
        ):
            _validate_sha256(value, label=label)

    def matches(
        self,
        *,
        request: JvmExecutionRequest,
        contract: JvmProfileContract,
    ) -> bool:
        expected_kind = (
            JvmExecutionAuthorizationKind.PROFILE_VALIDATION
            if request.purpose is JvmExecutionPurpose.PROFILE_VALIDATION
            else JvmExecutionAuthorizationKind.GATE_7
        )
        return (
            self.kind is expected_kind
            and self.project_id == request.project_id
            and self.source_revision_content_hash == request.source_revision.content_hash
            and self.profile_validation_content_hash == contract.validation.content_hash
            and self.execution_plan_content_hash == contract.execution_plan.content_hash
            and self.runner_image_digest == contract.runner.image.digest
            and self.policy_content_hash == request.policy_content_hash
            and self.authorized_by_user_id == request.owner_user_id
        )


@dataclass(frozen=True, slots=True)
class JvmExecutionRequest:
    """Complete JVM execution request without arbitrary command input."""

    project_id: UUID
    owner_user_id: UUID
    source_revision: JvmSourceRevisionReference
    snapshot: JvmDetectionSnapshot
    declaration: JvmToolchainDeclaration
    profile_id: str
    profile_version: str
    runner: JvmContainerRunnerContract
    policy_content_hash: str
    purpose: JvmExecutionPurpose
    trigger: JvmExecutionAttemptTrigger
    authorization: JvmExecutionAuthorization | None
    rerun_phases: tuple[JvmExecutionPhase, ...] | None = None

    def __post_init__(self) -> None:
        if self.project_id != self.source_revision.project_id:
            raise ValueError("JVM request and source revision projects differ")
        _validate_sha256(self.policy_content_hash, label="JVM execution policy hash")
        if self.policy_content_hash != self.runner.execution_policy.content_hash:
            raise ValueError("JVM request policy hash differs from the runner policy")
        if self.rerun_phases is not None:
            order = {phase: index for index, phase in enumerate(JvmExecutionPhase)}
            if not self.rerun_phases:
                raise ValueError("JVM rerun phase selection must not be empty")
            if self.rerun_phases != tuple(sorted(self.rerun_phases, key=order.__getitem__)) or len(
                self.rerun_phases
            ) != len(set(self.rerun_phases)):
                raise ValueError("JVM rerun phases must be canonical and unique")


@dataclass(frozen=True, slots=True)
class JvmExecutionServiceResult:
    """Application result carrying an attempt only after successful persistence."""

    status: JvmExecutionServiceStatus
    attempt: JvmExecutionAttempt | None
    message: str

    def __post_init__(self) -> None:
        if not self.message or self.message != " ".join(self.message.split()):
            raise ValueError("JVM execution service message must be normalized")
        if (self.status is JvmExecutionServiceStatus.RECORDED) != (self.attempt is not None):
            raise ValueError("JVM execution service result shape is inconsistent")


class JvmPhaseExecutionPort(Protocol):
    """Execute one validated JVM phase through a controlled adapter."""

    async def execute(
        self,
        phase_plan: JvmPhasePlan,
        *,
        contract: JvmProfileContract,
    ) -> JvmPhaseResult: ...


class JvmExecutionClock(Protocol):
    def now(self) -> datetime: ...


class JvmExecutionIdProvider(Protocol):
    def new_id(self) -> UUID: ...


class LocalGovernedJvmExecutionService:
    """Orchestrate one exact JVM profile run and preserve every phase result."""

    def __init__(
        self,
        *,
        registry: JvmExecutionProfileRegistry,
        attempts: JvmExecutionAttemptRepository,
        phase_executor: JvmPhaseExecutionPort,
        clock: JvmExecutionClock,
        ids: JvmExecutionIdProvider,
    ) -> None:
        self._registry = registry
        self._attempts = attempts
        self._phase_executor = phase_executor
        self._clock = clock
        self._ids = ids

    async def execute(self, request: JvmExecutionRequest) -> JvmExecutionServiceResult:
        profile = self._registry.find(request.profile_id, request.profile_version)
        if profile is None:
            return _failed(
                JvmExecutionServiceStatus.PROFILE_NOT_FOUND,
                "Requested JVM execution profile was not found.",
            )
        validation = profile.validate(request.snapshot, request.declaration)
        if not validation.is_ready:
            return _failed(
                JvmExecutionServiceStatus.PROFILE_INVALID,
                "JVM project is outside the selected profile validation contract.",
            )
        contract = profile.create_contract(
            request.snapshot,
            request.declaration,
            source_revision=request.source_revision,
            runner=request.runner,
        )
        if (
            request.purpose is JvmExecutionPurpose.OWNER_PROJECT
            and profile.scope.capability_status is not ExecutionCapabilityStatus.VALIDATED_LEVEL_D
        ):
            return _failed(
                JvmExecutionServiceStatus.CAPABILITY_BLOCKED,
                "Owner JVM execution remains blocked until the profile has Level D evidence.",
            )
        if request.authorization is None:
            return _failed(
                JvmExecutionServiceStatus.AUTHORIZATION_REQUIRED,
                "Exact JVM execution authorization is required for this request.",
            )
        if not request.authorization.matches(request=request, contract=contract):
            return _failed(
                JvmExecutionServiceStatus.AUTHORIZATION_MISMATCH,
                "JVM authorization targets another source, plan, policy, or runner.",
            )

        current = await self._attempts.current(project_id=request.project_id)
        rerun_issue = _rerun_issue(request, current=current)
        if rerun_issue is not None:
            return _failed(JvmExecutionServiceStatus.RERUN_INVALID, rerun_issue)
        phases_to_execute = (
            tuple(JvmExecutionPhase) if request.rerun_phases is None else request.rerun_phases
        )
        started_at = self._clock.now()
        results: list[JvmPhaseResult] = []
        executed_phases: list[JvmExecutionPhase] = []
        failed = False
        previous_results = (
            {}
            if current is None
            else {result.phase: result for result in current.report.phase_results}
        )
        for phase_plan in contract.execution_plan.phases:
            phase = phase_plan.phase
            if failed:
                results.append(
                    _not_run_result(
                        phase_plan,
                        "A previous JVM phase failed.",
                    )
                )
                continue
            if phase not in phases_to_execute:
                previous = previous_results.get(phase)
                if previous is None:
                    return _failed(
                        JvmExecutionServiceStatus.RERUN_INVALID,
                        "JVM rerun cannot reuse a phase without previous evidence.",
                    )
                results.append(previous)
                continue
            result = await self._phase_executor.execute(phase_plan, contract=contract)
            if result.phase is not phase:
                raise ValueError("JVM phase executor returned evidence for another phase")
            if result.command_plan_hash != phase_plan.command_plan.content_hash:
                raise ValueError("JVM phase executor returned evidence for another plan")
            results.append(result)
            executed_phases.append(phase)
            failed = result.is_failure

        report = create_jvm_execution_report(contract.execution_plan, tuple(results))
        completed_at = self._clock.now()
        attempt = JvmExecutionAttempt(
            id=self._ids.new_id(),
            project_id=request.project_id,
            created_by_user_id=request.owner_user_id,
            attempt_number=1 if current is None else current.attempt_number + 1,
            previous_attempt_id=None if current is None else current.id,
            source_revision=request.source_revision,
            profile_id=contract.validation.profile_id,
            profile_version=contract.validation.profile_version,
            profile_validation_content_hash=contract.validation.content_hash,
            execution_plan_content_hash=contract.execution_plan.content_hash,
            runner_id=contract.runner.runner_id,
            runner_version=contract.runner.version,
            runner_image_digest=contract.runner.image.digest,
            policy_content_hash=request.policy_content_hash,
            trigger=request.trigger,
            executed_phases=tuple(executed_phases),
            report=report,
            started_at=started_at,
            completed_at=completed_at,
        )
        persisted = await self._attempts.append(attempt)
        if persisted.status not in {
            JvmExecutionAttemptAppendStatus.APPENDED,
            JvmExecutionAttemptAppendStatus.ALREADY_PRESENT,
        }:
            return _failed(
                JvmExecutionServiceStatus.PERSISTENCE_CONFLICT,
                "JVM execution attempt could not be appended to the current lineage.",
            )
        assert persisted.attempt is not None
        return JvmExecutionServiceResult(
            status=JvmExecutionServiceStatus.RECORDED,
            attempt=persisted.attempt,
            message="JVM execution attempt was recorded.",
        )


def _rerun_issue(
    request: JvmExecutionRequest,
    *,
    current: JvmExecutionAttempt | None,
) -> str | None:
    rerun_trigger = request.trigger in {
        JvmExecutionAttemptTrigger.REPAIR_RERUN,
        JvmExecutionAttemptTrigger.MANUAL_RERUN,
    }
    if current is None:
        if rerun_trigger or request.rerun_phases is not None:
            return "A JVM rerun requires a previous execution attempt."
        return None
    if request.trigger is JvmExecutionAttemptTrigger.INITIAL:
        return "INITIAL JVM execution cannot follow an existing attempt."
    if rerun_trigger and request.rerun_phases is None:
        return "A JVM rerun requires an explicit bounded phase selection."
    if request.trigger is JvmExecutionAttemptTrigger.REPAIR_RERUN:
        if request.source_revision.version_number != current.source_revision.version_number + 1:
            return "Repair rerun requires the immediate next JVM source revision."
    elif request.source_revision != current.source_revision:
        return "Non-repair JVM rerun must keep the current source revision."
    if (
        request.profile_id != current.profile_id
        or request.profile_version != current.profile_version
    ):
        return "JVM rerun must keep the exact profile version."
    if request.runner.image.digest != current.runner_image_digest:
        return "JVM rerun must keep the exact runner image."
    if request.policy_content_hash != current.policy_content_hash:
        return "JVM rerun must keep the exact execution policy."
    return None


def _not_run_result(
    phase_plan: JvmPhasePlan,
    summary: str,
) -> JvmPhaseResult:
    return JvmPhaseResult(
        phase=phase_plan.phase,
        status=JvmPhaseResultStatus.NOT_RUN,
        command_plan_hash=phase_plan.command_plan.content_hash,
        started_at=None,
        completed_at=None,
        exit_codes=(),
        stdout_refs=(),
        stderr_refs=(),
        artifact_refs=(),
        findings=(),
        failure_category=None,
        failure_code=None,
        normalized_summary=summary,
    )


def _failed(status: JvmExecutionServiceStatus, message: str) -> JvmExecutionServiceResult:
    return JvmExecutionServiceResult(status=status, attempt=None, message=message)


def _validate_sha256(value: str, *, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} must be lowercase SHA-256")
