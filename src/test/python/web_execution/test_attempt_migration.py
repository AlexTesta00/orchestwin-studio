"""Static contract tests for the Web execution-attempt migration."""

from __future__ import annotations

import ast
from pathlib import Path

MIGRATION = Path("src/orchestwin/persistence/migrations/versions/0021_web_execution_attempts.py")


def test_migration_extends_the_web_source_revision_head() -> None:
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
        "revision": "0021_web_execution_attempts",
        "down_revision": "0020_web_source_revisions",
    }


def test_migration_guards_immutability_lineage_and_exact_source_binding() -> None:
    content = MIGRATION.read_text(encoding="utf-8")

    assert "BEFORE UPDATE OR DELETE" in content
    assert "previous_attempt_id" in content
    assert "source_revision_id" in content
    assert "uq_web_execution_attempts_project_number" in content
    assert "attempt_snapshot" in content
