from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from orchestwin.knowledge.project_import_persistence import PROJECT_IMPORTS, SOURCE_NAME_LIMIT

MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "orchestwin"
    / "persistence"
    / "migrations"
    / "versions"
    / "0061_project_imports.py"
)
TABLE = "project_imports"
FUNCTION = "reject_project_import_mutation"
TRIGGER = "trg_project_imports_immutable"
COLUMNS = [
    "id",
    "project_id",
    "owner_user_id",
    "source_project_id",
    "source_project_name",
    "package_version",
    "package_content_hash",
    "schema_version",
    "archive_hash",
    "archive_size",
    "stage_versions",
    "imported_at",
]


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("project_imports_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load the project imports migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record_operations(migration, monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, tuple, dict]] = []
    for name in ("create_table", "create_index", "drop_index", "drop_table", "execute"):
        monkeypatch.setattr(
            migration.op,
            name,
            lambda *args, _name=name, **kwargs: calls.append((_name, args, kwargs)),
        )
    monkeypatch.setattr(migration.op, "f", lambda value: value)
    return calls


def created_table(call) -> sa.Table:
    name, *elements = call[1]
    return sa.Table(name, sa.MetaData(), *elements)


def flattened(statement: str) -> str:
    return " ".join(statement.split())


def test_revision_follows_the_knowledge_packages_and_mirrors_the_repository_table():
    migration = load_migration()
    assert migration.revision == "0061_project_imports"
    assert migration.down_revision == "0060_knowledge_package_versions"
    assert migration.SOURCE_NAME_LIMIT == SOURCE_NAME_LIMIT
    assert PROJECT_IMPORTS.name == TABLE
    assert [column.name for column in PROJECT_IMPORTS.columns] == COLUMNS


def test_upgrade_creates_the_append_only_import_table(monkeypatch: pytest.MonkeyPatch):
    migration = load_migration()
    calls = record_operations(migration, monkeypatch)
    migration.upgrade()
    assert [call[0] for call in calls] == ["create_table", "create_index", "execute", "execute"]
    table = created_table(calls[0])
    assert table.name == TABLE
    assert [column.name for column in table.columns] == COLUMNS
    assert [column.name for column in table.columns if column.nullable] == []
    for name in ("id", "project_id", "owner_user_id", "source_project_id"):
        assert isinstance(table.c[name].type, postgresql.UUID)
        assert table.c[name].type.as_uuid is True
    for name in ("package_version", "schema_version", "archive_size"):
        assert isinstance(table.c[name].type, sa.Integer)
    assert table.c.source_project_name.type.length == 200
    assert table.c.package_content_hash.type.length == 64
    assert table.c.archive_hash.type.length == 64
    assert isinstance(table.c.stage_versions.type, postgresql.JSONB)
    assert isinstance(table.c.imported_at.type, sa.DateTime)
    assert table.c.imported_at.type.timezone is True
    assert table.primary_key.name == f"pk_{TABLE}"
    assert list(table.primary_key.columns.keys()) == ["id"]
    assert {
        constraint.name: [column.name for column in constraint.columns]
        for constraint in table.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    } == {f"uq_{TABLE}_project": ["project_id"]}
    assert {
        constraint.name: (
            [element.parent.name for element in constraint.elements],
            [element.target_fullname for element in constraint.elements],
            constraint.ondelete,
        )
        for constraint in table.foreign_key_constraints
    } == {
        f"fk_{TABLE}_project": (["project_id"], ["projects.id"], "RESTRICT"),
        f"fk_{TABLE}_owner": (["owner_user_id"], ["users.id"], "RESTRICT"),
    }
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }
    assert checks == {
        f"ck_{TABLE}_package_version": "package_version >= 1",
        f"ck_{TABLE}_schema_version": "schema_version >= 1",
        f"ck_{TABLE}_archive_size": "archive_size >= 1",
        f"ck_{TABLE}_package_content_hash": "package_content_hash ~ '^[0-9a-f]{64}$'",
        f"ck_{TABLE}_archive_hash": "archive_hash ~ '^[0-9a-f]{64}$'",
        f"ck_{TABLE}_source_project_name": "char_length(source_project_name) BETWEEN 1 AND 200",
    }
    assert calls[1][1:] == (
        (f"ix_{TABLE}_owner_imported", TABLE, ["owner_user_id", "imported_at"]),
        {},
    )
    assert [call[1:] for call in calls[2:]] == [
        ((migration.CREATE_FUNCTION,), {}),
        ((migration.CREATE_TRIGGER,), {}),
    ]
    assert flattened(migration.CREATE_FUNCTION) == (
        f"CREATE FUNCTION {FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN"
        " RAISE EXCEPTION 'Project imports are immutable'; END; $$;"
    )
    assert flattened(migration.CREATE_TRIGGER) == (
        f"CREATE TRIGGER {TRIGGER} BEFORE UPDATE OR DELETE ON {TABLE} FOR EACH ROW"
        f" EXECUTE FUNCTION {FUNCTION}();"
    )


def test_downgrade_drops_the_trigger_the_function_the_index_and_the_table(
    monkeypatch: pytest.MonkeyPatch,
):
    migration = load_migration()
    calls = record_operations(migration, monkeypatch)
    migration.downgrade()
    assert calls == [
        ("execute", (f"DROP TRIGGER IF EXISTS {TRIGGER} ON {TABLE};",), {}),
        ("execute", (f"DROP FUNCTION IF EXISTS {FUNCTION}();",), {}),
        ("drop_index", (f"ix_{TABLE}_owner_imported",), {"table_name": TABLE}),
        ("drop_table", (TABLE,), {}),
    ]
