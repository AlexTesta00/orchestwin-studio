"""Tests for the SQLAlchemy user repository adapter."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import UUID

from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.identity.domain import (
    NormalizedEmail,
    create_user_account,
)
from orchestwin.identity.persistence.models import UserRecord
from orchestwin.identity.persistence.repositories import (
    SqlAlchemyUserRepository,
)
from orchestwin.persistence.migrate import (
    create_alembic_config,
)

TEST_DATABASE_URL = "postgresql+psycopg://user:password@localhost:5432/orchestwin"


def build_user():
    """Create a deterministic account for repository tests."""
    return create_user_account(
        user_id=UUID("00000000-0000-4000-8000-000000000001"),
        email=NormalizedEmail.parse("owner@example.com"),
        password_hash="$argon2id$repository-test",
        created_at=datetime(
            2026,
            8,
            7,
            12,
            0,
            tzinfo=UTC,
        ),
    )


def test_repository_adds_user_record_to_transaction() -> None:
    """Map a domain account into the SQLAlchemy session."""
    session = Mock(spec=AsyncSession)
    session.flush = AsyncMock()
    repository = SqlAlchemyUserRepository(session)
    user = build_user()

    persisted = asyncio.run(repository.add(user))

    session.add.assert_called_once()
    asyncio.run(session.flush())
    assert persisted == user


def test_repository_maps_record_back_to_domain() -> None:
    """Return immutable domain values instead of ORM records."""
    user = build_user()
    record = UserRecord(
        id=user.id,
        email_normalized=user.email.value,
        password_hash=user.password_hash,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )

    session = Mock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=record)
    repository = SqlAlchemyUserRepository(session)

    loaded = asyncio.run(repository.get_by_email(user.email))

    assert loaded == user


def test_user_revision_follows_persistence_baseline() -> None:
    """Keep the user migration attached to the expected revision."""
    scripts = ScriptDirectory.from_config(create_alembic_config(TEST_DATABASE_URL))
    revision = scripts.get_revision("0002_identity_users")

    assert revision is not None
    assert revision.down_revision == ("0001_persistence_baseline")
