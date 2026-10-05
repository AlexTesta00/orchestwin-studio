from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
import sqlalchemy as sa


def migration():
    return importlib.import_module(
        "orchestwin.persistence.migrations.versions.0069_human_validation"
    )


def capture(monkeypatch):
    module = migration()
    calls = []
    for name in ("create_table", "create_index", "execute", "drop_index", "drop_table"):
        monkeypatch.setattr(
            module.op, name, lambda *args, _name=name, **kwargs: calls.append((_name, args, kwargs))
        )
    return module, calls


def test_additive_migration_owns_only_two_tables_and_immutable_triggers(monkeypatch):
    module, calls = capture(monkeypatch)
    assert (
        module.revision == "0069_human_validation"
        and module.down_revision == "0068_research_evidence"
    )
    module.upgrade()
    created = [
        sa.Table(call[1][0], sa.MetaData(), *call[1][1:])
        for call in calls
        if call[0] == "create_table"
    ]
    assert [table.name for table in created] == [
        "project_validation_hypotheses",
        "project_validation_outcomes",
    ]
    assert set(created[0].primary_key.columns.keys()) == {"id", "version_number"}
    assert len(created[1].foreign_key_constraints) == 4
    assert all(
        item.ondelete == "RESTRICT" for table in created for item in table.foreign_key_constraints
    )
    triggers = [str(call[1][0]) for call in calls if call[0] == "execute"]
    assert len(triggers) == 3 and all("UPDATE OR DELETE" in sql for sql in triggers[1:])


def test_downgrade_refuses_any_validation_data_without_silent_deletion(monkeypatch):
    module, calls = capture(monkeypatch)
    monkeypatch.setattr(module.op, "get_bind", lambda: SimpleNamespace(scalar=lambda _: True))
    with pytest.raises(RuntimeError, match="must be preserved"):
        module.downgrade()
    assert calls == []


def test_empty_downgrade_drops_only_owned_tables_and_function(monkeypatch):
    module, calls = capture(monkeypatch)
    monkeypatch.setattr(module.op, "get_bind", lambda: SimpleNamespace(scalar=lambda _: False))
    module.downgrade()
    assert [call[1][0] for call in calls if call[0] == "drop_table"] == [
        "project_validation_outcomes",
        "project_validation_hypotheses",
    ]
    assert calls[-1][1] == ("DROP FUNCTION human_validation_append_only()",)
