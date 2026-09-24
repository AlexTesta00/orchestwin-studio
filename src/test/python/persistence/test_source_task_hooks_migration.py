from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "orchestwin"
    / "persistence"
    / "migrations"
    / "versions"
    / "0053_source_task_hooks.py"
)

TRIGGERS = (
    ("model_proposal_generations", "model_source_file_request"),
    ("model_proposal_generations", "model_source_syntax_retry"),
    ("model_proposal_generation_events", "model_source_file_acceptance"),
    ("model_proposal_artifact_links", "model_source_artifact_exact"),
)
FUNCTIONS = (
    "validate_source_file_request",
    "validate_source_syntax_retry",
    "validate_source_file_acceptance",
    "validate_model_source_link",
)
INDEX = "uq_source_file_parent_ordinal"


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("source_task_hooks_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load the source task hooks migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_extends_the_design_first_scope_head() -> None:
    migration = load_migration()

    assert migration.revision == "0053_source_task_hooks"
    assert migration.down_revision == "0052_design_first_scope"
    assert migration.TRIGGERS == TRIGGERS
    assert migration.FUNCTIONS == FUNCTIONS
    assert migration.INDEX == INDEX
    assert "model_source_context" not in migration.FUNCTIONS


def test_upgrade_drops_the_triggers_before_their_functions_and_the_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = load_migration()
    executed: list[str] = []
    dropped_indexes: list[tuple[str, str]] = []
    monkeypatch.setattr(migration.op, "execute", lambda statement: executed.append(statement))
    monkeypatch.setattr(
        migration.op,
        "drop_index",
        lambda name, *, table_name: dropped_indexes.append((name, table_name)),
    )

    migration.upgrade()

    assert executed[:4] == [f"DROP TRIGGER {trigger} ON {table}" for table, trigger in TRIGGERS]
    assert executed[4:] == [f"DROP FUNCTION {function}()" for function in FUNCTIONS]
    assert dropped_indexes == [(INDEX, "model_proposal_generations")]


def test_downgrade_restores_the_functions_the_index_and_the_triggers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = load_migration()
    executed: list[str] = []
    monkeypatch.setattr(migration.op, "execute", lambda statement: executed.append(statement))

    migration.downgrade()

    functions, index, triggers = executed
    assert re.findall(r"^CREATE OR REPLACE FUNCTION ([a-z_]+)\(\)", functions, re.M) == list(
        FUNCTIONS
    )
    assert index.strip().startswith(f"CREATE UNIQUE INDEX {INDEX} ON model_proposal_generations")
    assert "WHERE model_source_context(snapshot_json) ? 'source_step'" in index
    created = re.findall(r"^CREATE TRIGGER ([a-z_]+) BEFORE INSERT ON ([a-z_]+)", triggers, re.M)
    assert created == [(trigger, table) for table, trigger in TRIGGERS]
    for function in FUNCTIONS:
        assert f"EXECUTE FUNCTION {function}()" in triggers
    assert "public." not in functions + index + triggers
    assert not re.search(r"^(DROP |TRUNCATE |DELETE FROM )", functions + index + triggers, re.M)
