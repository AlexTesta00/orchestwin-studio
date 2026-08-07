"""SQLAlchemy implementations of identity repository ports."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.identity.domain import (
    NormalizedEmail,
    UserAccount,
)
from orchestwin.identity.persistence.models import UserRecord


def user_record_to_domain(record: UserRecord) -> UserAccount:
    """Translate a persistence record into an immutable domain value."""
    return UserAccount(
        id=record.id,
        email=NormalizedEmail(record.email_normalized),
        password_hash=record.password_hash,
        is_active=record.is_active,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


class SqlAlchemyUserRepository:
    """SQLAlchemy user repository bound to one transaction session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: UserAccount) -> UserAccount:
        """Add a new account to the current transaction."""
        record = UserRecord(
            id=user.id,
            email_normalized=user.email.value,
            password_hash=user.password_hash,
            is_active=user.is_active,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )

        self._session.add(record)
        await self._session.flush()

        return user_record_to_domain(record)

    async def get_by_id(
        self,
        user_id: UUID,
    ) -> UserAccount | None:
        """Return an account by identifier."""
        record = await self._session.scalar(select(UserRecord).where(UserRecord.id == user_id))

        if record is None:
            return None

        return user_record_to_domain(record)

    async def get_by_email(
        self,
        email: NormalizedEmail,
    ) -> UserAccount | None:
        """Return an account by normalized email."""
        record = await self._session.scalar(
            select(UserRecord).where(UserRecord.email_normalized == email.value)
        )

        if record is None:
            return None

        return user_record_to_domain(record)
