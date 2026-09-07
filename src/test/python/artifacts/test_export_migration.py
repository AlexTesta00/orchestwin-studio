"""Static contracts for deterministic export persistence migration."""

from __future__ import annotations

import ast
from pathlib import Path

MIGRATION = Path("src/orchestwin/persistence/migrations/versions/0028_export_bundles.py")
ENVIRONMENT = Path("src/orchestwin/persistence/migrations/env.py")


def test_export_migration_is_linear_and_append_only() -> None:
    content = MIGRATION.read_text(encoding="utf-8")

    assert 'revision: str = "0028_export_bundles"' in content
    assert 'down_revision: str | None = "0027_final_review_gate"' in content
    assert '"export_bundles"' in content
    assert "trg_export_bundles_immutable" in content
    assert "archive_hash" in content


def test_alembic_environment_registers_export_bundle_record() -> None:
    tree = ast.parse(ENVIRONMENT.read_text(encoding="utf-8"))
    imported = {
        alias.name for node in tree.body if isinstance(node, ast.ImportFrom) for alias in node.names
    }
    model_tuple = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_IMPORTED_MODELS"
            for target in node.targets
        )
    )
    registered = {element.id for element in model_tuple.elts if isinstance(element, ast.Name)}

    assert "ExportBundleRecord" in imported
    assert "ExportBundleRecord" in registered
