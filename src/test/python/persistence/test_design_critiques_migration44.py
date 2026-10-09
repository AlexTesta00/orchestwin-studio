from __future__ import annotations

import importlib
import re
from io import StringIO
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql

from orchestwin.artifacts.design_critique import (
    MAX_SHOT_BYTES,
    MAX_TITLE_LENGTH,
    SHOT_MEDIA_TYPES,
    DesignCritiqueSourceKind,
)
from orchestwin.artifacts.design_critique_persistence import RUNS, SHOTS, SOURCES
from orchestwin.persistence.migrate import create_alembic_config

URL = "postgresql+psycopg://synthetic@localhost:5432/orchestwin"
REVISION = "0075_design_critiques"
PREVIOUS = "0074_design_version_restore"
SOURCES_TABLE = "design_critique_sources"
SHOTS_TABLE = "design_critique_shots"
RUNS_TABLE = "design_critique_runs"
SOURCE_INDEX = "ix_design_critique_sources_project_created"
RUN_INDEX = "ix_design_critique_runs_project_started"
SOURCE_COLUMNS = [
    "id",
    "project_id",
    "owner_user_id",
    "kind",
    "title",
    "url",
    "page_snapshot",
    "created_at",
    "content_hash",
]
SHOT_COLUMNS = [
    "id",
    "source_id",
    "project_id",
    "owner_user_id",
    "code",
    "media_type",
    "byte_size",
    "sha256",
    "width",
    "height",
    "viewport_width",
    "content",
]
RUN_COLUMNS = [
    "id",
    "project_id",
    "owner_user_id",
    "source_id",
    "evaluator_id",
    "evaluator_version",
    "model_config_ref",
    "prompt_version_ref",
    "response_count",
    "finding_count",
    "started_at",
    "completed_at",
    "content_hash",
    "run_snapshot",
]
CHECKS = {
    SOURCES_TABLE: {"ck_design_critique_sources_kind": "kind IN ('IMAGE','WEB_PAGE')"},
    SHOTS_TABLE: {
        "ck_design_critique_shots_media_type": "media_type IN ('image/png','image/jpeg')",
        "ck_design_critique_shots_byte_size": "byte_size BETWEEN 1 AND 5242880",
    },
    RUNS_TABLE: {},
}
NULLABLE = {
    SOURCES_TABLE: ["url", "page_snapshot"],
    SHOTS_TABLE: ["viewport_width"],
    RUNS_TABLE: [],
}
SOURCE_FRAGMENTS = (
    "id UUID NOT NULL",
    "kind VARCHAR(16) NOT NULL",
    "title VARCHAR(200) NOT NULL",
    "url TEXT,",
    "page_snapshot JSONB,",
    "created_at TIMESTAMP WITH TIME ZONE NOT NULL",
    "content_hash VARCHAR(64) NOT NULL",
    "CONSTRAINT pk_design_critique_sources PRIMARY KEY (id)",
    "CONSTRAINT fk_design_critique_sources_project FOREIGN KEY(project_id)"
    " REFERENCES projects (id) ON DELETE RESTRICT",
    "CONSTRAINT fk_design_critique_sources_owner FOREIGN KEY(owner_user_id)"
    " REFERENCES users (id) ON DELETE RESTRICT",
    "CONSTRAINT ck_design_critique_sources_kind CHECK (kind IN ('IMAGE','WEB_PAGE'))",
)
SHOT_FRAGMENTS = (
    "source_id UUID NOT NULL",
    "code VARCHAR(8) NOT NULL",
    "media_type VARCHAR(16) NOT NULL",
    "byte_size INTEGER NOT NULL",
    "sha256 VARCHAR(64) NOT NULL",
    "width INTEGER NOT NULL",
    "height INTEGER NOT NULL",
    "viewport_width INTEGER,",
    "content BYTEA NOT NULL",
    "CONSTRAINT pk_design_critique_shots PRIMARY KEY (id)",
    "CONSTRAINT uq_design_critique_shots_source_code UNIQUE (source_id, code)",
    "CONSTRAINT fk_design_critique_shots_source FOREIGN KEY(source_id)"
    " REFERENCES design_critique_sources (id) ON DELETE RESTRICT",
    "CONSTRAINT fk_design_critique_shots_project FOREIGN KEY(project_id)"
    " REFERENCES projects (id) ON DELETE RESTRICT",
    "CONSTRAINT fk_design_critique_shots_owner FOREIGN KEY(owner_user_id)"
    " REFERENCES users (id) ON DELETE RESTRICT",
    "CONSTRAINT ck_design_critique_shots_media_type CHECK"
    " (media_type IN ('image/png','image/jpeg'))",
    "CONSTRAINT ck_design_critique_shots_byte_size CHECK (byte_size BETWEEN 1 AND 5242880)",
)
RUN_FRAGMENTS = (
    "source_id UUID NOT NULL",
    "evaluator_id VARCHAR(256) NOT NULL",
    "prompt_version_ref VARCHAR(256) NOT NULL",
    "response_count INTEGER NOT NULL",
    "finding_count INTEGER NOT NULL",
    "started_at TIMESTAMP WITH TIME ZONE NOT NULL",
    "completed_at TIMESTAMP WITH TIME ZONE NOT NULL",
    "run_snapshot JSONB NOT NULL",
    "CONSTRAINT pk_design_critique_runs PRIMARY KEY (id)",
    "CONSTRAINT fk_design_critique_runs_project FOREIGN KEY(project_id)"
    " REFERENCES projects (id) ON DELETE RESTRICT",
    "CONSTRAINT fk_design_critique_runs_owner FOREIGN KEY(owner_user_id)"
    " REFERENCES users (id) ON DELETE RESTRICT",
    "CONSTRAINT fk_design_critique_runs_source FOREIGN KEY(source_id)"
    " REFERENCES design_critique_sources (id) ON DELETE RESTRICT",
)


def migration():
    return importlib.import_module(f"orchestwin.persistence.migrations.versions.{REVISION}")


def capture(monkeypatch):
    module = migration()
    calls = []
    for name in ("create_table", "create_index", "drop_index", "drop_table"):
        monkeypatch.setattr(
            module.op, name, lambda *args, _name=name, **kwargs: calls.append((_name, args, kwargs))
        )
    monkeypatch.setattr(module.op, "f", lambda value: value)
    return module, calls


def offline_sql(step, revisions) -> str:
    output = StringIO()
    step(create_alembic_config(URL, output_buffer=output), revisions, sql=True)
    return output.getvalue()


def statements(sql: str) -> list[str]:
    text = "\n".join(line for line in sql.splitlines() if not line.startswith("--"))
    return [" ".join(part.split()) for part in text.split(";\n") if part.strip()]


def tables(calls):
    return [
        sa.Table(call[1][0], sa.MetaData(), *call[1][1:])
        for call in calls
        if call[0] == "create_table"
    ]


def foreign_keys(table):
    return {
        (
            tuple(element.parent.name for element in constraint.elements),
            tuple(element.target_fullname for element in constraint.elements),
            constraint.ondelete,
            constraint.name,
        )
        for constraint in table.foreign_key_constraints
    }


def checks(table):
    return {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }


def owned(table):
    return {
        (("project_id",), ("projects.id",), "RESTRICT", f"fk_{table}_project"),
        (("owner_user_id",), ("users.id",), "RESTRICT", f"fk_{table}_owner"),
    }


def test_revision_follows_the_design_restore_and_is_the_single_head():
    module = migration()
    assert (module.revision, module.down_revision) == (REVISION, PREVIOUS)
    assert (module.branch_labels, module.depends_on) == (None, None)
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert {
        name.split(".")[0] for name in re.findall(r"^(?:from|import) ([\w.]+)", source, re.M)
    } == {"alembic", "sqlalchemy"}
    scripts = ScriptDirectory.from_config(create_alembic_config(URL))
    assert scripts.get_heads() == [REVISION]
    assert scripts.get_revision(REVISION).down_revision == PREVIOUS
    assert scripts.get_revision(PREVIOUS).nextrev == {REVISION}


def test_the_checked_values_are_the_values_of_the_domain():
    module = migration()
    assert ",".join(f"'{kind.value}'" for kind in DesignCritiqueSourceKind) == module.KINDS
    assert set(module.MEDIA_TYPES.split(",")) == {f"'{item}'" for item in SHOT_MEDIA_TYPES}
    assert module.MAX_SHOT_BYTES == MAX_SHOT_BYTES == 5242880
    assert module.TITLE_LIMIT == MAX_TITLE_LENGTH


def test_upgrade_creates_the_three_tables_and_their_indexes_in_order(monkeypatch):
    module, calls = capture(monkeypatch)
    module.upgrade()
    assert [call[0] for call in calls] == [
        "create_table",
        "create_index",
        "create_table",
        "create_table",
        "create_index",
    ]
    assert calls[1] == (
        "create_index",
        (SOURCE_INDEX, SOURCES_TABLE, ["project_id", "created_at"]),
        {},
    )
    assert calls[4] == ("create_index", (RUN_INDEX, RUNS_TABLE, ["project_id", "started_at"]), {})
    sources, shots, runs = tables(calls)
    assert (sources.name, shots.name, runs.name) == (SOURCES_TABLE, SHOTS_TABLE, RUNS_TABLE)
    assert [column.name for column in sources.columns] == SOURCE_COLUMNS
    assert [column.name for column in shots.columns] == SHOT_COLUMNS
    assert [column.name for column in runs.columns] == RUN_COLUMNS
    for table in (sources, shots, runs):
        assert [column.name for column in table.columns if column.nullable] == NULLABLE[table.name]
        assert table.primary_key.name == f"pk_{table.name}"
        assert [column.name for column in table.primary_key.columns] == ["id"]
        assert checks(table) == CHECKS[table.name]
        for name in ("id", "project_id", "owner_user_id"):
            assert isinstance(table.c[name].type, postgresql.UUID)
            assert table.c[name].type.as_uuid is True
    assert foreign_keys(sources) == owned(SOURCES_TABLE)
    assert foreign_keys(shots) == owned(SHOTS_TABLE) | {
        (
            ("source_id",),
            ("design_critique_sources.id",),
            "RESTRICT",
            "fk_design_critique_shots_source",
        )
    }
    assert foreign_keys(runs) == owned(RUNS_TABLE) | {
        (
            ("source_id",),
            ("design_critique_sources.id",),
            "RESTRICT",
            "fk_design_critique_runs_source",
        )
    }
    assert [
        (constraint.name, tuple(constraint.columns.keys()))
        for table in (sources, shots, runs)
        for constraint in table.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    ] == [("uq_design_critique_shots_source_code", ("source_id", "code"))]
    assert (sources.c.kind.type.length, sources.c.title.type.length) == (16, 200)
    assert isinstance(sources.c.url.type, sa.Text)
    assert isinstance(sources.c.page_snapshot.type, postgresql.JSONB)
    assert sources.c.created_at.type.timezone is True
    assert (shots.c.code.type.length, shots.c.media_type.type.length) == (8, 16)
    assert shots.c.sha256.type.length == 64
    assert isinstance(shots.c.content.type, sa.LargeBinary)
    for name in ("byte_size", "width", "height", "viewport_width"):
        assert isinstance(shots.c[name].type, sa.Integer)
    for name in ("evaluator_id", "evaluator_version", "model_config_ref", "prompt_version_ref"):
        assert runs.c[name].type.length == 256
    assert isinstance(runs.c.run_snapshot.type, postgresql.JSONB)
    assert runs.c.started_at.type.timezone is True
    assert runs.c.completed_at.type.timezone is True


def test_offline_upgrade_renders_exact_names_and_touches_no_other_table():
    rendered = statements(offline_sql(command.upgrade, f"{PREVIOUS}:{REVISION}"))
    assert [" ".join(statement.split()[:2]) for statement in rendered] == [
        "BEGIN",
        "CREATE TABLE",
        "CREATE INDEX",
        "CREATE TABLE",
        "CREATE TABLE",
        "CREATE INDEX",
        "UPDATE alembic_version",
        "COMMIT",
    ]
    sources, shots, runs = rendered[1], rendered[3], rendered[4]
    for table, statement, fragments, constraints in (
        (SOURCES_TABLE, sources, SOURCE_FRAGMENTS, 4),
        (SHOTS_TABLE, shots, SHOT_FRAGMENTS, 7),
        (RUNS_TABLE, runs, RUN_FRAGMENTS, 4),
    ):
        assert statement.startswith(f"CREATE TABLE {table} (")
        for fragment in fragments:
            assert fragment in statement, fragment
        assert statement.count("CONSTRAINT ") == constraints
    assert rendered[2] == (
        f"CREATE INDEX {SOURCE_INDEX} ON {SOURCES_TABLE} (project_id, created_at)"
    )
    assert rendered[5] == f"CREATE INDEX {RUN_INDEX} ON {RUNS_TABLE} (project_id, started_at)"
    assert f"SET version_num='{REVISION}'" in rendered[6]
    assert f"version_num = '{PREVIOUS}'" in rendered[6]
    assert "ALTER TABLE" not in " ".join(rendered)
    assert "synthetic" not in " ".join(rendered)


def test_offline_downgrade_drops_the_runs_the_shots_and_then_the_sources():
    rendered = statements(offline_sql(command.downgrade, f"{REVISION}:{PREVIOUS}"))
    assert rendered[:6] == [
        "BEGIN",
        f"DROP INDEX {RUN_INDEX}",
        f"DROP TABLE {RUNS_TABLE}",
        f"DROP TABLE {SHOTS_TABLE}",
        f"DROP INDEX {SOURCE_INDEX}",
        f"DROP TABLE {SOURCES_TABLE}",
    ]
    assert f"SET version_num='{PREVIOUS}'" in rendered[6]
    assert f"version_num = '{REVISION}'" in rendered[6]
    assert rendered[7:] == ["COMMIT"]


def test_downgrade_drops_the_tables_in_reverse_order(monkeypatch):
    module, calls = capture(monkeypatch)
    module.downgrade()
    assert calls == [
        ("drop_index", (RUN_INDEX,), {"table_name": RUNS_TABLE}),
        ("drop_table", (RUNS_TABLE,), {}),
        ("drop_table", (SHOTS_TABLE,), {}),
        ("drop_index", (SOURCE_INDEX,), {"table_name": SOURCES_TABLE}),
        ("drop_table", (SOURCES_TABLE,), {}),
    ]


def test_the_repository_tables_declare_the_same_columns_as_the_migration():
    assert (SOURCES.name, SHOTS.name, RUNS.name) == (SOURCES_TABLE, SHOTS_TABLE, RUNS_TABLE)
    assert [column.name for column in SOURCES.c] == SOURCE_COLUMNS
    assert [column.name for column in SHOTS.c] == SHOT_COLUMNS
    assert [column.name for column in RUNS.c] == RUN_COLUMNS
    for table in (SOURCES, SHOTS, RUNS):
        for name in ("id", "project_id", "owner_user_id"):
            assert isinstance(table.c[name].type, postgresql.UUID)
    assert isinstance(SOURCES.c.page_snapshot.type, postgresql.JSONB)
    assert SOURCES.c.page_snapshot.type.none_as_null is True
    assert isinstance(RUNS.c.run_snapshot.type, postgresql.JSONB)
    assert isinstance(SHOTS.c.content.type, sa.LargeBinary)
    assert (SOURCES.c.kind.type.length, SOURCES.c.title.type.length) == (16, 200)
    assert (SHOTS.c.code.type.length, SHOTS.c.media_type.type.length) == (8, 16)
