"""Align pending-write persistence with the LangGraph checkpoint contract."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0029_langgraph_pending_writes"
down_revision: str | None = "0028_export_bundles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WRITES_TABLE = "workflow_graph_writes"
_CHECKPOINTS_TABLE = "workflow_graph_checkpoints"
_CHECKPOINT_FOREIGN_KEY = "fk_workflow_graph_writes_checkpoint"


def upgrade() -> None:
    """Allow LangGraph pending writes to precede their checkpoint row."""
    op.drop_constraint(
        _CHECKPOINT_FOREIGN_KEY,
        _WRITES_TABLE,
        type_="foreignkey",
    )


def downgrade() -> None:
    """Restore the original strict checkpoint-to-write relationship."""
    op.create_foreign_key(
        _CHECKPOINT_FOREIGN_KEY,
        _WRITES_TABLE,
        _CHECKPOINTS_TABLE,
        [
            "run_id",
            "checkpoint_namespace",
            "checkpoint_id",
        ],
        [
            "run_id",
            "checkpoint_namespace",
            "checkpoint_id",
        ],
        ondelete="CASCADE",
    )
