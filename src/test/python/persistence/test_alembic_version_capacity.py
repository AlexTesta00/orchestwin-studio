"""Tests for Alembic revision identifier capacity."""

from io import StringIO

from alembic import command
from alembic.script import (
    ScriptDirectory,
)

from orchestwin.persistence.migrate import (
    create_alembic_config,
)

TEST_DATABASE_URL = (
    "postgresql+psycopg://user:database-secret-must-not-leak-8472@localhost:5432/orchestwin"
)

CAPACITY_REVISION = "0005a_expand_alembic_version"
CLARIFICATION_REVISION = "0006_clarification_rounds_assumptions"


def test_capacity_revision_precedes_long_revision() -> None:
    """Expand the version column before using a long revision ID."""
    configuration = create_alembic_config(TEST_DATABASE_URL)
    scripts = ScriptDirectory.from_config(configuration)

    capacity_revision = scripts.get_revision(CAPACITY_REVISION)
    clarification_revision = scripts.get_revision(CLARIFICATION_REVISION)

    assert capacity_revision is not None
    assert clarification_revision is not None

    assert capacity_revision.down_revision == ("0005_project_brief_versions")
    assert clarification_revision.down_revision == (CAPACITY_REVISION)

    assert len(CAPACITY_REVISION) <= 32
    assert len(CLARIFICATION_REVISION) > 32

    assert len(scripts.get_heads()) == 1


def test_offline_upgrade_expands_version_capacity_first() -> None:
    """Widen Alembic's version column before stamping revision 0006."""
    output = StringIO()
    configuration = create_alembic_config(
        TEST_DATABASE_URL,
        output_buffer=output,
    )

    command.upgrade(
        configuration,
        "head",
        sql=True,
    )

    generated_sql = output.getvalue()
    alter_statement = "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)"

    assert alter_statement in generated_sql
    assert CLARIFICATION_REVISION in (generated_sql)

    assert generated_sql.index(alter_statement) < generated_sql.index(CLARIFICATION_REVISION)

    assert "database-secret-must-not-leak-8472" not in generated_sql
