"""Static contract tests for the Gate 8 final-review migration."""

from __future__ import annotations

import ast
from pathlib import Path

MIGRATION = Path("src/orchestwin/persistence/migrations/versions/0027_final_review_gate.py")
ENVIRONMENT = Path("src/orchestwin/persistence/migrations/env.py")
MODELS = Path("src/orchestwin/workflow/persistence/models.py")


def test_final_review_migration_is_linear_and_append_only() -> None:
    content = MIGRATION.read_text(encoding="utf-8")

    assert 'revision: str = "0027_final_review_gate"' in content
    assert 'down_revision: str | None = "0026_synthetic_evaluations"' in content
    assert '"final_reviews"' in content
    assert "trg_final_reviews_immutable" in content
    assert '"FINAL_OUTPUT"' in content


def test_alembic_environment_registers_final_review_record() -> None:
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

    assert "FinalReviewRecord" in imported
    assert "FinalReviewRecord" in registered


def test_orm_gate_constraints_include_final_output() -> None:
    content = MODELS.read_text(encoding="utf-8")

    assert content.count("'FINAL_OUTPUT'") == 2
