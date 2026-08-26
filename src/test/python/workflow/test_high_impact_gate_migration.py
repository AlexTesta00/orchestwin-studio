"""Tests for Gate 7 request and human-gate persistence migration."""

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
    / "0019_high_impact_gate_type.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("high_impact_gate_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load Gate 7 migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_extends_sandbox_run_head() -> None:
    migration = _load()

    assert migration.revision == "0019_high_impact_gate_type"
    assert migration.down_revision == "0018_sandbox_runs"


def test_upgrade_creates_immutable_requests_and_enables_gate_7(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load()
    created: dict[str, tuple[Any, ...]] = {}
    constraints: list[str] = []
    executed: list[str] = []

    monkeypatch.setattr(
        migration.op,
        "create_table",
        lambda name, *elements, **_kwargs: created.setdefault(name, elements),
    )
    monkeypatch.setattr(migration.op, "create_index", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(migration.op, "execute", lambda statement: executed.append(str(statement)))
    monkeypatch.setattr(migration.op, "drop_constraint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        migration.op,
        "create_check_constraint",
        lambda _name, _table, expression: constraints.append(expression),
    )

    migration.upgrade()

    columns = {
        element.name: element
        for element in created["high_impact_operation_versions"]
        if isinstance(element, sa.Column)
    }
    assert isinstance(columns["request_snapshot"].type, postgresql.JSONB)
    assert isinstance(columns["classification_snapshot"].type, postgresql.JSONB)
    assert len(constraints) == 2
    assert all("'HIGH_IMPACT_OPERATION'" in expression for expression in constraints)
    assert any("CREATE TRIGGER" in statement for statement in executed)
