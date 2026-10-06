from __future__ import annotations

import importlib
import re
from io import StringIO
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql

from orchestwin.persistence.migrate import create_alembic_config
from orchestwin.projects.knowledge_alignment import ProposalSection, ProposalStatus
from orchestwin.projects.persistence.knowledge_alignment import PROPOSALS, RUNS

RUNS_TABLE = "knowledge_alignment_runs"
PROPOSALS_TABLE = "knowledge_alignment_proposals"
RUN_INDEX = "ix_knowledge_alignment_runs_project_created"
PROPOSAL_INDEX = "ix_knowledge_alignment_proposals_project_status"
RUN_COLUMNS = [
    "id",
    "project_id",
    "owner_user_id",
    "from_commit",
    "to_commit",
    "commits",
    "locale",
    "requirements_version_number",
    "design_version_number",
    "alternative_code",
    "summary",
    "created_at",
    "cost_microusd",
    "generation_ids",
]
PROPOSAL_COLUMNS = [
    "id",
    "run_id",
    "project_id",
    "owner_user_id",
    "number",
    "section",
    "title",
    "request",
    "rationale",
    "subjects",
    "origin",
    "status",
    "created_at",
    "decided_at",
    "decision_note",
    "applied_text",
    "applied_diff_id",
]
RUN_CHECKS = {
    "ck_knowledge_alignment_runs_to_commit": "to_commit ~ '^[0-9a-f]{7,64}$'",
    "ck_knowledge_alignment_runs_from_commit": (
        "from_commit IS NULL OR from_commit ~ '^[0-9a-f]{7,64}$'"
    ),
    "ck_knowledge_alignment_runs_commits": (
        "jsonb_typeof(commits) = 'array' AND jsonb_array_length(commits) BETWEEN 1 AND 50"
    ),
    "ck_knowledge_alignment_runs_locale": "char_length(locale) BETWEEN 2 AND 20",
    "ck_knowledge_alignment_runs_versions": (
        "requirements_version_number >= 1 AND design_version_number >= 1"
    ),
    "ck_knowledge_alignment_runs_alternative_code": "alternative_code ~ '^DES-[0-9]{3,6}$'",
    "ck_knowledge_alignment_runs_summary": "char_length(summary) BETWEEN 1 AND 600",
    "ck_knowledge_alignment_runs_cost": "cost_microusd >= 0",
    "ck_knowledge_alignment_runs_generation_ids": "jsonb_typeof(generation_ids) = 'array'",
}
PROPOSAL_CHECKS = {
    "ck_knowledge_alignment_proposals_number": "number BETWEEN 1 AND 999999",
    "ck_knowledge_alignment_proposals_section": "section IN ('REQUIREMENTS','DESIGN','TESTS')",
    "ck_knowledge_alignment_proposals_title": "char_length(title) BETWEEN 1 AND 200",
    "ck_knowledge_alignment_proposals_request": "char_length(request) BETWEEN 1 AND 2000",
    "ck_knowledge_alignment_proposals_rationale": "char_length(rationale) BETWEEN 1 AND 400",
    "ck_knowledge_alignment_proposals_subjects": "jsonb_typeof(subjects) = 'object'",
    "ck_knowledge_alignment_proposals_origin": "jsonb_typeof(origin) = 'object'",
    "ck_knowledge_alignment_proposals_status": "status IN ('PROPOSED','APPLIED','SKIPPED')",
    "ck_knowledge_alignment_proposals_decision_time": (
        "(status = 'PROPOSED') = (decided_at IS NULL)"
    ),
    "ck_knowledge_alignment_proposals_decision_note": (
        "decision_note IS NULL OR (status <> 'PROPOSED' AND "
        "char_length(decision_note) BETWEEN 1 AND 300)"
    ),
    "ck_knowledge_alignment_proposals_applied_text": (
        "applied_text IS NULL OR (status = 'APPLIED' AND "
        "char_length(applied_text) BETWEEN 1 AND 2000)"
    ),
    "ck_knowledge_alignment_proposals_applied_diff": (
        "applied_diff_id IS NULL OR status = 'APPLIED'"
    ),
}
RUN_FRAGMENTS = (
    "id UUID NOT NULL",
    "from_commit VARCHAR(64),",
    "to_commit VARCHAR(64) NOT NULL",
    "commits JSONB NOT NULL",
    "locale VARCHAR(20) NOT NULL",
    "alternative_code VARCHAR(16) NOT NULL",
    "summary TEXT NOT NULL",
    "created_at TIMESTAMP WITH TIME ZONE NOT NULL",
    "cost_microusd INTEGER NOT NULL",
    "generation_ids JSONB NOT NULL",
    "CONSTRAINT pk_knowledge_alignment_runs PRIMARY KEY (id)",
    "CONSTRAINT fk_knowledge_alignment_runs_project FOREIGN KEY(project_id)"
    " REFERENCES projects (id) ON DELETE RESTRICT",
    "CONSTRAINT fk_knowledge_alignment_runs_owner FOREIGN KEY(owner_user_id)"
    " REFERENCES users (id) ON DELETE RESTRICT",
    "CONSTRAINT ck_knowledge_alignment_runs_to_commit CHECK (to_commit ~ '^[0-9a-f]{7,64}$')",
)
PROPOSAL_FRAGMENTS = (
    "run_id UUID NOT NULL",
    "number INTEGER NOT NULL",
    "section VARCHAR(16) NOT NULL",
    "title VARCHAR(200) NOT NULL",
    "request TEXT NOT NULL",
    "subjects JSONB NOT NULL",
    "origin JSONB NOT NULL",
    "status VARCHAR(16) NOT NULL",
    "decided_at TIMESTAMP WITH TIME ZONE,",
    "decision_note TEXT,",
    "applied_text TEXT,",
    "applied_diff_id UUID,",
    "CONSTRAINT pk_knowledge_alignment_proposals PRIMARY KEY (id)",
    "CONSTRAINT uq_knowledge_alignment_proposals_number UNIQUE (project_id, number)",
    "CONSTRAINT fk_knowledge_alignment_proposals_run FOREIGN KEY(run_id)"
    " REFERENCES knowledge_alignment_runs (id) ON DELETE RESTRICT",
    "CONSTRAINT fk_knowledge_alignment_proposals_project FOREIGN KEY(project_id)"
    " REFERENCES projects (id) ON DELETE RESTRICT",
    "CONSTRAINT ck_knowledge_alignment_proposals_status CHECK"
    " (status IN ('PROPOSED','APPLIED','SKIPPED'))",
)


def migration():
    return importlib.import_module(
        "orchestwin.persistence.migrations.versions.0073_knowledge_alignment"
    )


def capture(monkeypatch):
    module = migration()
    calls = []
    for name in ("create_table", "create_index", "drop_index", "drop_table"):
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


def test_revision_follows_the_guidance_choice_and_is_the_single_head():
    module = migration()
    assert module.revision == "0073_knowledge_alignment"
    assert module.down_revision == "0072_guidance_choice"
    assert ",".join(f"'{item.value}'" for item in ProposalSection) == module.SECTIONS
    assert ",".join(f"'{item.value}'" for item in ProposalStatus) == module.STATUSES
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert {
        name.split(".")[0] for name in re.findall(r"^(?:from|import) ([\w.]+)", source, re.M)
    } == {"alembic", "sqlalchemy"}
    scripts = ScriptDirectory.from_config(
        create_alembic_config("postgresql+psycopg://synthetic@localhost:5432/orchestwin")
    )
    assert scripts.get_heads() == [module.revision]
    assert scripts.get_revision(module.revision).down_revision == module.down_revision


def test_upgrade_creates_the_two_tables_and_their_indexes_in_order(monkeypatch):
    module, calls = capture(monkeypatch)
    module.upgrade()
    assert [call[0] for call in calls] == [
        "create_table",
        "create_index",
        "create_table",
        "create_index",
    ]
    assert calls[1] == ("create_index", (RUN_INDEX, RUNS_TABLE, ["project_id", "created_at"]), {})
    assert calls[3] == (
        "create_index",
        (PROPOSAL_INDEX, PROPOSALS_TABLE, ["project_id", "status"]),
        {},
    )
    runs, proposals = tables(calls)
    assert (runs.name, proposals.name) == (RUNS_TABLE, PROPOSALS_TABLE)
    assert [column.name for column in runs.columns] == RUN_COLUMNS
    assert [column.name for column in proposals.columns] == PROPOSAL_COLUMNS
    assert [column.name for column in runs.columns if column.nullable] == ["from_commit"]
    assert [column.name for column in proposals.columns if column.nullable] == [
        "decided_at",
        "decision_note",
        "applied_text",
        "applied_diff_id",
    ]
    for table in (runs, proposals):
        for name in ("id", "project_id", "owner_user_id"):
            assert isinstance(table.c[name].type, postgresql.UUID)
            assert table.c[name].type.as_uuid is True
        assert table.c.created_at.type.timezone is True
    assert isinstance(runs.c.commits.type, postgresql.JSONB)
    assert isinstance(runs.c.generation_ids.type, postgresql.JSONB)
    assert isinstance(runs.c.cost_microusd.type, sa.Integer)
    assert (runs.c.from_commit.type.length, runs.c.to_commit.type.length) == (64, 64)
    assert (runs.c.locale.type.length, runs.c.alternative_code.type.length) == (20, 16)
    assert isinstance(runs.c.summary.type, sa.Text)
    assert (proposals.c.section.type.length, proposals.c.status.type.length) == (16, 16)
    assert proposals.c.title.type.length == 200
    for name in ("request", "rationale", "decision_note", "applied_text"):
        assert isinstance(proposals.c[name].type, sa.Text)
    assert isinstance(proposals.c.subjects.type, postgresql.JSONB)
    assert isinstance(proposals.c.origin.type, postgresql.JSONB)
    assert isinstance(proposals.c.applied_diff_id.type, postgresql.UUID)
    assert proposals.c.decided_at.type.timezone is True
    assert runs.primary_key.name == "pk_knowledge_alignment_runs"
    assert proposals.primary_key.name == "pk_knowledge_alignment_proposals"
    assert foreign_keys(runs) == {
        (("project_id",), ("projects.id",), "RESTRICT", "fk_knowledge_alignment_runs_project"),
        (("owner_user_id",), ("users.id",), "RESTRICT", "fk_knowledge_alignment_runs_owner"),
    }
    assert foreign_keys(proposals) == {
        (
            ("run_id",),
            ("knowledge_alignment_runs.id",),
            "RESTRICT",
            "fk_knowledge_alignment_proposals_run",
        ),
        (
            ("project_id",),
            ("projects.id",),
            "RESTRICT",
            "fk_knowledge_alignment_proposals_project",
        ),
        (("owner_user_id",), ("users.id",), "RESTRICT", "fk_knowledge_alignment_proposals_owner"),
    }
    assert [
        (constraint.name, tuple(constraint.columns.keys()))
        for constraint in runs.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    ] == []
    assert [
        (constraint.name, tuple(constraint.columns.keys()))
        for constraint in proposals.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    ] == [("uq_knowledge_alignment_proposals_number", ("project_id", "number"))]
    assert checks(runs) == RUN_CHECKS
    assert checks(proposals) == PROPOSAL_CHECKS


def test_offline_upgrade_renders_exact_names_and_touches_no_other_table():
    module = migration()
    statements = offline_upgrade_statements(module)
    assert [" ".join(statement.split()[:2]) for statement in statements] == [
        "BEGIN",
        "CREATE TABLE",
        "CREATE INDEX",
        "CREATE TABLE",
        "CREATE INDEX",
        "UPDATE alembic_version",
        "COMMIT",
    ]
    runs, proposals = statements[1], statements[3]
    assert runs.startswith(f"CREATE TABLE {RUNS_TABLE} (")
    assert proposals.startswith(f"CREATE TABLE {PROPOSALS_TABLE} (")
    for fragment in RUN_FRAGMENTS:
        assert fragment in runs, fragment
    for fragment in PROPOSAL_FRAGMENTS:
        assert fragment in proposals, fragment
    assert runs.count("CONSTRAINT ") == 1 + 2 + len(RUN_CHECKS)
    assert proposals.count("CONSTRAINT ") == 1 + 1 + 3 + len(PROPOSAL_CHECKS)
    assert statements[2] == f"CREATE INDEX {RUN_INDEX} ON {RUNS_TABLE} (project_id, created_at)"
    assert statements[4] == (
        f"CREATE INDEX {PROPOSAL_INDEX} ON {PROPOSALS_TABLE} (project_id, status)"
    )
    assert module.revision in statements[5] and module.down_revision in statements[5]
    assert "ALTER TABLE" not in " ".join(statements)


def test_the_repository_tables_declare_the_same_columns_as_the_migration():
    assert RUNS.name == RUNS_TABLE
    assert PROPOSALS.name == PROPOSALS_TABLE
    assert [column.name for column in RUNS.c] == RUN_COLUMNS
    assert [column.name for column in PROPOSALS.c] == PROPOSAL_COLUMNS
    for table in (RUNS, PROPOSALS):
        for name in ("id", "project_id", "owner_user_id"):
            assert isinstance(table.c[name].type, postgresql.UUID)
    assert (RUNS.c.to_commit.type.length, RUNS.c.locale.type.length) == (64, 20)
    assert RUNS.c.alternative_code.type.length == 16
    assert (PROPOSALS.c.section.type.length, PROPOSALS.c.title.type.length) == (16, 200)
    assert isinstance(PROPOSALS.c.subjects.type, postgresql.JSONB)
    assert isinstance(PROPOSALS.c.origin.type, postgresql.JSONB)


def test_downgrade_drops_the_proposals_before_the_runs(monkeypatch):
    module, calls = capture(monkeypatch)
    module.downgrade()
    assert calls == [
        ("drop_index", (PROPOSAL_INDEX,), {"table_name": PROPOSALS_TABLE}),
        ("drop_table", (PROPOSALS_TABLE,), {}),
        ("drop_index", (RUN_INDEX,), {"table_name": RUNS_TABLE}),
        ("drop_table", (RUNS_TABLE,), {}),
    ]
