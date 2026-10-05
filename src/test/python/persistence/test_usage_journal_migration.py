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

from orchestwin.activity import (
    JOURNAL_KINDS,
    MAX_DURATION_MS,
    SECTIONS,
    SESSION_CODE_PATTERN,
    SESSION_KINDS,
    STATUS_PATTERN,
    TARGET_PATTERN,
)
from orchestwin.persistence.migrate import create_alembic_config
from orchestwin.projects.persistence.usage_journal import USAGE_EVENTS

TABLE = "project_usage_events"
FUNCTION = "usage_journal_append_only"
TRIGGER = (
    f"CREATE TRIGGER {TABLE}_immutable BEFORE UPDATE OR DELETE ON {TABLE}"
    f" FOR EACH ROW EXECUTE FUNCTION {FUNCTION}()"
)
COLUMNS = [
    "id",
    "project_id",
    "owner_user_id",
    "session_code",
    "sequence",
    "source",
    "kind",
    "section",
    "target",
    "client_at",
    "received_at",
    "duration_ms",
    "status",
]
CHECKS = {
    "ck_project_usage_event_session_code": "session_code ~ '^SES-[A-Z0-9][A-Z0-9-]{0,19}$'",
    "ck_project_usage_event_sequence": "sequence >= 1",
    "ck_project_usage_event_source": "source IN ('WEB', 'UT', 'STUDIO')",
    "ck_project_usage_event_kind": (
        "kind IN ('SECTION_OPENED', 'DETAIL_OPENED', 'WHY_OPENED', 'MOCKUP_OPENED', "
        "'MODE_CHANGED', 'LOCALE_SET', 'PAGE_HIDDEN', 'PAGE_VISIBLE', 'REQUEST_FAILED', "
        "'COMMAND_STARTED', 'COMMAND_FINISHED', 'GENERATION_WAITED', 'SESSION_STARTED', "
        "'SESSION_ENDED')"
    ),
    "ck_project_usage_event_section": (
        "section IS NULL OR section IN "
        "('BRIEF', 'TEAM', 'USER_TWINS', 'REQUIREMENTS', 'DESIGN', 'PACKAGE')"
    ),
    "ck_project_usage_event_target": (
        "target IS NULL OR target ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$'"
    ),
    "ck_project_usage_event_duration_ms": (
        "duration_ms IS NULL OR duration_ms BETWEEN 0 AND 86400000"
    ),
    "ck_project_usage_event_status": (
        "status IS NULL OR status ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$'"
    ),
}


def migration():
    return importlib.import_module("orchestwin.persistence.migrations.versions.0071_usage_journal")


def capture(monkeypatch):
    module = migration()
    calls = []
    for name in ("create_table", "create_index", "execute", "drop_index", "drop_table"):
        monkeypatch.setattr(
            module.op, name, lambda *args, _name=name, **kwargs: calls.append((_name, args, kwargs))
        )
    monkeypatch.setattr(module.op, "f", lambda value: value)
    return module, calls


def quoted(values):
    return ", ".join(f"'{value}'" for value in values)


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


def test_revision_follows_workflow_inputs_and_writes_the_activity_rules_in_full():
    module = migration()
    assert module.revision == "0071_usage_journal"
    assert module.down_revision == "0070_workflow_inputs"
    assert quoted((*JOURNAL_KINDS, "STUDIO")) == module.SOURCES
    assert quoted((*JOURNAL_KINDS["WEB"], *JOURNAL_KINDS["UT"], *SESSION_KINDS)) == module.KINDS
    assert quoted(SECTIONS) == module.SECTIONS
    assert f"^{SESSION_CODE_PATTERN}$" == module.SESSION_CODE
    assert f"^{TARGET_PATTERN}$" == module.TARGET
    assert f"^{STATUS_PATTERN}$" == module.STATUS
    assert module.MAX_DURATION_MS == MAX_DURATION_MS
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert {
        name.split(".")[0] for name in re.findall(r"^(?:from|import) ([\w.]+)", source, re.M)
    } == {"alembic", "sqlalchemy"}
    assert USAGE_EVENTS.name == TABLE
    assert [column.name for column in USAGE_EVENTS.columns] == COLUMNS


def test_upgrade_creates_only_the_append_only_journal_table(monkeypatch):
    module, calls = capture(monkeypatch)
    module.upgrade()
    assert [call[0] for call in calls] == ["create_table", "execute", "execute"]
    table = sa.Table(calls[0][1][0], sa.MetaData(), *calls[0][1][1:])
    assert table.name == TABLE
    assert [column.name for column in table.columns] == COLUMNS
    assert [column.name for column in table.columns if column.nullable] == [
        "section",
        "target",
        "client_at",
        "duration_ms",
        "status",
    ]
    for name in ("id", "project_id", "owner_user_id"):
        assert isinstance(table.c[name].type, postgresql.UUID)
        assert table.c[name].type.as_uuid is True
    for name in ("sequence", "duration_ms"):
        assert isinstance(table.c[name].type, sa.Integer)
    for name in ("client_at", "received_at"):
        assert isinstance(table.c[name].type, sa.DateTime)
        assert table.c[name].type.timezone is True
    assert {
        name: table.c[name].type.length
        for name in ("session_code", "source", "kind", "section", "target", "status")
    } == {"session_code": 24, "source": 8, "kind": 32, "section": 16, "target": 80, "status": 64}
    assert table.primary_key.name == "pk_project_usage_events"
    assert list(table.primary_key.columns.keys()) == ["id"]
    assert {
        (
            tuple(element.parent.name for element in constraint.elements),
            tuple(element.target_fullname for element in constraint.elements),
            constraint.ondelete,
            constraint.name,
        )
        for constraint in table.foreign_key_constraints
    } == {
        (("project_id",), ("projects.id",), "RESTRICT", None),
        (("owner_user_id",), ("users.id",), "RESTRICT", None),
    }
    assert {
        constraint.name: [column.name for column in constraint.columns]
        for constraint in table.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    } == {"uq_project_usage_event_sequence": ["project_id", "sequence"]}
    assert {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint)
    } == CHECKS
    function, trigger = (str(call[1][0]) for call in calls[1:])
    assert function == (
        f"CREATE FUNCTION {FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN"
        " RAISE EXCEPTION 'usage journal events are append-only'; END $$"
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
    for name, condition in CHECKS.items():
        assert f"CONSTRAINT {name} CHECK ({condition})" in table
    for fragment in (
        "CONSTRAINT pk_project_usage_events PRIMARY KEY (id)",
        "CONSTRAINT fk_project_usage_events_project_id_projects FOREIGN KEY(project_id)"
        " REFERENCES projects (id) ON DELETE RESTRICT",
        "CONSTRAINT fk_project_usage_events_owner_user_id_users FOREIGN KEY(owner_user_id)"
        " REFERENCES users (id) ON DELETE RESTRICT",
        "CONSTRAINT uq_project_usage_event_sequence UNIQUE (project_id, sequence)",
    ):
        assert fragment in table
    assert table.count("CONSTRAINT ") == 12
    assert statements[3] == TRIGGER
    assert module.revision in statements[4] and module.down_revision in statements[4]


def test_populated_downgrade_refuses_before_any_drop(monkeypatch):
    module, calls = capture(monkeypatch)
    queries = []

    def scalar(statement):
        queries.append(str(statement))
        return True

    monkeypatch.setattr(module.op, "get_bind", lambda: SimpleNamespace(scalar=scalar))
    with pytest.raises(RuntimeError, match="usage journal events must be preserved"):
        module.downgrade()
    assert calls == []
    assert queries == [f"SELECT EXISTS (SELECT 1 FROM {TABLE})"]


def test_empty_downgrade_drops_only_the_journal_table_and_its_function(monkeypatch):
    module, calls = capture(monkeypatch)
    monkeypatch.setattr(module.op, "get_bind", lambda: SimpleNamespace(scalar=lambda _: False))
    module.downgrade()
    assert calls == [
        ("drop_table", (TABLE,), {}),
        ("execute", (f"DROP FUNCTION {FUNCTION}()",), {}),
    ]
