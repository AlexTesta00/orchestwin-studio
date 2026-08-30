"""Static contracts for workflow run and checkpoint migration 0024."""

from __future__ import annotations

import ast
from pathlib import Path

MIGRATION = Path("src/orchestwin/persistence/migrations/versions/0024_workflow_runs_checkpoints.py")


def test_workflow_persistence_migration_extends_jvm_head() -> None:
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    assignments = {
        node.target.id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id in {"revision", "down_revision"}
        and node.value is not None
    }

    assert assignments == {
        "revision": "0024_workflow_runs_checkpoints",
        "down_revision": "0023_jvm_execution_attempts",
    }


def test_migration_preserves_owner_scope_cas_and_checkpoint_immutability() -> None:
    content = MIGRATION.read_text(encoding="utf-8")

    assert "workflow_runs" in content
    assert "workflow_checkpoints" in content
    assert "workflow_graph_checkpoints" in content
    assert "workflow_graph_writes" in content
    assert "owner_user_id" in content
    assert "state_version" in content
    assert "checkpoint_sequence" in content
    assert "BEFORE UPDATE OR DELETE" in content
    assert "fk_workflow_checkpoints_parent" in content
