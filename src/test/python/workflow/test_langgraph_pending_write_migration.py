"""Contracts for LangGraph pending-write persistence ordering."""

from __future__ import annotations

import ast
from pathlib import Path

from sqlalchemy import ForeignKeyConstraint

from orchestwin.workflow.langgraph_persistence import (
    LangGraphWriteRecord,
)

MIGRATION = Path("src/orchestwin/persistence/migrations/versions/0029_langgraph_pending_writes.py")


def test_pending_write_migration_extends_export_head() -> None:
    """Keep the repair migration on the single Sprint 10 Alembic branch."""
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))

    assignments = {
        node.target.id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id
        in {
            "revision",
            "down_revision",
        }
        and node.value is not None
    }

    assert assignments == {
        "revision": "0029_langgraph_pending_writes",
        "down_revision": "0028_export_bundles",
    }


def test_pending_write_migration_removes_checkpoint_foreign_key() -> None:
    """Permit pending writes before the corresponding checkpoint is visible."""
    content = MIGRATION.read_text(encoding="utf-8")

    assert "workflow_graph_writes" in content
    assert "workflow_graph_checkpoints" in content
    assert "fk_workflow_graph_writes_checkpoint" in content

    assert "op.drop_constraint(" in content
    assert 'type_="foreignkey"' in content

    assert "op.create_foreign_key(" in content


def test_pending_write_orm_does_not_require_checkpoint_row() -> None:
    """Keep the SQLAlchemy mapping aligned with LangGraph write ordering."""
    foreign_keys = {
        constraint.name
        for constraint in LangGraphWriteRecord.__table__.constraints
        if isinstance(
            constraint,
            ForeignKeyConstraint,
        )
    }

    assert "fk_workflow_graph_writes_checkpoint" not in foreign_keys
