"""Static contracts for QLoRA training run migration 0031."""

from __future__ import annotations

import ast
from pathlib import Path

MIGRATION = Path("src/orchestwin/persistence/migrations/versions/0031_training_runs.py")
ENVIRONMENT = Path("src/orchestwin/persistence/migrations/env.py")


def test_training_run_migration_extends_the_dataset_head() -> None:
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
        "revision": "0031_training_runs",
        "down_revision": "0030_training_datasets",
    }


def test_migration_preserves_reproducibility_evidence_and_immutability() -> None:
    content = MIGRATION.read_text(encoding="utf-8")

    for required in (
        "training_runs",
        "training_run_checkpoints",
        "owner_user_id",
        "dataset_content_hash",
        "configuration_sha256",
        "package_lock_sha256",
        "environment_sha256",
        "process_log_sha256",
        "peak_gpu_memory_mb",
        "outcome_snapshot_json",
        "BEFORE UPDATE OR DELETE",
    ):
        assert required in content


def test_alembic_environment_registers_training_run_records() -> None:
    tree = ast.parse(ENVIRONMENT.read_text(encoding="utf-8"))
    imported_names = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "orchestwin.training.training_run_persistence"
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
    expected = {"TrainingRunRecord", "TrainingRunCheckpointRecord"}

    assert expected <= imported_names
    assert expected <= registered_names
