"""Owner-governed static inspections: immutable plans, Gate 7 and one-shot execution.

The browser executor remains a component, not a validated full execution profile.
No workflow, model, repair, final approval or formal-case outcome is inferred here.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager, suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from orchestwin.web_execution.static_browser_executor import BrowserExecutionAuthorization
from orchestwin.web_execution.static_browser_jobs import (
    BrowserAction,
    BrowserScenario,
    StaticBrowserJob,
    StaticFile,
    canonical_bytes,
    content_hash,
    require_hash,
)
from orchestwin.web_execution.verified_browser_runner import read_json
from orchestwin.workflow.gates import (
    DEFAULT_GATE_ITERATION_LIMIT,
    GateArtifactReference,
    HumanGate,
    HumanGateAction,
    HumanGateEvent,
    HumanGateStatus,
    HumanGateTransitionStatus,
    HumanGateType,
    create_human_gate,
    mark_human_gate_stale,
    transition_human_gate,
)

_LOG = logging.getLogger(__name__)


class InspectionError(RuntimeError):
    """Public error codes never include source bytes, secrets or local paths."""

    def __init__(self, code: str, status_code: int = 409) -> None:
        if re.fullmatch(r"[A-Z][A-Z0-9_]{0,99}", code) is None:
            raise ValueError("invalid inspection error code")
        self.code = code
        self.status_code = status_code
        super().__init__(code)


class InspectionState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def operation_policy() -> dict[str, object]:
    """Fixed inspector scope; no request may replace these settings."""
    return {
        "kind": "STATIC_BROWSER_INSPECTION",
        "contract_version": 1,
        "capability": "EXPERIMENTAL_COMPONENT_NOT_FULL_PROFILE",
        "network": "none",
        "host_mounts": False,
        "package_installation": False,
        "container_user": "65532:65532",
        "memory_bytes": 1073741824,
        "cpu_count": 2,
        "pids_limit": 256,
        "execute_timeout_seconds": 120,
        "chromium_sandbox_required": True,
        "source_scope": "WEB_STATIC",
        "level_d_validated": False,
    }


def scenarios_from_snapshot(values: object) -> tuple[BrowserScenario, ...]:
    if not isinstance(values, list) or not 1 <= len(values) <= 2:
        raise InspectionError("SCENARIOS_INVALID", 422)
    try:
        scenarios = tuple(
            BrowserScenario(
                scenario_id=item["id"],
                route=item["route"],
                actions=tuple(BrowserAction(**action) for action in item["actions"]),
            )
            for item in values
        )
    except (KeyError, TypeError, ValueError):
        raise InspectionError("SCENARIOS_INVALID", 422) from None
    if canonical_bytes([item.snapshot() for item in scenarios]) != canonical_bytes(values):
        raise InspectionError("SCENARIOS_INVALID", 422)
    return scenarios


def job_from_snapshot(value: object) -> StaticBrowserJob:
    """Strictly restore the frozen job; recalculate hashes instead of trusting JSON."""
    if not isinstance(value, dict):
        raise InspectionError("STORED_JOB_INVALID")
    try:
        source = value["source"]
        job = StaticBrowserJob(
            project_id=UUID(source["project_id"]),
            owner_user_id=UUID(source["owner_user_id"]),
            revision_id=UUID(source["revision_id"]),
            revision_content_hash=source["content_hash"],
            source_tree_hash=source["source_tree_hash"],
            runner_manifest_content_hash=value["runner_manifest_content_hash"],
            harness_sha256=value["harness_sha256"],
            files=tuple(
                StaticFile(item["path"], base64.b64decode(item["content_base64"], validate=True))
                for item in value["files"]
            ),
            scenarios=scenarios_from_snapshot(value["scenarios"]),
        )
        if job.wire_bytes() != canonical_bytes(value):
            raise InspectionError("STORED_JOB_MISMATCH")
    except (KeyError, TypeError, ValueError):
        raise InspectionError("STORED_JOB_INVALID") from None
    return job


@dataclass(frozen=True, slots=True)
class SourceContext:
    """Returned only after ownership, current revision and Gate 6 checks in storage."""

    revision: Mapping[str, object]
    architecture: GateArtifactReference


@dataclass(frozen=True, slots=True)
class InspectionPlan:
    job: StaticBrowserJob
    architecture: GateArtifactReference
    platform_commit: str
    runner_image_id: str

    def __post_init__(self) -> None:
        if (
            self.architecture.project_id != self.job.project_id
            or self.architecture.gate_type is not HumanGateType.ARCHITECTURE
            or re.fullmatch(r"[0-9a-f]{40}", self.platform_commit) is None
            or re.fullmatch(r"sha256:[0-9a-f]{64}", self.runner_image_id) is None
        ):
            raise InspectionError("INSPECTION_PLAN_INVALID")

    def snapshot(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "job": read_json(self.job.wire_bytes()),
            "architecture": {
                "id": str(self.architecture.artifact_id),
                "version": self.architecture.version,
                "content_hash": self.architecture.content_hash,
            },
            "platform_commit": self.platform_commit,
            "runner_image_id": self.runner_image_id,
            "operation_policy": operation_policy(),
        }

    @property
    def content_hash(self) -> str:
        return content_hash(self.snapshot())

    def public_snapshot(self) -> dict[str, object]:
        result = self.snapshot()
        job = dict(result.pop("job"))
        job.pop("files")
        result["job"] = job
        result["source_file_count"] = len(self.job.files)
        result["source_bytes"] = sum(len(file.content) for file in self.job.files)
        result["plan_content_hash"] = self.content_hash
        return result

    @classmethod
    def from_json(cls, body: str) -> InspectionPlan:
        try:
            value = read_json(body.encode("utf-8"))
            job = job_from_snapshot(value["job"])
            architecture = value["architecture"]
            plan = cls(
                job=job,
                architecture=GateArtifactReference(
                    project_id=job.project_id,
                    gate_type=HumanGateType.ARCHITECTURE,
                    artifact_id=UUID(architecture["id"]),
                    version=architecture["version"],
                    content_hash=architecture["content_hash"],
                ),
                platform_commit=value["platform_commit"],
                runner_image_id=value["runner_image_id"],
            )
            if canonical_bytes(plan.snapshot()).decode("utf-8") != body:
                raise InspectionError("STORED_PLAN_NOT_CANONICAL")
            return plan
        except (KeyError, TypeError, ValueError):
            raise InspectionError("STORED_PLAN_INVALID") from None


@dataclass(frozen=True, slots=True)
class Inspection:
    id: UUID
    gate_id: UUID
    plan: InspectionPlan
    created_at: datetime
    state: InspectionState = InspectionState.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result_json: str | None = None

    def __post_init__(self) -> None:
        for instant in (self.created_at, self.started_at, self.finished_at):
            if instant is not None and instant.utcoffset() is None:
                raise InspectionError("INSPECTION_TIMESTAMP_INVALID")
        if (self.state is InspectionState.PENDING) != (self.started_at is None):
            raise InspectionError("INSPECTION_START_INCONSISTENT")
        terminal = self.state in {InspectionState.COMPLETED, InspectionState.FAILED}
        if terminal != (self.finished_at is not None and self.result_json is not None):
            raise InspectionError("INSPECTION_RESULT_INCONSISTENT")
        if not terminal and (self.finished_at is not None or self.result_json is not None):
            raise InspectionError("INSPECTION_RESULT_INCONSISTENT")
        if self.started_at is not None and self.started_at < self.created_at:
            raise InspectionError("INSPECTION_TIMESTAMP_INVALID")
        if self.finished_at is not None and self.finished_at < self.started_at:
            raise InspectionError("INSPECTION_TIMESTAMP_INVALID")

    @property
    def artifact(self) -> GateArtifactReference:
        return GateArtifactReference(
            self.plan.job.project_id,
            HumanGateType.HIGH_IMPACT_OPERATION,
            self.id,
            1,
            self.plan.content_hash,
        )

    def snapshot(self, gate: HumanGate, *, current: bool) -> dict[str, object]:
        return {
            "id": str(self.id),
            "state": self.state.value,
            "plan": self.plan.public_snapshot(),
            "gate": {
                "id": str(gate.id),
                "type": gate.gate_type.value,
                "status": gate.status.value,
                "event_sequence": gate.event_sequence,
                "iteration": gate.iteration,
                "max_iterations": gate.max_iterations,
                "is_current": current,
            },
            "created_at": self.created_at.isoformat(),
            "started_at": None if self.started_at is None else self.started_at.isoformat(),
            "finished_at": None if self.finished_at is None else self.finished_at.isoformat(),
            "result": None if self.result_json is None else read_json(self.result_json.encode()),
            "formal_case_completion": "NOT_ASSESSED",
            "full_profile_execution": False,
        }


class InspectionScope(Protocol):
    async def get(self, request_id: UUID) -> Inspection | None: ...
    async def history(self) -> tuple[Inspection, ...]: ...
    async def source_context(self, revision_id: UUID) -> SourceContext: ...
    async def latest_gate(self) -> HumanGate | None: ...
    async def gate(self, gate_id: UUID) -> HumanGate: ...
    async def add_gate(self, gate: HumanGate, event: HumanGateEvent) -> None: ...
    async def save_gate(
        self, previous: HumanGate, updated: HumanGate, event: HumanGateEvent
    ) -> None: ...
    async def insert(self, inspection: Inspection) -> None: ...
    async def update(self, previous: Inspection, updated: Inspection) -> None: ...


class InspectionStore(Protocol):
    def scope(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> AbstractAsyncContextManager[InspectionScope]: ...


class InspectionBackend(Protocol):
    async def plan(
        self, context: SourceContext, scenarios: tuple[BrowserScenario, ...]
    ) -> InspectionPlan: ...
    async def check_binding(self, plan: InspectionPlan) -> None: ...
    async def execute(self, inspection: Inspection, authorize: Callable) -> None: ...
    def result(self, inspection: Inspection) -> dict[str, object]: ...


class StaticInspectionService:
    """Short database transactions surround, but never contain, the Docker operation."""

    def __init__(self, store: InspectionStore, backend: InspectionBackend) -> None:
        self._store = store
        self._backend = backend

    @staticmethod
    async def _required(scope: InspectionScope, request_id: UUID) -> Inspection:
        record = await scope.get(request_id)
        if record is None:
            raise InspectionError("STATIC_INSPECTION_NOT_FOUND", 404)
        return record

    @staticmethod
    async def _view(scope: InspectionScope, record: Inspection) -> dict[str, object]:
        gate = await scope.gate(record.gate_id)
        latest = await scope.latest_gate()
        return record.snapshot(gate, current=latest is not None and latest.id == gate.id)

    async def get(self, *, owner_user_id: UUID, project_id: UUID, request_id: UUID):
        async with self._store.scope(owner_user_id=owner_user_id, project_id=project_id) as scope:
            return await self._view(scope, await self._required(scope, request_id))

    async def history(self, *, owner_user_id: UUID, project_id: UUID):
        async with self._store.scope(owner_user_id=owner_user_id, project_id=project_id) as scope:
            return tuple([await self._view(scope, item) for item in await scope.history()])

    async def prepare(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        request_id: UUID,
        revision_id: UUID,
        scenarios: tuple[BrowserScenario, ...],
    ) -> dict[str, object]:
        async with self._store.scope(owner_user_id=owner_user_id, project_id=project_id) as scope:
            existing = await scope.get(request_id)
            if existing is not None:
                if (
                    existing.plan.job.revision_id != revision_id
                    or existing.plan.job.scenarios != scenarios
                ):
                    raise InspectionError("STATIC_INSPECTION_ID_CONFLICT")
                return await self._view(scope, existing)
            history = await scope.history()
            if any(item.state is InspectionState.RUNNING for item in history):
                raise InspectionError("STATIC_INSPECTION_ALREADY_RUNNING")
            if any(
                item.state is InspectionState.FAILED
                and item.result_json is not None
                and read_json(item.result_json.encode()).get("cleanup_confirmed") is not True
                for item in history
            ):
                raise InspectionError("STATIC_INSPECTION_CLEANUP_REQUIRES_OPERATOR")
            latest = await scope.latest_gate()
            if latest is not None and latest.status in {
                HumanGateStatus.DRAFT,
                HumanGateStatus.PENDING_APPROVAL,
                HumanGateStatus.PAUSED,
                HumanGateStatus.PAUSED_NEEDS_HUMAN,
            }:
                raise InspectionError("EXISTING_GATE_7_REQUIRES_DECISION")
            iteration = 1 if latest is None else latest.iteration + 1
            if iteration > DEFAULT_GATE_ITERATION_LIMIT:
                raise InspectionError("GATE_7_ITERATION_LIMIT_REACHED")
            context = await scope.source_context(revision_id)
            plan = await self._backend.plan(context, scenarios)
            if plan.job.project_id != project_id or plan.job.owner_user_id != owner_user_id:
                raise InspectionError("STATIC_INSPECTION_OWNER_MISMATCH", 404)
            if plan.job.revision_id != revision_id or plan.job.scenarios != scenarios:
                raise InspectionError("STATIC_INSPECTION_PLAN_MISMATCH")
            now = datetime.now(UTC)
            record = Inspection(request_id, uuid4(), plan, now)
            gate = create_human_gate(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.HIGH_IMPACT_OPERATION,
                artifact=record.artifact,
                gate_id=record.gate_id,
                iteration=iteration,
                created_at=now,
            )
            transition = transition_human_gate(
                gate, action=HumanGateAction.SUBMIT, actor_user_id=owner_user_id, occurred_at=now
            )
            if (
                transition.status is not HumanGateTransitionStatus.APPLIED
                or transition.event is None
            ):
                raise InspectionError("GATE_7_SUBMISSION_FAILED")
            if latest is not None:
                stale = mark_human_gate_stale(
                    latest, current_artifact=record.artifact, occurred_at=now
                )
                if stale.status is HumanGateTransitionStatus.APPLIED and stale.event is not None:
                    await scope.save_gate(latest, stale.gate, stale.event)
            await scope.add_gate(transition.gate, transition.event)
            await scope.insert(record)
            return record.snapshot(transition.gate, current=True)

    @staticmethod
    def _expected(record: Inspection, expected_hash: str) -> None:
        require_hash(expected_hash)
        if expected_hash != record.plan.content_hash:
            raise InspectionError("STATIC_INSPECTION_PLAN_CHANGED")

    @staticmethod
    async def _exact_gate(scope: InspectionScope, record: Inspection) -> HumanGate:
        gate = await scope.latest_gate()
        if (
            gate is None
            or gate.id != record.gate_id
            or gate.artifact != record.artifact
            or gate.owner_user_id != record.plan.job.owner_user_id
        ):
            raise InspectionError("STATIC_INSPECTION_GATE_STALE")
        return gate

    @staticmethod
    async def _current_source(scope: InspectionScope, record: Inspection) -> None:
        context = await scope.source_context(record.plan.job.revision_id)
        if (
            context.architecture != record.plan.architecture
            or context.revision.get("content_hash") != record.plan.job.revision_content_hash
            or context.revision.get("source_tree_hash") != record.plan.job.source_tree_hash
        ):
            raise InspectionError("STATIC_INSPECTION_SOURCE_STALE")

    async def decide(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        request_id: UUID,
        expected_hash: str,
        expected_event_sequence: int,
        action: HumanGateAction,
        reason: str | None = None,
    ):
        if type(expected_event_sequence) is not int or expected_event_sequence < 1:
            raise InspectionError("GATE_7_EVENT_SEQUENCE_INVALID", 422)
        if action is HumanGateAction.SUBMIT:
            raise InspectionError("STATIC_INSPECTION_ACTION_INVALID", 422)
        async with self._store.scope(owner_user_id=owner_user_id, project_id=project_id) as scope:
            record = await self._required(scope, request_id)
            self._expected(record, expected_hash)
            if record.state is not InspectionState.PENDING:
                raise InspectionError("STATIC_INSPECTION_ALREADY_CLAIMED")
            gate = await self._exact_gate(scope, record)
            if gate.event_sequence != expected_event_sequence:
                raise InspectionError("GATE_7_STATE_CONFLICT")
            if action is HumanGateAction.APPROVE:
                await self._current_source(scope, record)
            transition = transition_human_gate(
                gate,
                action=action,
                actor_user_id=owner_user_id,
                reason=reason,
            )
            if transition.status is HumanGateTransitionStatus.REJECTED:
                raise InspectionError(
                    transition.issue.value if transition.issue else "GATE_7_REJECTED"
                )
            if transition.status is HumanGateTransitionStatus.APPLIED:
                if transition.event is None:
                    raise InspectionError("GATE_7_EVENT_REQUIRED")
                await scope.save_gate(gate, transition.gate, transition.event)
            return record.snapshot(transition.gate, current=True)

    async def execute(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        request_id: UUID,
        expected_hash: str,
    ):
        async with self._store.scope(owner_user_id=owner_user_id, project_id=project_id) as scope:
            record = await self._required(scope, request_id)
            self._expected(record, expected_hash)
            if record.state in {InspectionState.COMPLETED, InspectionState.FAILED}:
                return await self._view(scope, record)
            if record.state is InspectionState.RUNNING:
                raise InspectionError("STATIC_INSPECTION_ALREADY_RUNNING")
            gate = await self._exact_gate(scope, record)
            if gate.status is not HumanGateStatus.APPROVED:
                raise InspectionError("GATE_7_APPROVAL_REQUIRED")
            await self._current_source(scope, record)
            await self._backend.check_binding(record.plan)
            claimed = replace(record, state=InspectionState.RUNNING, started_at=datetime.now(UTC))
            await scope.update(record, claimed)

        # The claim has committed. Retries/concurrent requests cannot start a second container.
        async def authorize(job: StaticBrowserJob) -> BrowserExecutionAuthorization:
            async with self._store.scope(
                owner_user_id=owner_user_id, project_id=project_id
            ) as scope:
                current = await self._required(scope, request_id)
                gate = await self._exact_gate(scope, current)
                if (
                    current.state is not InspectionState.RUNNING
                    or current.plan.content_hash != claimed.plan.content_hash
                    or current.plan.job.content_hash != job.content_hash
                    or gate.status is not HumanGateStatus.APPROVED
                ):
                    raise InspectionError("GATE_7_AUTHORIZATION_MISMATCH")
                await self._current_source(scope, current)
                await self._backend.check_binding(current.plan)
                return BrowserExecutionAuthorization(job.content_hash, "GATE_7", f"gate:{gate.id}")

        try:
            await self._backend.execute(claimed, authorize)
            result = self._backend.result(claimed)
        except asyncio.CancelledError:
            # A killed API process must never cause an automatic retry. Recovery reads evidence.
            _LOG.warning(
                "Static inspection interrupted; explicit recovery required: %s", request_id
            )
            raise
        except Exception as error:
            # Runtime boundary: record a redacted failure, never source/driver/Docker output.
            _LOG.error("Static inspection failed: %s (%s)", request_id, type(error).__name__)
            result = {
                "execution_status": "FAILED",
                "assertion_status": "NOT_OBSERVED",
                "failure_code": "STATIC_INSPECTION_EXECUTOR_FAILED",
                "cleanup_confirmed": None,
            }
            with suppress(OSError, ValueError, InspectionError):
                result = self._backend.result(claimed)
        return await self._finish(owner_user_id, project_id, request_id, expected_hash, result)

    async def _finish(self, owner_user_id, project_id, request_id, expected_hash, result):
        state = (
            InspectionState.COMPLETED
            if result["execution_status"] == "COMPLETED"
            else InspectionState.FAILED
        )
        async with self._store.scope(owner_user_id=owner_user_id, project_id=project_id) as scope:
            record = await self._required(scope, request_id)
            self._expected(record, expected_hash)
            if record.state in {InspectionState.COMPLETED, InspectionState.FAILED}:
                return await self._view(scope, record)
            if record.state is not InspectionState.RUNNING:
                raise InspectionError("STATIC_INSPECTION_NOT_STARTED")
            updated = replace(
                record,
                state=state,
                finished_at=datetime.now(UTC),
                result_json=canonical_bytes(result).decode("utf-8"),
            )
            await scope.update(record, updated)
            return await self._view(scope, updated)

    async def recover(self, *, owner_user_id, project_id, request_id, expected_hash):
        """Import existing terminal evidence only. Never launch or reauthorize a job."""
        async with self._store.scope(owner_user_id=owner_user_id, project_id=project_id) as scope:
            record = await self._required(scope, request_id)
            self._expected(record, expected_hash)
            if record.state in {InspectionState.COMPLETED, InspectionState.FAILED}:
                return await self._view(scope, record)
            if record.state is not InspectionState.RUNNING:
                raise InspectionError("STATIC_INSPECTION_NOT_STARTED")
        result = self._backend.result(record)
        return await self._finish(owner_user_id, project_id, request_id, expected_hash, result)
