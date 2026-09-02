"""Static contracts for training dataset migration 0030."""

from __future__ import annotations

import ast
from pathlib import Path

MIGRATION = Path("src/orchestwin/persistence/migrations/versions/0030_training_datasets.py")
ENVIRONMENT = Path("src/orchestwin/persistence/migrations/env.py")


def test_training_dataset_migration_extends_the_current_langgraph_head() -> None:
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
        "revision": "0030_training_datasets",
        "down_revision": "0029_langgraph_pending_writes",
    }


def test_migration_preserves_owner_scope_quality_evidence_and_immutability() -> None:
    content = MIGRATION.read_text(encoding="utf-8")

    assert "training_dataset_versions" in content
    assert "training_dataset_quality_reports" in content
    assert "owner_user_id" in content
    assert "policy_content_hash" in content
    assert "examples_digest" in content
    assert "leakage_issue_count" in content
    assert "BEFORE UPDATE OR DELETE" in content


def test_alembic_environment_registers_training_dataset_records() -> None:
    tree = ast.parse(ENVIRONMENT.read_text(encoding="utf-8"))
    imported_names = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "orchestwin.training.persistence"
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
    expected = {
        "TrainingDatasetVersionRecord",
        "TrainingDatasetQualityReportRecord",
    }

    assert expected <= imported_names
    assert expected <= registered_names
