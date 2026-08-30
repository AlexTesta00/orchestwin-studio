"""SQLAlchemy records for durable LangGraph checkpoint and pending-write data."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from orchestwin.persistence.orm import OrmBase


class LangGraphCheckpointRecord(OrmBase):
    """Full serialized LangGraph checkpoint bound to one workflow run."""

    __tablename__ = "workflow_graph_checkpoints"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "project_id", "owner_user_id"],
            ["workflow_runs.id", "workflow_runs.project_id", "workflow_runs.owner_user_id"],
            name="fk_workflow_graph_checkpoints_run_scope",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "run_id",
            "checkpoint_namespace",
            "checkpoint_id",
            name="uq_workflow_graph_checkpoints_identity",
        ),
        Index(
            "ix_workflow_graph_checkpoints_latest",
            "run_id",
            "checkpoint_namespace",
            "checkpoint_id",
        ),
    )

    run_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    checkpoint_namespace: Mapped[str] = mapped_column(
        String(256),
        primary_key=True,
        default="",
        server_default="",
    )
    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    parent_checkpoint_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    checkpoint_type: Mapped[str] = mapped_column(String(64), nullable=False)
    checkpoint_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    metadata_type: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class LangGraphWriteRecord(OrmBase):
    """One serialized pending write associated with a LangGraph checkpoint."""

    __tablename__ = "workflow_graph_writes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "checkpoint_namespace", "checkpoint_id"],
            [
                "workflow_graph_checkpoints.run_id",
                "workflow_graph_checkpoints.checkpoint_namespace",
                "workflow_graph_checkpoints.checkpoint_id",
            ],
            name="fk_workflow_graph_writes_checkpoint",
            ondelete="CASCADE",
        ),
        Index(
            "ix_workflow_graph_writes_checkpoint",
            "run_id",
            "checkpoint_namespace",
            "checkpoint_id",
        ),
    )

    run_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    checkpoint_namespace: Mapped[str] = mapped_column(String(256), primary_key=True)
    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    write_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    task_path: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    channel: Mapped[str] = mapped_column(String(256), nullable=False)
    value_type: Mapped[str] = mapped_column(String(64), nullable=False)
    value_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
