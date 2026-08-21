"""Tests for Architecture SQLAlchemy runtime composition."""

from __future__ import annotations

import asyncio
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.models.architecture_runtime import ArchitectureRuntimeMode
from orchestwin.projects.architecture_runtime import (
    ManagedArchitectureUnitOfWork,
    SqlAlchemyArchitectureGateUnitOfWork,
    build_architecture_services,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")


class FakeSession:
    """Minimal async session lifecycle double."""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def close(self) -> None:
        self.closes += 1


def test_managed_architecture_uow_rolls_back_and_closes_unfinished_work() -> None:
    """Release a fresh Architecture command session when no command commits."""
    session = FakeSession()

    async def run() -> None:
        async with ManagedArchitectureUnitOfWork(
            cast(AsyncSession, session),
            owner_user_id=OWNER_ID,
        ):
            pass

    asyncio.run(run())

    assert session.rollbacks == 1
    assert session.commits == 0
    assert session.closes == 1


def test_architecture_gate_uow_commits_and_closes_successful_transitions() -> None:
    """Persist Gate 6 transitions when their use case exits normally."""
    session = FakeSession()

    async def run() -> None:
        async with SqlAlchemyArchitectureGateUnitOfWork(
            cast(AsyncSession, session),
            owner_user_id=OWNER_ID,
        ):
            pass

    asyncio.run(run())

    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closes == 1


def test_architecture_services_share_one_configured_session_factory() -> None:
    """Compose generation, revision, query, and Gate 6 services together."""
    session_factory = cast(
        async_sessionmaker[AsyncSession],
        lambda: cast(AsyncSession, FakeSession()),
    )

    services = build_architecture_services(session_factory)

    assert services.runtime_mode is ArchitectureRuntimeMode.FAKE_DETERMINISTIC
    assert services.generation is not None
    assert services.revisions is not None
    assert services.queries is not None
    assert services.gate is not None
