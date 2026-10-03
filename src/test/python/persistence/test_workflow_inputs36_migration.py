from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
import sqlalchemy as sa


def capture(monkeypatch):
    migration = importlib.import_module(
        "orchestwin.persistence.migrations.versions.0070_workflow_inputs"
    )
    calls = []
    for name in (
        "create_table",
        "create_index",
        "create_check_constraint",
        "drop_constraint",
        "execute",
        "drop_index",
        "drop_table",
    ):
        monkeypatch.setattr(
            migration.op,
            name,
            lambda *args, _name=name, **kwargs: calls.append((_name, args, kwargs)),
        )
    return migration, calls


def test_migration_preserves_legacy_team_origins_and_owns_only_two_immutable_tables(monkeypatch):
    migration, calls = capture(monkeypatch)
    migration.upgrade()
    assert migration.down_revision == "0069_human_validation"
    tables = [
        sa.Table(args[0], sa.MetaData(), *args[1:])
        for name, args, _ in calls
        if name == "create_table"
    ]
    assert [table.name for table in tables] == [
        "project_workflow_decisions",
        "project_provided_prototypes",
    ]
    assert all(
        foreign.ondelete == "RESTRICT"
        for table in tables
        for foreign in table.foreign_key_constraints
    )
    checks = [args for name, args, _ in calls if name == "create_check_constraint"]
    assert len(checks) == 2 and all(args[1] == "team_proposals" for args in checks)
    assert all(
        "PROPOSER_GENERATED" in args[2]
        and "OWNER_EDITED" in args[2]
        and "OWNER_PROVIDED" in args[2]
        for args in checks
    )
    sql = [str(args[0]) for name, args, _ in calls if name == "execute"]
    assert len(sql) == 3 and all("UPDATE OR DELETE" in statement for statement in sql[1:])


def test_populated_downgrade_refuses_before_any_drop_or_constraint_change(monkeypatch):
    migration, calls = capture(monkeypatch)
    monkeypatch.setattr(
        migration.op,
        "get_bind",
        lambda: SimpleNamespace(scalar=lambda statement: "OWNER_PROVIDED" in str(statement)),
    )
    with pytest.raises(RuntimeError, match="must be preserved"):
        migration.downgrade()
    assert calls == []


def test_empty_downgrade_restores_both_original_team_checks(monkeypatch):
    migration, calls = capture(monkeypatch)
    monkeypatch.setattr(migration.op, "get_bind", lambda: SimpleNamespace(scalar=lambda _: False))
    migration.downgrade()
    assert [args[0] for name, args, _ in calls if name == "drop_table"] == [
        "project_provided_prototypes",
        "project_workflow_decisions",
    ]
    checks = [args for name, args, _ in calls if name == "create_check_constraint"]
    assert len(checks) == 2 and all("OWNER_PROVIDED" not in args[2] for args in checks)
