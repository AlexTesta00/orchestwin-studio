from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from orchestwin.artifacts.design_finding_validations import FindingDecision

MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "orchestwin"
    / "persistence"
    / "migrations"
    / "versions"
    / "0058_design_finding_validations.py"
)
TABLE = "design_finding_validations"


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "design_finding_validations_migration", MIGRATION_PATH
    )
    if spec is None or spec.loader is None:
        raise AssertionError("could not load the design finding validations migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record_operations(migration, monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, tuple, dict]] = []
    for name in ("create_table", "create_index", "drop_index", "drop_table"):
        monkeypatch.setattr(
            migration.op,
            name,
            lambda *args, _name=name, **kwargs: calls.append((_name, args, kwargs)),
        )
    return calls


def created_table(call) -> sa.Table:
    name, *elements = call[1]
    return sa.Table(name, sa.MetaData(), *elements)


def test_revision_follows_the_design_evaluation_loop():
    migration = load_migration()
    assert migration.revision == "0058_design_finding_validations"
    assert migration.down_revision == "0057_design_evaluation_loop"
    assert set(migration.DECISIONS.split(",")) == {f"'{item.value}'" for item in FindingDecision}


def test_upgrade_creates_the_append_only_validation_table(monkeypatch: pytest.MonkeyPatch):
    migration = load_migration()
    calls = record_operations(migration, monkeypatch)
    migration.upgrade()
    assert [call[0] for call in calls] == ["create_table", "create_index"]
    table = created_table(calls[0])
    assert table.name == TABLE
    assert [column.name for column in table.columns] == [
        "evaluation_run_id",
        "twin_id",
        "finding_id",
        "sequence_number",
        "project_id",
        "owner_user_id",
        "decision",
        "note",
        "decided_at",
        "content_hash",
        "validation_snapshot",
    ]
    assert [column.name for column in table.columns if column.nullable] == ["note"]
    assert table.c.finding_id.type.length == 64
    assert table.c.decision.type.length == 24
    assert isinstance(table.c.note.type, sa.Text)
    assert table.c.decided_at.type.timezone is True
    assert isinstance(table.c.validation_snapshot.type, postgresql.JSONB)
    assert table.primary_key.name == f"pk_{TABLE}"
    assert list(table.primary_key.columns.keys()) == [
        "evaluation_run_id",
        "twin_id",
        "finding_id",
        "sequence_number",
    ]
    assert {
        constraint.name: (
            [element.parent.name for element in constraint.elements],
            [element.target_fullname for element in constraint.elements],
            constraint.ondelete,
        )
        for constraint in table.foreign_key_constraints
    } == {
        f"fk_{TABLE}_finding": (
            ["evaluation_run_id", "twin_id", "finding_id"],
            [
                "design_synthetic_findings.evaluation_run_id",
                "design_synthetic_findings.twin_id",
                "design_synthetic_findings.finding_id",
            ],
            "CASCADE",
        ),
        f"fk_{TABLE}_project": (["project_id"], ["projects.id"], "RESTRICT"),
        f"fk_{TABLE}_owner": (["owner_user_id"], ["users.id"], "RESTRICT"),
    }
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }
    assert checks == {
        f"ck_{TABLE}_decision": f"decision IN ({migration.DECISIONS})",
        f"ck_{TABLE}_sequence": "sequence_number >= 1",
        f"ck_{TABLE}_content_hash": "content_hash ~ '^[0-9a-f]{64}$'",
        f"ck_{TABLE}_note": "note IS NULL OR char_length(note) BETWEEN 1 AND 1000",
    }
    assert calls[1][1] == (f"ix_{TABLE}_project_decided", TABLE, ["project_id", "decided_at"])


def test_downgrade_drops_the_index_and_the_table(monkeypatch: pytest.MonkeyPatch):
    migration = load_migration()
    calls = record_operations(migration, monkeypatch)
    migration.downgrade()
    assert calls == [
        ("drop_index", (f"ix_{TABLE}_project_decided",), {"table_name": TABLE}),
        ("drop_table", (TABLE,), {}),
    ]
