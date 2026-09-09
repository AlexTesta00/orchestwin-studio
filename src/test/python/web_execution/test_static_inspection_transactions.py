"""Execute the SQL store's actual context manager using a recording session, not PostgreSQL."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from orchestwin.web_execution.static_inspection_persistence import SqlAlchemyInspectionStore
from orchestwin.web_execution.static_inspections import InspectionError


class Session:
    def __init__(self, project):
        self.project = project
        self.actions = []
        self.statements = []

    async def __aenter__(self):
        self.actions.append("open")
        return self

    async def __aexit__(self, *args):
        self.actions.append("close")

    @asynccontextmanager
    async def begin(self):
        self.actions.append("begin")
        try:
            yield
        except BaseException:
            self.actions.append("rollback")
            raise
        else:
            self.actions.append("commit")

    async def scalar(self, statement):
        self.statements.append(statement)
        return self.project


@pytest.mark.parametrize("failure", [None, RuntimeError, asyncio.CancelledError])
def test_scope_closes_and_rolls_back_or_commits_around_each_operation(failure):
    owner, project_id = uuid4(), uuid4()
    session = Session(SimpleNamespace(mode="GREENFIELD_GENERATION"))
    store = SqlAlchemyInspectionStore(lambda: session)

    async def scenario():
        async with store.scope(owner_user_id=owner, project_id=project_id) as scope:
            assert scope.session is session
            assert scope.owner_user_id == owner and scope.project_id == project_id
            if failure:
                raise failure()

    if failure:
        with pytest.raises(failure):
            asyncio.run(scenario())
    else:
        asyncio.run(scenario())
    assert session.actions == ["open", "begin", "rollback" if failure else "commit", "close"]
    sql = str(session.statements[0])
    assert "FOR UPDATE" in sql and "archived_at IS NULL" in sql
    assert "owner_user_id" in sql
    assert {owner, project_id} <= set(session.statements[0].compile().params.values())


@pytest.mark.parametrize("project", [None, SimpleNamespace(mode="BROWNFIELD_ASSESSMENT")])
def test_missing_or_non_greenfield_project_cannot_open_an_inspection_scope(project):
    session = Session(project)
    store = SqlAlchemyInspectionStore(lambda: session)

    async def scenario():
        async with store.scope(owner_user_id=uuid4(), project_id=uuid4()):
            pytest.fail("scope should have been rejected")

    with pytest.raises(InspectionError):
        asyncio.run(scenario())
    assert session.actions == ["open", "begin", "rollback", "close"]
