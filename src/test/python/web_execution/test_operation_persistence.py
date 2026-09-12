"""SQL ownership/CAS and additive migration checks, without a database connection."""

import asyncio
from io import StringIO
from uuid import UUID

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import AddConstraint

from orchestwin.persistence.migrate import create_alembic_config
from orchestwin.web_execution.operation_governance import WebGovernedOperation, WebOperationError
from orchestwin.web_execution.operation_persistence import (
    WEB_GOVERNED_OPERATIONS,
    SqlAlchemyWebOperationScope,
    SqlAlchemyWebOperationStore,
)


def test_every_read_joins_active_owner_project_and_operation_owner():
    owner, project = UUID(int=1), UUID(int=2)
    scope = SqlAlchemyWebOperationScope(None, owner, project)
    compiled = scope._owned().compile(dialect=postgresql.dialect())
    assert "JOIN projects" in str(compiled)
    assert "archived_at IS NULL" in str(compiled)
    assert "web_governed_operations.owner_user_id" in str(compiled)
    assert owner in compiled.params.values() and project in compiled.params.values()


def test_orm_registers_every_lifecycle_and_payload_constraint():
    names = {item.name for item in WEB_GOVERNED_OPERATIONS.constraints}
    for name in (
        "payload_object",
        "result_bounded",
        "result_hash_valid",
        "started_order",
        "finished_order",
        "lifecycle_valid",
    ):
        assert f"ck_web_governed_operations_{name}" in names


def test_cancellation_check_compiles_without_json_colon_bind_parameters():
    constraint = next(
        item
        for item in WEB_GOVERNED_OPERATIONS.constraints
        if item.name == "ck_web_governed_operations_lifecycle_valid"
    )
    assert not constraint.sqltext.compile(dialect=postgresql.dialect()).params
    orm_sql = str(AddConstraint(constraint).compile(dialect=postgresql.dialect()))
    for sql in (orm_sql, migration_sql()):
        assert (
            "jsonb_build_object('failure_code', 'WEB_OPERATION_CANCELLED', 'execution_started', false)"
            in sql
        )


@pytest.mark.parametrize("owned", [True, False])
def test_store_locks_owned_project_and_closes_transaction_before_return(owned):
    events = []

    class Transaction:
        async def __aenter__(self):
            events.append("begin")

        async def __aexit__(self, error_type, error, traceback):
            events.append("rollback" if error_type else "commit")

    class Session:
        async def __aenter__(self):
            events.append("open")
            return self

        async def __aexit__(self, *args):
            events.append("close")

        def begin(self):
            return Transaction()

        async def scalar(self, statement):
            assert "FOR UPDATE" in str(statement.compile(dialect=postgresql.dialect()))
            events.append("lock")
            return object() if owned else None

    store = SqlAlchemyWebOperationStore(Session)

    async def scenario():
        async with store.scope(owner_user_id=UUID(int=1), project_id=UUID(int=2)) as scope:
            assert isinstance(scope, SqlAlchemyWebOperationScope)
            events.append("body")

    if owned:
        asyncio.run(scenario())
        assert events == ["open", "begin", "lock", "body", "commit", "close"]
    else:
        with pytest.raises(WebOperationError, match="PROJECT_NOT_FOUND"):
            asyncio.run(scenario())
        assert events == ["open", "begin", "lock", "rollback", "close"]


def migration_sql(downgrade=False):
    scripts = ScriptDirectory.from_config(
        create_alembic_config("postgresql+psycopg://u:p@localhost/unused")
    )
    script = scripts.get_revision("0035_web_governed_operations")
    assert script.down_revision == "0034_web_validation_evidence"
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        (script.module.downgrade if downgrade else script.module.upgrade)()
    return output.getvalue()


def test_migration_enforces_immutable_identity_and_bounded_lifecycle():
    sql = migration_sql()
    assert "CREATE TABLE web_governed_operations" in sql
    assert "REFERENCES human_gates" in sql and "REFERENCES web_source_revisions" in sql
    assert "CREATE UNIQUE INDEX" in sql and "WHERE state = 'RUNNING'" in sql
    assert "BEFORE UPDATE OR DELETE" in sql and "BEFORE TRUNCATE" in sql
    assert "OLD.payload_json" in sql and "OLD.content_hash" in sql
    assert "OLD.state = 'RUNNING'" in sql and "NEW.state IN ('COMPLETED', 'FAILED')" in sql
    assert "octet_length(payload_json)" in sql


def test_downgrade_removes_guards_before_table():
    sql = migration_sql(True)
    assert sql.rindex("DROP TRIGGER") < sql.index("DROP FUNCTION") < sql.index("DROP TABLE")


def test_update_cas_does_not_accept_a_lost_race():
    class Session:
        async def execute(self, statement):
            compiled = statement.compile(dialect=postgresql.dialect())
            assert "state" in str(compiled) and "content_hash" in str(compiled)
            return type("Result", (), {"rowcount": 0})()

    scope = SqlAlchemyWebOperationScope(Session(), UUID(int=1), UUID(int=2))
    original = WebGovernedOperation.create(
        project_id=UUID(int=2),
        owner_user_id=UUID(int=1),
        source_revision_id=UUID(int=3),
        kind="REPAIR",
        payload={"x": 1},
    )
    with pytest.raises(WebOperationError, match="STATE_CONFLICT"):
        asyncio.run(scope.update(original, original))
