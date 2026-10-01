import asyncio
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from orchestwin.twins.persistence.uow import SqlAlchemyUserModelingUnitOfWork
from orchestwin.twins.runtime import ManagedArchetypeUnitOfWork, ManagedUserModelingUnitOfWork

OWNER = UUID(int=1)
PROJECT = UUID(int=2)


@pytest.mark.parametrize(
    "unit_type",
    [SqlAlchemyUserModelingUnitOfWork, ManagedUserModelingUnitOfWork, ManagedArchetypeUnitOfWork],
)
def test_all_command_uows_share_owner_scoped_project_lock_and_pending_query(unit_type):
    session = AsyncMock()
    session.scalar.side_effect = [object(), UUID(int=3)]
    unit = unit_type(session, owner_user_id=OWNER)
    assert asyncio.run(unit.lock_project(project_id=PROJECT))
    assert asyncio.run(unit.has_pending_revision(project_id=PROJECT))
    assert unit_type.lock_project is SqlAlchemyUserModelingUnitOfWork.lock_project
    assert unit_type.has_pending_revision is SqlAlchemyUserModelingUnitOfWork.has_pending_revision
    lock, pending = [
        call.args[0].compile(dialect=postgresql.dialect()) for call in session.scalar.call_args_list
    ]
    assert "FOR UPDATE" in str(lock)
    assert "archived_at IS NULL" in str(lock)
    assert OWNER in lock.params.values() and PROJECT in lock.params.values()
    assert "EXISTS" in str(pending)
    assert "archived_at IS NULL" in str(pending)
    assert "PROPOSED" in pending.params.values()
    assert OWNER in pending.params.values() and PROJECT in pending.params.values()
    assert "base_snapshot_version_id" not in str(pending)


@pytest.mark.parametrize("available", [False, True])
def test_base_uow_lock_and_pending_return_booleans_without_committing(available):
    session = AsyncMock()
    session.scalar.return_value = object() if available else None
    unit = SqlAlchemyUserModelingUnitOfWork(session, owner_user_id=OWNER)

    async def run():
        async with unit:
            assert await unit.lock_project(project_id=PROJECT) is available
            assert await unit.has_pending_revision(project_id=PROJECT) is available

    asyncio.run(run())
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()
