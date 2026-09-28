from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from orchestwin.knowledge.packages import MAX_PACKAGE_ARCHIVE_SIZE, MAX_PACKAGE_FILE_NAME_LENGTH

MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "orchestwin"
    / "persistence"
    / "migrations"
    / "versions"
    / "0060_knowledge_package_versions.py"
)
TABLE = "knowledge_package_versions"
FUNCTION = "reject_knowledge_package_version_mutation"
TRIGGER = "trg_knowledge_package_versions_immutable"


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "knowledge_package_versions_migration", MIGRATION_PATH
    )
    if spec is None or spec.loader is None:
        raise AssertionError("could not load the knowledge package versions migration")
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


def test_revision_follows_the_twin_discussions_and_mirrors_the_package_limits():
    migration = load_migration()
    assert migration.revision == "0060_knowledge_package_versions"
    assert migration.down_revision == "0059_twin_discussions"
    assert migration.ARCHIVE_LIMIT == MAX_PACKAGE_ARCHIVE_SIZE
    assert migration.FILE_NAME_LIMIT == MAX_PACKAGE_FILE_NAME_LENGTH


def test_upgrade_creates_the_append_only_package_table(monkeypatch: pytest.MonkeyPatch):
    migration = load_migration()
    calls = record_operations(migration, monkeypatch)
    migration.upgrade()
    assert [call[0] for call in calls] == ["create_table", "create_index", "execute", "execute"]
    table = created_table(calls[0])
    assert table.name == TABLE
    assert [column.name for column in table.columns] == [
        "id",
        "project_id",
        "owner_user_id",
        "version_number",
        "schema_version",
        "content_hash",
        "archive_hash",
        "file_name",
        "file_count",
        "archive_size",
        "manifest",
        "archive",
        "created_at",
    ]
    assert [column.name for column in table.columns if column.nullable] == []
    for name in ("id", "project_id", "owner_user_id"):
        assert isinstance(table.c[name].type, postgresql.UUID)
        assert table.c[name].type.as_uuid is True
    for name in ("version_number", "schema_version", "file_count", "archive_size"):
        assert isinstance(table.c[name].type, sa.Integer)
    assert table.c.content_hash.type.length == 64
    assert table.c.archive_hash.type.length == 64
    assert table.c.file_name.type.length == 200
    assert isinstance(table.c.manifest.type, postgresql.JSONB)
    assert isinstance(table.c.archive.type, sa.LargeBinary)
    assert isinstance(table.c.created_at.type, sa.DateTime)
    assert table.c.created_at.type.timezone is True
    assert table.primary_key.name == f"pk_{TABLE}"
    assert list(table.primary_key.columns.keys()) == ["id"]
    assert {
        constraint.name: [column.name for column in constraint.columns]
        for constraint in table.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    } == {f"uq_{TABLE}_project_version": ["project_id", "version_number"]}
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
        f"ck_{TABLE}_version_number": "version_number >= 1",
        f"ck_{TABLE}_schema_version": "schema_version >= 1",
        f"ck_{TABLE}_file_count": "file_count >= 1",
        f"ck_{TABLE}_archive_size": "archive_size BETWEEN 1 AND 67108864",
        f"ck_{TABLE}_content_hash": "content_hash ~ '^[0-9a-f]{64}$'",
        f"ck_{TABLE}_archive_hash": "archive_hash ~ '^[0-9a-f]{64}$'",
        f"ck_{TABLE}_archive_length": "octet_length(archive) = archive_size",
        f"ck_{TABLE}_file_name": "char_length(file_name) BETWEEN 1 AND 200",
    }
    assert calls[1][1:] == (
        (f"ix_{TABLE}_project_created", TABLE, ["project_id", "created_at"]),
        {},
    )
    assert [call[1:] for call in calls[2:]] == [
        ((migration.CREATE_FUNCTION,), {}),
        ((migration.CREATE_TRIGGER,), {}),
    ]
    assert flattened(migration.CREATE_FUNCTION) == (
        f"CREATE FUNCTION {FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN"
        " RAISE EXCEPTION 'Knowledge package versions are immutable'; END; $$;"
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
        ("drop_index", (f"ix_{TABLE}_project_created",), {"table_name": TABLE}),
        ("drop_table", (TABLE,), {}),
    ]
