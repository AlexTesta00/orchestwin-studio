"""Tests for the SQLAlchemy user repository adapter."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.identity.domain import (
    GuidanceMode,
    NormalizedEmail,
    create_user_account,
)
from orchestwin.identity.persistence.models import UserGuidanceChoiceRecord, UserRecord
from orchestwin.identity.persistence.repositories import (
    SqlAlchemyUserRepository,
)
from orchestwin.persistence.migrate import (
    create_alembic_config,
)

TEST_DATABASE_URL = "postgresql+psycopg://user:password@localhost:5432/orchestwin"
ACCOUNT_QUERY = (
    "SELECT users.id, users.email_normalized, users.password_hash, users.is_active,"
    " users.created_at, users.updated_at, user_guidance_choices.mode FROM users"
    " LEFT OUTER JOIN user_guidance_choices ON user_guidance_choices.user_id = users.id"
)


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


def build_record() -> UserRecord:
    user = build_user()
    return UserRecord(
        id=user.id,
        email_normalized=user.email.value,
        password_hash=user.password_hash,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def reading_session(row: tuple[UserRecord, str | None] | None) -> Mock:
    session = Mock(spec=AsyncSession)
    result = Mock()
    result.one_or_none.return_value = row
    session.execute = AsyncMock(return_value=result)
    session.scalar = AsyncMock(side_effect=AssertionError("accounts are read in one query"))
    return session


def compiled(statement) -> str:
    return " ".join(str(statement.compile(dialect=postgresql.dialect())).split())


def test_repository_maps_record_back_to_domain() -> None:
    """Return immutable domain values instead of ORM records."""
    user = build_user()
    session = reading_session((build_record(), None))
    repository = SqlAlchemyUserRepository(session)

    loaded = asyncio.run(repository.get_by_email(user.email))

    assert loaded == user


@pytest.mark.parametrize("mode", list(GuidanceMode))
def test_an_account_is_read_with_its_guidance_mode_in_one_outer_join(mode: GuidanceMode) -> None:
    user = build_user()
    by_id = reading_session((build_record(), mode.value))
    by_email = reading_session((build_record(), mode.value))

    loaded_by_id = asyncio.run(SqlAlchemyUserRepository(by_id).get_by_id(user.id))
    loaded_by_email = asyncio.run(SqlAlchemyUserRepository(by_email).get_by_email(user.email))

    assert loaded_by_id == loaded_by_email == replace(user, guidance_mode=mode)
    assert loaded_by_id is not None
    assert loaded_by_id.guidance_mode is mode
    by_id.execute.assert_awaited_once()
    by_email.execute.assert_awaited_once()
    assert compiled(by_id.execute.await_args.args[0]) == (
        f"{ACCOUNT_QUERY} WHERE users.id = %(id_1)s::UUID"
    )
    assert compiled(by_email.execute.await_args.args[0]) == (
        f"{ACCOUNT_QUERY} WHERE users.email_normalized = %(email_normalized_1)s"
    )


def test_a_missing_account_is_read_as_none() -> None:
    user = build_user()

    assert asyncio.run(SqlAlchemyUserRepository(reading_session(None)).get_by_id(user.id)) is None
    assert (
        asyncio.run(SqlAlchemyUserRepository(reading_session(None)).get_by_email(user.email))
        is None
    )


def test_a_guidance_choice_is_added_as_one_row_and_flushed() -> None:
    session = Mock(spec=AsyncSession)
    session.flush = AsyncMock()
    chosen_at = datetime(2026, 10, 5, 9, 30, tzinfo=UTC)

    asyncio.run(
        SqlAlchemyUserRepository(session).add_guidance_choice(
            user_id=build_user().id,
            mode=GuidanceMode.GUIDED,
            chosen_at=chosen_at,
        )
    )

    session.add.assert_called_once()
    [record] = session.add.call_args.args
    assert isinstance(record, UserGuidanceChoiceRecord)
    assert (record.user_id, record.mode, record.chosen_at) == (
        build_user().id,
        "GUIDED",
        chosen_at,
    )
    session.flush.assert_awaited_once()
    session.execute.assert_not_called()


def test_a_second_guidance_choice_raises_the_integrity_error() -> None:
    session = Mock(spec=AsyncSession)
    conflict = IntegrityError("INSERT INTO user_guidance_choices", {}, Exception("duplicate"))
    session.flush = AsyncMock(side_effect=conflict)

    with pytest.raises(IntegrityError) as raised:
        asyncio.run(
            SqlAlchemyUserRepository(session).add_guidance_choice(
                user_id=build_user().id,
                mode=GuidanceMode.EXPERT,
                chosen_at=datetime(2026, 10, 5, 9, 30, tzinfo=UTC),
            )
        )

    assert raised.value is conflict


def test_user_revision_follows_persistence_baseline() -> None:
    """Keep the user migration attached to the expected revision."""
    scripts = ScriptDirectory.from_config(create_alembic_config(TEST_DATABASE_URL))
    revision = scripts.get_revision("0002_identity_users")

    assert revision is not None
    assert revision.down_revision == ("0001_persistence_baseline")
