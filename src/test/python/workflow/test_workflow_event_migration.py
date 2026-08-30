"""Static contracts for ordered workflow-event migration 0025."""

from __future__ import annotations

import ast
from pathlib import Path

MIGRATION = Path("src/orchestwin/persistence/migrations/versions/0025_workflow_events.py")


def test_workflow_event_migration_extends_checkpoint_head() -> None:
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
        "revision": "0025_workflow_events",
        "down_revision": "0024_workflow_runs_checkpoints",
    }


def test_migration_preserves_scope_order_hash_and_append_only_history() -> None:
    content = MIGRATION.read_text(encoding="utf-8")

    assert "workflow_events" in content
    assert "owner_user_id" in content
    assert "sequence_number" in content
    assert "payload_hash" in content
    assert "ck_workflow_events_event_type" in content
    assert "fk_workflow_events_run_scope" in content
    assert "uq_workflow_events_sequence" in content
    assert "BEFORE UPDATE OR DELETE" in content
