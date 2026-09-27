from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from orchestwin.artifacts.design_discussion import (
    MAX_DISCUSSION_ROUNDS,
    MAX_LOCALE_LENGTH,
    MAX_OWNER_NOTE_LENGTH,
    DiscussionStatus,
)
from orchestwin.artifacts.design_discussion_persistence import OPEN_DISCUSSION_INDEX
from orchestwin.models.proposal_tasks import TASKS
from orchestwin.projects.insight_applications import InsightSourceKind

VERSIONS = (
    Path(__file__).resolve().parents[3] / "orchestwin" / "persistence" / "migrations" / "versions"
)
GENERATIONS = "model_proposal_generations"
APPLICATIONS = "insight_applications"
DISCUSSIONS = "design_discussions"
ROUNDS = "design_discussion_rounds"
TASK_CONSTRAINT = f"ck_{GENERATIONS}_task_valid"
SOURCE_KIND_CONSTRAINT = "ck_insight_applications_ck_insight_applications_source_kind"


def load(filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), VERSIONS / filename)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load the migration {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_migration() -> ModuleType:
    return load("0059_twin_discussions.py")


def record_operations(migration, monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, tuple, dict]] = []
    for name in (
        "drop_constraint",
        "create_check_constraint",
        "create_table",
        "create_index",
        "drop_index",
        "drop_table",
        "execute",
    ):
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


def quoted(items):
    return {f"'{item.value}'" for item in items}


def foreign_keys(table: sa.Table):
    return {
        constraint.name: (
            [element.parent.name for element in constraint.elements],
            [element.target_fullname for element in constraint.elements],
            constraint.ondelete,
        )
        for constraint in table.foreign_key_constraints
    }


def checks(table: sa.Table):
    return {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }


def test_revision_follows_the_finding_validations_and_extends_the_previous_lists():
    migration = load_migration()
    brief_dialogue = load("0055_brief_dialogue.py")
    evaluation_loop = load("0057_design_evaluation_loop.py")
    assert migration.revision == "0059_twin_discussions"
    assert migration.down_revision == "0058_design_finding_validations"
    assert f"{brief_dialogue.KNOWN_TASKS},{brief_dialogue.DIALOGUE_TASK}" == migration.KNOWN_TASKS
    assert migration.DISCUSSION_TASK == "'proposal-twin-discussion-v1'"
    assert {f"'proposal-{task}-v1'" for task in TASKS} <= {
        *migration.KNOWN_TASKS.split(","),
        migration.DISCUSSION_TASK,
    }
    assert migration.SOURCE_KINDS == evaluation_loop.SOURCE_KINDS
    assert f"'{InsightSourceKind.TWIN_DISCUSSION.value}'" == migration.DISCUSSION_SOURCE
    assert {*migration.SOURCE_KINDS.split(","), migration.DISCUSSION_SOURCE} == quoted(
        InsightSourceKind
    )
    assert set(migration.STATUSES.split(",")) == quoted(DiscussionStatus)
    assert migration.ROUND_LIMIT == MAX_DISCUSSION_ROUNDS
    assert migration.NOTE_LIMIT == MAX_OWNER_NOTE_LENGTH
    assert migration.LOCALE_LIMIT == MAX_LOCALE_LENGTH
    assert migration.OPEN_INDEX == OPEN_DISCUSSION_INDEX


def test_upgrade_accepts_the_new_task_and_source_kind_and_creates_the_tables(
    monkeypatch: pytest.MonkeyPatch,
):
    migration = load_migration()
    calls = record_operations(migration, monkeypatch)
    migration.upgrade()
    assert [call[0] for call in calls] == [
        "drop_constraint",
        "create_check_constraint",
        "drop_constraint",
        "create_check_constraint",
        "create_table",
        "create_index",
        "create_index",
        "create_table",
    ]
    assert calls[:4] == [
        ("drop_constraint", (TASK_CONSTRAINT, GENERATIONS), {"type_": "check"}),
        (
            "create_check_constraint",
            (
                "task_valid",
                GENERATIONS,
                f"COALESCE((task_id IN ({migration.KNOWN_TASKS},{migration.DISCUSSION_TASK})),"
                " false)",
            ),
            {},
        ),
        ("drop_constraint", (SOURCE_KIND_CONSTRAINT, APPLICATIONS), {"type_": "check"}),
        (
            "create_check_constraint",
            (
                SOURCE_KIND_CONSTRAINT,
                APPLICATIONS,
                f"source_kind IN ({migration.SOURCE_KINDS},{migration.DISCUSSION_SOURCE})",
            ),
            {},
        ),
    ]
    discussions = created_table(calls[4])
    assert discussions.name == DISCUSSIONS
    assert [column.name for column in discussions.columns] == [
        "id",
        "project_id",
        "owner_user_id",
        "design_version_id",
        "design_version_number",
        "design_content_hash",
        "alternative_id",
        "alternative_code",
        "locale",
        "status",
        "created_at",
        "decided_at",
    ]
    assert [column.name for column in discussions.columns if column.nullable] == ["decided_at"]
    assert discussions.c.locale.type.length == MAX_LOCALE_LENGTH
    assert discussions.c.status.type.length == 16
    assert discussions.c.created_at.type.timezone is True
    assert discussions.primary_key.name == f"pk_{DISCUSSIONS}"
    assert foreign_keys(discussions) == {
        f"fk_{DISCUSSIONS}_project": (["project_id"], ["projects.id"], "RESTRICT"),
        f"fk_{DISCUSSIONS}_owner": (["owner_user_id"], ["users.id"], "RESTRICT"),
        f"fk_{DISCUSSIONS}_design_version": (
            ["design_version_id"],
            ["design_package_versions.id"],
            "RESTRICT",
        ),
    }
    assert checks(discussions) == {
        f"ck_{DISCUSSIONS}_status": f"status IN ({migration.STATUSES})",
        f"ck_{DISCUSSIONS}_design_version": "design_version_number >= 1",
        f"ck_{DISCUSSIONS}_design_hash": "design_content_hash ~ '^[0-9a-f]{64}$'",
        f"ck_{DISCUSSIONS}_alternative_code": "alternative_code ~ '^DES-[0-9]{3,}$'",
        f"ck_{DISCUSSIONS}_locale": "char_length(locale) BETWEEN 2 AND 20",
        f"ck_{DISCUSSIONS}_decision": (
            "(status = 'OPEN' AND decided_at IS NULL)"
            " OR (status <> 'OPEN' AND decided_at IS NOT NULL AND decided_at >= created_at)"
        ),
    }
    assert calls[5][1:] == (
        ("ix_design_discussions_project_created", DISCUSSIONS, ["project_id", "created_at"]),
        {},
    )
    assert calls[6][1] == (OPEN_DISCUSSION_INDEX, DISCUSSIONS, ["design_version_id"])
    assert calls[6][2]["unique"] is True
    assert str(calls[6][2]["postgresql_where"]) == "status = 'OPEN'"
    rounds = created_table(calls[7])
    assert rounds.name == ROUNDS
    assert [column.name for column in rounds.columns] == [
        "discussion_id",
        "ordinal",
        "owner_note",
        "content_hash",
        "created_at",
        "round_snapshot",
    ]
    assert [column.name for column in rounds.columns if column.nullable] == ["owner_note"]
    assert isinstance(rounds.c.round_snapshot.type, postgresql.JSONB)
    assert rounds.primary_key.name == f"pk_{ROUNDS}"
    assert list(rounds.primary_key.columns.keys()) == ["discussion_id", "ordinal"]
    assert foreign_keys(rounds) == {
        f"fk_{ROUNDS}_discussion": (["discussion_id"], [f"{DISCUSSIONS}.id"], "CASCADE"),
    }
    assert checks(rounds) == {
        f"ck_{ROUNDS}_ordinal": "ordinal BETWEEN 1 AND 4",
        f"ck_{ROUNDS}_content_hash": "content_hash ~ '^[0-9a-f]{64}$'",
        f"ck_{ROUNDS}_owner_note": (
            "owner_note IS NULL OR char_length(owner_note) BETWEEN 1 AND 1000"
        ),
    }


def test_downgrade_guards_retained_data_and_restores_the_previous_checks(
    monkeypatch: pytest.MonkeyPatch,
):
    migration = load_migration()
    brief_dialogue = load("0055_brief_dialogue.py")
    evaluation_loop = load("0057_design_evaluation_loop.py")
    calls = record_operations(migration, monkeypatch)
    migration.downgrade()
    assert calls[0][0] == "execute"
    guard = calls[0][1][0]
    assert "SELECT 1 FROM design_discussions" in guard
    assert "source_kind = 'TWIN_DISCUSSION'" in guard
    assert "task_id = 'proposal-twin-discussion-v1'" in guard
    assert calls[1:] == [
        ("drop_table", (ROUNDS,), {}),
        ("drop_index", (OPEN_DISCUSSION_INDEX,), {"table_name": DISCUSSIONS}),
        ("drop_index", ("ix_design_discussions_project_created",), {"table_name": DISCUSSIONS}),
        ("drop_table", (DISCUSSIONS,), {}),
        ("drop_constraint", (SOURCE_KIND_CONSTRAINT, APPLICATIONS), {"type_": "check"}),
        (
            "create_check_constraint",
            (
                SOURCE_KIND_CONSTRAINT,
                APPLICATIONS,
                f"source_kind IN ({evaluation_loop.SOURCE_KINDS})",
            ),
            {},
        ),
        ("drop_constraint", (TASK_CONSTRAINT, GENERATIONS), {"type_": "check"}),
        (
            "create_check_constraint",
            (
                "task_valid",
                GENERATIONS,
                "COALESCE((task_id IN "
                f"({brief_dialogue.KNOWN_TASKS},{brief_dialogue.DIALOGUE_TASK})), false)",
            ),
            {},
        ),
    ]
