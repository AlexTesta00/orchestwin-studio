"""Static contract tests for the JVM execution-attempt migration."""

from __future__ import annotations

import ast
from pathlib import Path

MIGRATION = Path("src/orchestwin/persistence/migrations/versions/0023_jvm_execution_attempts.py")


def test_migration_extends_the_jvm_source_revision_head() -> None:
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
        "revision": "0023_jvm_execution_attempts",
        "down_revision": "0022_jvm_source_revisions",
    }


def test_migration_guards_immutability_lineage_and_exact_jvm_binding() -> None:
    content = MIGRATION.read_text(encoding="utf-8")

    assert "BEFORE UPDATE OR DELETE" in content
    assert "previous_attempt_id" in content
    assert "jvm_source_revisions.project_id" in content
    assert "uq_jvm_execution_attempts_project_number" in content
    assert "attempt_snapshot" in content
    assert "JVM_KOTLIN" in content
    assert "ANDROID" not in content
