"""Scoped SQL and read-only adapter checks without executing project code."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from orchestwin.api import web_execution_read_runtime as module

OWNER = UUID(int=5801)
PROJECT = UUID(int=5802)
EXECUTION = UUID(int=5803)


class Session:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        self.closed = True

    async def execute(self, query):
        self.queries.append(query)
        return SimpleNamespace(
            mappings=lambda: SimpleNamespace(
                all=lambda: self.rows, one_or_none=lambda: self.rows[0] if self.rows else None
            )
        )


@pytest.fixture
def schema(monkeypatch: pytest.MonkeyPatch):
    # SQL clauses are real SQLAlchemy expressions; no database connection is made.
    attempts = sa.table(
        "web_execution_attempts",
        *[sa.column(name) for name in ("id", "project_id", "created_by_user_id", "attempt_number")],
    )
    projects = sa.table(
        "projects", *[sa.column(name) for name in ("id", "owner_user_id", "archived_at")]
    )
    monkeypatch.setattr(module, "_schema", lambda: (attempts, projects))


def test_query_filters_owner_creator_project_and_archival(schema) -> None:
    query = module._owned_attempts(OWNER).where(module._schema()[0].c.project_id == PROJECT)
    compiled = query.compile(dialect=postgresql.dialect())
    text = str(compiled)
    assert "projects.owner_user_id =" in text
    assert "web_execution_attempts.created_by_user_id =" in text
    assert "projects.archived_at IS NULL" in text
    assert "web_execution_attempts.project_id =" in text
    assert OWNER in compiled.params.values()
    assert PROJECT in compiled.params.values()


def test_empty_history_remains_empty_and_closes_session(schema) -> None:
    session = Session([])
    service = module.SqlAlchemyWebExecutionReadApiService(lambda: session)
    assert asyncio.run(service.execution_history(owner_user_id=OWNER, project_id=PROJECT)) == ()
    assert session.closed
    assert "ORDER BY web_execution_attempts.attempt_number" in str(session.queries[0])


def test_missing_execution_does_not_invent_a_report(schema) -> None:
    session = Session([])
    service = module.SqlAlchemyWebExecutionReadApiService(lambda: session)
    assert (
        asyncio.run(service.execution_report(owner_user_id=OWNER, execution_id=EXECUTION)) is None
    )
    assert session.closed


def test_existing_execution_is_decoded_before_return(
    schema, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = {"attempt_snapshot": "test sentinel"}
    session = Session([row])
    observed = []

    def decode(value):
        observed.append(value)
        return SimpleNamespace(
            to_snapshot=lambda: {"id": str(EXECUTION), "report": {"status": "FAILED"}}
        )

    monkeypatch.setattr(module, "_decode_attempt", decode)
    service = module.SqlAlchemyWebExecutionReadApiService(lambda: session)
    report = asyncio.run(service.execution_report(owner_user_id=OWNER, execution_id=EXECUTION))
    assert report == {"status": "FAILED"}
    assert observed == [row]
    assert session.closed


def test_bad_hash_never_becomes_success(schema, monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(_row):
        raise ValueError("private-row-value")

    monkeypatch.setattr(module, "_decode_attempt", reject)
    session = Session([{}])
    service = module.SqlAlchemyWebExecutionReadApiService(lambda: session)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(service.execution(owner_user_id=OWNER, execution_id=EXECUTION))
    assert caught.value.status_code == 409
    assert "private" not in str(caught.value.detail)
    assert session.closed


def test_constructor_never_opens_a_session() -> None:
    def prohibited():
        raise AssertionError("startup must not connect")

    assert module.SqlAlchemyWebExecutionReadApiService(prohibited) is not None
