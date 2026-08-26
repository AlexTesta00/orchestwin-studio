"""Tests for the brownfield intake persistence migration."""

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
    / "0017_brownfield_intake.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("brownfield_intake_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load brownfield intake migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_extends_architecture_gate_head() -> None:
    migration = _load_migration()

    assert migration.revision == "0017_brownfield_intake"
    assert migration.down_revision == "0016_architecture_gate_type"


def test_upgrade_creates_immutable_jsonb_intake_versions(
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

    assert tuple(created) == ("brownfield_intake_versions",)
    columns = {
        element.name: element
        for element in created["brownfield_intake_versions"]
        if isinstance(element, sa.Column)
    }
    checks = {
        str(element.name)
        for element in created["brownfield_intake_versions"]
        if isinstance(element, sa.CheckConstraint)
    }

    assert isinstance(columns["intake_snapshot"].type, postgresql.JSONB)
    assert "ck_brownfield_intake_versions_linear_lineage" in checks
    assert "ck_brownfield_intake_versions_capability_status" in checks
    assert indexes == [
        (
            "ix_brownfield_intake_versions_project_version",
            "brownfield_intake_versions",
            ("project_id", "version_number"),
            False,
        )
    ]
    assert any("CREATE OR REPLACE FUNCTION" in statement for statement in executed)
    assert any("CREATE TRIGGER" in statement for statement in executed)


def test_downgrade_removes_guard_before_table(monkeypatch: pytest.MonkeyPatch) -> None:
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

    assert operations[0][0] == "execute"
    assert "DROP TRIGGER" in operations[0][1]
    assert operations[-1] == ("drop_table", "brownfield_intake_versions")
