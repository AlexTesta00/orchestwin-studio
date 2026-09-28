from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa

from orchestwin.knowledge.package_persistence import (
    PACKAGE_VERSIONS,
    PROJECT_VERSION_CONSTRAINT,
    KnowledgePackageWriteStatus,
    SqlAlchemyKnowledgePackageRepository,
)

MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "orchestwin"
    / "persistence"
    / "migrations"
    / "versions"
    / "0060_knowledge_package_versions.py"
)


class EmptyResult:
    def mappings(self) -> EmptyResult:
        return self

    def all(self) -> list[object]:
        return []

    def one_or_none(self) -> None:
        return None

    def scalar_one_or_none(self) -> None:
        return None


class RecordingSession:
    def __init__(self) -> None:
        self.statements: list[sa.Select] = []

    async def execute(self, statement: sa.Select) -> EmptyResult:
        self.statements.append(statement)
        return EmptyResult()


def migrated_table(monkeypatch: pytest.MonkeyPatch) -> sa.Table:
    spec = importlib.util.spec_from_file_location(
        "knowledge_package_versions_migration", MIGRATION_PATH
    )
    if spec is None or spec.loader is None:
        raise AssertionError("could not load the knowledge package versions migration")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    tables: list[sa.Table] = []
    monkeypatch.setattr(
        migration.op,
        "create_table",
        lambda name, *elements: tables.append(sa.Table(name, sa.MetaData(), *elements)),
    )
    for name in ("create_index", "execute"):
        monkeypatch.setattr(migration.op, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "f", lambda value: value)
    migration.upgrade()
    [table] = tables
    return table


def shape(table: sa.TableClause) -> list[tuple[str, type, object, object]]:
    return [
        (
            column.name,
            type(column.type),
            getattr(column.type, "length", None),
            getattr(column.type, "timezone", None),
        )
        for column in table.columns
    ]


def test_the_table_mirrors_the_migration_columns_in_order(monkeypatch: pytest.MonkeyPatch):
    migrated = migrated_table(monkeypatch)
    assert PACKAGE_VERSIONS.name == migrated.name
    assert [column.name for column in PACKAGE_VERSIONS.columns] == [
        column.name for column in migrated.columns
    ]
    assert shape(PACKAGE_VERSIONS) == shape(migrated)
    assert [
        constraint.name
        for constraint in migrated.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    ] == [PROJECT_VERSION_CONSTRAINT]


def test_write_statuses_name_every_outcome():
    assert [status.value for status in KnowledgePackageWriteStatus] == [
        "WRITTEN",
        "PROJECT_NOT_FOUND",
        "VERSION_CONFLICT",
    ]


def test_metadata_reads_never_select_the_archive():
    session = RecordingSession()
    repository = SqlAlchemyKnowledgePackageRepository(session, owner_user_id=uuid4())
    project = uuid4()

    async def scenario():
        assert await repository.list(project_id=project) == ()
        assert await repository.get(project_id=project, version_number=1) is None
        assert await repository.latest(project_id=project) is None
        assert await repository.archive(project_id=project, version_number=1) is None

    asyncio.run(scenario())
    metadata = [column.name for column in PACKAGE_VERSIONS.columns if column.name != "archive"]
    assert [
        [column.name for column in statement.selected_columns] for statement in session.statements
    ] == [metadata, metadata, metadata, ["archive"]]
