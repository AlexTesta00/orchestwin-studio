from __future__ import annotations

import importlib
import re
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from orchestwin.identity.domain import GuidanceMode
from orchestwin.identity.persistence.models import UserGuidanceChoiceRecord
from orchestwin.persistence.migrate import create_alembic_config

TABLE = "user_guidance_choices"
FUNCTION = "user_guidance_choice_append_only"
TRIGGER = (
    f"CREATE TRIGGER {TABLE}_immutable BEFORE UPDATE OR DELETE ON {TABLE}"
    f" FOR EACH ROW EXECUTE FUNCTION {FUNCTION}()"
)
COLUMNS = ["user_id", "mode", "chosen_at"]
CHECK = "ck_user_guidance_choice_mode"
FRAGMENTS = (
    "user_id UUID NOT NULL",
    "mode VARCHAR(8) NOT NULL",
    "chosen_at TIMESTAMP WITH TIME ZONE NOT NULL",
    "CONSTRAINT pk_user_guidance_choices PRIMARY KEY (user_id)",
    "CONSTRAINT fk_user_guidance_choices_user_id_users FOREIGN KEY(user_id)"
    " REFERENCES users (id) ON DELETE RESTRICT",
    f"CONSTRAINT {CHECK} CHECK (mode IN ('GUIDED', 'EXPERT'))",
)


def migration():
    return importlib.import_module(
        "orchestwin.persistence.migrations.versions.0072_guidance_choice"
    )


def capture(monkeypatch):
    module = migration()
    calls = []
    for name in ("create_table", "create_index", "execute", "drop_index", "drop_table"):
        monkeypatch.setattr(
            module.op, name, lambda *args, _name=name, **kwargs: calls.append((_name, args, kwargs))
        )
    monkeypatch.setattr(module.op, "f", lambda value: value)
    return module, calls


def offline_upgrade_statements(module) -> list[str]:
    output = StringIO()
    command.upgrade(
        create_alembic_config(
            "postgresql+psycopg://synthetic@localhost:5432/orchestwin", output_buffer=output
        ),
        f"{module.down_revision}:{module.revision}",
        sql=True,
    )
    text = "\n".join(line for line in output.getvalue().splitlines() if not line.startswith("--"))
    return [" ".join(part.split()) for part in text.split(";\n") if part.strip()]


def test_revision_follows_the_usage_journal_and_lists_exactly_the_guidance_modes():
    module = migration()
    assert module.revision == "0072_guidance_choice"
    assert module.down_revision == "0071_usage_journal"
    assert ", ".join(f"'{mode.value}'" for mode in GuidanceMode) == module.MODES
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert {
        name.split(".")[0] for name in re.findall(r"^(?:from|import) ([\w.]+)", source, re.M)
    } == {"alembic", "sqlalchemy"}
    assert UserGuidanceChoiceRecord.__tablename__ == TABLE
    assert [column.name for column in UserGuidanceChoiceRecord.__table__.columns] == COLUMNS


def test_upgrade_creates_only_the_append_only_choice_table(monkeypatch):
    module, calls = capture(monkeypatch)
    module.upgrade()
    assert [call[0] for call in calls] == ["create_table", "execute", "execute"]
    table = sa.Table(calls[0][1][0], sa.MetaData(), *calls[0][1][1:])
    assert table.name == TABLE
    assert [column.name for column in table.columns] == COLUMNS
    assert [column.name for column in table.columns if column.nullable] == []
    assert isinstance(table.c.user_id.type, postgresql.UUID)
    assert table.c.user_id.type.as_uuid is True
    assert isinstance(table.c.mode.type, sa.String)
    assert table.c.mode.type.length == 8
    assert isinstance(table.c.chosen_at.type, sa.DateTime)
    assert table.c.chosen_at.type.timezone is True
    assert table.primary_key.name == "pk_user_guidance_choices"
    assert list(table.primary_key.columns.keys()) == ["user_id"]
    assert {
        (
            tuple(element.parent.name for element in constraint.elements),
            tuple(element.target_fullname for element in constraint.elements),
            constraint.ondelete,
            constraint.name,
        )
        for constraint in table.foreign_key_constraints
    } == {(("user_id",), ("users.id",), "RESTRICT", None)}
    assert [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    ] == []
    assert {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint)
    } == {CHECK: "mode IN ('GUIDED', 'EXPERT')"}
    function, trigger = (str(call[1][0]) for call in calls[1:])
    assert function == (
        f"CREATE FUNCTION {FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN"
        " RAISE EXCEPTION 'guidance choices are append-only'; END $$"
    )
    assert trigger == TRIGGER


def test_offline_upgrade_renders_exact_names_and_leaves_existing_tables_untouched():
    module = migration()
    statements = offline_upgrade_statements(module)
    assert [" ".join(statement.split()[:2]) for statement in statements] == [
        "BEGIN",
        "CREATE TABLE",
        "CREATE FUNCTION",
        "CREATE TRIGGER",
        "UPDATE alembic_version",
        "COMMIT",
    ]
    table = statements[1]
    assert table.startswith(f"CREATE TABLE {TABLE} (")
    for fragment in FRAGMENTS:
        assert fragment in table
    assert table.count("CONSTRAINT ") == 3
    assert statements[3] == TRIGGER
    assert module.revision in statements[4] and module.down_revision in statements[4]


def test_the_orm_record_declares_the_same_table_as_the_migration():
    table = " ".join(
        str(
            CreateTable(UserGuidanceChoiceRecord.__table__).compile(dialect=postgresql.dialect())
        ).split()
    )
    assert table.startswith(f"CREATE TABLE {TABLE} (")
    for fragment in FRAGMENTS:
        assert fragment in table
    assert table.count("CONSTRAINT ") == 3


def test_populated_downgrade_refuses_before_any_drop(monkeypatch):
    module, calls = capture(monkeypatch)
    queries = []

    def scalar(statement):
        queries.append(str(statement))
        return True

    monkeypatch.setattr(module.op, "get_bind", lambda: SimpleNamespace(scalar=scalar))
    with pytest.raises(RuntimeError, match="guidance choices must be preserved before downgrade"):
        module.downgrade()
    assert calls == []
    assert queries == [f"SELECT EXISTS (SELECT 1 FROM {TABLE})"]


def test_empty_downgrade_drops_only_the_choice_table_and_its_function(monkeypatch):
    module, calls = capture(monkeypatch)
    monkeypatch.setattr(module.op, "get_bind", lambda: SimpleNamespace(scalar=lambda _: False))
    module.downgrade()
    assert calls == [
        ("drop_table", (TABLE,), {}),
        ("execute", (f"DROP FUNCTION {FUNCTION}()",), {}),
    ]
