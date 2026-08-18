"""Contract tests for User Twin profile-diff migration."""

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
    / "0010_user_twin_profile_diffs.py"
)


def load_migration() -> ModuleType:
    """Load migration directly from its file."""
    spec = importlib.util.spec_from_file_location(
        "user_twin_profile_diff_migration",
        MIGRATION_PATH,
    )

    if spec is None or spec.loader is None:
        raise AssertionError("could not load User Twin profile diff migration")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def test_revision_extends_user_modeling_snapshot_head() -> None:
    """Keep Alembic history linear."""
    migration = load_migration()

    assert migration.revision == ("0010_user_twin_profile_diffs")
    assert migration.down_revision == ("0009_user_modeling_snapshots")


def test_upgrade_creates_reviewable_diff_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persist immutable proposal payload plus explicit decision metadata."""
    migration = load_migration()

    created: dict[
        str,
        tuple[Any, ...],
    ] = {}
    indexes: list[
        tuple[
            str,
            str,
            tuple[str, ...],
            bool,
            object,
        ]
    ] = []

    def create_table(
        name: str,
        *elements: Any,
        **_kwargs: Any,
    ) -> None:
        created[name] = elements

    def create_index(
        name: str,
        table_name: str,
        columns: list[str],
        *,
        unique: bool,
        **kwargs: Any,
    ) -> None:
        indexes.append(
            (
                name,
                table_name,
                tuple(columns),
                unique,
                kwargs.get("postgresql_where"),
            )
        )

    monkeypatch.setattr(
        migration.op,
        "create_table",
        create_table,
    )
    monkeypatch.setattr(
        migration.op,
        "create_index",
        create_index,
    )

    migration.upgrade()

    assert tuple(created) == ("user_twin_profile_diffs",)

    elements = created["user_twin_profile_diffs"]

    columns = {
        element.name: element
        for element in elements
        if isinstance(
            element,
            sa.Column,
        )
    }

    assert {
        "id",
        "project_id",
        "base_snapshot_version_id",
        "base_snapshot_version_number",
        "base_snapshot_content_hash",
        "twin_id",
        "base_twin_version_id",
        "base_twin_version_number",
        "base_twin_content_hash",
        "proposal_hash",
        "diff_snapshot",
        "status",
        "created_by_user_id",
        "created_at",
        "decided_by_user_id",
        "decided_at",
        "decision_reason",
        "applied_snapshot_version_id",
    }.issubset(columns)

    assert isinstance(
        columns["diff_snapshot"].type,
        postgresql.JSONB,
    )

    checks = {
        str(element.name)
        for element in elements
        if isinstance(
            element,
            sa.CheckConstraint,
        )
    }

    assert "ck_user_twin_profile_diffs_status" in checks
    assert "ck_user_twin_profile_diffs_decision_metadata" in checks

    assert len(indexes) == 2

    pending_index = next(
        index for index in indexes if index[0] == ("uq_user_twin_profile_diffs_pending_base_twin")
    )

    assert pending_index[3] is True
    assert "status = 'PROPOSED'" in str(pending_index[4])


def test_downgrade_removes_indexes_before_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drop dependent indexes before removing diff storage."""
    migration = load_migration()

    operations: list[tuple[str, str]] = []

    monkeypatch.setattr(
        migration.op,
        "drop_index",
        lambda name, **_kwargs: operations.append(
            (
                "drop_index",
                name,
            )
        ),
    )
    monkeypatch.setattr(
        migration.op,
        "drop_table",
        lambda name, **_kwargs: operations.append(
            (
                "drop_table",
                name,
            )
        ),
    )

    migration.downgrade()

    assert operations[-1] == (
        "drop_table",
        "user_twin_profile_diffs",
    )

    assert all(operation == "drop_index" for operation, _value in operations[:-1])
