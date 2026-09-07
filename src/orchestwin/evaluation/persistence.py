"""Owner-scoped append-only persistence for synthetic evaluation runs and findings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from orchestwin.evaluation.application import (
    SyntheticEvaluationRun,
    SyntheticEvaluationRunStatus,
)
from orchestwin.evaluation.evaluator import UserTwinEvaluatorConfiguration
from orchestwin.evaluation.findings import (
    SyntheticFinding,
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
    create_synthetic_finding,
)
from orchestwin.persistence.orm import OrmBase
from orchestwin.projects.requirements_primitives import (
    canonical_json,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.workflow.run_persistence import WorkflowRunRecord

_FINDING_CRITERIA = ", ".join(f"'{value.value}'" for value in SyntheticFindingCriterion)
_FINDING_SEVERITIES = ", ".join(f"'{value.value}'" for value in SyntheticFindingSeverity)
_EPISTEMIC_STATUSES = ", ".join(f"'{value.value}'" for value in SyntheticFindingEpistemicStatus)
_EVALUATION_STATUSES = ", ".join(f"'{value.value}'" for value in SyntheticEvaluationRunStatus)


class EvaluationRunRecord(OrmBase):
    """Append-only owner-scoped synthetic evaluation run."""

    __tablename__ = "evaluation_runs"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_EVALUATION_STATUSES})",
            name="status_valid",
        ),
        CheckConstraint(
            "artifact_bundle_hash ~ '^[0-9a-f]{64}$'",
            name="artifact_bundle_hash_valid",
        ),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="content_hash_valid",
        ),
        CheckConstraint("response_count BETWEEN 1 AND 4", name="response_count_valid"),
        CheckConstraint("finding_count >= 0", name="finding_count_non_negative"),
        CheckConstraint("char_length(run_snapshot_json) > 0", name="snapshot_required"),
        CheckConstraint("completed_at >= started_at", name="time_order_valid"),
        ForeignKeyConstraint(
            ["workflow_run_id", "project_id", "owner_user_id"],
            ["workflow_runs.id", "workflow_runs.project_id", "workflow_runs.owner_user_id"],
            name="fk_evaluation_runs_workflow_scope",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "id",
            "project_id",
            "owner_user_id",
            name="uq_evaluation_runs_scope",
        ),
        Index("ix_evaluation_runs_project_completed", "project_id", "completed_at"),
        Index("ix_evaluation_runs_workflow_completed", "workflow_run_id", "completed_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    workflow_run_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    artifact_bundle_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    artifact_bundle_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluator_id: Mapped[str] = mapped_column(String(256), nullable=False)
    evaluator_version: Mapped[str] = mapped_column(String(256), nullable=False)
    model_config_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    prompt_version_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    response_count: Mapped[int] = mapped_column(Integer, nullable=False)
    finding_count: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    run_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)


class SyntheticFindingRecord(OrmBase):
    """Append-only synthetic finding belonging to one exact evaluation run."""

    __tablename__ = "synthetic_findings"
    __table_args__ = (
        CheckConstraint("sequence_number >= 1", name="sequence_positive"),
        CheckConstraint("twin_version >= 1", name="twin_version_positive"),
        CheckConstraint("artifact_version >= 1", name="artifact_version_positive"),
        CheckConstraint(f"criterion IN ({_FINDING_CRITERIA})", name="criterion_valid"),
        CheckConstraint(f"severity IN ({_FINDING_SEVERITIES})", name="severity_valid"),
        CheckConstraint(
            f"epistemic_status IN ({_EPISTEMIC_STATUSES})",
            name="epistemic_status_valid",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_valid"),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="content_hash_valid",
        ),
        CheckConstraint(
            "char_length(finding_snapshot_json) > 0",
            name="snapshot_required",
        ),
        ForeignKeyConstraint(
            ["evaluation_run_id", "project_id", "owner_user_id"],
            ["evaluation_runs.id", "evaluation_runs.project_id", "evaluation_runs.owner_user_id"],
            name="fk_synthetic_findings_evaluation_scope",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "evaluation_run_id",
            "finding_id",
            name="uq_synthetic_findings_identity",
        ),
        UniqueConstraint(
            "evaluation_run_id",
            "sequence_number",
            name="uq_synthetic_findings_sequence",
        ),
        Index(
            "ix_synthetic_findings_run_sequence",
            "evaluation_run_id",
            "sequence_number",
        ),
        Index(
            "ix_synthetic_findings_project_severity",
            "project_id",
            "severity",
        ),
        Index(
            "ix_synthetic_findings_twin",
            "twin_id",
            "twin_version",
        ),
    )

    evaluation_run_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    finding_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    twin_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    twin_version: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    artifact_version: Mapped[int] = mapped_column(Integer, nullable=False)
    criterion: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    epistemic_status: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    requires_human_validation: Mapped[bool] = mapped_column(nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    finding_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)


@dataclass(frozen=True, slots=True)
class StoredSyntheticEvaluationRun:
    """Queryable persisted projection without duplicating all evaluator output."""

    id: UUID
    project_id: UUID
    workflow_run_id: UUID
    owner_user_id: UUID
    artifact_bundle_id: UUID
    artifact_bundle_hash: str
    evaluator: UserTwinEvaluatorConfiguration
    status: SyntheticEvaluationRunStatus
    response_count: int
    finding_count: int
    started_at: datetime
    completed_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        validate_sha256(
            self.artifact_bundle_hash,
            label="stored evaluation artifact bundle hash",
        )
        validate_sha256(
            self.content_hash,
            label="stored evaluation content hash",
        )
        validate_positive_integer(
            self.response_count,
            label="stored evaluation response count",
        )
        if self.response_count > 4:
            raise ValueError("stored evaluation response count must not exceed four")
        if isinstance(self.finding_count, bool) or self.finding_count < 0:
            raise ValueError("stored evaluation finding count must be non-negative")
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            raise ValueError("stored evaluation start timestamp must be timezone-aware")
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None:
            raise ValueError("stored evaluation completion timestamp must be timezone-aware")
        if self.completed_at < self.started_at:
            raise ValueError("stored evaluation cannot complete before it starts")

    @classmethod
    def from_domain(cls, run: SyntheticEvaluationRun) -> StoredSyntheticEvaluationRun:
        return cls(
            id=run.id,
            project_id=run.project_id,
            workflow_run_id=run.workflow_run_id,
            owner_user_id=run.owner_user_id,
            artifact_bundle_id=run.artifact_bundle_id,
            artifact_bundle_hash=run.artifact_bundle_hash,
            evaluator=run.evaluator,
            status=run.status,
            response_count=len(run.twin_evaluations),
            finding_count=len(run.findings),
            started_at=run.started_at,
            completed_at=run.completed_at,
            content_hash=run.content_hash,
        )


class SyntheticEvaluationStoreStatus(StrEnum):
    """Owner-safe outcomes of append-only evaluation persistence."""

    CREATED = "CREATED"
    ALREADY_PRESENT = "ALREADY_PRESENT"
    WORKFLOW_RUN_NOT_FOUND = "WORKFLOW_RUN_NOT_FOUND"
    CONTENT_CONFLICT = "CONTENT_CONFLICT"


@dataclass(frozen=True, slots=True)
class SyntheticEvaluationStoreResult:
    """Store result exposing a projection only for successful outcomes."""

    status: SyntheticEvaluationStoreStatus
    run: StoredSyntheticEvaluationRun | None

    def __post_init__(self) -> None:
        successful = self.status in {
            SyntheticEvaluationStoreStatus.CREATED,
            SyntheticEvaluationStoreStatus.ALREADY_PRESENT,
        }
        if successful != (self.run is not None):
            raise ValueError("synthetic evaluation store result shape is inconsistent")


class SyntheticEvaluationRepository(Protocol):
    """Owner-bound append-only persistence port."""

    async def append(self, run: SyntheticEvaluationRun) -> SyntheticEvaluationStoreResult: ...

    async def get_owned(self, *, run_id: UUID) -> StoredSyntheticEvaluationRun | None: ...

    async def list_findings(self, *, run_id: UUID) -> tuple[SyntheticFinding, ...]: ...


class InMemorySyntheticEvaluationRepository:
    """Deterministic owner-scoped repository for ordinary tests."""

    def __init__(
        self,
        *,
        owner_user_id: UUID,
        workflow_run_projects: dict[UUID, UUID],
    ) -> None:
        self._owner_user_id = owner_user_id
        self._workflow_run_projects = dict(workflow_run_projects)
        self._runs: dict[UUID, SyntheticEvaluationRun] = {}

    async def append(self, run: SyntheticEvaluationRun) -> SyntheticEvaluationStoreResult:
        if (
            run.owner_user_id != self._owner_user_id
            or self._workflow_run_projects.get(run.workflow_run_id) != run.project_id
        ):
            return SyntheticEvaluationStoreResult(
                SyntheticEvaluationStoreStatus.WORKFLOW_RUN_NOT_FOUND,
                None,
            )
        existing = self._runs.get(run.id)
        if existing is not None:
            if existing == run:
                return SyntheticEvaluationStoreResult(
                    SyntheticEvaluationStoreStatus.ALREADY_PRESENT,
                    StoredSyntheticEvaluationRun.from_domain(existing),
                )
            return SyntheticEvaluationStoreResult(
                SyntheticEvaluationStoreStatus.CONTENT_CONFLICT,
                None,
            )
        self._runs[run.id] = run
        return SyntheticEvaluationStoreResult(
            SyntheticEvaluationStoreStatus.CREATED,
            StoredSyntheticEvaluationRun.from_domain(run),
        )

    async def get_owned(self, *, run_id: UUID) -> StoredSyntheticEvaluationRun | None:
        run = self._runs.get(run_id)
        if run is None or run.owner_user_id != self._owner_user_id:
            return None
        return StoredSyntheticEvaluationRun.from_domain(run)

    async def list_findings(self, *, run_id: UUID) -> tuple[SyntheticFinding, ...]:
        run = self._runs.get(run_id)
        if run is None or run.owner_user_id != self._owner_user_id:
            return ()
        return run.findings


class SqlAlchemySyntheticEvaluationRepository:
    """PostgreSQL append-only evaluation repository bound to one owner."""

    def __init__(self, session: AsyncSession, *, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id

    async def append(self, run: SyntheticEvaluationRun) -> SyntheticEvaluationStoreResult:
        if run.owner_user_id != self._owner_user_id:
            return SyntheticEvaluationStoreResult(
                SyntheticEvaluationStoreStatus.WORKFLOW_RUN_NOT_FOUND,
                None,
            )
        workflow_run_exists = await self._session.scalar(
            select(WorkflowRunRecord.id).where(
                WorkflowRunRecord.id == run.workflow_run_id,
                WorkflowRunRecord.project_id == run.project_id,
                WorkflowRunRecord.owner_user_id == self._owner_user_id,
            )
        )
        if workflow_run_exists is None:
            return SyntheticEvaluationStoreResult(
                SyntheticEvaluationStoreStatus.WORKFLOW_RUN_NOT_FOUND,
                None,
            )
        existing = await self.get_owned(run_id=run.id)
        if existing is not None:
            if existing.content_hash == run.content_hash:
                return SyntheticEvaluationStoreResult(
                    SyntheticEvaluationStoreStatus.ALREADY_PRESENT,
                    existing,
                )
            return SyntheticEvaluationStoreResult(
                SyntheticEvaluationStoreStatus.CONTENT_CONFLICT,
                None,
            )

        try:
            async with self._session.begin_nested():
                self._session.add(evaluation_run_to_record(run))
                for sequence_number, finding in enumerate(run.findings, start=1):
                    self._session.add(
                        synthetic_finding_to_record(
                            run,
                            finding,
                            sequence_number=sequence_number,
                        )
                    )
                await self._session.flush()
        except IntegrityError:
            return SyntheticEvaluationStoreResult(
                SyntheticEvaluationStoreStatus.CONTENT_CONFLICT,
                None,
            )
        return SyntheticEvaluationStoreResult(
            SyntheticEvaluationStoreStatus.CREATED,
            StoredSyntheticEvaluationRun.from_domain(run),
        )

    async def get_owned(self, *, run_id: UUID) -> StoredSyntheticEvaluationRun | None:
        record = await self._session.scalar(
            select(EvaluationRunRecord).where(
                EvaluationRunRecord.id == run_id,
                EvaluationRunRecord.owner_user_id == self._owner_user_id,
            )
        )
        return None if record is None else evaluation_run_record_to_domain(record)

    async def list_findings(self, *, run_id: UUID) -> tuple[SyntheticFinding, ...]:
        records = await self._session.scalars(
            select(SyntheticFindingRecord)
            .where(
                SyntheticFindingRecord.evaluation_run_id == run_id,
                SyntheticFindingRecord.owner_user_id == self._owner_user_id,
            )
            .order_by(SyntheticFindingRecord.sequence_number)
        )
        return tuple(synthetic_finding_record_to_domain(record) for record in records.all())


def evaluation_run_to_record(run: SyntheticEvaluationRun) -> EvaluationRunRecord:
    """Translate one immutable domain run into its append-only record."""
    return EvaluationRunRecord(
        id=run.id,
        project_id=run.project_id,
        workflow_run_id=run.workflow_run_id,
        owner_user_id=run.owner_user_id,
        artifact_bundle_id=run.artifact_bundle_id,
        artifact_bundle_hash=run.artifact_bundle_hash,
        evaluator_id=run.evaluator.evaluator_id,
        evaluator_version=run.evaluator.evaluator_version,
        model_config_ref=run.evaluator.model_config_ref,
        prompt_version_ref=run.evaluator.prompt_version_ref,
        status=run.status.value,
        response_count=len(run.twin_evaluations),
        finding_count=len(run.findings),
        started_at=run.started_at,
        completed_at=run.completed_at,
        content_hash=run.content_hash,
        run_snapshot_json=canonical_json(run.to_snapshot()),
    )


def evaluation_run_record_to_domain(record: EvaluationRunRecord) -> StoredSyntheticEvaluationRun:
    """Restore a verified query projection from one persistence record."""
    payload = _object_payload(record.run_snapshot_json, label="evaluation run snapshot")
    if payload.get("content_hash") != record.content_hash:
        raise ValueError("evaluation run record content hash does not match its snapshot")
    return StoredSyntheticEvaluationRun(
        id=record.id,
        project_id=record.project_id,
        workflow_run_id=record.workflow_run_id,
        owner_user_id=record.owner_user_id,
        artifact_bundle_id=record.artifact_bundle_id,
        artifact_bundle_hash=record.artifact_bundle_hash,
        evaluator=UserTwinEvaluatorConfiguration(
            evaluator_id=record.evaluator_id,
            evaluator_version=record.evaluator_version,
            model_config_ref=record.model_config_ref,
            prompt_version_ref=record.prompt_version_ref,
        ),
        status=SyntheticEvaluationRunStatus(record.status),
        response_count=record.response_count,
        finding_count=record.finding_count,
        started_at=record.started_at,
        completed_at=record.completed_at,
        content_hash=record.content_hash,
    )


def synthetic_finding_to_record(
    run: SyntheticEvaluationRun,
    finding: SyntheticFinding,
    *,
    sequence_number: int,
) -> SyntheticFindingRecord:
    """Translate one finding into an ordered append-only persistence row."""
    validate_positive_integer(
        sequence_number,
        label="synthetic finding sequence number",
    )
    return SyntheticFindingRecord(
        evaluation_run_id=run.id,
        finding_id=finding.finding_id,
        project_id=run.project_id,
        owner_user_id=run.owner_user_id,
        sequence_number=sequence_number,
        twin_id=finding.twin_id,
        twin_version=finding.twin_version,
        artifact_id=finding.artifact_id,
        artifact_version=finding.artifact_version,
        criterion=finding.criterion.value,
        severity=finding.severity.value,
        epistemic_status=finding.epistemic_status.value,
        confidence=float(finding.confidence),
        requires_human_validation=finding.requires_human_validation,
        content_hash=finding.content_hash,
        finding_snapshot_json=canonical_json(finding.to_snapshot()),
    )


def synthetic_finding_record_to_domain(record: SyntheticFindingRecord) -> SyntheticFinding:
    """Restore one finding and verify its canonical content hash."""
    payload = _object_payload(record.finding_snapshot_json, label="synthetic finding snapshot")
    evidence_refs = payload.get("evidence_refs")
    if not isinstance(evidence_refs, list) or not all(
        isinstance(reference, str) for reference in evidence_refs
    ):
        raise ValueError("synthetic finding snapshot evidence references are invalid")
    requires_human_validation = payload.get("requires_human_validation")
    if not isinstance(requires_human_validation, bool):
        raise ValueError("synthetic finding snapshot validation flag is invalid")
    confidence = payload.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, int | float):
        raise ValueError("synthetic finding snapshot confidence is invalid")

    finding = create_synthetic_finding(
        finding_id=str(payload["finding_id"]),
        twin_id=UUID(str(payload["twin_id"])),
        twin_version=int(str(payload["twin_version"])),
        artifact_id=UUID(str(payload["artifact_id"])),
        artifact_version=int(str(payload["artifact_version"])),
        location=str(payload["location"]),
        summary=str(payload["summary"]),
        rationale=str(payload["rationale"]),
        criterion=SyntheticFindingCriterion(str(payload["criterion"])),
        severity=SyntheticFindingSeverity(str(payload["severity"])),
        epistemic_status=SyntheticFindingEpistemicStatus(str(payload["epistemic_status"])),
        evidence_refs=tuple(evidence_refs),
        confidence=float(confidence),
        recommended_action=str(payload["recommended_action"]),
        requires_human_validation=requires_human_validation,
        model_config_ref=str(payload["model_config_ref"]),
        prompt_version_ref=str(payload["prompt_version_ref"]),
    )
    if (
        finding.content_hash != record.content_hash
        or payload.get("content_hash") != record.content_hash
    ):
        raise ValueError("synthetic finding record content hash is inconsistent")
    if (
        finding.finding_id != record.finding_id
        or finding.twin_id != record.twin_id
        or finding.twin_version != record.twin_version
        or finding.artifact_id != record.artifact_id
        or finding.artifact_version != record.artifact_version
        or finding.criterion.value != record.criterion
        or finding.severity.value != record.severity
        or finding.epistemic_status.value != record.epistemic_status
    ):
        raise ValueError("synthetic finding record projection is inconsistent")
    return finding


def _object_payload(raw_json: str, *, label: str) -> dict[str, object]:
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} is not valid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload
