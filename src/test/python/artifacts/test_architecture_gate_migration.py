from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "orchestwin"
    / "persistence"
    / "migrations"
    / "versions"
    / "0016_architecture_gate_type.py"
)


def load_migration() -> ModuleType:
    """Load the migration directly from its file."""
    spec = importlib.util.spec_from_file_location(
        "architecture_gate_type_migration",
        MIGRATION_PATH,
    )

    if spec is None or spec.loader is None:
        raise AssertionError("could not load architecture gate type migration")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def test_revision_extends_architecture_package_head() -> None:
    """Keep Gate 6 migration after Architecture Package persistence."""
    migration = load_migration()

    assert migration.revision == "0016_architecture_gate_type"
    assert migration.down_revision == "0015_architecture_packages"


def test_upgrade_adds_architecture_to_gate_and_event_constraints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Allow Gate 6 state and events without dropping prior gate types."""
    migration = load_migration()
    dropped: list[tuple[str, str, str]] = []
    created: list[tuple[str, str, str]] = []

    monkeypatch.setattr(
        migration.op,
        "drop_constraint",
        lambda name, table, *, type_: dropped.append((name, table, type_)),
    )
    monkeypatch.setattr(
        migration.op,
        "create_check_constraint",
        lambda name, table, expression: created.append((name, table, expression)),
    )

    migration.upgrade()

    assert len(dropped) == 2
    assert len(created) == 2

    for _name, _table, expression in created:
        assert "'PROJECT_BRIEF'" in expression
        assert "'AGENT_TEAM'" in expression
        assert "'USER_MODELING'" in expression
        assert "'REQUIREMENTS'" in expression
        assert "'DESIGN'" in expression
        assert "'ARCHITECTURE'" in expression


def test_downgrade_removes_only_architecture_gate_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Restore Gate 1 through Gate 5 persistence semantics."""
    migration = load_migration()
    created: list[str] = []

    monkeypatch.setattr(
        migration.op,
        "drop_constraint",
        lambda _name, _table, *, type_: None,
    )
    monkeypatch.setattr(
        migration.op,
        "create_check_constraint",
        lambda _name, _table, expression: created.append(expression),
    )

    migration.downgrade()

    assert len(created) == 2

    for expression in created:
        assert "'PROJECT_BRIEF'" in expression
        assert "'AGENT_TEAM'" in expression
        assert "'USER_MODELING'" in expression
        assert "'REQUIREMENTS'" in expression
        assert "'DESIGN'" in expression
        assert "'ARCHITECTURE'" not in expression
