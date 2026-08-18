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
    / "0011_requirements_specifications.py"
)


def load_migration() -> ModuleType:
    """Load the migration directly from its file."""
    spec = importlib.util.spec_from_file_location(
        "requirements_specification_migration",
        MIGRATION_PATH,
    )

    if spec is None or spec.loader is None:
        raise AssertionError("could not load requirements specification migration")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def test_revision_extends_user_twin_profile_diff_head() -> None:
    """Keep Alembic history linear from the Sprint 04 head."""
    migration = load_migration()

    assert migration.revision == "0011_requirements_specifications"
    assert migration.down_revision == "0010_user_twin_profile_diffs"


def test_upgrade_creates_version_diff_and_traceability_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persist immutable baselines and reviewable owner changes."""
    migration = load_migration()
    created: dict[str, tuple[Any, ...]] = {}
    indexes: list[
        tuple[
            str,
            str,
            tuple[str, ...],
            bool,
            object,
        ]
    ] = []
    executed: list[str] = []

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

    monkeypatch.setattr(migration.op, "create_table", create_table)
    monkeypatch.setattr(migration.op, "create_index", create_index)
    monkeypatch.setattr(
        migration.op,
        "execute",
        lambda statement: executed.append(str(statement)),
    )

    migration.upgrade()

    assert tuple(created) == (
        "requirements_specification_versions",
        "requirements_specification_diffs",
    )

    version_columns = {
        element.name: element
        for element in created["requirements_specification_versions"]
        if isinstance(element, sa.Column)
    }
    diff_columns = {
        element.name: element
        for element in created["requirements_specification_diffs"]
        if isinstance(element, sa.Column)
    }

    assert isinstance(
        version_columns["specification_snapshot"].type,
        postgresql.JSONB,
    )
    assert isinstance(
        version_columns["traceability_snapshot"].type,
        postgresql.JSONB,
    )
    assert isinstance(
        version_columns["coverage_snapshot"].type,
        postgresql.JSONB,
    )
    assert isinstance(
        diff_columns["diff_snapshot"].type,
        postgresql.JSONB,
    )

    version_checks = {
        str(element.name)
        for element in created["requirements_specification_versions"]
        if isinstance(element, sa.CheckConstraint)
    }
    diff_checks = {
        str(element.name)
        for element in created["requirements_specification_diffs"]
        if isinstance(element, sa.CheckConstraint)
    }

    assert "ck_requirements_specification_versions_linear_lineage" in version_checks
    assert "ck_requirements_specification_diffs_decision_metadata" in diff_checks

    pending_index = next(
        index for index in indexes if index[0] == "uq_requirements_specification_diffs_pending_base"
    )

    assert pending_index[3] is True
    assert "status = 'PROPOSED'" in str(pending_index[4])
    assert any("CREATE FUNCTION" in statement for statement in executed)
    assert any("CREATE TRIGGER" in statement for statement in executed)


def test_downgrade_removes_diffs_guard_and_versions_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drop dependent data before immutable requirements history."""
    migration = load_migration()
    operations: list[tuple[str, str]] = []

    monkeypatch.setattr(
        migration.op,
        "drop_index",
        lambda name, **_kwargs: operations.append(("drop_index", name)),
    )
    monkeypatch.setattr(
        migration.op,
        "drop_table",
        lambda name, **_kwargs: operations.append(("drop_table", name)),
    )
    monkeypatch.setattr(
        migration.op,
        "execute",
        lambda statement: operations.append(("execute", str(statement))),
    )

    migration.downgrade()

    diff_drop = operations.index(("drop_table", "requirements_specification_diffs"))
    version_drop = operations.index(("drop_table", "requirements_specification_versions"))

    assert diff_drop < version_drop
    assert any(
        operation == "execute" and "DROP TRIGGER" in value for operation, value in operations
    )
    assert operations[-1] == (
        "drop_table",
        "requirements_specification_versions",
    )
