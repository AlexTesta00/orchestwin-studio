from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa

MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "orchestwin"
    / "persistence"
    / "migrations"
    / "versions"
    / "0056_drop_clarification_rounds.py"
)


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("drop_clarification_rounds", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load the drop clarification rounds migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record_operations(migration, monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, tuple, dict]] = []
    for name in ("drop_index", "drop_table", "create_table", "create_index"):
        monkeypatch.setattr(
            migration.op,
            name,
            lambda *args, _name=name, **kwargs: calls.append((_name, args, kwargs)),
        )
    return calls


def test_revision_extends_the_brief_dialogue_head() -> None:
    migration = load_migration()

    assert migration.revision == "0056_drop_clarification_rounds"
    assert migration.down_revision == "0055_brief_dialogue"
    assert migration.TABLE == "clarification_rounds"


def test_upgrade_drops_the_indexes_before_the_table(monkeypatch: pytest.MonkeyPatch) -> None:
    migration = load_migration()
    calls = record_operations(migration, monkeypatch)

    migration.upgrade()

    assert calls == [
        (
            "drop_index",
            ("uq_clarification_rounds_open_project",),
            {"table_name": "clarification_rounds"},
        ),
        (
            "drop_index",
            ("ix_clarification_rounds_project_id",),
            {"table_name": "clarification_rounds"},
        ),
        ("drop_table", ("clarification_rounds",), {}),
    ]


def test_downgrade_recreates_the_table_as_the_original_migration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = load_migration()
    calls = record_operations(migration, monkeypatch)

    migration.downgrade()

    assert [call[0] for call in calls] == ["create_table", "create_index", "create_index"]
    table = calls[0][1]
    assert table[0] == "clarification_rounds"
    assert [item.name for item in table[1:] if isinstance(item, sa.Column)] == [
        "id",
        "project_id",
        "source_brief_version_number",
        "round_number",
        "catalog_version",
        "questions",
        "status",
        "created_by_user_id",
        "created_at",
        "answered_at",
        "resulting_brief_version_number",
    ]
    assert [item.name for item in table[1:] if isinstance(item, sa.CheckConstraint)] == [
        "ck_clarification_rounds_source_brief_version_positive",
        "ck_clarification_rounds_round_number_valid",
        "ck_clarification_rounds_catalog_version_positive",
        "ck_clarification_rounds_questions_non_empty_array",
        "ck_clarification_rounds_status_valid",
        "ck_clarification_rounds_state_consistent",
    ]
    assert [item.name for item in table[1:] if isinstance(item, sa.UniqueConstraint)] == [
        "uq_clarification_rounds_project_id_round_number",
        "uq_clarification_rounds_project_id_source_brief_version",
    ]
    assert calls[1][1] == (
        "ix_clarification_rounds_project_id",
        "clarification_rounds",
        ["project_id"],
    )
    assert calls[2][1] == (
        "uq_clarification_rounds_open_project",
        "clarification_rounds",
        ["project_id"],
    )
    assert calls[2][2]["unique"] is True
    assert str(calls[2][2]["postgresql_where"]) == "status = 'OPEN'"
