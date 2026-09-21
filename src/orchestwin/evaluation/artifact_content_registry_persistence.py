"""PostgreSQL persistence for owner-scoped evaluator artifact metadata."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Integer,
    String,
    Uuid,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from orchestwin.evaluation.artifact_content_registry import (
    ArtifactContentRegistryStoreStatus,
    AuthorizedEvaluationArtifactRecord,
)
from orchestwin.evaluation.artifacts import (
    EvaluationArtifactKind,
    EvaluationArtifactReference,
)
from orchestwin.persistence.orm import OrmBase
from orchestwin.workflow.run_persistence import WorkflowRunRecord

_ARTIFACT_KINDS = ", ".join(f"'{kind.value}'" for kind in EvaluationArtifactKind)


class AuthorizedEvaluationArtifactRecordRow(OrmBase):
    """Immutable authoritative evaluator-artifact registration."""

    __tablename__ = "authorized_evaluation_artifacts"

    __table_args__ = (
        ForeignKeyConstraint(
            [
                "workflow_run_id",
                "project_id",
                "owner_user_id",
            ],
            [
                "workflow_runs.id",
                "workflow_runs.project_id",
                "workflow_runs.owner_user_id",
            ],
            name=("fk_authorized_evaluation_artifacts_workflow_scope"),
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "version_number >= 1",
            name=("ck_authorized_evaluation_artifacts_version_positive"),
        ),
        CheckConstraint(
            f"kind IN ({_ARTIFACT_KINDS})",
            name=("ck_authorized_evaluation_artifacts_kind"),
        ),
        CheckConstraint(
            "sha256_digest ~ '^[0-9a-f]{64}$'",
            name=("ck_authorized_evaluation_artifacts_digest"),
        ),
        CheckConstraint(
            "size_bytes >= 1",
            name=("ck_authorized_evaluation_artifacts_size_positive"),
        ),
        CheckConstraint(
            (
                "storage_key = "
                "'sha256/' || "
                "substring(sha256_digest from 1 for 2) || "
                "'/' || sha256_digest"
            ),
            name=("ck_authorized_evaluation_artifacts_storage_key"),
        ),
        CheckConstraint(
            ("char_length(media_type) BETWEEN 3 AND 127 AND position('/' in media_type) > 1"),
            name=("ck_authorized_evaluation_artifacts_media_type"),
        ),
        CheckConstraint(
            "char_length(location) BETWEEN 1 AND 500",
            name=("ck_authorized_evaluation_artifacts_location"),
        ),
    )

    owner_user_id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
    )
    project_id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
    )
    workflow_run_id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
    )
    artifact_id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
    )
    version_number: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )
    kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    media_type: Mapped[str] = mapped_column(
        String(127),
        nullable=False,
    )
    sha256_digest: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    size_bytes: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    storage_key: Mapped[str] = mapped_column(
        String(74),
        nullable=False,
    )
    location: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )


def _reference_from_row(
    row: AuthorizedEvaluationArtifactRecordRow,
) -> EvaluationArtifactReference:
    return EvaluationArtifactReference(
        artifact_id=row.artifact_id,
        version_number=row.version_number,
        kind=EvaluationArtifactKind(row.kind),
        media_type=row.media_type,
        sha256_digest=row.sha256_digest,
        size_bytes=row.size_bytes,
        storage_key=row.storage_key,
        location=row.location,
    )


def _row_from_record(
    record: AuthorizedEvaluationArtifactRecord,
) -> AuthorizedEvaluationArtifactRecordRow:
    reference = record.reference

    return AuthorizedEvaluationArtifactRecordRow(
        owner_user_id=record.owner_user_id,
        project_id=record.project_id,
        workflow_run_id=record.workflow_run_id,
        artifact_id=reference.artifact_id,
        version_number=reference.version_number,
        kind=reference.kind.value,
        media_type=reference.media_type,
        sha256_digest=reference.sha256_digest,
        size_bytes=reference.size_bytes,
        storage_key=reference.storage_key,
        location=reference.location,
    )


class SqlAlchemyAuthorizedEvaluationArtifactRegistry:
    """PostgreSQL implementation of the immutable scoped registry."""

    def __init__(
        self,
        session: AsyncSession,
    ) -> None:
        self._session = session

    async def resolve_owned(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        workflow_run_id: UUID,
        artifact_id: UUID,
        version_number: int,
    ) -> EvaluationArtifactReference | None:
        row = await self._session.scalar(
            select(AuthorizedEvaluationArtifactRecordRow).where(
                AuthorizedEvaluationArtifactRecordRow.owner_user_id == owner_user_id,
                AuthorizedEvaluationArtifactRecordRow.project_id == project_id,
                AuthorizedEvaluationArtifactRecordRow.workflow_run_id == workflow_run_id,
                AuthorizedEvaluationArtifactRecordRow.artifact_id == artifact_id,
                AuthorizedEvaluationArtifactRecordRow.version_number == version_number,
            )
        )

        return None if row is None else _reference_from_row(row)

    async def append(
        self,
        record: AuthorizedEvaluationArtifactRecord,
    ) -> ArtifactContentRegistryStoreStatus:
        existing = await self.resolve_owned(
            owner_user_id=record.owner_user_id,
            project_id=record.project_id,
            workflow_run_id=record.workflow_run_id,
            artifact_id=record.reference.artifact_id,
            version_number=record.reference.version_number,
        )

        if existing is not None:
            if existing == record.reference:
                return ArtifactContentRegistryStoreStatus.ALREADY_PRESENT

            return ArtifactContentRegistryStoreStatus.CONTENT_CONFLICT

        workflow_exists = await self._session.scalar(
            select(WorkflowRunRecord.id).where(
                WorkflowRunRecord.id == record.workflow_run_id,
                WorkflowRunRecord.project_id == record.project_id,
                WorkflowRunRecord.owner_user_id == record.owner_user_id,
            )
        )

        if workflow_exists is None:
            return ArtifactContentRegistryStoreStatus.CONTENT_CONFLICT

        try:
            async with self._session.begin_nested():
                self._session.add(_row_from_record(record))
                await self._session.flush()
        except IntegrityError:
            existing = await self.resolve_owned(
                owner_user_id=record.owner_user_id,
                project_id=record.project_id,
                workflow_run_id=record.workflow_run_id,
                artifact_id=record.reference.artifact_id,
                version_number=(record.reference.version_number),
            )

            if existing == record.reference:
                return ArtifactContentRegistryStoreStatus.ALREADY_PRESENT

            return ArtifactContentRegistryStoreStatus.CONTENT_CONFLICT

        return ArtifactContentRegistryStoreStatus.CREATED


__all__ = [
    "AuthorizedEvaluationArtifactRecordRow",
    "SqlAlchemyAuthorizedEvaluationArtifactRegistry",
]
