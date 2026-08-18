"""Async SQLAlchemy engine and session-factory composition."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from orchestwin.persistence.config import DatabaseSettings


@dataclass(frozen=True, slots=True)
class DatabaseRuntime:
    """Process-level database engine and session factory."""

    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]

    async def dispose(self) -> None:
        """Dispose the engine and all pooled connections."""
        await self.engine.dispose()


def create_database_runtime(settings: DatabaseSettings) -> DatabaseRuntime:
    """Create the async database runtime without opening a connection."""
    engine = create_async_engine(
        settings.sqlalchemy_url,
        echo=settings.echo,
        pool_pre_ping=True,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_timeout=settings.pool_timeout_seconds,
        pool_recycle=settings.pool_recycle_seconds,
    )

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        autoflush=False,
        expire_on_commit=False,
    )

    return DatabaseRuntime(
        engine=engine,
        session_factory=session_factory,
    )


@asynccontextmanager
async def open_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Open and close a session without committing implicitly."""
    async with session_factory() as session:
        yield session


@asynccontextmanager
async def transactional_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Open a transaction that commits or rolls back as one unit."""
    async with session_factory.begin() as session:
        yield session
