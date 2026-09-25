from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from orchestwin.twins.limits import MAX_USER_TWINS

MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "orchestwin"
    / "persistence"
    / "migrations"
    / "versions"
    / "0054_eight_user_twins.py"
)
TABLE = "user_modeling_snapshot_versions"
NAMES = (f"ck_{TABLE}_persona_count", f"ck_{TABLE}_twin_count")


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("eight_user_twins_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load the eight user twins migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record_operations(migration, monkeypatch: pytest.MonkeyPatch):
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
    return dropped, created


def test_revision_extends_the_source_task_hooks_head() -> None:
    migration = load_migration()

    assert migration.revision == "0054_eight_user_twins"
    assert migration.down_revision == "0053_source_task_hooks"
    assert migration.LIMIT == MAX_USER_TWINS
    assert migration.PREVIOUS_LIMIT == 4


def test_upgrade_widens_both_count_constraints_to_the_shared_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = load_migration()
    dropped, created = record_operations(migration, monkeypatch)

    migration.upgrade()

    assert dropped == [(name, TABLE, "check") for name in NAMES]
    assert created == [
        (NAMES[0], TABLE, f"persona_count BETWEEN 1 AND {MAX_USER_TWINS}"),
        (NAMES[1], TABLE, f"twin_count BETWEEN 1 AND {MAX_USER_TWINS}"),
    ]


def test_downgrade_restores_the_limit_of_four(monkeypatch: pytest.MonkeyPatch) -> None:
    migration = load_migration()
    dropped, created = record_operations(migration, monkeypatch)

    migration.downgrade()

    assert dropped == [(name, TABLE, "check") for name in NAMES]
    assert created == [
        (NAMES[0], TABLE, "persona_count BETWEEN 1 AND 4"),
        (NAMES[1], TABLE, "twin_count BETWEEN 1 AND 4"),
    ]
