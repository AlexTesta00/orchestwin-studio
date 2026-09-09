"""SQLAlchemy row/DDL contracts; these tests do not claim a live PostgreSQL run."""

import asyncio
import importlib.util
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import postgresql

from orchestwin.web_execution.static_inspection_persistence import (
    SqlAlchemyInspectionScope,
    record_from_row,
    record_values,
)
from orchestwin.web_execution.static_inspections import InspectionError

from .static_inspection_support import prepare, setup_service

ROOT = Path(__file__).resolve().parents[4]


def test_owner_and_project_filters_are_in_every_inspection_query(tmp_path):
    _, store, _, _ = setup_service(tmp_path)
    scope = SqlAlchemyInspectionScope(None, store.owner, store.project)
    query = scope._owned().compile(dialect=postgresql.dialect())
    assert "owner_user_id" in str(query) and "project_id" in str(query)
    assert store.owner in query.params.values() and store.project in query.params.values()


@pytest.mark.parametrize(
    "field", ["plan_hash", "job_hash", "project_id", "source_revision_id", "owner_user_id"]
)
def test_persisted_projection_cannot_contradict_immutable_plan(tmp_path, field):
    service, store, backend, args = setup_service(tmp_path)
    asyncio.run(prepare(service, backend, args))
    record = store.records[args["request_id"]]
    row = record_values(record)
    assert record_from_row(row) == record
    row[field] = "wrong"
    with pytest.raises(InspectionError, match="INTEGRITY"):
        record_from_row(row)


def test_migration_renders_additive_table_and_database_immutability_guards():
    path = (
        ROOT / "src/orchestwin/persistence/migrations/versions/0032_static_browser_inspections.py"
    )
    spec = importlib.util.spec_from_file_location("static_inspection_migration_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "0031_training_runs"
    assert module.revision == "0032_static_browser_inspections"
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        module.upgrade()
    sql = output.getvalue()
    assert "CREATE TABLE static_browser_inspections" in sql
    assert "REFERENCES human_gates" in sql and "REFERENCES web_source_revisions" in sql
    assert "static inspection plans are immutable" in sql
    assert "OLD.state = 'RUNNING'" in sql
    assert "TRUNCATE" not in sql and "DROP TABLE" not in sql
