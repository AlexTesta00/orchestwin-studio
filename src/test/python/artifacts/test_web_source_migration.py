"""Static contract tests for the Web source revision migration."""

from __future__ import annotations

import ast
from pathlib import Path

MIGRATION = Path("src/orchestwin/persistence/migrations/versions/0020_web_source_revisions.py")


def test_migration_extends_the_single_sprint07_head() -> None:
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
        "revision": "0020_web_source_revisions",
        "down_revision": "0019_high_impact_gate_type",
    }


def test_migration_contains_immutability_and_linear_lineage_guards() -> None:
    content = MIGRATION.read_text(encoding="utf-8")

    assert "BEFORE UPDATE OR DELETE" in content
    assert "version_number - 1" in content
    assert "uq_web_source_revisions_project_version" in content
    assert "revision_snapshot" in content
