"""Owner-scoped append-only persistence for final-review versions."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
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

from orchestwin.persistence.orm import OrmBase
from orchestwin.projects.requirements_primitives import canonical_json
from orchestwin.sandbox.execution_profiles import ExecutionCapabilityStatus
from orchestwin.workflow.final_review import (
    AcceptedFinalLimitation,
    FinalReviewAssessment,
    FinalReviewCheck,
    FinalReviewCheckKind,
    FinalReviewCheckStatus,
    FinalReviewIssue,
    FinalReviewIssueSeverity,
    HumanValidationStatus,
)
from orchestwin.workflow.run_persistence import WorkflowRunRecord
from orchestwin.workflow.runs import WorkflowArtifactReference

_IMPORTED_MODELS = (WorkflowRunRecord,)


class FinalReviewRecord(OrmBase):
    """Append-only exact final-review version."""

    __tablename__ = "final_reviews"
    __table_args__ = (
        CheckConstraint("version_number >= 1", name="version_positive"),
        CheckConstraint("workflow_state_version >= 1", name="workflow_state_positive"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="content_hash_valid"),
        CheckConstraint("char_length(review_snapshot_json) > 0", name="snapshot_required"),
        CheckConstraint(
            "(version_number = 1 AND parent_review_id IS NULL) OR "
            "(version_number > 1 AND parent_review_id IS NOT NULL)",
            name="parent_consistent",
        ),
        ForeignKeyConstraint(
            ["workflow_run_id", "project_id", "owner_user_id"],
            ["workflow_runs.id", "workflow_runs.project_id", "workflow_runs.owner_user_id"],
            name="fk_final_reviews_workflow_scope",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workflow_run_id",
            "version_number",
            name="uq_final_reviews_run_version",
        ),
        UniqueConstraint(
            "workflow_run_id",
            "content_hash",
            name="uq_final_reviews_run_hash",
        ),
        Index("ix_final_reviews_project_created", "project_id", "created_at"),
        Index("ix_final_reviews_run_version", "workflow_run_id", "version_number"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    workflow_run_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_review_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("final_reviews.id", ondelete="RESTRICT"),
        nullable=True,
    )
    workflow_state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    ready_for_gate8: Mapped[bool] = mapped_column(Boolean, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)


class FinalReviewPersistenceConflict(RuntimeError):
    """Raised when append-only final-review identity or lineage conflicts."""


class FinalReviewRepository(Protocol):
    """Owner-scoped append-only final-review persistence port."""

    async def append(self, review: FinalReviewAssessment) -> FinalReviewAssessment:
        """Append one exact review version."""

    async def get_owned(
        self,
        *,
        review_id: UUID,
        owner_user_id: UUID,
    ) -> FinalReviewAssessment | None:
        """Return one owned review by identity."""

    async def list_for_run_owned(
        self,
        *,
        workflow_run_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[FinalReviewAssessment, ...]:
        """Return all owned review versions in order."""


class InMemoryFinalReviewRepository:
    """Deterministic append-only repository used by workflow and API tests."""

    def __init__(self) -> None:
        self._reviews: dict[UUID, FinalReviewAssessment] = {}

    async def append(self, review: FinalReviewAssessment) -> FinalReviewAssessment:
        if review.id in self._reviews:
            raise FinalReviewPersistenceConflict("final review identity already exists")
        versions = [
            item
            for item in self._reviews.values()
            if item.workflow_run_id == review.workflow_run_id
        ]
        expected_version = len(versions) + 1
        if review.version_number != expected_version:
            raise FinalReviewPersistenceConflict("final review lineage is not contiguous")
        if versions:
            previous = max(versions, key=lambda item: item.version_number)
            if (
                review.parent_review_id != previous.id
                or review.parent_content_hash != previous.content_hash
            ):
                raise FinalReviewPersistenceConflict(
                    "final review parent does not match the current latest version"
                )
        self._reviews[review.id] = review
        return review

    async def get_owned(
        self,
        *,
        review_id: UUID,
        owner_user_id: UUID,
    ) -> FinalReviewAssessment | None:
        review = self._reviews.get(review_id)
        if review is None or review.owner_user_id != owner_user_id:
            return None
        return review

    async def list_for_run_owned(
        self,
        *,
        workflow_run_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[FinalReviewAssessment, ...]:
        return tuple(
            sorted(
                (
                    item
                    for item in self._reviews.values()
                    if item.workflow_run_id == workflow_run_id
                    and item.owner_user_id == owner_user_id
                ),
                key=lambda item: item.version_number,
            )
        )


class SqlAlchemyFinalReviewRepository:
    """PostgreSQL-backed append-only final-review repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, review: FinalReviewAssessment) -> FinalReviewAssessment:
        record = final_review_to_record(review)
        self._session.add(record)
        try:
            await self._session.flush()
        except IntegrityError as error:
            raise FinalReviewPersistenceConflict(
                "final review identity, scope, or lineage conflicts"
            ) from error
        return review

    async def get_owned(
        self,
        *,
        review_id: UUID,
        owner_user_id: UUID,
    ) -> FinalReviewAssessment | None:
        record = await self._session.scalar(
            select(FinalReviewRecord).where(
                FinalReviewRecord.id == review_id,
                FinalReviewRecord.owner_user_id == owner_user_id,
            )
        )
        return final_review_record_to_domain(record) if record is not None else None

    async def list_for_run_owned(
        self,
        *,
        workflow_run_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[FinalReviewAssessment, ...]:
        result = await self._session.scalars(
            select(FinalReviewRecord)
            .where(
                FinalReviewRecord.workflow_run_id == workflow_run_id,
                FinalReviewRecord.owner_user_id == owner_user_id,
            )
            .order_by(FinalReviewRecord.version_number)
        )
        return tuple(final_review_record_to_domain(record) for record in result.all())


def final_review_to_record(review: FinalReviewAssessment) -> FinalReviewRecord:
    return FinalReviewRecord(
        id=review.id,
        project_id=review.project_id,
        workflow_run_id=review.workflow_run_id,
        owner_user_id=review.owner_user_id,
        version_number=review.version_number,
        parent_review_id=review.parent_review_id,
        workflow_state_version=review.workflow_state_version,
        ready_for_gate8=review.ready_for_gate8,
        content_hash=review.content_hash,
        created_at=review.created_at,
        review_snapshot_json=canonical_json(review.to_snapshot()),
    )


def final_review_record_to_domain(record: FinalReviewRecord) -> FinalReviewAssessment:
    snapshot = json.loads(record.review_snapshot_json)
    artifacts = tuple(
        WorkflowArtifactReference(
            artifact_type=item["artifact_type"],
            artifact_id=UUID(item["artifact_id"]),
            version_number=item["version_number"],
            content_hash=item["content_hash"],
        )
        for item in snapshot["artifact_references"]
    )
    checks = tuple(
        FinalReviewCheck(
            check_id=item["check_id"],
            kind=FinalReviewCheckKind(item["kind"]),
            status=FinalReviewCheckStatus(item["status"]),
            summary=item["summary"],
            evidence_refs=tuple(item["evidence_refs"]),
            blocking=item["blocking"],
        )
        for item in snapshot["checks"]
    )
    issues = tuple(
        FinalReviewIssue(
            issue_id=item["issue_id"],
            severity=FinalReviewIssueSeverity(item["severity"]),
            summary=item["summary"],
            source_ref=item["source_ref"],
        )
        for item in snapshot["unresolved_issues"]
    )
    limitations = tuple(
        AcceptedFinalLimitation(
            limitation_id=item["limitation_id"],
            summary=item["summary"],
            rationale=item["rationale"],
        )
        for item in snapshot["accepted_limitations"]
    )
    return FinalReviewAssessment(
        id=UUID(snapshot["review_id"]),
        project_id=UUID(snapshot["project_id"]),
        workflow_run_id=UUID(snapshot["workflow_run_id"]),
        owner_user_id=UUID(snapshot["owner_user_id"]),
        version_number=snapshot["version_number"],
        parent_review_id=(
            UUID(snapshot["parent_review_id"]) if snapshot["parent_review_id"] else None
        ),
        parent_content_hash=snapshot["parent_content_hash"],
        workflow_state_version=snapshot["workflow_state_version"],
        artifact_references=artifacts,
        checks=checks,
        unresolved_issues=issues,
        accepted_limitations=limitations,
        latest_execution_attempt_id=(
            UUID(snapshot["latest_execution_attempt_id"])
            if snapshot["latest_execution_attempt_id"]
            else None
        ),
        latest_evaluation_run_id=(
            UUID(snapshot["latest_evaluation_run_id"])
            if snapshot["latest_evaluation_run_id"]
            else None
        ),
        evaluation_aggregation_hash=snapshot["evaluation_aggregation_hash"],
        capability_status=(
            ExecutionCapabilityStatus(snapshot["capability_status"])
            if snapshot["capability_status"]
            else None
        ),
        human_validation_status=HumanValidationStatus(snapshot["human_validation_status"]),
        created_at=datetime.fromisoformat(snapshot["created_at"]),
        content_hash=snapshot["content_hash"],
    )
