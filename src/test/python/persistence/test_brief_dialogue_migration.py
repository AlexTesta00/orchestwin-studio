from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa

from orchestwin.projects.brief_dialogue import MAX_DIALOGUE_QUESTIONS
from orchestwin.projects.briefs import LIST_FIELDS, TEXT_FIELDS

MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "orchestwin"
    / "persistence"
    / "migrations"
    / "versions"
    / "0055_brief_dialogue.py"
)
GENERATIONS = "model_proposal_generations"
TASK_CONSTRAINT = f"ck_{GENERATIONS}_task_valid"


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("brief_dialogue_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load the brief dialogue migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def quoted(fields):
    return {f"'{field.value}'" for field in fields}


def names(items, kind):
    return [item.name for item in items if isinstance(item, kind)]


def test_revision_extends_the_eight_user_twins_head() -> None:
    migration = load_migration()

    assert migration.revision == "0055_brief_dialogue"
    assert migration.down_revision == "0054_eight_user_twins"
    assert migration.DIALOGUE_TASK == "'proposal-brief-dialogue-v1'"
    assert migration.QUESTION_LIMIT == MAX_DIALOGUE_QUESTIONS
    known = migration.KNOWN_TASKS.split(",")
    assert len(known) == 12 and migration.DIALOGUE_TASK not in known
    assert "'proposal-twin-chat-v1'" in known and "'proposal-user-twin-evaluation-v1'" in known
    assert set(migration.TEXT_FIELDS.split(",")) == quoted(TEXT_FIELDS)
    assert set(migration.LIST_FIELDS.split(",")) == quoted(LIST_FIELDS)


def test_upgrade_registers_the_task_and_creates_the_dialogue_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = load_migration()
    calls = record_operations(migration, monkeypatch)

    migration.upgrade()

    assert calls[0] == ("drop_constraint", (TASK_CONSTRAINT, GENERATIONS), {"type_": "check"})
    name, (constraint, table, expression), _ = calls[1]
    assert (name, constraint, table) == ("create_check_constraint", "task_valid", GENERATIONS)
    assert expression == (
        f"COALESCE((task_id IN ({migration.KNOWN_TASKS},{migration.DIALOGUE_TASK})), false)"
    )
    assert [call[0] for call in calls[2:]] == [
        "create_table",
        "create_index",
        "create_index",
        "create_table",
    ]
    dialogues = calls[2][1]
    assert dialogues[0] == "brief_dialogues"
    assert names(dialogues[1:], sa.Column) == [
        "id",
        "project_id",
        "owner_user_id",
        "source_brief_version_number",
        "statement",
        "status",
        "created_at",
        "resulting_brief_version_number",
        "synthesis_generation_id",
        "completed_at",
    ]
    assert names(dialogues[1:], sa.ForeignKeyConstraint) == [
        "fk_brief_dialogues_project",
        "fk_brief_dialogues_owner",
        "fk_brief_dialogues_source_brief_version",
        "fk_brief_dialogues_resulting_brief_version",
        "fk_brief_dialogues_synthesis_generation",
    ]
    assert names(dialogues[1:], sa.CheckConstraint) == [
        "ck_brief_dialogues_status",
        "ck_brief_dialogues_source_version",
        "ck_brief_dialogues_statement",
        "ck_brief_dialogues_state",
    ]
    assert calls[3][1] == (
        "ix_brief_dialogues_project",
        "brief_dialogues",
        ["project_id", "created_at"],
    )
    assert calls[4][1] == ("uq_brief_dialogues_active_project", "brief_dialogues", ["project_id"])
    assert calls[4][2]["unique"] is True
    assert str(calls[4][2]["postgresql_where"]) == "status IN ('OPEN', 'READY')"
    turns = calls[5][1]
    assert turns[0] == "brief_dialogue_turns"
    assert names(turns[1:], sa.Column) == [
        "id",
        "dialogue_id",
        "ordinal",
        "field",
        "question",
        "model_generation_id",
        "asked_at",
        "answer_kind",
        "answer_text",
        "answer_items",
        "answered_at",
    ]
    assert names(turns[1:], sa.UniqueConstraint) == [
        "uq_brief_dialogue_turns_ordinal",
        "uq_brief_dialogue_turns_generation",
    ]
    checks = {
        item.name: str(item.sqltext) for item in turns[1:] if isinstance(item, sa.CheckConstraint)
    }
    assert list(checks) == [
        "ck_brief_dialogue_turns_ordinal",
        "ck_brief_dialogue_turns_field",
        "ck_brief_dialogue_turns_question",
        "ck_brief_dialogue_turns_answer_state",
        "ck_brief_dialogue_turns_list_answer_field",
        "ck_brief_dialogue_turns_text_answer_field",
        "ck_brief_dialogue_turns_answer_time",
    ]
    assert (
        checks["ck_brief_dialogue_turns_ordinal"]
        == f"ordinal BETWEEN 1 AND {MAX_DIALOGUE_QUESTIONS}"
    )
    assert "'goals'" in checks["ck_brief_dialogue_turns_list_answer_field"]
    assert "'name'" in checks["ck_brief_dialogue_turns_text_answer_field"]


def test_downgrade_guards_retained_dialogues_and_restores_the_task_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = load_migration()
    calls = record_operations(migration, monkeypatch)

    migration.downgrade()

    assert calls[0][0] == "execute"
    assert "SELECT 1 FROM brief_dialogues" in calls[0][1][0]
    assert calls[1] == ("drop_table", ("brief_dialogue_turns",), {})
    assert calls[2] == (
        "drop_index",
        ("uq_brief_dialogues_active_project",),
        {"table_name": "brief_dialogues"},
    )
    assert calls[3] == (
        "drop_index",
        ("ix_brief_dialogues_project",),
        {"table_name": "brief_dialogues"},
    )
    assert calls[4] == ("drop_table", ("brief_dialogues",), {})
    assert calls[5] == ("drop_constraint", (TASK_CONSTRAINT, GENERATIONS), {"type_": "check"})
    assert calls[6][1] == (
        "task_valid",
        GENERATIONS,
        f"COALESCE((task_id IN ({migration.KNOWN_TASKS})), false)",
    )
