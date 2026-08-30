"""Static contracts for synthetic evaluation migration 0026."""

from __future__ import annotations

import ast
from pathlib import Path

MIGRATION = Path("src/orchestwin/persistence/migrations/versions/0026_synthetic_evaluations.py")
ENVIRONMENT = Path("src/orchestwin/persistence/migrations/env.py")


def test_synthetic_evaluation_migration_extends_workflow_event_head() -> None:
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
        "revision": "0026_synthetic_evaluations",
        "down_revision": "0025_workflow_events",
    }


def test_migration_preserves_scope_epistemics_order_and_append_only_history() -> None:
    content = MIGRATION.read_text(encoding="utf-8")

    assert "evaluation_runs" in content
    assert "synthetic_findings" in content
    assert "owner_user_id" in content
    assert "workflow_run_id" in content
    assert "artifact_bundle_hash" in content
    assert "epistemic_status" in content
    assert "requires_human_validation" in content
    assert "uq_synthetic_findings_sequence" in content
    assert "BEFORE UPDATE OR DELETE" in content


def test_alembic_environment_registers_both_evaluation_records() -> None:
    tree = ast.parse(ENVIRONMENT.read_text(encoding="utf-8"))
    imported_names = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "orchestwin.evaluation.persistence"
        for alias in node.names
    }
    registered_names = {
        element.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_IMPORTED_MODELS"
            for target in node.targets
        )
        and isinstance(node.value, ast.Tuple)
        for element in node.value.elts
        if isinstance(element, ast.Name)
    }
    expected = {"EvaluationRunRecord", "SyntheticFindingRecord"}

    assert expected <= imported_names
    assert expected <= registered_names
