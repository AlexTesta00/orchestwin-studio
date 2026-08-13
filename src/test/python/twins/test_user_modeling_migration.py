"""Contract tests for User Modeling persistence migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

EXPECTED_TABLES = (
    "persona_profile_versions",
    "user_twin_profile_versions",
    "user_modeling_snapshot_versions",
)

MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "orchestwin"
    / "persistence"
    / "migrations"
    / "versions"
    / "0009_user_modeling_snapshots.py"
)


def load_migration() -> ModuleType:
    """Load the Alembic revision without requiring package imports."""
    spec = importlib.util.spec_from_file_location(
        "user_modeling_migration",
        MIGRATION_PATH,
    )

    if spec is None or spec.loader is None:
        raise AssertionError("could not load User Modeling migration")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def columns_of(
    elements: tuple[Any, ...],
) -> dict[str, sa.Column[Any]]:
    """Return table columns keyed by their stable name."""
    return {
        element.name: element
        for element in elements
        if isinstance(
            element,
            sa.Column,
        )
    }


def checks_of(
    elements: tuple[Any, ...],
) -> dict[str, sa.CheckConstraint]:
    """Return named check constraints."""
    return {
        str(element.name): element
        for element in elements
        if isinstance(
            element,
            sa.CheckConstraint,
        )
    }


def foreign_keys_of(
    elements: tuple[Any, ...],
) -> tuple[
    sa.ForeignKeyConstraint,
    ...,
]:
    """Return foreign-key constraints."""
    return tuple(
        element
        for element in elements
        if isinstance(
            element,
            sa.ForeignKeyConstraint,
        )
    )


def test_revision_extends_team_proposal_head() -> None:
    """Keep the Alembic history linear."""
    migration = load_migration()

    assert migration.revision == "0009_user_modeling_snapshots"
    assert migration.down_revision == "0008_versioned_team_proposals"
    assert len(migration.revision) <= 64


def test_upgrade_creates_three_versioned_jsonb_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create persona, twin, and complete snapshot storage."""
    migration = load_migration()

    created: dict[
        str,
        tuple[Any, ...],
    ] = {}
    executed_sql: list[str] = []

    def create_table(
        table_name: str,
        *elements: Any,
        **_kwargs: Any,
    ) -> None:
        created[table_name] = elements

    def execute(
        statement: Any,
        *_args: Any,
        **_kwargs: Any,
    ) -> None:
        executed_sql.append(str(statement))

    monkeypatch.setattr(
        migration.op,
        "create_table",
        create_table,
    )
    monkeypatch.setattr(
        migration.op,
        "execute",
        execute,
    )

    migration.upgrade()

    assert tuple(created) == EXPECTED_TABLES

    persona_columns = columns_of(created["persona_profile_versions"])
    twin_columns = columns_of(created["user_twin_profile_versions"])
    snapshot_columns = columns_of(created["user_modeling_snapshot_versions"])

    assert isinstance(
        persona_columns["profile_snapshot"].type,
        postgresql.JSONB,
    )
    assert isinstance(
        twin_columns["profile_snapshot"].type,
        postgresql.JSONB,
    )
    assert isinstance(
        snapshot_columns["snapshot"].type,
        postgresql.JSONB,
    )

    for columns in (
        persona_columns,
        twin_columns,
        snapshot_columns,
    ):
        assert {
            "id",
            "project_id",
            "version_number",
            "content_hash",
            "created_by_user_id",
            "created_at",
        }.issubset(columns)

    assert len(executed_sql) == 4


def test_persona_storage_protects_source_confirmation_and_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep persona identity and decision state constrained."""
    migration = load_migration()

    created: dict[
        str,
        tuple[Any, ...],
    ] = {}

    monkeypatch.setattr(
        migration.op,
        "create_table",
        lambda table_name, *elements, **_kwargs: created.__setitem__(
            table_name,
            elements,
        ),
    )
    monkeypatch.setattr(
        migration.op,
        "execute",
        lambda *_args, **_kwargs: None,
    )

    migration.upgrade()

    elements = created["persona_profile_versions"]
    columns = columns_of(elements)
    checks = checks_of(elements)

    assert {
        "persona_id",
        "based_on_version_number",
        "profile_schema_version",
        "profile_source",
        "profile_kind",
        "confirmation_status",
        "rejection_reason",
        "profile_snapshot",
    }.issubset(columns)

    assert "ck_persona_profile_versions_linear_lineage" in checks
    assert "ck_persona_profile_versions_source" in checks
    assert "ck_persona_profile_versions_kind" in checks
    assert "ck_persona_profile_versions_confirmation" in checks
    assert "ck_persona_profile_versions_rejection_reason" in checks
    assert "ck_persona_profile_versions_hash" in checks


def test_twin_storage_references_exact_persona_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Relationally bind each twin to a concrete persona version."""
    migration = load_migration()

    created: dict[
        str,
        tuple[Any, ...],
    ] = {}

    monkeypatch.setattr(
        migration.op,
        "create_table",
        lambda table_name, *elements, **_kwargs: created.__setitem__(
            table_name,
            elements,
        ),
    )
    monkeypatch.setattr(
        migration.op,
        "execute",
        lambda *_args, **_kwargs: None,
    )

    migration.upgrade()

    elements = created["user_twin_profile_versions"]
    columns = columns_of(elements)
    checks = checks_of(elements)
    foreign_keys = foreign_keys_of(elements)

    assert {
        "twin_id",
        "persona_id",
        "persona_version_number",
        "validation_status",
        "profile_snapshot",
    }.issubset(columns)

    target_sets = {
        tuple(element.target_fullname for element in constraint.elements)
        for constraint in foreign_keys
    }

    assert (
        "persona_profile_versions.project_id",
        "persona_profile_versions.persona_id",
        "persona_profile_versions.version_number",
    ) in target_sets

    assert "ck_user_twin_profile_versions_validation_status" in checks
    assert "ck_user_twin_profile_versions_linear_lineage" in checks


def test_snapshot_storage_binds_governed_context_and_cardinality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persist the exact brief, team, catalog, and one-to-four policy."""
    migration = load_migration()

    created: dict[
        str,
        tuple[Any, ...],
    ] = {}

    monkeypatch.setattr(
        migration.op,
        "create_table",
        lambda table_name, *elements, **_kwargs: created.__setitem__(
            table_name,
            elements,
        ),
    )
    monkeypatch.setattr(
        migration.op,
        "execute",
        lambda *_args, **_kwargs: None,
    )

    migration.upgrade()

    elements = created["user_modeling_snapshot_versions"]
    columns = columns_of(elements)
    checks = checks_of(elements)
    foreign_keys = foreign_keys_of(elements)

    assert {
        "brief_version_id",
        "brief_version_number",
        "brief_content_hash",
        "team_proposal_id",
        "team_version_number",
        "team_content_hash",
        "catalog_version",
        "catalog_content_hash",
        "persona_count",
        "twin_count",
        "snapshot",
    }.issubset(columns)

    target_sets = {
        tuple(element.target_fullname for element in constraint.elements)
        for constraint in foreign_keys
    }

    assert ("project_brief_versions.id",) in target_sets
    assert ("team_proposals.id",) in target_sets

    assert "ck_user_modeling_snapshot_versions_persona_count" in checks
    assert "ck_user_modeling_snapshot_versions_twin_count" in checks
    assert "ck_user_modeling_snapshot_versions_aligned_counts" in checks
    assert "ck_user_modeling_snapshot_versions_linear_lineage" in checks


def test_upgrade_installs_immutable_update_and_delete_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Protect append-only history at the PostgreSQL boundary."""
    migration = load_migration()

    executed_sql: list[str] = []

    monkeypatch.setattr(
        migration.op,
        "create_table",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        migration.op,
        "execute",
        lambda statement, *_args, **_kwargs: executed_sql.append(str(statement).lower()),
    )

    migration.upgrade()

    combined = "\n".join(executed_sql)

    assert "create function reject_user_modeling_version_mutation" in combined

    for table_name in EXPECTED_TABLES:
        assert f"on {table_name}" in combined

    assert combined.count("before update or delete") == 3


def test_downgrade_removes_guards_before_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remove triggers and then drop tables in dependency-safe order."""
    migration = load_migration()

    operations: list[
        tuple[
            str,
            str,
        ]
    ] = []

    monkeypatch.setattr(
        migration.op,
        "execute",
        lambda statement, *_args, **_kwargs: operations.append(
            (
                "execute",
                str(statement).lower(),
            )
        ),
    )
    monkeypatch.setattr(
        migration.op,
        "drop_table",
        lambda table_name, **_kwargs: operations.append(
            (
                "drop_table",
                table_name,
            )
        ),
    )

    migration.downgrade()

    dropped_tables = [
        value
        for (
            operation,
            value,
        ) in operations
        if operation == "drop_table"
    ]

    assert dropped_tables == [
        "user_modeling_snapshot_versions",
        "user_twin_profile_versions",
        "persona_profile_versions",
    ]

    first_drop_index = next(
        index
        for (
            index,
            item,
        ) in enumerate(operations)
        if item[0] == "drop_table"
    )

    assert all(
        operation == "execute"
        for (
            operation,
            _value,
        ) in operations[:first_drop_index]
    )
