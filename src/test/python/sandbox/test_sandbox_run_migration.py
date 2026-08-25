"""Tests for the immutable sandbox-run persistence migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "orchestwin"
    / "persistence"
    / "migrations"
    / "versions"
    / "0018_sandbox_runs.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sandbox_run_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load sandbox run migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_extends_brownfield_intake_head() -> None:
    migration = _load_migration()

    assert migration.revision == "0018_sandbox_runs"
    assert migration.down_revision == "0017_brownfield_intake"


def test_upgrade_creates_immutable_run_and_command_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration()
    created: dict[str, tuple[Any, ...]] = {}
    indexes: list[tuple[str, str, tuple[str, ...], bool]] = []
    executed: list[str] = []

    monkeypatch.setattr(
        migration.op,
        "create_table",
        lambda name, *elements, **_kwargs: created.setdefault(name, elements),
    )
    monkeypatch.setattr(
        migration.op,
        "create_index",
        lambda name, table_name, columns, *, unique, **_kwargs: indexes.append(
            (name, table_name, tuple(columns), unique)
        ),
    )
    monkeypatch.setattr(
        migration.op,
        "execute",
        lambda statement: executed.append(str(statement)),
    )

    migration.upgrade()

    assert tuple(created) == ("sandbox_runs", "sandbox_command_results")
    run_columns = {
        element.name: element
        for element in created["sandbox_runs"]
        if isinstance(element, sa.Column)
    }
    command_columns = {
        element.name: element
        for element in created["sandbox_command_results"]
        if isinstance(element, sa.Column)
    }
    assert isinstance(run_columns["evidence_snapshot"].type, postgresql.JSONB)
    assert isinstance(command_columns["stdout_log"].type, postgresql.JSONB)
    assert isinstance(command_columns["stderr_log"].type, postgresql.JSONB)
    assert isinstance(command_columns["artifacts"].type, postgresql.JSONB)
    assert indexes == [
        (
            "ix_sandbox_runs_project_recorded",
            "sandbox_runs",
            ("project_id", "recorded_at"),
            False,
        ),
        (
            "ix_sandbox_command_results_run_ordinal",
            "sandbox_command_results",
            ("run_id", "ordinal"),
            False,
        ),
    ]
    assert any("CREATE OR REPLACE FUNCTION" in statement for statement in executed)
    assert sum("CREATE TRIGGER" in statement for statement in executed) == 2


def test_downgrade_removes_children_before_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    migration = _load_migration()
    operations: list[tuple[str, str]] = []

    monkeypatch.setattr(
        migration.op,
        "execute",
        lambda statement: operations.append(("execute", str(statement))),
    )
    monkeypatch.setattr(
        migration.op,
        "drop_index",
        lambda name, **_kwargs: operations.append(("drop_index", name)),
    )
    monkeypatch.setattr(
        migration.op,
        "drop_table",
        lambda name, **_kwargs: operations.append(("drop_table", name)),
    )

    migration.downgrade()

    assert "DROP TRIGGER" in operations[0][1]
    assert operations[-2:] == [
        ("drop_table", "sandbox_command_results"),
        ("drop_table", "sandbox_runs"),
    ]
